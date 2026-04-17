"""
Chains API – Mission Control endpoints for execution chain observability.

Routes
──────
  GET  /api/v1/chains                     – Recent execution chains (ring buffer)
  GET  /api/v1/chains/{chain_id}          – Single chain summary
  GET  /api/v1/chains/{chain_id}/checkpoints – Checkpoints for a chain (from replay)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _outcome_from_chain(record: Dict[str, Any]) -> str:
    """
    Derive a frontend-friendly outcome string from an AuditChainRecord dict.

    This mirrors the OUTCOME_* constants from execution_guard without importing
    them at module level (avoids pulling heavy deps into the request path).
    """
    status = record.get("execution_status", "")
    eval_s = record.get("eval_status") or ""
    verdict = record.get("policy_verdict", "allow")

    if status == "denied" or verdict == "deny":
        return "blocked"
    if status == "approval_required":
        return "approval_required"
    if status in ("executed", "success"):
        if eval_s == "success":
            return "executed_verified"
        return "executed_unverified"
    if status == "error":
        return "failed_nonretryable"
    # Passthrough for guard OUTCOME_* constants (already correct strings)
    _known_outcomes = {
        "blocked", "approval_required", "executed_unverified", "executed_verified",
        "failed_retryable", "failed_nonretryable", "rolled_back", "rollback_failed",
    }
    if status in _known_outcomes:
        return status
    return "unknown"


def _risk_color(risk: str) -> str:
    return {"low": "green", "medium": "amber", "high": "red", "critical": "red"}.get(
        risk, "grey"
    )


def _extract_session_id(record: Dict[str, Any]) -> Optional[str]:
    """Best-effort session id extraction from capability payload."""
    capability = record.get("capability")
    if isinstance(capability, dict):
        sid = capability.get("session_id") or capability.get("session")
        if sid is not None:
            return str(sid)
    return None


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/chains", tags=["chains"])
async def list_chains(
    limit: int = Query(default=30, ge=1, le=200, description="Max chains to return"),
) -> List[Dict[str, Any]]:
    """
    Return the most recent *limit* execution chains from the in-memory ring buffer.

    Each item is a compact summary suitable for the Mission Control list view.
    The ring buffer holds up to 200 records; older chains are evicted.
    """
    from app.services.audit_chain import get_recent_chains

    raw = get_recent_chains(limit)

    summaries = []
    for r in raw:
        summaries.append(
            {
                "chain_id": r.get("chain_id"),
                "command": r.get("command", ""),
                "tool_name": r.get("tool_name", ""),
                "outcome": _outcome_from_chain(r),
                "execution_status": r.get("execution_status", ""),
                "risk_level": r.get("risk_level", "low"),
                "risk_color": _risk_color(r.get("risk_level", "low")),
                "policy_verdict": r.get("policy_verdict", "allow"),
                "approval_id": r.get("approval_id"),
                "approval_status": r.get("approval_status", "n/a"),
                "eval_status": r.get("eval_status"),
                "session_id": _extract_session_id(r),
                "timestamp": r.get("timestamp"),
                # State delta quick view
                "changed_fields": r.get("changed_fields", []),
                "state_after_summary": r.get("state_after_summary", ""),
            }
        )
    return summaries


@router.get("/chains/{chain_id}", tags=["chains"])
async def get_chain_detail(chain_id: str) -> Dict[str, Any]:
    """
    Return the full AuditChainRecord plus replay steps for a single chain.

    Combines the audit chain record (policy / approval / state delta) with
    replay step data (verification, checkpoints) if available.
    Returns 404 when the chain has been evicted from the ring buffer.
    """
    from app.services.audit_chain import get_chain
    from app.services.replay_service import get_replay

    record = get_chain(chain_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chain '{chain_id}' not found in ring buffer.",
        )

    base = record.to_dict()
    base["outcome"] = _outcome_from_chain(base)
    base["risk_color"] = _risk_color(base.get("risk_level", "low"))
    base["session_id"] = _extract_session_id(base)

    # Enrich with replay data if available
    replay = get_replay(chain_id)
    if replay is not None:
        replay_dict = replay.to_dict()
        base["replay_steps"] = replay_dict.get("steps", [])
        base["replay_final_status"] = replay_dict.get("final_status")
        base["replay_timeline_text"] = replay_dict.get("timeline_text", "")
    else:
        base["replay_steps"] = []
        base["replay_final_status"] = None
        base["replay_timeline_text"] = ""

    return base


@router.get("/chains/{chain_id}/checkpoints", tags=["chains"])
async def get_chain_checkpoints(chain_id: str) -> Dict[str, Any]:
    """
    Return the checkpoint list for a chain.

    Checkpoints are extracted from the replay steps when available.
    If the chain exists but has no checkpoint data, returns an empty list.
    Returns 404 when the chain is not in the ring buffer.
    """
    from app.services.audit_chain import get_chain
    from app.services.replay_service import get_replay

    record = get_chain(chain_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chain '{chain_id}' not found in ring buffer.",
        )

    checkpoints: List[Dict[str, Any]] = []
    replay = get_replay(chain_id)
    if replay is not None:
        for step in replay.steps:
            checkpoints.append(
                {
                    "step_number": step.step_number,
                    "action": step.action,
                    "result_status": step.result_status,
                    "result_summary": step.result_summary,
                    "verification_verdict": step.verification_verdict,
                    "failure_reason": step.failure_reason,
                    "state_delta_summary": step.state_delta_summary,
                    "timestamp": step.timestamp,
                    "notes": step.notes,
                }
            )

    return {
        "chain_id": chain_id,
        "tool_name": record.tool_name,
        "command": record.command,
        "total_checkpoints": len(checkpoints),
        "checkpoints": checkpoints,
    }
