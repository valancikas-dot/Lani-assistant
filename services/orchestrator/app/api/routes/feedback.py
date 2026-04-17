"""
API routes for user feedback (👍 / 👎) on assistant responses.

Endpoints:
  POST  /api/v1/feedback          – submit a rating for a response
  GET   /api/v1/feedback/stats    – overall accuracy + per-tool breakdown
  GET   /api/v1/feedback/negatives – list recently down-voted commands
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStats
from app.services import feedback_service

router = APIRouter()


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
async def submit_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit thumbs-up or thumbs-down for a command/response pair.

    Example body:
    ```json
    {
      "command": "ieškoti oro prognozės",
      "response": "Šiandien Vilniuje 12°C, debesuota.",
      "tool": "web_search",
      "positive": true
    }
    ```
    """
    entry = await feedback_service.record_feedback(db, payload)

    # Trigger self-reflection on negative feedback (non-blocking)
    if not payload.positive:
        try:
            import asyncio
            from app.services.self_reflection_service import reflect_on_failure
            asyncio.create_task(reflect_on_failure(
                command=payload.command,
                response=payload.response or "",
                tool=payload.tool or "chat",
                comment=payload.comment or "",
            ))
        except Exception:
            pass

    return entry


@router.get("/feedback/stats", response_model=FeedbackStats)
async def feedback_stats(db: AsyncSession = Depends(get_db)):
    """Return overall accuracy and per-tool breakdown."""
    return await feedback_service.get_feedback_stats(db)


@router.get("/feedback/negatives", response_model=List[str])
async def negative_commands(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Return the most recently down-voted commands (for debugging / improvement)."""
    return await feedback_service.get_negative_commands(db, limit=limit)
