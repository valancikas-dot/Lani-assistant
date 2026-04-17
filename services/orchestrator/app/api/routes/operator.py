"""Computer Operator API routes.

Endpoints
─────────
GET  /operator/capabilities   → OperatorManifest
GET  /operator/windows        → list of open windows
POST /operator/action         → execute a desktop action (with approval gate)
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.operator import (
    OperatorActionRequest,
    OperatorActionResponse,
    OperatorManifest,
)
from app.services.approval_service import create_approval_request
from app.services.audit_service import record_action
from app.services.operator import get_manifest, get_operator
from app.services.operator.macos_operator import DESTRUCTIVE_SHORTCUT_COMBOS

router = APIRouter(prefix="/operator", tags=["operator"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _shortcut_needs_approval(params: Dict[str, Any]) -> bool:
    raw_keys = params.get("keys", [])
    if isinstance(raw_keys, str):
        raw_keys = [k.strip() for k in raw_keys.replace("+", ",").split(",")]
    key_set = frozenset(k.lower().strip() for k in raw_keys if str(k).strip())
    return key_set in DESTRUCTIVE_SHORTCUT_COMBOS


def _action_needs_approval(action: str, params: Dict[str, Any]) -> bool:
    if action in {"type_text", "close_window"}:
        return True
    if action == "press_shortcut":
        return _shortcut_needs_approval(params)
    return False


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/capabilities", response_model=OperatorManifest)
async def get_capabilities() -> OperatorManifest:
    """Return the capability manifest for the current platform."""
    return get_manifest()


@router.get("/windows")
async def list_windows(db: AsyncSession = Depends(get_db)):
    """Return a list of visible application windows."""
    operator = get_operator()
    result = await operator.execute("list_open_windows", {})
    await record_action(
        db,
        command="operator.list_open_windows",
        tool_name="operator.list_open_windows",
        status="success" if result.ok else "error",
        result_summary=result.message,
    )
    return {
        "ok": result.ok,
        "windows": result.data or [],
        "message": result.message,
        "platform": operator.platform_display,
    }


@router.post("/action", response_model=OperatorActionResponse)
async def run_action(
    body: OperatorActionRequest,
    db: AsyncSession = Depends(get_db),
) -> OperatorActionResponse:
    """Execute a desktop action, creating an approval request when required."""
    operator = get_operator()
    manifest = get_manifest()
    platform = operator.platform_display

    # ── Look up the capability ────────────────────────────────────────────────
    capability = next(
        (c for c in manifest.capabilities if c.name == body.action), None
    )

    # ── Approval gate ─────────────────────────────────────────────────────────
    needs_approval = capability.requires_approval if capability else False
    # Dynamic check for press_shortcut (depends on the actual key combo).
    if not needs_approval:
        needs_approval = _action_needs_approval(body.action, body.params)

    if needs_approval:
        approval_id = await create_approval_request(
            db,
            tool_name=f"operator.{body.action}",
            command=body.action,
            params=body.params,
        )
        await record_action(
            db,
            command=f"operator.{body.action}",
            tool_name=f"operator.{body.action}",
            status="approval_required",
            result_summary=f"Approval requested (id={approval_id})",
        )
        return OperatorActionResponse(
            ok=False,
            action=body.action,
            message=f"This action requires approval before it can be executed.",
            requires_approval=True,
            approval_id=approval_id,
            platform=platform,
        )

    # ── Execute ───────────────────────────────────────────────────────────────
    result = await operator.execute(body.action, body.params)

    await record_action(
        db,
        command=f"operator.{body.action}",
        tool_name=f"operator.{body.action}",
        status="success" if result.ok else "error",
        result_summary=result.message,
        error_message="" if result.ok else result.message,
    )

    return OperatorActionResponse(
        ok=result.ok,
        action=body.action,
        message=result.message,
        data=result.data,
        platform=platform,
    )
