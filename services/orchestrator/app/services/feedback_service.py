"""
Feedback Service – stores and analyses user feedback (👍/👎) on responses.

Public API
──────────
  record_feedback(db, payload)          → FeedbackOut
  get_feedback_stats(db)                → FeedbackStats
  get_negative_commands(db, limit)      → list[str]  (commands that often get 👎)
  get_tool_accuracy(db)                 → dict[tool → accuracy_pct]
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import FeedbackEntry
from app.schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStats

log = logging.getLogger(__name__)


async def record_feedback(db: AsyncSession, payload: FeedbackCreate) -> FeedbackOut:
    """Save a feedback entry. Returns the saved record."""
    entry = FeedbackEntry(
        command=payload.command,
        response=payload.response[:500] if payload.response else "",
        tool=payload.tool or "chat",
        rating=1.0 if payload.positive else 0.0,
        comment=payload.comment or "",
        session_id=payload.session_id or "default",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    log.info("[feedback] recorded: tool=%s rating=%.0f", entry.tool, entry.rating)
    return FeedbackOut.model_validate(entry)


async def get_feedback_stats(db: AsyncSession) -> FeedbackStats:
    """
    Return overall stats:
      - total ratings
      - positive / negative counts
      - overall accuracy %
      - per-tool accuracy breakdown
    """
    result = await db.execute(
        select(
            FeedbackEntry.tool,
            func.count(FeedbackEntry.id).label("total"),
            func.sum(FeedbackEntry.rating).label("positives"),
        ).group_by(FeedbackEntry.tool)
    )
    rows = result.all()

    tool_stats: Dict[str, Dict[str, Any]] = {}
    overall_total = 0
    overall_positive = 0.0

    for tool, total, positives in rows:
        pos = float(positives or 0)
        pct = round(pos / total * 100, 1) if total else 0.0
        tool_stats[tool] = {
            "total": total,
            "positive": int(pos),
            "negative": total - int(pos),
            "accuracy_pct": pct,
        }
        overall_total += total
        overall_positive += pos

    overall_pct = round(overall_positive / overall_total * 100, 1) if overall_total else 0.0

    return FeedbackStats(
        total=overall_total,
        positive=int(overall_positive),
        negative=overall_total - int(overall_positive),
        accuracy_pct=overall_pct,
        by_tool=tool_stats,
    )


async def get_negative_commands(db: AsyncSession, limit: int = 20) -> List[str]:
    """
    Return a list of commands that repeatedly received negative feedback.
    Used by the planner to avoid repeating bad patterns.
    """
    result = await db.execute(
        select(FeedbackEntry.command)
        .where(FeedbackEntry.rating == 0.0)
        .order_by(FeedbackEntry.created_at.desc())
        .limit(limit)
    )
    return [row for (row,) in result.all()]


async def get_tool_accuracy(db: AsyncSession) -> Dict[str, float]:
    """Return {tool_name: accuracy_pct} mapping."""
    stats = await get_feedback_stats(db)
    return {tool: v["accuracy_pct"] for tool, v in stats.by_tool.items()}
