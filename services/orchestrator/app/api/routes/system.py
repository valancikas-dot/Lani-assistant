"""
System diagnostics endpoint.

GET /api/v1/system/status returns a structured readiness report the
frontend renders on the Diagnostics page.  The endpoint is intentionally
*read-only* and *free of side effects* so it can be polled safely.

What is checked
───────────────
1.  environment       – APP_ENV value (development / production / test)
2.  database          – can we reach SQLite? (simple SELECT 1)
3.  encryption        – is CONNECTOR_ENCRYPTION_KEY set *and* valid?
4.  voice_profile     – is at least one enrolled voice profile stored?
5.  connected_accounts – count of active connector accounts
6.  voice_provider    – is a real STT/TTS provider configured?
7.  platform          – underlying OS / operator platform
8.  openai_key        – is OPENAI_API_KEY set? (does NOT validate it)
9.  secret_key        – is SECRET_KEY set?
10. stt_enabled       – settings.STT_ENABLED flag
11. tts_enabled       – settings.TTS_ENABLED flag
"""

from __future__ import annotations

import logging
import platform
import sys
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

log = logging.getLogger(__name__)
router = APIRouter()


# ─── Response schema ──────────────────────────────────────────────────────────

class ComponentStatus(BaseModel):
    ok: bool
    label: str
    detail: Optional[str] = None


class SystemStatusResponse(BaseModel):
    """Full system readiness report."""

    # Overall convenience flag
    ready: bool

    # Individual components
    environment: ComponentStatus
    database: ComponentStatus
    encryption: ComponentStatus
    openai_key: ComponentStatus
    secret_key: ComponentStatus
    voice_provider: ComponentStatus
    voice_biometrics: ComponentStatus
    stt: ComponentStatus
    tts: ComponentStatus
    voice_profile: ComponentStatus
    connected_accounts: ComponentStatus
    platform: ComponentStatus

    # Extended diagnostics
    scheduler: ComponentStatus
    memory_stats: Optional[dict] = None
    feedback_stats: Optional[dict] = None
    tools_registered: int = 0
    tool_names: list = []
    db_size_kb: Optional[float] = None
    scheduled_tasks_count: int = 0
    token_usage_today: Optional[dict] = None

    # Raw values useful for display
    app_env: str
    app_version: str = "0.1.0"
    python_version: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _check_encryption() -> ComponentStatus:
    """Return whether a real (non-dev) encryption key is configured."""
    key = settings.CONNECTOR_ENCRYPTION_KEY
    if key:
        # Briefly validate it looks like a valid Fernet key
        try:
            import base64
            decoded = base64.urlsafe_b64decode(key + "==")
            if len(decoded) == 32:
                return ComponentStatus(ok=True, label="Real key configured", detail=None)
            return ComponentStatus(
                ok=False,
                label="Key format invalid",
                detail="CONNECTOR_ENCRYPTION_KEY must be a 32-byte base64 Fernet key.",
            )
        except Exception as exc:
            return ComponentStatus(ok=False, label="Key decode error", detail=str(exc))
    else:
        if settings.is_production:
            return ComponentStatus(
                ok=False,
                label="Not configured (REQUIRED in production)",
                detail="Set CONNECTOR_ENCRYPTION_KEY in your .env file.",
            )
        return ComponentStatus(
            ok=False,
            label="Using dev key",
            detail=(
                "CONNECTOR_ENCRYPTION_KEY is not set. "
                "A deterministic development key is in use — safe for local dev only."
            ),
        )


async def _check_database(db: AsyncSession) -> ComponentStatus:
    try:
        await db.execute(text("SELECT 1"))
        return ComponentStatus(ok=True, label="Connected")
    except Exception as exc:
        return ComponentStatus(ok=False, label="Unreachable", detail=str(exc))


async def _check_voice_profile(db: AsyncSession) -> ComponentStatus:
    try:
        from app.models.voice_profile import VoiceProfile
        from sqlalchemy import select, func
        result = await db.execute(select(func.count()).select_from(VoiceProfile))
        count: int = result.scalar_one()
        if count > 0:
            return ComponentStatus(ok=True, label=f"{count} profile(s) enrolled")
        return ComponentStatus(ok=False, label="No voice profile enrolled",
                               detail="Enroll a voice profile in Settings → Security to enable speaker verification.")
    except Exception as exc:
        return ComponentStatus(ok=False, label="Error reading profiles", detail=str(exc))


async def _check_connected_accounts(db: AsyncSession) -> ComponentStatus:
    try:
        from app.models.connector_account import ConnectorAccount
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.count()).select_from(ConnectorAccount)
            .where(ConnectorAccount.is_active == True)  # noqa: E712
        )
        count: int = result.scalar_one()
        label = f"{count} account(s) connected" if count else "No accounts connected"
        return ComponentStatus(ok=count > 0, label=label,
                               detail=None if count else "Connect Google or other accounts in the Connectors page.")
    except Exception as exc:
        return ComponentStatus(ok=False, label="Error reading accounts", detail=str(exc))


def _check_voice_provider() -> ComponentStatus:
    provider = settings.VOICE_PROVIDER
    if provider and provider != "placeholder":
        return ComponentStatus(ok=True, label=f"Provider: {provider}")
    return ComponentStatus(
        ok=False,
        label="Placeholder only",
        detail="Set VOICE_PROVIDER=openai (plus OPENAI_API_KEY) in services/orchestrator/.env to enable real STT/TTS.",
    )


def _check_voice_biometrics() -> ComponentStatus:
    """Report optional numpy-backed voice biometrics availability."""
    try:
        from app.services.voice_profile_service import get_voice_biometrics_availability

        info = get_voice_biometrics_availability()
        if bool(info.get("available", False)):
            return ComponentStatus(ok=True, label="Available")
        return ComponentStatus(
            ok=False,
            label="Unavailable",
            detail=str(info.get("reason_if_unavailable") or "unknown reason"),
        )
    except Exception as exc:
        return ComponentStatus(ok=False, label="Error", detail=str(exc))


def _check_platform() -> ComponentStatus:
    sys_name = platform.system()
    machine = platform.machine()
    detail = f"{sys_name} {platform.release()} ({machine})"
    supported = sys_name in ("Darwin", "Windows", "Linux")
    label = sys_name if supported else f"Unsupported: {sys_name}"
    return ComponentStatus(ok=supported, label=label, detail=detail)


def _check_scheduler() -> ComponentStatus:
    try:
        from app.services.scheduler_service import _scheduler, _APSCHEDULER_AVAILABLE
        if not _APSCHEDULER_AVAILABLE:
            return ComponentStatus(ok=False, label="apscheduler not installed",
                                   detail="pip install apscheduler")
        if _scheduler and _scheduler.running:
            jobs = len(_scheduler.get_jobs())
            return ComponentStatus(ok=True, label=f"Running ({jobs} active job(s))")
        return ComponentStatus(ok=False, label="Not running")
    except Exception as exc:
        return ComponentStatus(ok=False, label="Error", detail=str(exc))


async def _get_memory_stats(db: AsyncSession) -> dict:
    try:
        from app.services.memory_service import get_all
        all_entries = await get_all(db)
        by_category: dict = {}
        for e in all_entries:
            cat = e.category
            by_category[cat] = by_category.get(cat, 0) + 1
        return {"total": len(all_entries), "by_category": by_category}
    except Exception:
        return {}


async def _get_feedback_stats_safe(db: AsyncSession) -> dict:
    try:
        from app.services.feedback_service import get_feedback_stats
        stats = await get_feedback_stats(db)
        return stats.model_dump()
    except Exception:
        return {}


def _get_db_size_kb() -> Optional[float]:
    try:
        import os
        db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        size = os.path.getsize(db_path)
        return round(size / 1024, 1)
    except Exception:
        return None


def _get_tools_info() -> tuple[int, list]:
    try:
        from app.tools.registry import _TOOL_LIST  # type: ignore[attr-defined]
        names = [t.name for t in _TOOL_LIST]
        return len(names), names
    except Exception:
        return 0, []


async def _get_scheduled_tasks_count(db: AsyncSession) -> int:
    try:
        from app.services.scheduler_service import list_tasks
        tasks = await list_tasks(db)
        return len(tasks)
    except Exception:
        return 0


# ─── Route ────────────────────────────────────────────────────────────────────

@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(db: AsyncSession = Depends(get_db)) -> SystemStatusResponse:
    """
    Return a structured system readiness report.

    This endpoint is safe to poll frequently – it makes only lightweight
    read queries against SQLite and inspects environment variables in memory.
    """
    db_status = await _check_database(db)
    voice_profile_status = await _check_voice_profile(db)
    accounts_status = await _check_connected_accounts(db)

    env_is_prod = settings.is_production
    environment = ComponentStatus(
        ok=True,
        label="production" if env_is_prod else settings.APP_ENV,
        detail="Production mode – secrets required." if env_is_prod else None,
    )

    encryption = _check_encryption()

    openai_key = ComponentStatus(
        ok=bool(settings.OPENAI_API_KEY),
        label="Set" if settings.OPENAI_API_KEY else "Not set",
        detail=None if settings.OPENAI_API_KEY else "Set OPENAI_API_KEY in .env to enable LLM features.",
    )

    secret_key = ComponentStatus(
        ok=bool(settings.SECRET_KEY),
        label="Set" if settings.SECRET_KEY else "Not set (dev mode)",
        detail=None if settings.SECRET_KEY else "Set SECRET_KEY in .env for production use.",
    )

    voice_provider = _check_voice_provider()

    stt = ComponentStatus(
        ok=settings.STT_ENABLED,
        label="Enabled" if settings.STT_ENABLED else "Disabled",
        detail=None,
    )

    tts = ComponentStatus(
        ok=settings.TTS_ENABLED,
        label="Enabled" if settings.TTS_ENABLED else "Disabled",
        detail=None,
    )

    platform_status = _check_platform()
    scheduler_status = _check_scheduler()
    memory_stats = await _get_memory_stats(db)
    feedback_stats = await _get_feedback_stats_safe(db)
    db_size_kb = _get_db_size_kb()
    tools_count, tool_names = _get_tools_info()
    scheduled_count = await _get_scheduled_tasks_count(db)

    # Token usage today
    token_usage_today: Optional[dict] = None
    try:
        from app.services.token_tracker import get_usage_today
        summary = get_usage_today()
        token_usage_today = {
            "total_tokens": summary.total_tokens,
            "estimated_usd": round(summary.estimated_usd, 6),
            "by_model": summary.by_model,
        }
    except Exception:
        pass

    # Overall readiness: DB must be up; in production encryption must be real
    ready = (
        db_status.ok
        and (not env_is_prod or encryption.ok)
    )

    return SystemStatusResponse(
        ready=ready,
        environment=environment,
        database=db_status,
        encryption=encryption,
        openai_key=openai_key,
        secret_key=secret_key,
        voice_provider=voice_provider,
    voice_biometrics=_check_voice_biometrics(),
        stt=stt,
        tts=tts,
        voice_profile=voice_profile_status,
        connected_accounts=accounts_status,
        platform=platform_status,
        scheduler=scheduler_status,
        memory_stats=memory_stats,
        feedback_stats=feedback_stats,
        db_size_kb=db_size_kb,
        tools_registered=tools_count,
        tool_names=tool_names,
        scheduled_tasks_count=scheduled_count,
        token_usage_today=token_usage_today,
        app_env=settings.APP_ENV,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
