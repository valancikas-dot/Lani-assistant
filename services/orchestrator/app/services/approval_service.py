"""
Approval service – manages the pending approval queue.
"""

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_request import ApprovalRequest
from app.schemas.approvals import ApprovalRequestOut
from app.tools.registry import list_tools
from app.services.execution_guard import guarded_execute

log = logging.getLogger(__name__)


async def create_approval_request(
    db: AsyncSession,
    tool_name: str,
    command: str,
    params: Dict[str, Any],
    *,
    execution_context: Optional[Dict[str, Any]] = None,
) -> int:
    """Insert a new pending approval and return its ID.

    Args:
        execution_context: Optional dict persisted so the executor can resume
            after approval.  Typical shape for plan/workflow resumption::

                {"plan": <ExecutionPlan.model_dump()>, "start_from_step": int}
    """
    req = ApprovalRequest(
        tool_name=tool_name,
        command=command,
        params=params,
        status="pending",
        execution_context=execution_context,
    )
    db.add(req)
    await db.flush()
    return req.id


async def list_pending(db: AsyncSession) -> List[ApprovalRequestOut]:
    """Return all approval requests with status == 'pending'."""
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.status == "pending")
    )
    rows = result.scalars().all()
    return [ApprovalRequestOut.model_validate(r) for r in rows]


async def resolve(
    db: AsyncSession,
    approval_id: int,
    decision: str,  # "approved" | "denied"
) -> ApprovalRequestOut | None:
    """
    Set the decision on an approval request.

    If approved **and** an ``execution_context`` was stored, the executor
    will be resumed automatically (plan or workflow).  If no context was
    stored the individual tool is executed directly (legacy behaviour).
    """
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    req: ApprovalRequest | None = result.scalar_one_or_none()
    if req is None:
        return None

    req.status = decision
    req.resolved_at = datetime.datetime.now(datetime.timezone.utc)

    if decision == "approved":
        ctx = req.execution_context or {}
        if ctx.get("plan"):
            # Resume a paused plan / workflow execution
            await _resume_from_context(db, ctx)
        else:
            # Single-tool approval: run through the guard so policy/audit/eval
            # all fire correctly even on the resume path.
            try:
                await guarded_execute(
                    req.tool_name,
                    req.params or {},
                    req.command or req.tool_name,
                    db,
                    settings_row=None,
                    execution_context={"executor_type": "approval_resume"},
                    caller="approval_resume",
                )
            except Exception as exc:
                log.warning("Approval resume guarded_execute failed: %s", exc)

    await db.flush()
    return ApprovalRequestOut.model_validate(req)


async def _resume_from_context(db: AsyncSession, ctx: Dict[str, Any]) -> None:
    """Deserialise stored execution context and resume the correct executor."""
    plan_data: Optional[Dict[str, Any]] = ctx.get("plan")
    start_from_step: int = int(ctx.get("start_from_step", 0))
    executor_type: str = ctx.get("executor_type", "plan")  # "plan" | "workflow"

    if not plan_data:
        return

    try:
        if executor_type == "workflow":
            from app.schemas.plan import ExecutionPlan
            from app.services.workflow_executor import execute_workflow

            plan = ExecutionPlan.model_validate(plan_data)
            await execute_workflow(plan, db, start_from_step=start_from_step)
        else:
            from app.schemas.plan import ExecutionPlan
            from app.services.plan_executor import execute_plan

            plan = ExecutionPlan.model_validate(plan_data)
            await execute_plan(plan, db, start_from_step=start_from_step)
    except Exception as exc:
        log.error("Approval resume execution failed: %s", exc, exc_info=True)
