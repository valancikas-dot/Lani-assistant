"""Tests for the Mode System (Phase 11).

Covers:
  - mode_service: seed, list, activate/deactivate, set_modes, context block, custom modes
  - modes API: list, active, select, activate/deactivate, archive, suggestions
"""
import pytest

from app.core.database import init_db, AsyncSessionLocal
from app.services.mode_service import (
    seed_builtin_modes,
    list_modes,
    get_mode_by_slug,
    get_active_modes,
    activate_mode,
    deactivate_mode,
    set_modes,
    build_mode_context_block,
    create_custom_mode,
)
from app.models.mode import UserMode
from sqlalchemy import delete


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _clean_user_modes() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(UserMode))
        await session.commit()


# ─── Service Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_builtin_modes_idempotent():
    """Seeding twice should not create duplicate rows."""
    await init_db()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        modes_first = await list_modes(db)
        count_first = len(modes_first)

        await seed_builtin_modes(db)
        modes_second = await list_modes(db)
        count_second = len(modes_second)

    assert count_first == count_second
    assert count_first >= 7  # at least the 7 builtins


@pytest.mark.asyncio
async def test_list_modes_returns_builtins():
    """list_modes returns all 7 builtin modes after seeding."""
    await init_db()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        modes = await list_modes(db)

    slugs = {m.slug for m in modes}
    expected = {"developer", "researcher", "writer", "productivity", "communicator", "analyst", "student"}
    assert expected.issubset(slugs)


@pytest.mark.asyncio
async def test_activate_mode():
    """Activating a mode should make it appear in get_active_modes."""
    await init_db()
    await _clean_user_modes()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        mode = await get_mode_by_slug(db, "developer")
        assert mode is not None

        await activate_mode(db, mode.id, profile_id=None)
        active = await get_active_modes(db, profile_id=None)

    assert any(m.slug == "developer" for m in active)


@pytest.mark.asyncio
async def test_deactivate_mode():
    """Deactivating a mode should remove it from get_active_modes."""
    await init_db()
    await _clean_user_modes()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        mode = await get_mode_by_slug(db, "developer")
        assert mode is not None

        await activate_mode(db, mode.id, profile_id=None)
        await deactivate_mode(db, mode.id, profile_id=None)
        active = await get_active_modes(db, profile_id=None)

    assert all(m.slug != "developer" for m in active)


@pytest.mark.asyncio
async def test_set_modes_bulk_replaces_active():
    """set_modes atomically replaces any previously active modes."""
    await init_db()
    await _clean_user_modes()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        dev = await get_mode_by_slug(db, "developer")
        researcher = await get_mode_by_slug(db, "researcher")
        writer = await get_mode_by_slug(db, "writer")
        assert dev is not None
        assert researcher is not None
        assert writer is not None

        # Activate dev + researcher first
        await activate_mode(db, dev.id, profile_id=None)
        await activate_mode(db, researcher.id, profile_id=None)

        # set_modes to only writer
        await set_modes(db, [writer.id], profile_id=None)
        active = await get_active_modes(db, profile_id=None)

    active_slugs = {m.slug for m in active}
    assert active_slugs == {"writer"}


@pytest.mark.asyncio
async def test_build_mode_context_block_empty():
    """build_mode_context_block with an empty list returns empty string."""
    result = build_mode_context_block([])
    assert result == ""


@pytest.mark.asyncio
async def test_build_mode_context_block_with_modes():
    """build_mode_context_block includes mode names and hints when modes are active."""
    await init_db()
    await _clean_user_modes()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        dev = await get_mode_by_slug(db, "developer")
        assert dev is not None
        await activate_mode(db, dev.id, profile_id=None)
        active = await get_active_modes(db, profile_id=None)

    block = build_mode_context_block(active)
    assert block != ""
    assert "developer" in block.lower() or "Developer" in block


@pytest.mark.asyncio
async def test_create_custom_mode():
    """create_custom_mode creates a non-builtin mode with a derived slug."""
    await init_db()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        mode = await create_custom_mode(
            db,
            name="My Custom Mode",
            description="A test mode",
            tagline="Testing modes",
            system_prompt_hint="Focus on testing.",
        )

    assert mode is not None
    assert mode.is_builtin is False
    assert "my-custom-mode" in mode.slug


@pytest.mark.asyncio
async def test_create_custom_mode_slug_collision():
    """Creating two modes with the same name yields unique slugs."""
    await init_db()
    async with AsyncSessionLocal() as db:
        await seed_builtin_modes(db)
        mode1 = await create_custom_mode(db, name="Dupe Mode")
        mode2 = await create_custom_mode(db, name="Dupe Mode")

    assert mode1.slug != mode2.slug


# ─── API Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_modes(async_client):
    """GET /api/v1/modes returns ok=True and at least 7 builtin modes."""
    r = await async_client.get("/api/v1/modes")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["total"] >= 7
    slugs = {m["slug"] for m in data["modes"]}
    assert "developer" in slugs
    assert "researcher" in slugs


@pytest.mark.asyncio
async def test_api_get_active_modes_empty(async_client):
    """GET /api/v1/modes/active returns empty list when none are selected."""
    r = await async_client.get("/api/v1/modes/active")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["total"] == 0
    assert data["modes"] == []


@pytest.mark.asyncio
async def test_api_select_modes(async_client):
    """POST /api/v1/modes/select activates selected modes; GET /active reflects change."""
    # Get list to find some IDs
    r = await async_client.get("/api/v1/modes")
    assert r.status_code == 200
    modes = r.json()["modes"]
    ids = [m["id"] for m in modes[:2]]

    # Select first two
    r = await async_client.post("/api/v1/modes/select", json={"mode_ids": ids})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Active list should now have those two
    r = await async_client.get("/api/v1/modes/active")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    active_ids = {m["id"] for m in data["modes"]}
    assert set(ids) == active_ids


@pytest.mark.asyncio
async def test_api_activate_deactivate(async_client):
    """POST activate/deactivate toggles a mode's active state."""
    r = await async_client.get("/api/v1/modes")
    mode = r.json()["modes"][0]
    mode_id = mode["id"]

    # Activate
    r = await async_client.post(f"/api/v1/modes/{mode_id}/activate")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Should appear in active
    r = await async_client.get("/api/v1/modes/active")
    active_ids = {m["id"] for m in r.json()["modes"]}
    assert mode_id in active_ids

    # Deactivate
    r = await async_client.post(f"/api/v1/modes/{mode_id}/deactivate")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Should no longer appear in active
    r = await async_client.get("/api/v1/modes/active")
    active_ids = {m["id"] for m in r.json()["modes"]}
    assert mode_id not in active_ids


@pytest.mark.asyncio
async def test_api_archive_builtin_not_allowed(async_client):
    """POST /modes/{id}/archive on a builtin mode returns 400."""
    r = await async_client.get("/api/v1/modes")
    builtin = next(m for m in r.json()["modes"] if m["is_builtin"])
    r = await async_client.post(f"/api/v1/modes/{builtin['id']}/archive")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_mode_suggestions_no_history(async_client):
    """GET /api/v1/modes/suggestions succeeds even with no audit log history."""
    r = await async_client.get("/api/v1/modes/suggestions")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["suggestions"], list)


@pytest.mark.asyncio
async def test_api_get_mode_by_id(async_client):
    """GET /api/v1/modes/{id} returns the mode with is_active field."""
    r = await async_client.get("/api/v1/modes")
    mode = r.json()["modes"][0]
    mode_id = mode["id"]

    r = await async_client.get(f"/api/v1/modes/{mode_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["mode"]["id"] == mode_id
    assert "is_active" in data["mode"]
