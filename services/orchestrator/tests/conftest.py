"""Pytest configuration for the orchestrator test suite.

Provides:
  - ``async_client``: an httpx AsyncClient wired to a fully-initialised app.
    Tables are created (via init_db), the UserSettings row is reset to factory
    defaults, and the voice-session singleton is reset before each test so
    tests are fully isolated from one another and from prior runs.
"""
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.main import create_app
from app.core.database import init_db, AsyncSessionLocal
from app.models.settings import UserSettings
from app.models.audit_log import AuditLog
from app.models.connector_account import ConnectorAccount
from app.models.connector_token import ConnectorToken
from app.services.voice_session_service import reset_session


async def _reset_settings_row() -> None:
    """Delete the persisted UserSettings row so the next request recreates it
    with ORM column defaults.  This prevents stale values (e.g. wake_word_enabled=True
    written by a previous test) from leaking into subsequent tests."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(UserSettings))
        await session.commit()


async def _truncate_audit_logs() -> None:
    """Remove all audit log rows so the table never exceeds the default query
    limit, preventing count-based assertions from becoming flaky over time."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AuditLog))
        await session.commit()


async def _truncate_connector_tables() -> None:
    """Remove all connector rows so each test starts with no connected accounts."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ConnectorToken))
        await session.execute(delete(ConnectorAccount))
        await session.commit()


@pytest_asyncio.fixture()
async def async_client():
    """Yield a ready-to-use AsyncClient for each test function.

    - Calls init_db() so all ORM tables exist (safe to call many times).
    - Deletes the UserSettings row so every test starts from clean defaults.
    - Truncates the audit_log table so count-based assertions are stable.
    - Resets the in-process voice-session singleton so state does not
      bleed between test cases.
    """
    await init_db()
    await _reset_settings_row()
    await _truncate_audit_logs()
    await _truncate_connector_tables()
    reset_session()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    # Ensure session is clean after the test too.
    reset_session()
