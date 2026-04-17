"""ORM model for the approval request queue."""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApprovalRequest(Base):
    """Holds sensitive actions waiting for user approval."""

    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    resolved_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending | approved | denied

    # Execution context stored so the executor can resume after approval.
    # Shape: {"plan": <serialized ExecutionPlan dict>, "start_from_step": int}
    execution_context: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )
