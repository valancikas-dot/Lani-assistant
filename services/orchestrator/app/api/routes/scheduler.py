"""
API routes for the proactive task scheduler.

Endpoints:
  POST   /api/v1/scheduler/tasks        – schedule a new task (auto-parse or explicit)
  GET    /api/v1/scheduler/tasks        – list all active scheduled tasks
  DELETE /api/v1/scheduler/tasks/{id}   – cancel a scheduled task
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    command: str
    """Natural-language command to execute when the trigger fires."""

    run_at: Optional[datetime] = None
    """One-time execution time (UTC).  Leave None to use cron_expr or auto-parse."""

    cron_expr: Optional[str] = None
    """Cron expression (5-part: minute hour day month dow).  Leave None to use run_at or auto-parse."""

    auto_parse: bool = True
    """
    When True (default), attempt to extract scheduling intent from the command
    string itself (e.g. "primink rytoj 9:00 …").  run_at/cron_expr override
    auto-detected values if supplied.
    """


class ScheduleResponse(BaseModel):
    id: str
    command: str
    trigger: Dict[str, Any]
    created_at: str
    status: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/scheduler/tasks", response_model=ScheduleResponse, status_code=201)
async def create_scheduled_task(
    req: ScheduleRequest,
    db=Depends(get_db),
):
    """
    Schedule a task.

    If neither `run_at` nor `cron_expr` is provided and `auto_parse` is True,
    the command string is scanned for a time phrase (e.g. "rytoj 9:00",
    "kiekvieną rytą", "po 30 minučių").
    """
    from app.services import scheduler_service

    run_at = req.run_at
    cron_expr = req.cron_expr
    clean_command = req.command

    # Auto-detect scheduling intent from command text
    if req.auto_parse and run_at is None and cron_expr is None:
        parsed = await scheduler_service.parse_schedule_from_command(req.command)
        if parsed["detected"]:
            run_at = parsed["run_at"]
            cron_expr = parsed["cron_expr"]
            clean_command = parsed["clean_command"].strip() or req.command

    if run_at is None and cron_expr is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not detect a schedule from the command. "
                "Please supply run_at (datetime) or cron_expr (5-part cron string)."
            ),
        )

    try:
        task = await scheduler_service.schedule_task(
            command=clean_command,
            run_at=run_at,
            cron_expr=cron_expr,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ScheduleResponse(**task)


@router.get("/scheduler/tasks", response_model=List[ScheduleResponse])
async def get_scheduled_tasks(db=Depends(get_db)):
    """List all active scheduled tasks."""
    from app.services import scheduler_service
    tasks = await scheduler_service.list_tasks(db)
    return [ScheduleResponse(**t) for t in tasks]


@router.delete("/scheduler/tasks/{task_id}", status_code=204)
async def cancel_scheduled_task(task_id: str, db=Depends(get_db)):
    """Cancel and delete a scheduled task by ID."""
    from app.services import scheduler_service
    removed = await scheduler_service.delete_task(task_id, db)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found.")
