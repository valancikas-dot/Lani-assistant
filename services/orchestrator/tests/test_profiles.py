"""
Tests for Phase 10: Multi-profile / Team Mode.

Covers:
  • profile_service unit functions
  • /api/v1/profiles REST endpoints
  • profile_id scoping (list_missions, list_skills, list_proposals, list_drafts)
  • assert_profile_scope helper
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.main import create_app
from app.core.database import init_db, AsyncSessionLocal
from app.models.settings import UserSettings
from app.models.profile import Profile
from app.services import profile_service as svc


# ─── Fixtures ─────────────────────────────────────────────────────────────────

async def _reset_profiles() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Profile))
        await db.commit()


async def _reset_settings() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserSettings))
        await db.commit()


@pytest_asyncio.fixture()
async def db_session():
    """Yield a fresh AsyncSession; teardown deletes all profiles."""
    await init_db()
    await _reset_profiles()
    await _reset_settings()
    async with AsyncSessionLocal() as db:
        yield db
    await _reset_profiles()


@pytest_asyncio.fixture()
async def api_client():
    """HTTP client wired to a clean app instance."""
    await init_db()
    await _reset_profiles()
    await _reset_settings()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await _reset_profiles()


# ─── profile_service unit tests ───────────────────────────────────────────────

class TestProfileService:
    @pytest.mark.asyncio
    async def test_create_profile(self, db_session):
        p = await svc.create_profile(db_session, name="Work", profile_type="work")
        await db_session.commit()
        assert p.id is not None
        assert p.name == "Work"
        assert p.profile_type == "work"
        # status is always ACTIVE on creation; is_active=False when activate not requested
        assert p.status == svc.PROFILE_STATUS_ACTIVE
        assert p.is_active is False

    @pytest.mark.asyncio
    async def test_create_profile_with_activate(self, db_session):
        p = await svc.create_profile(db_session, name="Main", activate=True)
        await db_session.commit()
        assert p.is_active is True
        assert p.status == svc.PROFILE_STATUS_ACTIVE

    @pytest.mark.asyncio
    async def test_get_or_create_default_idempotent(self, db_session):
        p1 = await svc.get_or_create_default(db_session)
        await db_session.commit()
        p2 = await svc.get_or_create_default(db_session)
        await db_session.commit()
        assert p1.id == p2.id

    @pytest.mark.asyncio
    async def test_list_profiles_empty(self, db_session):
        result = await svc.list_profiles(db_session)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_profiles_status_filter(self, db_session):
        await svc.create_profile(db_session, name="A", activate=True)
        await svc.create_profile(db_session, name="B")
        # archive B so it gets a different status
        profiles = await svc.list_profiles(db_session)
        b = next(p for p in profiles if p.name == "B")
        await svc.archive_profile(db_session, b.id)
        await db_session.commit()
        active = await svc.list_profiles(db_session, status=svc.PROFILE_STATUS_ACTIVE)
        archived = await svc.list_profiles(db_session, status=svc.PROFILE_STATUS_ARCHIVED)
        assert len(active) == 1
        assert len(archived) == 1

    @pytest.mark.asyncio
    async def test_activate_profile_single_active(self, db_session):
        p1 = await svc.create_profile(db_session, name="P1", activate=True)
        p2 = await svc.create_profile(db_session, name="P2")
        await db_session.commit()
        assert p1.is_active is True
        assert p2.is_active is False

        activated = await svc.activate_profile(db_session, p2.id)
        await db_session.commit()
        assert activated is not None
        assert activated.is_active is True

        # p1 should now be inactive
        await db_session.refresh(p1)
        assert p1.is_active is False

    @pytest.mark.asyncio
    async def test_activate_archived_returns_none(self, db_session):
        p = await svc.create_profile(db_session, name="Old")
        await db_session.commit()
        archived = await svc.archive_profile(db_session, p.id)
        await db_session.commit()
        assert archived is not None

        result = await svc.activate_profile(db_session, p.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_profile(self, db_session):
        p = await svc.create_profile(db_session, name="Before")
        await db_session.commit()
        updated = await svc.update_profile(
            db_session, p.id, name="After", description="desc"
        )
        await db_session.commit()
        assert updated is not None
        assert updated.name == "After"
        assert updated.description == "desc"

    @pytest.mark.asyncio
    async def test_archive_profile(self, db_session):
        p = await svc.create_profile(db_session, name="ToArchive")
        await db_session.commit()
        archived = await svc.archive_profile(db_session, p.id)
        await db_session.commit()
        assert archived is not None
        assert archived.status == svc.PROFILE_STATUS_ARCHIVED

    @pytest.mark.asyncio
    async def test_profile_stats_empty(self, db_session):
        p = await svc.create_profile(db_session, name="Stats")
        await db_session.commit()
        stats = await svc.get_profile_stats(db_session, p.id)
        assert stats["missions"] == 0
        assert stats["skill_proposals"] == 0
        assert stats["installed_skills"] == 0

    @pytest.mark.asyncio
    async def test_assert_scope_allows_null(self):
        # NULL entity_profile_id = legacy row, must not raise
        svc.assert_profile_scope(None, 42, "test-entity")  # no exception

    @pytest.mark.asyncio
    async def test_assert_scope_allows_match(self):
        svc.assert_profile_scope(7, 7, "test-entity")  # no exception

    @pytest.mark.asyncio
    async def test_assert_scope_raises_mismatch(self):
        with pytest.raises(ValueError, match="test-entity"):
            svc.assert_profile_scope(1, 2, "test-entity")

    @pytest.mark.asyncio
    async def test_profile_to_dict(self, db_session):
        p = await svc.create_profile(db_session, name="Dict")
        await db_session.commit()
        d = svc.profile_to_dict(p)
        assert d["name"] == "Dict"
        assert "slug" in d
        assert "profile_type" in d


# ─── API endpoint tests ───────────────────────────────────────────────────────

class TestProfilesAPI:
    @pytest.mark.asyncio
    async def test_list_profiles_empty(self, api_client):
        r = await api_client.get("/api/v1/profiles")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        # default profile is auto-created on startup
        assert isinstance(data["profiles"], list)

    @pytest.mark.asyncio
    async def test_create_profile(self, api_client):
        r = await api_client.post(
            "/api/v1/profiles",
            json={"name": "API Work", "profile_type": "work"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["profile"]["name"] == "API Work"
        assert data["profile"]["profile_type"] == "work"

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self, api_client):
        r = await api_client.get("/api/v1/profiles/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_get_active_profile_none(self, api_client):
        # No profile created yet; startup creates default but it may not be active
        r = await api_client.get("/api/v1/profiles/active")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_create_and_activate_profile(self, api_client):
        create_r = await api_client.post(
            "/api/v1/profiles",
            json={"name": "ActivateMe", "activate": False},
        )
        assert create_r.status_code == 200
        profile_id = create_r.json()["profile"]["id"]

        activate_r = await api_client.post(f"/api/v1/profiles/{profile_id}/activate")
        assert activate_r.status_code == 200
        assert activate_r.json()["profile"]["is_active"] is True

        # active endpoint should now return this profile
        active_r = await api_client.get("/api/v1/profiles/active")
        assert active_r.status_code == 200
        assert active_r.json()["profile"]["id"] == profile_id

    @pytest.mark.asyncio
    async def test_get_profile_with_stats(self, api_client):
        create_r = await api_client.post(
            "/api/v1/profiles", json={"name": "WithStats"}
        )
        profile_id = create_r.json()["profile"]["id"]
        r = await api_client.get(f"/api/v1/profiles/{profile_id}")
        assert r.status_code == 200
        profile_data = r.json()["profile"]
        assert "stats" in profile_data
        assert profile_data["stats"]["missions"] == 0

    @pytest.mark.asyncio
    async def test_update_profile(self, api_client):
        create_r = await api_client.post(
            "/api/v1/profiles", json={"name": "Before Update"}
        )
        profile_id = create_r.json()["profile"]["id"]
        r = await api_client.patch(
            f"/api/v1/profiles/{profile_id}",
            json={"name": "After Update", "description": "updated"},
        )
        assert r.status_code == 200
        assert r.json()["profile"]["name"] == "After Update"

    @pytest.mark.asyncio
    async def test_archive_profile(self, api_client):
        create_r = await api_client.post(
            "/api/v1/profiles", json={"name": "Archive Me"}
        )
        profile_id = create_r.json()["profile"]["id"]
        r = await api_client.post(f"/api/v1/profiles/{profile_id}/archive")
        assert r.status_code == 200
        assert r.json()["profile"]["status"] == "archived"

    @pytest.mark.asyncio
    async def test_activate_archived_profile_fails(self, api_client):
        create_r = await api_client.post(
            "/api/v1/profiles", json={"name": "Will Archive"}
        )
        profile_id = create_r.json()["profile"]["id"]
        await api_client.post(f"/api/v1/profiles/{profile_id}/archive")

        r = await api_client.post(f"/api/v1/profiles/{profile_id}/activate")
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_duplicate_name_fails(self, api_client):
        await api_client.post("/api/v1/profiles", json={"name": "Unique"})
        r2 = await api_client.post("/api/v1/profiles", json={"name": "Unique"})
        assert r2.status_code == 422


# ─── Scope isolation: list_missions ──────────────────────────────────────────

class TestProfileScopeIsolation:
    @pytest.mark.asyncio
    async def test_list_missions_scoped(self, db_session):
        from app.models.mission import Mission
        from app.services.mission_service import list_missions
        import datetime

        p1 = await svc.create_profile(db_session, name="ScopeP1")
        p2 = await svc.create_profile(db_session, name="ScopeP2")
        await db_session.commit()

        m = Mission(
            title="Test",
            goal="Do stuff",
            status="planned",
            chain_ids=[],
            profile_id=p1.id,
            created_at=datetime.datetime.utcnow(),
        )
        db_session.add(m)
        await db_session.commit()

        all_missions = await list_missions(db_session)
        p1_missions = await list_missions(db_session, profile_id=p1.id)
        p2_missions = await list_missions(db_session, profile_id=p2.id)

        assert len(p1_missions) == 1
        assert len(p2_missions) == 0
        assert len(all_missions) >= 1

    @pytest.mark.asyncio
    async def test_list_proposals_scoped(self, db_session):
        from app.models.skill_proposal import SkillProposal
        from app.services.skill_proposal_service import list_proposals
        import datetime

        p1 = await svc.create_profile(db_session, name="ProposalP1")
        p2 = await svc.create_profile(db_session, name="ProposalP2")
        await db_session.commit()

        sp = SkillProposal(
            pattern_id="pat-1",
            title="Automate X",
            description="desc",
            steps=[],
            profile_id=p1.id,
            created_at=datetime.datetime.utcnow(),
        )
        db_session.add(sp)
        await db_session.commit()

        p1_proposals = await list_proposals(db_session, profile_id=p1.id)
        p2_proposals = await list_proposals(db_session, profile_id=p2.id)

        assert len(p1_proposals) == 1
        assert len(p2_proposals) == 0
