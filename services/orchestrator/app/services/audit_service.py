"""
Audit service – records every tool execution in the SQLite audit_logs table.
"""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models.audit_log import AuditLog


async def record_action(
    db: AsyncSession,
    command: str,
    tool_name: str,
    status: str,
    result_summary: str = "",
    error_message: str = "",
) -> None:
    """Persist an audit log entry for the given action."""
    entry = AuditLog(
        timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        command=command,
        tool_name=tool_name,
        status=status,
        result_summary=result_summary,
        error_message=error_message,
    )
    db.add(entry)
    await db.flush()


async def get_recent_logs(db: AsyncSession, limit: int = 100) -> list[AuditLog]:
    """Return the most recent *limit* audit log entries."""
    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(limit)
    )
    return list(result.scalars().all())
