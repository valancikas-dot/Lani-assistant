"""
API route for the World State Model.

GET  /api/v1/state            – current world snapshot
POST /api/v1/state/apps       – update open apps list (from operator)
POST /api/v1/state/windows    – update windows list
POST /api/v1/state/tabs       – update browser tabs
DELETE /api/v1/state/reset    – reset world state (testing)
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from app.services.world_state import (
    get_state,
    record_tool_execution,
)

router = APIRouter()


@router.get("/state", tags=["state"])
async def get_world_state() -> Dict[str, Any]:
    """Return the current world state snapshot."""
    return get_state().snapshot()


@router.post("/state/apps", tags=["state"])
async def update_open_apps(body: Dict[str, Any]) -> Dict[str, Any]:
    """Update the list of open applications."""
    apps: List[Dict[str, Any]] = body.get("apps", [])
    get_state().update_open_apps(apps)
    return {"ok": True, "count": len(apps)}


@router.post("/state/windows", tags=["state"])
async def update_windows(body: Dict[str, Any]) -> Dict[str, Any]:
    """Update the list of active windows."""
    windows: List[Dict[str, Any]] = body.get("windows", [])
    get_state().update_windows(windows)
    return {"ok": True, "count": len(windows)}


@router.post("/state/tabs", tags=["state"])
async def update_browser_tabs(body: Dict[str, Any]) -> Dict[str, Any]:
    """Update the active browser tabs."""
    tabs: List[Dict[str, Any]] = body.get("tabs", [])
    get_state().update_browser_tabs(tabs)
    return {"ok": True, "count": len(tabs)}


@router.delete("/state/reset", tags=["state"])
async def reset_world_state() -> Dict[str, Any]:
    """Reset all world state (useful in testing)."""
    from app.services import world_state as _ws
    _ws._world_state = None
    return {"ok": True, "message": "World state reset."}
