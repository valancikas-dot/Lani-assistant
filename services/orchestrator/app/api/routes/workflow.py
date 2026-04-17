"""
Workflow API – runs multi-step cross-tool automation workflows.

Routes
──────
POST /workflow/run          – plan and execute a workflow
GET  /workflow/status/{id}  – retrieve a completed/in-progress workflow result
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.workflow import WorkflowRequest, WorkflowResult
from app.services.workflow_planner import plan_workflow
from app.services.workflow_executor import execute_workflow

router = APIRouter()

# In-memory store for completed workflow results (keyed by workflow_id).
# Sufficient for MVP; replace with a DB-backed store for persistence.
_workflow_store: Dict[str, WorkflowResult] = {}


@router.post(
    "/workflow/run",
    response_model=WorkflowResult,
    summary="Run a multi-step cross-tool workflow",
    tags=["workflow"],
)
async def run_workflow(
    request: WorkflowRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResult:
    """
    Plan and execute a cross-tool automation workflow from a natural-language goal.

    The planner detects which workflow archetype the goal implies and builds an
    ordered plan.  The executor runs each step sequentially, piping artifacts
    (file paths, summaries, draft IDs) into subsequent steps.

    Returns a ``WorkflowResult`` with:
    - ``steps`` – per-step status and any artifacts produced
    - ``artifacts`` – flat list of all artifacts (files, email drafts, etc.)
    - ``overall_status`` – completed | failed | approval_required | partial
    - ``tts_text`` – optional short sentence for voice read-back
    """
    plan = plan_workflow(request.goal)
    if plan is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not determine a workflow plan for the given goal. "
                "Try rephrasing or use a more specific command."
            ),
        )

    result = await execute_workflow(
        plan,
        db,
        tts_response=request.tts_response,
    )

    # Cache for status polling
    _workflow_store[result.workflow_id] = result

    return result


@router.get(
    "/workflow/status/{workflow_id}",
    response_model=WorkflowResult,
    summary="Get the status / result of a workflow run",
    tags=["workflow"],
)
async def get_workflow_status(workflow_id: str) -> WorkflowResult:
    """
    Retrieve a previously-run workflow result by its ``workflow_id``.

    The workflow result is stored in memory after each ``POST /workflow/run``
    call.  Results persist for the lifetime of the server process.
    """
    result = _workflow_store.get(workflow_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' not found. "
                   "It may have expired or never existed.",
        )
    return result
