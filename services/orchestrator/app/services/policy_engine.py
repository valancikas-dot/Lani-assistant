"""
Policy Engine – evaluates every action BEFORE execution.

Decision flow
─────────────
  evaluate(action, params, context) → PolicyDecision

  PolicyDecision.verdict:
    "allow"            – proceed immediately
    "deny"             – hard block, never execute
    "require_approval" – queue for human confirmation

Rules (applied in order, first match wins)
──────────────────────────────────────────
  1. CRITICAL risk              → require_approval (always)
  2. HIGH risk                  → require_approval
  3. Sensitive domain match     → require_approval in strict mode
  4. Account not allowed        → deny
  5. Explicit approval on cap   → require_approval
  6. MEDIUM risk in strict mode → require_approval
  7. Default                    → allow

Thread-safety: policy rules are read-only after load; safe to share.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.capability_registry import get_capability, CapabilityMeta

log = logging.getLogger(__name__)

# ─── Sensitive domain keywords ────────────────────────────────────────────────
# If a tool name or command text contains any of these keywords and security_mode
# is "strict", the action is escalated to require_approval.
_SENSITIVE_DOMAINS = {
    "bank", "payment", "credit", "password", "auth", "login", "token",
    "secret", "private", "encrypt", "decrypt", "ssh", "gpg", "wallet",
    "transfer", "wire", "invoice", "tax",
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PolicyContext:
    """Caller-supplied context that influences policy decisions."""
    security_mode: str = "disabled"        # disabled | normal | strict
    active_accounts: List[str] = field(default_factory=list)
    user_authenticated: bool = True
    session_active: bool = True
    command_text: str = ""                 # raw user command for domain check


@dataclass
class PolicyDecision:
    verdict: str                            # allow | deny | require_approval
    reason: str = ""
    risk_level: str = "low"
    capability: Optional[CapabilityMeta] = None

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"

    @property
    def denied(self) -> bool:
        return self.verdict == "deny"

    @property
    def needs_approval(self) -> bool:
        return self.verdict == "require_approval"


# ─── Core policy functions ────────────────────────────────────────────────────

def evaluate(
    action: str,
    params: Dict[str, Any],
    context: Optional[PolicyContext] = None,
) -> PolicyDecision:
    """
    Evaluate whether *action* should be allowed, denied, or queued.

    Parameters
    ----------
    action  : tool name (e.g. "move_file", "gmail_send_email")
    params  : runtime parameters for the action
    context : caller-supplied policy context (defaults to permissive)
    """
    if context is None:
        context = PolicyContext()

    cap = get_capability(action)
    risk = cap.risk_level if cap else "low"

    # ── Rule 1: CRITICAL → always require approval ────────────────────────
    if risk == "critical":
        return PolicyDecision(
            verdict="require_approval",
            reason=f"Action '{action}' is CRITICAL risk – human confirmation required.",
            risk_level=risk,
            capability=cap,
        )

    # ── Rule 2: HIGH risk → require approval ─────────────────────────────
    if risk == "high":
        return PolicyDecision(
            verdict="require_approval",
            reason=f"Action '{action}' is HIGH risk – requires approval.",
            risk_level=risk,
            capability=cap,
        )

    # ── Rule 3: Sensitive domain in strict mode ───────────────────────────
    if context.security_mode == "strict":
        combined = (action + " " + context.command_text).lower()
        matched = _SENSITIVE_DOMAINS & set(combined.split())
        if matched:
            return PolicyDecision(
                verdict="require_approval",
                reason=f"Sensitive domain detected ({matched}) in strict mode.",
                risk_level=risk,
                capability=cap,
            )

    # ── Rule 4: Account scope check ───────────────────────────────────────
    if cap and cap.allowed_accounts:
        # If none of the required accounts are active, deny
        available = set(context.active_accounts)
        required = set(cap.allowed_accounts)
        if not required.intersection(available):
            return PolicyDecision(
                verdict="deny",
                reason=(
                    f"Action '{action}' requires one of {cap.allowed_accounts} "
                    f"but active accounts are {context.active_accounts}."
                ),
                risk_level=risk,
                capability=cap,
            )

    # ── Rule 5: Explicit approval flag on capability ──────────────────────
    if cap and cap.requires_approval:
        return PolicyDecision(
            verdict="require_approval",
            reason=f"Action '{action}' is configured to always require approval.",
            risk_level=risk,
            capability=cap,
        )

    # ── Rule 6: MEDIUM risk in strict mode ────────────────────────────────
    if risk == "medium" and context.security_mode == "strict":
        return PolicyDecision(
            verdict="require_approval",
            reason=f"MEDIUM risk action in strict security mode requires approval.",
            risk_level=risk,
            capability=cap,
        )

    # ── Rule 7: Default → allow ───────────────────────────────────────────
    return PolicyDecision(
        verdict="allow",
        reason="Action is within policy.",
        risk_level=risk,
        capability=cap,
    )


def evaluate_plan(
    steps: List[Dict[str, Any]],
    context: Optional[PolicyContext] = None,
) -> List[PolicyDecision]:
    """Evaluate an entire list of plan steps and return one decision per step."""
    return [evaluate(s.get("tool", ""), s.get("args", {}), context) for s in steps]


def build_context_from_settings(settings_row: Any, active_accounts: List[str]) -> PolicyContext:
    """
    Convenience builder – creates a PolicyContext from a UserSettings ORM row.
    """
    mode = "disabled"
    if settings_row is not None:
        raw = getattr(settings_row, "security_mode", "disabled") or "disabled"
        mode = raw

    return PolicyContext(
        security_mode=mode,
        active_accounts=active_accounts,
    )
