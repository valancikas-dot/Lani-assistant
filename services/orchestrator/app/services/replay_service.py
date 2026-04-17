"""
Replay Service – step-by-step replay and dry-run simulation of execution chains.

The replay service reads from the in-memory audit chain ring buffer
(``audit_chain.get_chain``) and reconstructs a human-readable timeline,
allows simulated step-by-step replay, and can export the full chain as a
structured dict.

Design notes
────────────
1. **No side-effects** – replay never calls tool.run(); it only re-reads stored
   chain data.  For dry-run simulation, it returns hypothetical outcomes based
   on stored metadata.
2. **Observable** – every step, including simulated outcomes, is logged so ops
   teams can audit the replay.
3. **Composable** – the API returns structured dicts so callers (API layer,
   frontend) can render timelines without understanding internals.

Public API
──────────
  get_replay(chain_id)  → ReplayResult | None
      Reconstruct replay for a given audit chain ID.

  simulate_chain(steps) → List[SimulatedStep]
      Simulate a list of steps without executing them (dry-run).

  export_timeline(chain_id) → str
      Human-readable text timeline for a given chain.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class ReplayStep:
    """One step in a replayed execution chain."""
    step_number: int
    action: str
    inputs: Dict[str, Any]
    result_status: str
    result_summary: str
    verification_verdict: Optional[str]
    state_delta_summary: str
    failure_reason: Optional[str]
    timestamp: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "inputs": self.inputs,
            "result_status": self.result_status,
            "result_summary": self.result_summary,
            "verification_verdict": self.verification_verdict,
            "state_delta_summary": self.state_delta_summary,
            "failure_reason": self.failure_reason,
            "timestamp": self.timestamp,
            "notes": self.notes,
        }


@dataclass
class SimulatedStep:
    """Result of dry-run simulation for one planned step."""
    step_number: int
    action: str
    inputs: Dict[str, Any]
    simulated_outcome: str       # "would_succeed" | "would_require_approval" | "would_be_blocked" | "unknown"
    risk_level: str = "low"
    approval_required: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "inputs": self.inputs,
            "simulated_outcome": self.simulated_outcome,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "notes": self.notes,
        }


@dataclass
class ReplayResult:
    """Full reconstruction of an execution chain."""
    chain_id: str
    command: str
    tool_name: str
    steps: List[ReplayStep] = field(default_factory=list)
    total_steps: int = 0
    final_status: str = ""
    timeline_text: str = ""
    replay_timestamp: str = field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "command": self.command,
            "tool_name": self.tool_name,
            "steps": [s.to_dict() for s in self.steps],
            "total_steps": self.total_steps,
            "final_status": self.final_status,
            "timeline_text": self.timeline_text,
            "replay_timestamp": self.replay_timestamp,
        }


# ─── Public API ───────────────────────────────────────────────────────────────

def get_replay(chain_id: str) -> Optional[ReplayResult]:
    """
    Reconstruct a replay for a given audit chain ID.

    Looks up the chain in the in-memory ring buffer and converts its
    checkpoint / execution data into a structured ReplayResult.

    Parameters
    ----------
    chain_id : The chain_id returned by ``guarded_execute()`` (stored in GuardResult).

    Returns
    -------
    ReplayResult, or None if the chain is not found (no longer in ring buffer).
    """
    from app.services.audit_chain import get_chain

    chain = get_chain(chain_id)
    if chain is None:
        log.info("[replay_service] chain_id '%s' not found in ring buffer.", chain_id)
        return None

    steps = _build_steps_from_chain(chain)
    timeline = _render_timeline(chain_id, chain.command, chain.tool_name, steps)

    return ReplayResult(
        chain_id=chain_id,
        command=chain.command,
        tool_name=chain.tool_name,
        steps=steps,
        total_steps=len(steps),
        final_status=chain.execution_status,
        timeline_text=timeline,
    )


def simulate_chain(
    steps: List[Dict[str, Any]],
    *,
    settings_row: Any = None,
) -> List[SimulatedStep]:
    """
    Simulate a list of planned steps in dry-run mode (no side-effects).

    Each item in ``steps`` must be a dict with at least::

        {"action": str, "inputs": dict}

    The function consults the capability registry and policy engine to
    predict whether each step would succeed, require approval, or be blocked,
    without executing anything.

    Parameters
    ----------
    steps        : List of planned steps to simulate.
    settings_row : Optional UserSettings ORM row for policy context.

    Returns
    -------
    List of SimulatedStep describing predicted outcomes.
    """
    results: List[SimulatedStep] = []
    for i, raw_step in enumerate(steps, start=1):
        action = raw_step.get("action") or raw_step.get("tool_name") or "unknown"
        inputs = raw_step.get("inputs") or raw_step.get("params") or {}
        simulated = _simulate_one_step(i, action, inputs, settings_row=settings_row)
        results.append(simulated)
    return results


def export_timeline(chain_id: str) -> str:
    """
    Export a human-readable text timeline for a given chain.

    Returns the timeline string, or a "not found" message if the chain
    is no longer in the ring buffer.
    """
    replay = get_replay(chain_id)
    if replay is None:
        return f"[Replay] Chain '{chain_id}' not found in ring buffer."
    return replay.timeline_text


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _build_steps_from_chain(chain: Any) -> List[ReplayStep]:
    """
    Convert an AuditChainRecord into a list of ReplayStep objects.

    The chain may contain checkpoint data embedded in its result_summary
    or it may be a single-step chain (most common case).
    """
    steps: List[ReplayStep] = []

    # Primary step – always present
    step = ReplayStep(
        step_number=1,
        action=chain.tool_name,
        inputs={},               # params not stored in AuditChainRecord (by design)
        result_status=chain.execution_status,
        result_summary=chain.result_summary or "",
        verification_verdict=None,
        state_delta_summary=_summarise_delta(chain),
        failure_reason=None,
        timestamp=chain.timestamp,
        notes=_step_notes(chain),
    )
    steps.append(step)

    return steps


def _summarise_delta(chain: Any) -> str:
    """Extract state-delta summary from an AuditChainRecord."""
    changed = getattr(chain, "changed_fields", None) or []
    if changed:
        return f"changed: {', '.join(changed[:10])}"
    before = getattr(chain, "state_before_summary", "") or ""
    after  = getattr(chain, "state_after_summary", "") or ""
    if before or after:
        return f"before={before!r} → after={after!r}"
    return ""


def _step_notes(chain: Any) -> str:
    """Generate human-readable notes for a chain step."""
    notes = []
    if getattr(chain, "approval_id", None):
        notes.append(f"approval #{chain.approval_id} ({chain.approval_status})")
    if getattr(chain, "policy_verdict", None) not in (None, "allow"):
        notes.append(f"policy: {chain.policy_verdict} – {chain.policy_reason or ''}")
    if getattr(chain, "risk_level", None) and chain.risk_level != "low":
        notes.append(f"risk: {chain.risk_level}")
    return "; ".join(notes)


def _simulate_one_step(
    step_number: int,
    action: str,
    inputs: Dict[str, Any],
    *,
    settings_row: Any,
) -> SimulatedStep:
    """Simulate one step using capability registry + policy engine."""
    risk_level = "low"
    approval_required = False
    simulated_outcome = "would_succeed"
    notes_parts: List[str] = []

    try:
        from app.services.capability_registry import get_capability
        cap = get_capability(action)
        if cap is not None:
            risk_level = cap.risk_level
            if risk_level in ("critical", "high"):
                notes_parts.append(f"risk={risk_level}")
    except Exception as exc:
        log.debug("[replay_service] capability lookup failed: %s", exc)

    try:
        from app.services.policy_engine import evaluate as policy_evaluate, build_context_from_settings
        from app.services.session_manager import list_active_account_types
        active_accounts = list_active_account_types()
        ctx = build_context_from_settings(settings_row, active_accounts)
        decision = policy_evaluate(action, inputs, ctx)
        if decision.denied:
            simulated_outcome = "would_be_blocked"
            notes_parts.append(f"policy denies: {decision.reason or ''}")
        elif decision.needs_approval:
            simulated_outcome = "would_require_approval"
            approval_required = True
            notes_parts.append(f"policy requires approval: {decision.reason or ''}")
    except Exception as exc:
        log.debug("[replay_service] policy simulation failed: %s", exc)
        simulated_outcome = "unknown"
        notes_parts.append(f"policy sim error: {exc}")

    return SimulatedStep(
        step_number=step_number,
        action=action,
        inputs=inputs,
        simulated_outcome=simulated_outcome,
        risk_level=risk_level,
        approval_required=approval_required,
        notes="; ".join(notes_parts),
    )


def _render_timeline(
    chain_id: str,
    command: str,
    tool_name: str,
    steps: List[ReplayStep],
) -> str:
    """Render a human-readable text timeline."""
    lines = [
        "═" * 60,
        f"  EXECUTION REPLAY  –  chain {chain_id}",
        "═" * 60,
        f"  Command  : {command}",
        f"  Tool     : {tool_name}",
        f"  Steps    : {len(steps)}",
        "─" * 60,
    ]
    for step in steps:
        status_icon = "✓" if step.result_status == "success" else "✗"
        lines.append(
            f"  [{step.step_number:02d}] {status_icon} {step.action}"
            + (f"  [{step.result_status.upper()}]" if step.result_status else "")
        )
        if step.result_summary:
            lines.append(f"        → {step.result_summary[:120]}")
        if step.verification_verdict:
            lines.append(f"        ✦ verification: {step.verification_verdict}")
        if step.failure_reason:
            lines.append(f"        ⚠ failure: {step.failure_reason}")
        if step.state_delta_summary:
            lines.append(f"        Δ state: {step.state_delta_summary[:80]}")
        if step.notes:
            lines.append(f"        ℹ {step.notes}")
        lines.append(f"        @ {step.timestamp}")
        lines.append("")
    lines.append("═" * 60)
    return "\n".join(lines)
