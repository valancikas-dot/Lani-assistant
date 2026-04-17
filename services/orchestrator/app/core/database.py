"""
Async SQLite database setup using SQLAlchemy + aiosqlite.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def _run_migrations(conn) -> None:
    """
    Apply incremental schema migrations that SQLAlchemy create_all cannot handle
    (adding columns to existing tables).  Each ALTER is idempotent via
    'column not exists' checks so it is safe to run on every startup.
    """
    # ── memory_entries: add embedding column (introduced for semantic search) ──
    try:
        await conn.execute(
            text("ALTER TABLE memory_entries ADD COLUMN embedding JSON")
        )
        log.info("[db] migration: added memory_entries.embedding column")
    except Exception:
        pass  # column already exists – SQLite raises OperationalError

    # ── approval_requests: add execution_context column (plan resume support) ──
    try:
        await conn.execute(
            text("ALTER TABLE approval_requests ADD COLUMN execution_context JSON")
        )
        log.info("[db] migration: added approval_requests.execution_context column")
    except Exception:
        pass  # column already exists – SQLite raises OperationalError

    # ── skill_proposals: Phase 6.5 feedback + ranking columns ────────────────
    _sp_migrations = [
        ("feedback_score",   "REAL    NOT NULL DEFAULT 0.0"),
        ("feedback_count",   "INTEGER NOT NULL DEFAULT 0"),
        ("last_feedback_at", "DATETIME"),
        ("dismissed",        "BOOLEAN NOT NULL DEFAULT 0"),
        ("relevance_score",  "REAL    NOT NULL DEFAULT 0.0"),
        ("suppressed_by",    "VARCHAR(64)"),
        ("why_suggested",    "VARCHAR(400)"),
    ]
    for col_name, col_def in _sp_migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE skill_proposals ADD COLUMN {col_name} {col_def}")
            )
            log.info("[db] migration: added skill_proposals.%s column", col_name)
        except Exception:
            pass  # column already exists

    # ── skill_drafts: Phase 7 – create table guard columns ───────────────────
    # The table is created by create_all, but we add ALTER TABLE guards for
    # any columns that may have been added in patch releases.
    _sd_migrations: list[tuple[str, str]] = [
        # reserved for future patch columns
    ]
    for col_name, col_def in _sd_migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE skill_drafts ADD COLUMN {col_name} {col_def}")
            )
            log.info("[db] migration: added skill_drafts.%s column", col_name)
        except Exception:
            pass  # column already exists

    # ── missions / mission_checkpoints: Phase 8 – guard columns ──────────────
    # Tables are created by create_all; guards reserved for future patches.
    _mission_migrations: list[tuple[str, str]] = [
        # reserved for future patch columns
    ]
    for col_name, col_def in _mission_migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE missions ADD COLUMN {col_name} {col_def}")
            )
            log.info("[db] migration: added missions.%s column", col_name)
        except Exception:
            pass  # column already exists

    # ── installed_skills / installed_skill_versions: Phase 9 – guard columns ─
    # Tables are created by create_all; guards reserved for future patches.
    _is_migrations: list[tuple[str, str]] = [
        # reserved for future patch columns
    ]
    for col_name, col_def in _is_migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE installed_skills ADD COLUMN {col_name} {col_def}")
            )
            log.info("[db] migration: added installed_skills.%s column", col_name)
        except Exception:
            pass  # column already exists

    # ── Phase 10: Multi-profile – add profile_id to scoped tables ────────────
    # profile_id is nullable so legacy rows (created before Phase 10) are
    # preserved and continue to work – they simply have no profile association.
    _p10_tables = [
        "missions",
        "skill_proposals",
        "skill_drafts",
        "installed_skills",
        "approval_requests",
    ]
    for tbl in _p10_tables:
        try:
            await conn.execute(
                text(f"ALTER TABLE {tbl} ADD COLUMN profile_id INTEGER")
            )
            log.info("[db] migration: added %s.profile_id column", tbl)
        except Exception:
            pass  # column already exists – SQLite raises OperationalError


    # ── Phase 11: Mode System ────────────────────────────────────────────────
    # modes and user_modes tables are created by create_all (via the Mode /
    # UserMode ORM models). Guard ALTER statements are reserved for future patches.
    _mode_migrations: list[tuple[str, str]] = [
        # reserved for future patch columns
    ]
    for col_name, col_def in _mode_migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE modes ADD COLUMN {col_name} {col_def}")
            )
            log.info("[db] migration: added modes.%s column", col_name)
        except Exception:
            pass  # column already exists


async def init_db() -> None:
    """Create all tables and run incremental migrations on startup."""
    # Import models so they are registered with Base before create_all
    from app.models import (
        audit_log,
        approval_request,
        settings as settings_model,
        memory_entry,
        voice_profile,
        connector_account,
        connector_token,
        conversation,
        feedback,
        episodic_memory,
        eval_log,       # ← Part 6: Evaluation System
        skill_proposal,  # ← Phase 6: Skill Proposal Engine
        skill_draft,     # ← Phase 7: Skill Scaffold Generator
        mission,         # ← Phase 8: Autonomous Missions
        mission_checkpoint,  # ← Phase 8: Autonomous Missions
        installed_skill,          # ← Phase 9: Installed Skills Registry
        installed_skill_version,  # ← Phase 9: Installed Skills Versioning
        profile,                  # ← Phase 10: Multi-profile / Team Mode
        mode,                     # ← Phase 11: Mode System
        # user_mode is part of the mode module
        user,                     # ← Users / auth
        token_ledger,             # ← Token economy
    )  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db():
    """FastAPI dependency – yields a scoped async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
