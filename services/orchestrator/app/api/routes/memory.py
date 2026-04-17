"""
Memory API routes.

GET    /api/v1/memory                    List all entries (filterable)
POST   /api/v1/memory                    Create / upsert an entry
PATCH  /api/v1/memory/{id}               Update an entry
DELETE /api/v1/memory/{id}               Delete an entry
GET    /api/v1/memory/suggestions        Run suggestion engine + return cards
POST   /api/v1/memory/context            Return relevant context for a command
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.commands import CommandRequest
from app.schemas.memory import (
    MemoryContext,
    MemoryEntryCreate,
    MemoryEntryOut,
    MemoryEntryUpdate,
    SuggestionOut,
)
from app.services import memory_service

router = APIRouter()


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("/memory", response_model=List[MemoryEntryOut])
async def list_memory(
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> List[MemoryEntryOut]:
    """
    Return all memory entries.

    Optional query params:
    - ``category``: filter to one category (user_preferences, workflow_preferences…)
    - ``status``:   active | dismissed
    """
    return await memory_service.get_all(db, category=category, status=status)


# ─── Create / upsert ──────────────────────────────────────────────────────────

@router.post("/memory", response_model=MemoryEntryOut, status_code=201)
async def create_memory(
    payload: MemoryEntryCreate,
    db: AsyncSession = Depends(get_db),
) -> MemoryEntryOut:
    """
    Create or update a memory entry.

    Uses (category, key) as the logical primary key – sending the same key
    twice updates the existing entry instead of creating a duplicate.
    """
    return await memory_service.write_memory(db, payload)


# ─── Suggestions (must come BEFORE /{id} to avoid route conflict) ─────────────

@router.get("/memory/suggestions", response_model=List[SuggestionOut])
async def get_suggestions(
    db: AsyncSession = Depends(get_db),
) -> List[SuggestionOut]:
    """
    Run the suggestion engine and return actionable recommendation cards.

    Call this when the Memory page loads.  Suggestions are persisted in the DB
    with category='suggestions'; accepting/dismissing calls PATCH /memory/{id}.
    """
    return await memory_service.generate_suggestions(db)


# ─── Context for a command ────────────────────────────────────────────────────

@router.post("/memory/context", response_model=MemoryContext)
async def get_context(
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryContext:
    """
    Return relevant memory context for a given command.

    Useful for the frontend to preview which defaults will be applied before
    submitting the command to the planner.
    """
    return await memory_service.get_context_for_command(db, request.command)


# ─── Update ───────────────────────────────────────────────────────────────────

@router.patch("/memory/{entry_id}", response_model=MemoryEntryOut)
async def update_memory(
    entry_id: int,
    patch: MemoryEntryUpdate,
    db: AsyncSession = Depends(get_db),
) -> MemoryEntryOut:
    """
    Partial update for a memory entry.

    Common use-cases:
    - Pin / unpin:        PATCH with ``{"pinned": true}``
    - Accept suggestion:  PATCH with ``{"status": "active", "confidence": 1.0}``
    - Dismiss suggestion: PATCH with ``{"status": "dismissed"}``
    - Edit value:         PATCH with ``{"value": {...}}``
    """
    updated = await memory_service.update_memory(db, entry_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Memory entry {entry_id} not found.")
    return updated


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/memory/{entry_id}", status_code=204)
async def delete_memory(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a memory entry."""
    deleted = await memory_service.delete_memory(db, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory entry {entry_id} not found.")
