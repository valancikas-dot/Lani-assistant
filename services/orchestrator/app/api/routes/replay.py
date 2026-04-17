"""
Replay API – endpoints for execution chain replay and dry-run simulation.

Routes
──────
  GET  /api/v1/replay/{chain_id}           – Replay a stored execution chain
  GET  /api/v1/replay/{chain_id}/timeline  – Human-readable text timeline
  POST /api/v1/replay/simulate             – Dry-run simulate a list of steps
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


# ─── Request / response models ────────────────────────────────────────────────

class SimulateStepRequest(BaseModel):
    action: str
    inputs: Dict[str, Any] = {}


class SimulateRequest(BaseModel):
    steps: List[SimulateStepRequest]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/replay/{chain_id}", tags=["replay"])
async def get_replay(chain_id: str) -> Dict[str, Any]:
    """
    Replay a stored execution chain by its chain_id.

    Returns a structured ReplayResult dict with steps, timeline text,
    and final status.  Returns 404 if the chain is no longer in the
    in-memory ring buffer.
    """
    from app.services.replay_service import get_replay as _get_replay

    result = _get_replay(chain_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chain '{chain_id}' not found. "
                   "It may have been evicted from the ring buffer.",
        )
    return result.to_dict()


@router.get("/replay/{chain_id}/timeline", tags=["replay"])
async def get_timeline(chain_id: str) -> Dict[str, str]:
    """
    Return a human-readable text timeline for a given execution chain.
    """
    from app.services.replay_service import export_timeline

    text = export_timeline(chain_id)
    return {"chain_id": chain_id, "timeline": text}


@router.post("/replay/simulate", tags=["replay"])
async def simulate_steps(body: SimulateRequest) -> Dict[str, Any]:
    """
    Dry-run simulate a list of planned steps without executing them.

    Each step is evaluated against the capability registry and policy engine.
    No tool.run() calls are made.
    """
    from app.services.replay_service import simulate_chain

    raw_steps = [{"action": s.action, "inputs": s.inputs} for s in body.steps]
    simulated = simulate_chain(raw_steps)
    return {
        "total_steps": len(simulated),
        "steps": [s.to_dict() for s in simulated],
    }
