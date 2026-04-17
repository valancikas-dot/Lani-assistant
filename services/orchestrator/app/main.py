"""
FastAPI entry point for the Lani orchestrator service.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import (
    health,
    commands,
    approvals,
    app_settings,
    api_keys,
    auth,
    tokens,
    payments,
    logs,
    voice,
    plans,
    memory,
    research,
    security,
    wake,
    builder,
    connectors,
    operator,
    workflow,
    system,
    stream,
    scheduler,
    feedback,
    vision,
    chat_stream,
    capabilities,
    policy,
    state,
    evals,
    voice_confirm,
    self_improvement,
    replay,
    chains,
    skill_proposals,
    skill_drafts,
    missions,
    installed_skills,
    profiles,
    modes,  # ← Phase 11: Mode System
    pipelines,  # ← Phase 12: Pipeline Execution System
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup, clean up on shutdown."""
    import asyncio
    settings.validate_production_secrets()
    await init_db()

    # Ensure a default profile exists
    from app.core.database import AsyncSessionLocal
    from app.services.profile_service import get_or_create_default
    async with AsyncSessionLocal() as _db:
        await get_or_create_default(_db)
        await _db.commit()

    # Seed built-in modes (Phase 11)
    from app.services.mode_service import seed_builtin_modes
    async with AsyncSessionLocal() as _db:
        await seed_builtin_modes(_db)
        await _db.commit()

    # Start proactive scheduler (APScheduler)
    from app.services import scheduler_service
    await scheduler_service.start_scheduler()

    # Start voice-confirmation TTL sweeper (every 30 s)
    async def _voice_confirm_sweeper():
        from app.services.voice_confirmation import sweep_expired_confirmations
        while True:
            await asyncio.sleep(30)
            try:
                await sweep_expired_confirmations()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "voice_confirm sweeper error: %s", exc
                )

    _sweeper_task = asyncio.create_task(_voice_confirm_sweeper())

    yield

    # Graceful shutdown
    _sweeper_task.cancel()
    await scheduler_service.stop_scheduler()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Lani – Orchestrator",
        description="Backend service for Lani, the local-first personal AI assistant",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Allow requests from the Tauri frontend (local origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(commands.router, prefix="/api/v1", tags=["commands"])
    app.include_router(approvals.router, prefix="/api/v1", tags=["approvals"])
    app.include_router(app_settings.router, prefix="/api/v1", tags=["settings"])
    app.include_router(api_keys.router, prefix="/api/v1", tags=["settings"])
    app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
    app.include_router(tokens.router, prefix="/api/v1", tags=["tokens"])
    app.include_router(payments.router, prefix="/api/v1", tags=["payments"])
    app.include_router(logs.router, prefix="/api/v1", tags=["logs"])
    app.include_router(voice.router, prefix="/api/v1", tags=["voice"])
    app.include_router(security.router, prefix="/api/v1", tags=["security"])
    app.include_router(plans.router, prefix="/api/v1", tags=["plans"])
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(research.router, prefix="/api/v1", tags=["research"])
    app.include_router(wake.router, prefix="/api/v1", tags=["wake"])
    app.include_router(builder.router, prefix="/api/v1", tags=["builder"])
    app.include_router(connectors.router, prefix="/api/v1", tags=["connectors"])
    app.include_router(operator.router, prefix="/api/v1", tags=["operator"])
    app.include_router(workflow.router, prefix="/api/v1", tags=["workflow"])
    app.include_router(system.router, prefix="/api/v1", tags=["system"])
    app.include_router(stream.router, prefix="/api/v1", tags=["stream"])
    app.include_router(scheduler.router, prefix="/api/v1", tags=["scheduler"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
    app.include_router(vision.router, prefix="/api/v1", tags=["vision"])
    app.include_router(chat_stream.router, prefix="/api/v1", tags=["chat"])
    # ── New core layer routers ────────────────────────────────────────────────
    app.include_router(capabilities.router, prefix="/api/v1", tags=["capabilities"])
    app.include_router(policy.router, prefix="/api/v1", tags=["policy"])
    app.include_router(state.router, prefix="/api/v1", tags=["state"])
    app.include_router(evals.router, prefix="/api/v1", tags=["evals"])
    app.include_router(voice_confirm.router, prefix="/api/v1", tags=["voice"])
    app.include_router(self_improvement.router, prefix="/api/v1", tags=["self-improvement"])
    app.include_router(replay.router, prefix="/api/v1", tags=["replay"])
    app.include_router(chains.router, prefix="/api/v1", tags=["chains"])
    # ── Phase 6: Skill Proposal Engine ───────────────────────────────────────
    app.include_router(skill_proposals.router, prefix="/api/v1", tags=["skill-proposals"])
    # ── Phase 7: Skill Scaffold Generator ────────────────────────────────────
    app.include_router(skill_drafts.router, prefix="/api/v1", tags=["skill-drafts"])
    # ── Phase 8: Autonomous Missions ─────────────────────────────────────────
    app.include_router(missions.router, prefix="/api/v1", tags=["missions"])
    # ── Phase 9: Installed Skills Registry ───────────────────────────────────
    app.include_router(installed_skills.router, prefix="/api/v1", tags=["installed-skills"])
    # ── Phase 10: Multi-profile / Team Mode ──────────────────────────────────
    app.include_router(profiles.router, prefix="/api/v1", tags=["profiles"])
    # ── Phase 11: Mode System ─────────────────────────────────────────────────
    app.include_router(modes.router, prefix="/api/v1", tags=["modes"])
    # ── Phase 12: Pipeline Execution System ──────────────────────────────────
    app.include_router(pipelines.router, prefix="/api/v1", tags=["pipelines"])

    return app


app = create_app()
