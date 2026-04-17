"""Pydantic schemas for the approval queue."""

from typing import Any, Dict, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ApprovalRequestOut(BaseModel):
    """Serialised approval request returned to the frontend."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    tool_name: str
    command: str
    params: Dict[str, Any]
    status: Literal["pending", "approved", "denied"]


class ApprovalDecision(BaseModel):
    """Payload to approve or deny a pending request."""
    decision: Literal["approved", "denied"]
