"""ORM model for task evaluation logs."""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EvalLog(Base):
    """Every task execution is evaluated and recorded here."""

    __tablename__ = "eval_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    # What was executed
    command: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=True)  # plan/workflow ID if applicable
    # Outcome
    status: Mapped[str] = mapped_column(String(40), nullable=False)   # success | error | approval_required | denied
    duration_ms: Mapped[float] = mapped_column(Float, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    # Risk & policy
    risk_level: Mapped[str] = mapped_column(String(20), nullable=True)   # low | medium | high | critical
    policy_verdict: Mapped[str] = mapped_column(String(30), nullable=True)  # allow | deny | require_approval
    # Quality scores (optional, filled by self-reflection if enabled)
    quality_score: Mapped[float] = mapped_column(Float, nullable=True)    # 0.0 – 1.0
    user_rating: Mapped[int] = mapped_column(Integer, nullable=True)       # 1-5 thumbs
    # Error details
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    # Extra context (JSON string)
    context_json: Mapped[str] = mapped_column(Text, nullable=True)
