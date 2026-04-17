"""
Audit Chain – records a complete, linked execution trace for each action.

Each record ties together:
  • user intent (command + intent preview)
  • capability metadata used
  • policy decision
  • approval outcome (if applicable)
  • execution result summary
  • state delta summary
  • eval reference/summary
  • timestamp

Records are stored in-memory (ring buffer) and also written to the audit log
via audit_service.record_action so they appear in the Logs page.

Usage::

    chain_id = await record_audit_chain(
        db=db,
        command="delete ~/Desktop/test.txt",
        tool_name="delete_file",
        cap_meta=cap_meta,
        policy_decision=policy_decision,
        execution_status="success",
        tool_result=tool_result,
        state_delta=delta,
        eval_status="success",
        approval_id=None,
    )
"""

from __future__ import annotations

import collections
import datetime
import logging
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)

_MAX_CHAINS = 200   # ring buffer size


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class AuditChainRecord:
    """One complete execution trace."""
    chain_id: str
    command: str
    tool_name: str

    # Capability snapshot
    capability: Optional[Dict[str, Any]]

    # Policy snapshot
    policy_verdict: str
    policy_reason: str
    risk_level: str

    # Approval info
    approval_id: Optional[int]
    approval_status: str   # "n/a" | "pending" | "approved" | "denied"

    # Execution
    execution_status: str   # "executed" | "approval_required" | "denied" | "error"
    result_summary: str

    # State delta
    changed_fields: List[str]
    state_before_summary: str
    state_after_summary: str

    # Eval
    eval_status: Optional[str]   # "success" | "error" | "denied" | None

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Ring buffer ──────────────────────────────────────────────────────────────

_chain_buffer: Deque[AuditChainRecord] = collections.deque(maxlen=_MAX_CHAINS)


def get_recent_chains(n: int = 20) -> List[Dict[str, Any]]:
    """Return the n most recent audit chain records as dicts."""
    return [c.to_dict() for c in list(_chain_buffer)[:n]]


def get_chain(chain_id: str) -> Optional[AuditChainRecord]:
    """Look up a specific chain by ID."""
    return next((c for c in _chain_buffer if c.chain_id == chain_id), None)


# ─── Recorder ────────────────────────────────────────────────────────────────

async def record_audit_chain(
    db: Any,
    command: str,
    tool_name: str,
    cap_meta: Optional[Dict[str, Any]],
    policy_decision: Any,
    execution_status: str,
    tool_result: Any,
    state_delta: Any,
    eval_status: Optional[str],
    approval_id: Optional[int],
) -> str:
    """
    Build, store, and audit-log a complete chain record.

    Returns the ``chain_id`` so callers can reference it.
    """
    chain_id = secrets.token_hex(8)

    # ── Policy fields ──
    policy_verdict = "allow"
    policy_reason = ""
    risk_level = "low"
    if policy_decision is not None:
        policy_verdict = getattr(policy_decision, "verdict", "allow") or "allow"
        policy_reason = getattr(policy_decision, "reason", "") or ""
        risk_level = getattr(policy_decision, "risk_level", "low") or "low"
    elif cap_meta:
        risk_level = cap_meta.get("risk_level", "low")

    # ── Capability snapshot ──
    cap_snapshot: Optional[Dict[str, Any]] = None
    if cap_meta:
        cap_snapshot = {k: cap_meta[k] for k in ("name", "risk_level", "requires_approval")
                        if k in cap_meta}

    # ── Approval status ──
    approval_status = "n/a"
    if approval_id is not None:
        approval_status = "pending"
    if execution_status == "approval_required":
        approval_status = "pending"
    elif execution_status == "denied":
        approval_status = "n/a"

    # ── Result summary ──
    result_summary = ""
    if tool_result is not None:
        status_str = getattr(tool_result, "status", "")
        msg = getattr(tool_result, "message", "") or ""
        result_summary = f"{status_str}: {msg[:200]}"
    elif execution_status == "denied":
        result_summary = f"Blocked by policy: {policy_reason}"
    elif execution_status == "approval_required":
        result_summary = f"Paused – approval #{approval_id} created"

    # ── State delta ──
    changed_fields: List[str] = []
    state_before = ""
    state_after = ""
    if state_delta is not None:
        changed_fields = getattr(state_delta, "changed_fields", [])
        state_before = getattr(state_delta, "before_summary", "")
        state_after = getattr(state_delta, "after_summary", "")

    record = AuditChainRecord(
        chain_id=chain_id,
        command=command,
        tool_name=tool_name,
        capability=cap_snapshot,
        policy_verdict=policy_verdict,
        policy_reason=policy_reason,
        risk_level=risk_level,
        approval_id=approval_id,
        approval_status=approval_status,
        execution_status=execution_status,
        result_summary=result_summary,
        changed_fields=changed_fields,
        state_before_summary=state_before,
        state_after_summary=state_after,
        eval_status=eval_status,
    )
    _chain_buffer.appendleft(record)

    # ── Persist a compact line to the audit log ───────────────────────────────
    try:
        from app.services.audit_service import record_action
        summary = (
            f"[chain:{chain_id}] tool={tool_name} verdict={policy_verdict} "
            f"risk={risk_level} status={execution_status} "
            f"changed={','.join(changed_fields) or 'none'}"
        )
        await record_action(db, command, tool_name, execution_status, summary)
    except Exception as exc:
        log.warning("[audit_chain] audit_service write failed: %s", exc)

    return chain_id
