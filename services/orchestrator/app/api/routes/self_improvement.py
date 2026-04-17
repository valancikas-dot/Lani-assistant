"""
API routes for the Self-Improvement Pipeline.

GET  /api/v1/self-improvement/proposals            – list proposals
GET  /api/v1/self-improvement/proposals/{id}       – get single proposal
POST /api/v1/self-improvement/cycle                – trigger improvement cycle
POST /api/v1/self-improvement/proposals/{id}/approve – deploy an approved proposal
POST /api/v1/self-improvement/proposals/{id}/reject  – reject a proposal
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services import self_improvement_service as svc

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/self-improvement/proposals", tags=["self-improvement"])
async def list_proposals() -> Dict[str, Any]:
    """Return all improvement proposals."""
    proposals = svc.get_proposals()
    return {"proposals": proposals, "total": len(proposals)}


@router.get("/self-improvement/proposals/{proposal_id}", tags=["self-improvement"])
async def get_proposal(proposal_id: str) -> Dict[str, Any]:
    """Return a single improvement proposal."""
    prop = svc.get_proposal(proposal_id)
    if prop is None:
        return {"ok": False, "message": "Proposal not found."}
    return {"ok": True, "proposal": prop.to_dict()}


@router.post("/self-improvement/cycle", tags=["self-improvement"])
async def trigger_cycle(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Trigger a full improvement detection cycle."""
    created = await svc.run_improvement_cycle(db)
    return {
        "ok": True,
        "proposals_created": len(created),
        "proposals": [p.to_dict() for p in created],
    }


@router.post("/self-improvement/proposals/{proposal_id}/approve", tags=["self-improvement"])
async def approve_proposal(proposal_id: str) -> Dict[str, Any]:
    """Deploy an approved self-improvement proposal."""
    prop = svc.get_proposal(proposal_id)
    if prop is None:
        return {"ok": False, "message": "Proposal not found."}

    result = svc.deploy_proposal(prop)
    return {
        "ok": result.ok,
        "message": result.message,
        "plugin_path": result.plugin_path,
    }


@router.post("/self-improvement/proposals/{proposal_id}/reject", tags=["self-improvement"])
async def reject_proposal(proposal_id: str) -> Dict[str, Any]:
    """Reject a self-improvement proposal."""
    svc.reject_proposal(proposal_id)
    return {"ok": True, "message": f"Proposal {proposal_id} rejected."}
