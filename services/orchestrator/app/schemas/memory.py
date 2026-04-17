"""
Pydantic schemas for the memory layer.

Mirrors app/models/memory_entry.py but adds:
  - MemoryEntryCreate  (write)
  - MemoryEntryUpdate  (patch)
  - MemoryEntryOut     (read)
  - SuggestionOut      (generated recommendation card)
  - MemoryContext      (subset returned to planner/executor)
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ─── Allowed category values ──────────────────────────────────────────────────

MemoryCategory = Literal[
    "user_preferences",
    "workflow_preferences",
    "task_history",
    "suggestions",
    "scheduled_tasks",
]

MemorySource = Literal[
    "user_explicit",
    "inferred_from_repeated_actions",
    "settings_sync",
    "executor_outcome",
    "scheduler",
]


# ─── Write schemas ────────────────────────────────────────────────────────────

class MemoryEntryCreate(BaseModel):
    """Payload accepted by POST /api/v1/memory."""

    category: MemoryCategory
    key: str = Field(..., min_length=1, max_length=120)
    value: Dict[str, Any]
    source: MemorySource = "user_explicit"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    pinned: bool = False

    @field_validator("key")
    @classmethod
    def key_no_spaces(cls, v: str) -> str:
        """Keys must be snake_case identifiers, not free-text sentences."""
        return v.strip().lower().replace(" ", "_")


class MemoryEntryUpdate(BaseModel):
    """Payload accepted by PATCH /api/v1/memory/{id}."""

    value: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pinned: Optional[bool] = None
    status: Optional[Literal["active", "dismissed"]] = None


# ─── Read schema ──────────────────────────────────────────────────────────────

class MemoryEntryOut(BaseModel):
    """Full memory entry returned by the API."""

    id: int
    category: str
    key: str
    value: Dict[str, Any]
    source: str
    confidence: float
    pinned: bool
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


# ─── Suggestion card ──────────────────────────────────────────────────────────

class SuggestionOut(BaseModel):
    """
    A generated recommendation shown in the UI as an actionable card.

    The frontend renders two buttons: "Accept" and "Dismiss".
    Accepting calls PATCH /memory/{entry_id} to promote status='active' and
    raise confidence to 1.0.
    Dismissing calls PATCH /memory/{entry_id} with status='dismissed'.
    """

    entry_id: int
    """The memory_entries row that backs this suggestion."""

    category: str
    key: str
    value: Dict[str, Any]
    confidence: float
    explanation: str
    """Human-readable sentence shown on the suggestion card."""

    model_config = {"from_attributes": True}


# ─── Context slice returned to planner/executor ───────────────────────────────

class MemoryContext(BaseModel):
    """
    Lightweight subset of memory entries passed into plan generation.

    Contains only the key/value pairs relevant to the current command,
    plus a list of human-readable hints for the chat UI.
    """

    entries: List[MemoryEntryOut] = Field(default_factory=list)
    hints: List[str] = Field(default_factory=list)
    """Short plain-language strings like 'Used your default output folder.'"""
