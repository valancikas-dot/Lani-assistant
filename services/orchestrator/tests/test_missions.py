"""
Phase 8 – Autonomous Missions with Checkpoints
Test suite

Covers:
  • create / list / get mission
  • start / pause / resume / cancel lifecycle
  • advance_step: progress update, token budget exhaustion, time budget exhaustion
  • create_checkpoint: halts mission (waiting_approval)
  • resolve_checkpoint: approved → resumed, denied → failed
  • list checkpoints
  • API 404 for missing mission
  • No execution_guard bypass (structural source inspection)
  • All state changes have updated_at timestamps (auditability)
"""

from __future__ import annotations

import inspect
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.mission import Mission
from app.models.mission_checkpoint import MissionCheckpoint
from app.services import mission_service as svc


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def clean_missions():
    """Truncate missions + checkpoints before each test."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(MissionCheckpoint))
        await session.execute(delete(Mission))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(MissionCheckpoint))
        await session.execute(delete(Mission))
        await session.commit()


# ─── Service-layer helpers ────────────────────────────────────────────────────

async def _make_mission(
    title="Test mission",
    goal="Do something useful",
    total_steps=3,
    budget_tokens=None,
    budget_time_ms=None,
    checkpoint_policy="risky",
) -> Mission:
    async with AsyncSessionLocal() as db:
        m = await svc.create_mission(
            db,
            title=title,
            goal=goal,
            total_steps=total_steps,
            budget_tokens=budget_tokens,
            budget_time_ms=budget_time_ms,
            checkpoint_policy=checkpoint_policy,
        )
        await db.commit()
        await db.refresh(m)
        return m


# ─── Service unit tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMissionServiceCreate:
    async def test_create_returns_planned_status(self):
        m = await _make_mission()
        assert m.status == "planned"
        assert m.current_step == 0
        assert m.progress_percent == 0.0

    async def test_create_sets_title_and_goal(self):
        m = await _make_mission(title="Alpha", goal="Beta")
        assert m.title == "Alpha"
        assert m.goal == "Beta"

    async def test_create_budget_stored(self):
        m = await _make_mission(budget_tokens=500, budget_time_ms=30_000)
        assert m.budget_tokens == 500
        assert m.budget_time_ms == 30_000
        assert m.tokens_used == 0
        assert m.elapsed_time_ms == 0

    async def test_create_has_updated_at(self):
        m = await _make_mission()
        assert m.updated_at is not None  # auditability invariant


@pytest.mark.asyncio
class TestMissionServiceLifecycle:
    async def test_start_transitions_planned_to_running(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            updated = await svc.start_mission(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.status == "running"
        assert updated.started_at is not None

    async def test_start_noop_if_already_running(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.start_mission(db, m.id)
            await db.commit()
        # Returns the row unchanged (already running)
        assert updated is not None
        assert updated.status == "running"

    async def test_pause_transitions_running_to_paused(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.pause_mission(db, m.id, reason="manual pause")
            await db.commit()
        assert updated is not None
        assert updated.status == "paused"
        assert updated.last_error == "manual pause"

    async def test_resume_transitions_paused_to_running(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            await svc.pause_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.resume_mission(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.status == "running"

    async def test_cancel_from_running(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.cancel_mission(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.status == "cancelled"
        assert updated.completed_at is not None

    async def test_cancel_terminal_is_noop(self):
        m = await _make_mission()
        async with AsyncSessionLocal() as db:
            await svc.cancel_mission(db, m.id)
            await db.commit()
        # Already planned → cancelled
        async with AsyncSessionLocal() as db:
            updated = await svc.cancel_mission(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.status == "cancelled"

    async def test_get_missing_returns_none(self):
        async with AsyncSessionLocal() as db:
            result = await svc.get_mission(db, 99999)
        assert result is None

    async def test_list_missions_empty(self):
        async with AsyncSessionLocal() as db:
            missions = await svc.list_missions(db)
        assert missions == []


@pytest.mark.asyncio
class TestAdvanceStep:
    async def test_advance_increments_current_step(self):
        m = await _make_mission(total_steps=3)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id, tokens_used=10, elapsed_ms=500)
            await db.commit()
        assert updated is not None
        assert updated.current_step == 1
        assert updated.tokens_used == 10
        assert updated.elapsed_time_ms == 500

    async def test_advance_updates_progress_percent(self):
        m = await _make_mission(total_steps=4)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.progress_percent == 25.0

    async def test_advance_appends_chain_id(self):
        m = await _make_mission(total_steps=5)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id, chain_id="chain-abc-123")
            await db.commit()
        assert updated is not None
        assert "chain-abc-123" in updated.chain_ids

    async def test_advance_to_total_steps_completes_mission(self):
        m = await _make_mission(total_steps=2)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            await svc.advance_step(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id)
            await db.commit()
        assert updated is not None
        assert updated.status == "completed"
        assert updated.progress_percent == 100.0
        assert updated.completed_at is not None

    async def test_token_budget_exhaustion_sets_failed(self):
        m = await _make_mission(total_steps=10, budget_tokens=100)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id, tokens_used=150)
            await db.commit()
        assert updated is not None
        assert updated.status == "failed"
        assert "Token budget exhausted" in (updated.last_error or "")

    async def test_time_budget_exhaustion_sets_failed(self):
        m = await _make_mission(total_steps=10, budget_time_ms=1_000)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            updated = await svc.advance_step(db, m.id, elapsed_ms=2_000)
            await db.commit()
        assert updated is not None
        assert updated.status == "failed"
        assert "Time budget exhausted" in (updated.last_error or "")


@pytest.mark.asyncio
class TestCheckpoints:
    async def test_create_checkpoint_halts_mission(self):
        m = await _make_mission(total_steps=5)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            cp = await svc.create_checkpoint(db, m.id, step_index=1, reason="risky file delete")
            await db.commit()
        assert cp is not None
        assert cp.status == "pending"
        async with AsyncSessionLocal() as db:
            mission = await svc.get_mission(db, m.id)
        assert mission is not None
        assert mission.status == "waiting_approval"

    async def test_approve_checkpoint_resumes_mission(self):
        m = await _make_mission(total_steps=5)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            cp = await svc.create_checkpoint(db, m.id, step_index=1, reason="risky action")
            await db.commit()
            assert cp is not None
            cp_id = cp.id
        async with AsyncSessionLocal() as db:
            resolved = await svc.resolve_checkpoint(db, cp_id, approved=True)
            await db.commit()
        assert resolved is not None
        assert resolved.status == "approved"
        assert resolved.resolved_at is not None
        async with AsyncSessionLocal() as db:
            mission = await svc.get_mission(db, m.id)
        assert mission is not None
        assert mission.status == "running"

    async def test_deny_checkpoint_halts_mission_as_failed(self):
        """Safety invariant: denial MUST set mission to failed, never auto-resume."""
        m = await _make_mission(total_steps=5)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            cp = await svc.create_checkpoint(db, m.id, step_index=2, reason="dangerous step")
            await db.commit()
            assert cp is not None
            cp_id = cp.id
        async with AsyncSessionLocal() as db:
            resolved = await svc.resolve_checkpoint(db, cp_id, approved=False)
            await db.commit()
        assert resolved is not None
        assert resolved.status == "denied"
        async with AsyncSessionLocal() as db:
            mission = await svc.get_mission(db, m.id)
        assert mission is not None
        assert mission.status == "failed"
        assert str(cp_id) in (mission.last_error or "")

    async def test_resolve_already_resolved_is_noop(self):
        m = await _make_mission(total_steps=5)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            cp = await svc.create_checkpoint(db, m.id, step_index=1, reason="test")
            await db.commit()
            assert cp is not None
            cp_id = cp.id
        async with AsyncSessionLocal() as db:
            await svc.resolve_checkpoint(db, cp_id, approved=True)
            await db.commit()
        async with AsyncSessionLocal() as db:
            # Second resolve call should not change status
            resolved = await svc.resolve_checkpoint(db, cp_id, approved=False)
            await db.commit()
        assert resolved is not None
        assert resolved.status == "approved"  # unchanged

    async def test_get_checkpoints_returns_ordered(self):
        m = await _make_mission(total_steps=10)
        async with AsyncSessionLocal() as db:
            await svc.start_mission(db, m.id)
            await db.commit()
        async with AsyncSessionLocal() as db:
            cp1 = await svc.create_checkpoint(db, m.id, step_index=3, reason="step 3")
            await db.flush()
            assert cp1 is not None
            cp1_id = cp1.id
            # Resolve to allow another checkpoint
            await svc.resolve_checkpoint(db, cp1_id, approved=True)
            cp2 = await svc.create_checkpoint(db, m.id, step_index=7, reason="step 7")
            await db.flush()
            assert cp2 is not None
            cp2_id = cp2.id
            await svc.resolve_checkpoint(db, cp2_id, approved=True)
            await db.commit()
        async with AsyncSessionLocal() as db:
            checkpoints = await svc.get_checkpoints(db, m.id)
        assert len(checkpoints) == 2
        assert checkpoints[0].step_index <= checkpoints[1].step_index


# ─── API integration tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMissionsAPI:
    async def test_create_mission_201(self, async_client: AsyncClient):
        resp = await async_client.post(
            "/api/v1/missions",
            json={"title": "My Mission", "goal": "Accomplish things", "total_steps": 5},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Mission"
        assert data["status"] == "planned"
        assert data["id"] > 0

    async def test_list_missions(self, async_client: AsyncClient):
        for i in range(3):
            await async_client.post(
                "/api/v1/missions",
                json={"title": f"M{i}", "goal": "goal", "total_steps": 1},
            )
        resp = await async_client.get("/api/v1/missions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3
        assert len(data["missions"]) >= 3

    async def test_list_missions_filter_by_status(self, async_client: AsyncClient):
        resp_create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Filter test", "goal": "goal", "total_steps": 1},
        )
        mid = resp_create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")

        resp = await async_client.get("/api/v1/missions?status=running")
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data["missions"]]
        assert mid in ids

    async def test_get_mission_200(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Get me", "goal": "goal"},
        )
        mid = create.json()["id"]
        resp = await async_client.get(f"/api/v1/missions/{mid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == mid

    async def test_get_mission_404(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/missions/999999")
        assert resp.status_code == 404

    async def test_start_mission(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Start test", "goal": "go", "total_steps": 2},
        )
        mid = create.json()["id"]
        resp = await async_client.post(f"/api/v1/missions/{mid}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_pause_mission(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Pause test", "goal": "go", "total_steps": 2},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        resp = await async_client.post(
            f"/api/v1/missions/{mid}/pause",
            json={"reason": "user pause"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    async def test_resume_mission(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Resume test", "goal": "go", "total_steps": 2},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        await async_client.post(f"/api/v1/missions/{mid}/pause", json={})
        resp = await async_client.post(f"/api/v1/missions/{mid}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_cancel_mission(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Cancel test", "goal": "go"},
        )
        mid = create.json()["id"]
        resp = await async_client.post(f"/api/v1/missions/{mid}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_start_404(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/missions/999999/start")
        assert resp.status_code == 404

    async def test_invalid_checkpoint_policy_400(self, async_client: AsyncClient):
        resp = await async_client.post(
            "/api/v1/missions",
            json={
                "title": "Bad",
                "goal": "test",
                "checkpoint_policy": "invalid_policy",
            },
        )
        assert resp.status_code == 400

    async def test_invalid_status_filter_400(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/missions?status=nonexistent")
        assert resp.status_code == 400

    async def test_list_checkpoints_200(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "CP test", "goal": "go", "total_steps": 5},
        )
        mid = create.json()["id"]
        resp = await async_client.get(f"/api/v1/missions/{mid}/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoints" in data
        assert data["total"] == 0

    async def test_create_checkpoint_via_api(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "CP create test", "goal": "go", "total_steps": 5},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        resp = await async_client.post(
            f"/api/v1/missions/{mid}/checkpoints",
            json={"step_index": 1, "reason": "sensitive file operation"},
        )
        assert resp.status_code == 201
        cp = resp.json()
        assert cp["status"] == "pending"
        assert cp["mission_id"] == mid

        # Mission should now be waiting_approval
        m_resp = await async_client.get(f"/api/v1/missions/{mid}")
        assert m_resp.json()["status"] == "waiting_approval"

    async def test_resolve_checkpoint_approve_via_api(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Resolve test", "goal": "go", "total_steps": 5},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        cp_resp = await async_client.post(
            f"/api/v1/missions/{mid}/checkpoints",
            json={"step_index": 1, "reason": "approval needed"},
        )
        cp_id = cp_resp.json()["id"]

        resolve_resp = await async_client.post(
            f"/api/v1/missions/{mid}/checkpoints/{cp_id}/resolve",
            json={"approved": True},
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "approved"

        # Mission should be running again
        m_resp = await async_client.get(f"/api/v1/missions/{mid}")
        assert m_resp.json()["status"] == "running"

    async def test_resolve_checkpoint_deny_via_api(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Deny test", "goal": "go", "total_steps": 5},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        cp_resp = await async_client.post(
            f"/api/v1/missions/{mid}/checkpoints",
            json={"step_index": 1, "reason": "risky"},
        )
        cp_id = cp_resp.json()["id"]

        resolve_resp = await async_client.post(
            f"/api/v1/missions/{mid}/checkpoints/{cp_id}/resolve",
            json={"approved": False},
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "denied"

        # Safety invariant: denial → failed, NOT waiting or running
        m_resp = await async_client.get(f"/api/v1/missions/{mid}")
        assert m_resp.json()["status"] == "failed"

    async def test_advance_step_via_api(self, async_client: AsyncClient):
        create = await async_client.post(
            "/api/v1/missions",
            json={"title": "Advance test", "goal": "go", "total_steps": 3},
        )
        mid = create.json()["id"]
        await async_client.post(f"/api/v1/missions/{mid}/start")
        resp = await async_client.post(
            f"/api/v1/missions/{mid}/advance",
            json={"chain_id": "test-chain-001", "tokens_used": 25, "elapsed_ms": 300},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"] == 1
        assert data["tokens_used"] == 25
        assert "test-chain-001" in data["chain_ids"]


# ─── Safety invariant tests ───────────────────────────────────────────────────

class TestSafetyInvariants:
    """
    Structural source-inspection tests verifying that mission_service does NOT
    bypass execution_guard.

    These are NOT async – they inspect module source code directly.
    """

    def test_mission_service_does_not_import_get_tool(self):
        """
        mission_service must NOT import get_tool (the raw tool executor).
        All actual tool execution must go through execution_guard.guarded_execute()
        which is the caller's responsibility.
        """
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module)
        assert "get_tool" not in source, (
            "mission_service must NOT call get_tool directly — "
            "all execution must go through execution_guard.guarded_execute()"
        )

    def test_mission_service_does_not_call_tool_run(self):
        """mission_service must not call .run() on any tool directly."""
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module)
        # Allow 'running' (status string) but not 'tool.run(' or '.run('
        assert "tool.run(" not in source, (
            "mission_service must NOT call tool.run() directly"
        )

    def test_missions_route_does_not_import_get_tool(self):
        """API routes for missions must also not bypass the guard."""
        import app.api.routes.missions as routes_module
        source = inspect.getsource(routes_module)
        assert "get_tool" not in source, (
            "missions API routes must NOT call get_tool directly"
        )

    def test_all_state_transitions_set_updated_at(self):
        """
        Every transition function in mission_service must call _touch().
        This ensures all state changes are stamped and auditable.
        """
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module)
        # Each of the mutating functions should contain _touch(
        for fn_name in (
            "start_mission",
            "pause_mission",
            "resume_mission",
            "cancel_mission",
            "advance_step",
            "create_checkpoint",
            "resolve_checkpoint",
        ):
            fn = getattr(ms_module, fn_name)
            fn_source = inspect.getsource(fn)
            assert "_touch(" in fn_source, (
                f"{fn_name} must call _touch() to stamp updated_at for auditability"
            )

    def test_denied_checkpoint_always_sets_mission_failed(self):
        """
        Source inspection: resolve_checkpoint must set MISSION_STATUS_FAILED
        when approved=False — never resume or leave as waiting_approval.
        """
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module.resolve_checkpoint)
        assert "MISSION_STATUS_FAILED" in source, (
            "resolve_checkpoint must set MISSION_STATUS_FAILED on denial"
        )

    def test_budget_enforcement_in_advance_step(self):
        """
        Source inspection: advance_step must check both token and time budgets
        and set MISSION_STATUS_FAILED on exhaustion.
        """
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module.advance_step)
        assert "budget_tokens" in source, "advance_step must check token budget"
        assert "budget_time_ms" in source, "advance_step must check time budget"
        assert "MISSION_STATUS_FAILED" in source, (
            "advance_step must set MISSION_STATUS_FAILED on budget exhaustion"
        )

    def test_no_infinite_loop_risk(self):
        """
        mission_service must not contain any unconditional while True loops.
        Execution loops belong in orchestrators that call the service, not here.
        """
        import app.services.mission_service as ms_module
        source = inspect.getsource(ms_module)
        # 'while True' would be a red flag in a state-management service
        assert "while True" not in source, (
            "mission_service must not contain while True loops"
        )
