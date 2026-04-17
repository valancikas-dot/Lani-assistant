"""
API routes for the Evaluation System.

GET  /api/v1/evals             – paginated recent eval logs
GET  /api/v1/evals/stats       – aggregated statistics
POST /api/v1/evals/rate/{id}   – set user rating on an eval log entry
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.eval_log import EvalLog
from app.services import eval_service

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/evals", tags=["evals"])
async def list_evals(
    limit: int = 50,
    tool: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return recent evaluation log entries."""
    rows = await eval_service.list_recent(db, limit=limit, tool_filter=tool)
    return {"evals": rows, "total": len(rows)}


@router.get("/evals/stats", tags=["evals"])
async def get_eval_stats(
    since_days: int = 30,
    tool: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return aggregated eval statistics."""
    return await eval_service.get_stats(db, since_days=since_days, tool_filter=tool)


@router.post("/evals/rate/{eval_id}", tags=["evals"])
async def rate_eval(
    eval_id: int,
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Set a user rating (1-5) on an eval log entry."""
    rating = int(body.get("rating", 0))
    if rating < 1 or rating > 5:
        return {"ok": False, "message": "Rating must be 1-5."}

    result = await db.execute(select(EvalLog).where(EvalLog.id == eval_id))
    row = result.scalar_one_or_none()
    if row is None:
        return {"ok": False, "message": "Eval log entry not found."}

    row.user_rating = rating
    await db.flush()
    return {"ok": True, "eval_id": eval_id, "rating": rating}
