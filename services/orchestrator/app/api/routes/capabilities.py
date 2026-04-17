"""
API routes for the Capability Registry.

GET  /api/v1/capabilities          – list all capabilities
GET  /api/v1/capabilities/{name}   – get a single capability
POST /api/v1/capabilities/refresh  – force registry rebuild
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.services.capability_registry import (
    get_capability,
    list_capabilities,
    refresh_registry,
)

router = APIRouter()


@router.get("/capabilities", tags=["capabilities"])
async def get_all_capabilities(
    category: Optional[str] = None,
    risk_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Return all registered capabilities, optionally filtered."""
    caps = list_capabilities()
    if category:
        caps = [c for c in caps if c.get("category") == category]
    if risk_level:
        caps = [c for c in caps if c.get("risk_level") == risk_level]
    return {"capabilities": caps, "total": len(caps)}


@router.get("/capabilities/{name}", tags=["capabilities"])
async def get_single_capability(name: str) -> Dict[str, Any]:
    """Return metadata for a single capability by tool name."""
    cap = get_capability(name)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Capability '{name}' not found.")
    return cap.to_dict()


@router.post("/capabilities/refresh", tags=["capabilities"])
async def refresh_capabilities() -> Dict[str, Any]:
    """Force a rebuild of the capability registry (e.g. after plugin install)."""
    refresh_registry()
    caps = list_capabilities()
    return {"ok": True, "total": len(caps), "message": "Capability registry refreshed."}
