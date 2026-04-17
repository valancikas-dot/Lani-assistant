"""
Pipelines API – list available pipelines and their definitions.

GET  /api/v1/pipelines          → list all pipeline definitions
GET  /api/v1/pipelines/{id}     → single pipeline detail

Execution of a pipeline happens through the normal /api/v1/commands or
/api/v1/chat/stream endpoints: the command_router detects pipeline intent,
selects the matching pipeline, and runs it via pipeline_service.run_pipeline().
"""

from fastapi import APIRouter, HTTPException
from app.services.pipeline_service import list_pipelines, get_pipeline

router = APIRouter()


@router.get("/pipelines")
async def get_pipelines():
    """Return summary list of all available pipelines."""
    return {"pipelines": list_pipelines()}


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_detail(pipeline_id: str):
    """Return full definition of a single pipeline."""
    pipeline = get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
    return pipeline.to_dict()
