"""
Evaluation Service – tracks task quality, performance, and reliability.

Records every tool execution in the EvalLog table and provides aggregated
statistics for the /api/v1/evals endpoint.

Metrics tracked
───────────────
  • task_success_rate        – % of executions with status='success'
  • task_failure_rate        – % of executions with status='error'
  • approval_frequency       – % of executions that required_approval
  • avg_execution_time_ms    – average duration across completed tasks
  • retry_rate               – % of executions with retries > 0
  • top_failing_tools        – tools with highest error rates
  • timeline                 – daily success/failure counts

Public API
──────────
  record(db, entry)          → EvalLog  – save one eval entry
  get_stats(db, ...)         → EvalStats dict
  list_recent(db, limit)     → list[EvalLog]
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval_log import EvalLog

log = logging.getLogger(__name__)


# ─── Entry builder ────────────────────────────────────────────────────────────

async def record(
    db: AsyncSession,
    *,
    command: str,
    tool_name: str,
    status: str,
    duration_ms: Optional[float] = None,
    retries: int = 0,
    required_approval: bool = False,
    approval_granted: Optional[bool] = None,
    risk_level: Optional[str] = None,
    policy_verdict: Optional[str] = None,
    quality_score: Optional[float] = None,
    error_message: Optional[str] = None,
    plan_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> EvalLog:
    """Insert one EvalLog row. Call this after every tool execution."""
    entry = EvalLog(
        command=command[:1000],
        tool_name=tool_name,
        status=status,
        duration_ms=duration_ms,
        retries=retries,
        required_approval=required_approval,
        approval_granted=approval_granted,
        risk_level=risk_level,
        policy_verdict=policy_verdict,
        quality_score=quality_score,
        error_message=error_message,
        plan_id=plan_id,
        context_json=json.dumps(context) if context else None,
    )
    db.add(entry)
    try:
        await db.flush()
    except Exception as exc:
        log.error("[eval_service] failed to record eval: %s", exc)
    return entry


# ─── Aggregated stats ─────────────────────────────────────────────────────────

async def get_stats(
    db: AsyncSession,
    since_days: int = 30,
    tool_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return aggregated evaluation statistics.

    Parameters
    ----------
    since_days   – look back N days (default 30)
    tool_filter  – if set, restrict to this tool name
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=since_days)

    q = select(EvalLog).where(EvalLog.timestamp >= cutoff)
    if tool_filter:
        q = q.where(EvalLog.tool_name == tool_filter)

    result = await db.execute(q)
    rows: List[EvalLog] = list(result.scalars().all())

    if not rows:
        return _empty_stats(since_days)

    total = len(rows)
    successes = sum(1 for r in rows if r.status == "success")
    failures  = sum(1 for r in rows if r.status == "error")
    approvals = sum(1 for r in rows if r.required_approval)
    retried   = sum(1 for r in rows if r.retries and r.retries > 0)

    durations = [r.duration_ms for r in rows if r.duration_ms is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # Per-tool failure counts
    tool_failures: Dict[str, int] = {}
    tool_totals: Dict[str, int] = {}
    for r in rows:
        tool_totals[r.tool_name] = tool_totals.get(r.tool_name, 0) + 1
        if r.status == "error":
            tool_failures[r.tool_name] = tool_failures.get(r.tool_name, 0) + 1

    top_failing = sorted(
        [
            {
                "tool": t,
                "errors": cnt,
                "total": tool_totals[t],
                "error_rate": round(cnt / tool_totals[t], 3),
            }
            for t, cnt in tool_failures.items()
        ],
        key=lambda x: x["error_rate"],
        reverse=True,
    )[:10]

    # Daily timeline (last 14 days)
    timeline: Dict[str, Dict[str, int]] = {}
    for r in rows:
        day = r.timestamp.strftime("%Y-%m-%d")
        bucket = timeline.setdefault(day, {"success": 0, "error": 0, "total": 0})
        bucket["total"] += 1
        if r.status == "success":
            bucket["success"] += 1
        elif r.status == "error":
            bucket["error"] += 1

    # Quality scores
    scores = [r.quality_score for r in rows if r.quality_score is not None]
    avg_quality = round(sum(scores) / len(scores), 3) if scores else None

    return {
        "period_days": since_days,
        "total_tasks": total,
        "success_count": successes,
        "failure_count": failures,
        "approval_count": approvals,
        "retry_count": retried,
        "task_success_rate": round(successes / total, 3),
        "task_failure_rate": round(failures / total, 3),
        "approval_frequency": round(approvals / total, 3),
        "retry_rate": round(retried / total, 3),
        "avg_execution_time_ms": round(avg_duration, 1),
        "avg_quality_score": avg_quality,
        "top_failing_tools": top_failing,
        "daily_timeline": dict(sorted(timeline.items())),
    }


def _empty_stats(since_days: int) -> Dict[str, Any]:
    return {
        "period_days": since_days,
        "total_tasks": 0,
        "success_count": 0,
        "failure_count": 0,
        "approval_count": 0,
        "retry_count": 0,
        "task_success_rate": 0.0,
        "task_failure_rate": 0.0,
        "approval_frequency": 0.0,
        "retry_rate": 0.0,
        "avg_execution_time_ms": 0.0,
        "avg_quality_score": None,
        "top_failing_tools": [],
        "daily_timeline": {},
    }


async def list_recent(
    db: AsyncSession,
    limit: int = 50,
    tool_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the N most recent eval log entries as dicts."""
    q = select(EvalLog).order_by(EvalLog.timestamp.desc()).limit(limit)
    if tool_filter:
        q = q.where(EvalLog.tool_name == tool_filter)

    result = await db.execute(q)
    rows = result.scalars().all()

    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "command": r.command,
            "tool_name": r.tool_name,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "retries": r.retries,
            "required_approval": r.required_approval,
            "approval_granted": r.approval_granted,
            "risk_level": r.risk_level,
            "policy_verdict": r.policy_verdict,
            "quality_score": r.quality_score,
            "error_message": r.error_message,
            "plan_id": r.plan_id,
        }
        for r in rows
    ]
