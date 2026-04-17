"""Pydantic schemas for the feedback API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    command: str = Field(..., description="The original user command")
    response: str = Field(default="", description="Assistant's response (first 500 chars)")
    tool: str = Field(default="chat", description="Which tool produced the response")
    positive: bool = Field(..., description="True = thumbs up, False = thumbs down")
    comment: Optional[str] = Field(default="", description="Optional free-text comment")
    session_id: Optional[str] = Field(default="default")


class FeedbackOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    command: str
    response: str
    tool: str
    rating: float
    comment: str
    session_id: str
    created_at: datetime


class FeedbackStats(BaseModel):
    total: int
    positive: int
    negative: int
    accuracy_pct: float
    by_tool: Dict[str, Any] = Field(default_factory=dict)
