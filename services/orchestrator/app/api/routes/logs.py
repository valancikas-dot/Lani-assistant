"""Audit logs route – expose recent action history to the frontend."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

from app.core.database import get_db
from app.services.audit_service import get_recent_logs

router = APIRouter()


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    command: str
    tool_name: str
    status: str
    result_summary: Optional[str] = None
    error_message: Optional[str] = None


@router.get("/logs", response_model=list[AuditLogOut])
async def get_logs(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogOut]:
    """Return the most recent audit log entries."""
    logs = await get_recent_logs(db, limit=limit)
    return [AuditLogOut.model_validate(log) for log in logs]
