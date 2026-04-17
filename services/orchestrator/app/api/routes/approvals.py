"""Approvals route – manage the pending action approval queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.approvals import ApprovalDecision, ApprovalRequestOut
from app.services.approval_service import list_pending, resolve

router = APIRouter()


@router.get("/approvals", response_model=list[ApprovalRequestOut])
async def get_pending_approvals(
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalRequestOut]:
    """Return all actions waiting for user approval."""
    return await list_pending(db)


@router.post("/approvals/{approval_id}", response_model=ApprovalRequestOut)
async def decide_approval(
    approval_id: int,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestOut:
    """Approve or deny a pending action."""
    result = await resolve(db, approval_id, decision.decision)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Approval #{approval_id} not found.")
    return result
