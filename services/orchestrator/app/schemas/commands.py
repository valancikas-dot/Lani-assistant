"""Pydantic schemas for command requests and responses."""

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel


class CommandRequest(BaseModel):
    """Payload sent by the frontend when the user submits a command."""
    command: str
    context: Optional[Dict[str, Any]] = None


class ToolResult(BaseModel):
    """Structured result returned by a tool execution."""
    tool_name: str
    status: Literal["success", "error", "approval_required"]
    data: Optional[Any] = None
    message: Optional[str] = None


class CommandResponse(BaseModel):
    """Top-level response envelope returned to the frontend."""
    command: str
    result: ToolResult
    approval_id: Optional[int] = None  # set when status == approval_required
