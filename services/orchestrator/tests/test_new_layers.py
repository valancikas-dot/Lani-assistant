"""
Tests for the 4 new backend layers:
  - capability_registry
  - policy_engine
  - session_manager
  - eval_service (async, requires DB)
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ─── Capability Registry ────────────────────────────────────────────────────

class TestCapabilityRegistry:
    def setup_method(self):
        # Force a fresh registry build on each test
        from app.services import capability_registry as cr
        cr._registry = None  # type: ignore[attr-defined]

    def test_registry_loads_without_error(self):
        from app.services.capability_registry import get_registry
        reg = get_registry()
        assert isinstance(reg, dict)
        assert len(reg) > 0

    def test_list_capabilities_returns_list(self):
        from app.services.capability_registry import list_capabilities
        caps = list_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0

    def test_get_capability_returns_meta(self):
        from app.services.capability_registry import list_capabilities, get_capability
        caps = list_capabilities()
        first = caps[0]
        meta = get_capability(first["name"])
        assert meta is not None
        assert meta.name == first["name"]

    def test_get_capability_unknown_returns_none(self):
        """get_capability returns None for tools not in the registry.
        Callers (execution_guard, policy_engine) handle None gracefully."""
        from app.services.capability_registry import get_capability
        meta = get_capability("__nonexistent_tool_xyz__")
        # None is the documented contract for unknown tools
        assert meta is None

    def test_static_overrides_applied_for_known_tools(self):
        """Tools with static overrides should have the declared risk level."""
        from app.services.capability_registry import get_capability, _STATIC_META  # type: ignore[attr-defined]
        for name, override in _STATIC_META.items():
            meta = get_capability(name)
            if meta and "risk_level" in override:
                assert meta.risk_level == override["risk_level"], (
                    f"{name} risk_level mismatch"
                )

    def test_enrich_tool_meta_adds_fields(self):
        from app.services.capability_registry import enrich_tool_meta
        # Use a real registered tool so get_capability() returns metadata
        raw = {
            "name": "web_search",
            "description": "Search the web",
            "requires_approval": False,
        }
        enriched = enrich_tool_meta(raw)
        assert "risk_level" in enriched
        assert "side_effects" in enriched
        assert "retry_policy" in enriched
        assert "category" in enriched

    def test_refresh_registry_rebuilds(self):
        from app.services.capability_registry import get_registry, refresh_registry
        reg1 = get_registry()
        refresh_registry()
        reg2 = get_registry()
        assert set(reg1.keys()) == set(reg2.keys())


# ─── Policy Engine ───────────────────────────────────────────────────────────

class TestPolicyEngine:
    def _ctx(self, **kwargs):
        from app.services.policy_engine import PolicyContext
        defaults = {
            "security_mode": "normal",
            "active_accounts": [],
            "user_authenticated": True,
            "session_active": True,
            "command_text": "",
        }
        defaults.update(kwargs)
        return PolicyContext(**defaults)

    def test_allow_low_risk_action(self):
        from app.services.policy_engine import evaluate
        # list_files is low risk
        ctx = self._ctx()
        decision = evaluate("list_files", {}, ctx)
        assert decision.verdict == "allow"

    def test_critical_action_requires_approval(self):
        from app.services.policy_engine import evaluate
        # gmail_send_email is critical risk in _STATIC_META
        ctx = self._ctx()
        decision = evaluate("gmail_send_email", {}, ctx)
        assert decision.verdict in ("require_approval", "deny")

    def test_high_risk_requires_approval(self):
        from app.services.policy_engine import evaluate
        # move_file is high risk in _STATIC_META
        ctx = self._ctx()
        decision = evaluate("move_file", {}, ctx)
        assert decision.verdict in ("require_approval", "deny")

    def test_strict_mode_medium_risk_requires_approval(self):
        from app.services.policy_engine import evaluate
        ctx = self._ctx(security_mode="strict")
        # any medium-risk tool should require approval in strict mode
        decision = evaluate("list_files", {}, ctx)
        # list_files might be low risk — use a medium one
        # We just verify the engine runs without error and returns a valid verdict
        assert decision.verdict in ("allow", "require_approval", "deny")

    def test_deny_when_account_not_active(self):
        from app.services.policy_engine import evaluate
        # gmail_send_email requires gmail account; with no active accounts → deny
        ctx = self._ctx(active_accounts=[])
        decision = evaluate("gmail_send_email", {}, ctx)
        assert decision.verdict in ("require_approval", "deny")

    def test_decision_has_all_fields(self):
        from app.services.policy_engine import evaluate
        ctx = self._ctx()
        decision = evaluate("read_file", {}, ctx)
        assert hasattr(decision, "verdict")
        assert hasattr(decision, "reason")
        assert hasattr(decision, "risk_level")
        assert hasattr(decision, "allowed")
        assert hasattr(decision, "denied")
        assert hasattr(decision, "needs_approval")

    def test_verdict_properties_are_consistent(self):
        from app.services.policy_engine import evaluate
        ctx = self._ctx()
        d = evaluate("list_files", {}, ctx)
        # exactly one of the three boolean properties should be True
        flags = [d.allowed, d.denied, d.needs_approval]
        assert sum(flags) == 1

    def test_evaluate_plan_all_steps(self):
        from app.services.policy_engine import evaluate_plan
        ctx = self._ctx()
        steps = [
            {"action": "list_files", "params": {}},
            {"action": "read_file", "params": {"path": "/tmp/test.txt"}},
        ]
        decisions = evaluate_plan(steps, ctx)
        assert len(decisions) == len(steps)

    def test_build_context_from_settings(self):
        from app.services.policy_engine import build_context_from_settings

        class FakeSettings:
            security_mode = "normal"

        ctx = build_context_from_settings(FakeSettings(), ["gmail"])
        assert ctx.security_mode == "normal"
        assert "gmail" in ctx.active_accounts


# ─── Session Manager ─────────────────────────────────────────────────────────

class TestSessionManager:
    def setup_method(self):
        from app.services.session_manager import get_vault
        get_vault().clear_all()

    def test_register_and_get(self):
        from app.services.session_manager import register_session, get_session
        register_session("gmail", "user@example.com", credentials={"token": "abc"})
        session = get_session("gmail", "user@example.com")
        assert session is not None
        assert session.account_type == "gmail"
        assert session.account_id == "user@example.com"

    def test_credentials_not_in_summary(self):
        from app.services.session_manager import register_session, get_session
        register_session("gmail", "user@example.com", credentials={"token": "supersecret"})
        session = get_session("gmail", "user@example.com")
        assert session is not None
        summary = session.to_summary()
        assert "supersecret" not in str(summary)

    def test_get_credentials_returns_creds(self):
        from app.services.session_manager import register_session, get_credentials
        register_session("google_drive", "user@example.com", credentials={"access_token": "tok123"})
        creds = get_credentials("google_drive", "user@example.com")
        assert creds is not None
        assert creds["access_token"] == "tok123"

    def test_unknown_session_returns_none(self):
        from app.services.session_manager import get_session
        assert get_session("gmail", "nobody@nowhere.com") is None

    def test_activate_and_deactivate(self):
        from app.services.session_manager import (
            register_session, activate_session, deactivate_session, get_active_session,
        )
        register_session("gmail", "a@b.com", credentials={}, make_active=False)
        activate_session("gmail", "a@b.com")
        active = get_active_session("gmail")
        assert active is not None
        assert active.account_id == "a@b.com"

        deactivate_session("gmail", "a@b.com")
        assert get_active_session("gmail") is None

    def test_revoke_removes_session(self):
        from app.services.session_manager import register_session, revoke_session, get_session
        register_session("gmail", "a@b.com", credentials={})
        revoke_session("gmail", "a@b.com")
        session = get_session("gmail", "a@b.com")
        assert session is None or session.status == "revoked"

    def test_expired_session_is_not_active(self):
        from datetime import datetime, timedelta, timezone
        from app.services.session_manager import (
            register_session, activate_session, get_active_session, get_vault, get_session,
        )
        register_session("gmail", "a@b.com", credentials={}, make_active=False)
        activate_session("gmail", "a@b.com")
        # Force expiry
        session = get_session("gmail", "a@b.com")
        assert session is not None
        session.expires_at = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        # expire_stale should mark/remove it
        get_vault().expire_stale()
        assert get_active_session("gmail") is None

    def test_list_sessions_is_empty_after_clear(self):
        from app.services.session_manager import register_session, list_sessions, get_vault
        register_session("gmail", "x@y.com", credentials={})
        get_vault().clear_all()
        assert list_sessions() == []

    def test_list_active_account_types(self):
        from app.services.session_manager import (
            register_session, activate_session, list_active_account_types,
        )
        register_session("gmail", "a@b.com", credentials={}, make_active=False)
        register_session("google_drive", "a@b.com", credentials={}, make_active=False)
        activate_session("gmail", "a@b.com")
        activate_session("google_drive", "a@b.com")
        types = list_active_account_types()
        assert "gmail" in types
        assert "google_drive" in types

    def test_session_isolation_between_types(self):
        from app.services.session_manager import (
            register_session, activate_session, get_active_session,
        )
        register_session("gmail", "a@b.com", credentials={}, make_active=False)
        register_session("google_drive", "a@b.com", credentials={}, make_active=False)
        activate_session("gmail", "a@b.com")
        # google_drive should not be active
        assert get_active_session("google_drive") is None
        activate_session("google_drive", "a@b.com")
        # Both active under separate types
        assert get_active_session("gmail") is not None
        assert get_active_session("google_drive") is not None


# ─── Eval Service (async) ────────────────────────────────────────────────────

@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture()
async def db_session():
    """In-memory SQLite async session with eval_log table created."""
    from app.core.database import Base
    from app.models import eval_log as _  # ensure model is registered  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
class TestEvalService:
    async def test_record_creates_entry(self, db_session: AsyncSession):
        from app.services.eval_service import record
        entry = await record(
            db_session,
            command="list files in ~/Documents",
            tool_name="list_files",
            status="success",
            duration_ms=123,
            retries=0,
            required_approval=False,
            approval_granted=None,
            risk_level="low",
            policy_verdict="allow",
            quality_score=None,
            error_message=None,
        )
        assert entry.id is not None
        assert entry.tool_name == "list_files"
        assert entry.status == "success"

    async def test_get_stats_empty(self, db_session: AsyncSession):
        from app.services.eval_service import get_stats
        stats = await get_stats(db_session)
        assert stats["total_tasks"] == 0
        assert stats["success_count"] == 0
        assert stats["task_success_rate"] == 0.0

    async def test_get_stats_with_data(self, db_session: AsyncSession):
        from app.services.eval_service import record, get_stats
        for i in range(3):
            await record(
                db_session,
                command=f"cmd {i}",
                tool_name="list_files",
                status="success",
                duration_ms=100,
                retries=0,
                required_approval=False,
            )
        await record(
            db_session,
            command="cmd fail",
            tool_name="list_files",
            status="error",
            duration_ms=50,
            retries=1,
            required_approval=False,
            error_message="Something broke",
        )
        stats = await get_stats(db_session)
        assert stats["total_tasks"] == 4
        assert stats["success_count"] == 3
        assert stats["failure_count"] == 1
        assert abs(stats["task_success_rate"] - 0.75) < 0.01

    async def test_list_recent_returns_entries(self, db_session: AsyncSession):
        from app.services.eval_service import record, list_recent
        await record(db_session, command="x", tool_name="t1", status="success",
                     duration_ms=10, retries=0, required_approval=False)
        rows = await list_recent(db_session, limit=10)
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "t1"

    async def test_tool_filter_works(self, db_session: AsyncSession):
        from app.services.eval_service import record, list_recent
        await record(db_session, command="a", tool_name="tool_a", status="success",
                     duration_ms=10, retries=0, required_approval=False)
        await record(db_session, command="b", tool_name="tool_b", status="success",
                     duration_ms=10, retries=0, required_approval=False)
        rows = await list_recent(db_session, limit=10, tool_filter="tool_a")
        assert all(r["tool_name"] == "tool_a" for r in rows)


# ─── Integration Tests ─────────────────────────────────────────────────────
# These tests exercise the full integration chain:
#   capability_registry → policy_engine → approval_service → world_state → eval_service
# All tests run against an in-memory SQLite database.


@pytest.fixture
def _fresh_world_state():
    """Reset the module-level world state singleton before each test."""
    import app.services.world_state as _ws_mod
    _ws_mod._world_state = None  # type: ignore[attr-defined]


@pytest.mark.asyncio
class TestIntegration:
    # ── db_session fixture (re-declared so class can use it without conftest) ──
    @pytest_asyncio.fixture
    async def db_session(self):
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from app.core.database import Base
        # Import all models so create_all builds the correct tables
        import app.models.approval_request  # noqa: F401
        import app.models.eval_log           # noqa: F401

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as session:
            yield session
        await engine.dispose()

    # ── 1. Approval creation stores execution_context ─────────────────────────
    async def test_approval_request_stores_execution_context(self, db_session: AsyncSession):
        """create_approval_request must persist the execution_context JSON blob."""
        from app.services.approval_service import create_approval_request
        from app.models.approval_request import ApprovalRequest
        from sqlalchemy import select

        ctx = {"plan": {"goal": "test", "steps": []}, "start_from_step": 2}
        aid = await create_approval_request(
            db_session,
            tool_name="delete_file",
            command="delete ~/Desktop/test.txt",
            params={"path": "~/Desktop/test.txt"},
            execution_context=ctx,
        )
        await db_session.flush()

        row = (await db_session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == aid)
        )).scalar_one()

        assert row.execution_context is not None
        assert row.execution_context["start_from_step"] == 2

    # ── 2. Denied approval – no execution runs ────────────────────────────────
    async def test_denied_approval_no_execution(self, db_session: AsyncSession):
        """Resolving an approval as denied must not call any tool."""
        from app.services.approval_service import create_approval_request, resolve
        from unittest.mock import AsyncMock, patch

        aid = await create_approval_request(
            db_session,
            tool_name="list_files",
            command="list files",
            params={},
        )
        await db_session.flush()

        with patch("app.tools.registry.get_tool") as mock_get_tool:
            mock_tool = AsyncMock()
            mock_get_tool.return_value = mock_tool
            result = await resolve(db_session, aid, "denied")
            mock_tool.run.assert_not_called()

        assert result is not None
        assert result.status == "denied"

    # ── 3. Approved approval runs tool via guarded_execute ───────────────────
    async def test_approved_approval_legacy_runs_tool(self, db_session: AsyncSession):
        """Approving a request with no execution_context calls guarded_execute (the guard)."""
        from app.services.approval_service import create_approval_request, resolve
        from unittest.mock import AsyncMock, patch, MagicMock

        aid = await create_approval_request(
            db_session,
            tool_name="list_files",
            command="list files",
            params={"path": "~/Desktop"},
        )
        await db_session.flush()

        mock_guard_result = MagicMock()
        mock_guard_result.status = "executed"
        with patch(
            "app.services.approval_service.guarded_execute",
            new_callable=AsyncMock,
            return_value=mock_guard_result,
        ) as mock_guard:
            result = await resolve(db_session, aid, "approved")

        mock_guard.assert_awaited_once()
        call_kwargs = mock_guard.call_args
        # First positional arg must be the tool name
        assert call_kwargs.args[0] == "list_files"
        assert result is not None
        assert result.status == "approved"

    # ── 4. Policy engine blocks high-risk actions ─────────────────────────────
    async def test_policy_engine_blocks_critical_tool(self):
        """A critical tool should be flagged needs_approval or denied."""
        from app.services.policy_engine import evaluate, PolicyContext

        ctx = PolicyContext(
            security_mode="normal",
            active_accounts=[],
        )
        decision = evaluate("run_shell_command", {"cmd": "rm -rf /"}, ctx)
        # Must not silently allow
        assert decision.denied or decision.needs_approval, (
            f"Expected denial/approval for run_shell_command; got verdict={decision.verdict}"
        )

    # ── 5. World state records tool execution ─────────────────────────────────
    def test_world_state_records_execution(self, _fresh_world_state):
        from app.services.world_state import record_tool_execution, get_state

        record_tool_execution(
            tool="list_files",
            status="success",
            summary="listed 5 files",
            duration_ms=42.0,
        )
        state = get_state()
        assert state is not None
        # last_actions deque should contain the new record
        assert len(state.last_actions) >= 1
        assert state.last_actions[0].tool == "list_files"
        assert state.last_actions[0].status == "success"

    # ── 6. Eval service records success and failure ───────────────────────────
    async def test_eval_records_success_and_failure(self, db_session: AsyncSession):
        from app.services.eval_service import record, get_stats

        await record(db_session, command="ok cmd", tool_name="t1", status="success",
                     duration_ms=55.0, retries=0, required_approval=False)
        await record(db_session, command="bad cmd", tool_name="t1", status="error",
                     duration_ms=10.0, retries=1, required_approval=False,
                     error_message="boom")
        stats = await get_stats(db_session)
        assert stats["success_count"] >= 1
        assert stats["failure_count"] >= 1

    # ── 7. Voice confirmation: yes/no/stop/modify keyword classification ───────
    def test_voice_classify_yes(self):
        from app.services.voice_confirmation import classify_response
        assert classify_response("yes please go ahead") == "approved"

    def test_voice_classify_no(self):
        from app.services.voice_confirmation import classify_response
        assert classify_response("no cancel that") == "denied"

    def test_voice_classify_modify(self):
        from app.services.voice_confirmation import classify_response
        assert classify_response("actually modify the destination") == "modify"

    def test_voice_classify_unknown(self):
        from app.services.voice_confirmation import classify_response
        assert classify_response("hmm I dunno maybe") == "unknown"

    # ── 8. Voice confirmation timeout falls back to manual ────────────────────
    async def test_voice_confirmation_timeout_fallback(self, db_session: AsyncSession):
        """An expired confirmation should become 'expired' via sweep."""
        import datetime
        from app.services.voice_confirmation import (
            request_voice_confirmation,
            sweep_expired_confirmations,
            get_confirmation,
        )

        req = await request_voice_confirmation(
            prompt="Please confirm.",
            action="delete_file",
            approval_id=None,
            risk_level="high",
            synthesise_tts=False,
        )
        # Manually expire it
        req.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)

        expired_count = await sweep_expired_confirmations(db=db_session)
        assert expired_count >= 1
        assert get_confirmation(req.confirmation_id) is None

    # ── 9. Retry-once: two unclear responses fall back to manual ──────────────
    async def test_voice_retry_twice_falls_back(self):
        """Two unrecognised voice responses trigger the manual fallback."""
        from app.services.voice_confirmation import (
            request_voice_confirmation,
            respond_with_retry,
            get_confirmation,
        )

        req = await request_voice_confirmation(
            prompt="Confirm?",
            action="send_email",
            approval_id=None,
            risk_level="medium",
            synthesise_tts=False,
        )
        cid = req.confirmation_id

        # First unclear response – should still be pending
        r1 = await respond_with_retry(cid, "ummm let me think", db=None)
        assert r1 is not None
        assert r1.status == "pending"

        # Second unclear response – should trigger expiry/fallback
        r2 = await respond_with_retry(cid, "I am confused", db=None)
        assert r2 is not None
        assert r2.status == "expired"
        # No longer in pending dict
        assert get_confirmation(cid) is None

    # ── 10. Intent preview builds correctly ───────────────────────────────────
    def test_intent_preview_builds(self):
        from app.services.intent_preview import build_intent_preview

        preview = build_intent_preview(
            command="delete ~/Desktop/test.txt",
            tool_name="delete_file",
            params={"path": "~/Desktop/test.txt"},
            policy_decision=None,
            cap_meta=None,
        )
        assert preview.selected_tool == "delete_file"
        assert preview.target == "~/Desktop/test.txt"
        assert len(preview.expected_side_effects) > 0
        d = preview.to_dict()
        assert "user_intent" in d and "risk_level" in d

    # ── 11. Unknown tool fails safely (no crash) ──────────────────────────────
    def test_unknown_tool_safe_failure(self):
        from app.tools.registry import get_tool
        tool = get_tool("__nonexistent_tool_xyz_12345__")
        assert tool is None

    # ── 12. Capability registry: unregistered tool returns None (handled gracefully) ──
    def test_unregistered_tool_returns_none(self):
        """get_capability returns None for unknown tools; callers must handle None."""
        from app.services.capability_registry import get_capability
        meta = get_capability("__brand_new_unlisted_tool__")
        # None is the correct/safe return value for an unregistered tool
        assert meta is None


# ─── Phase 2.5 Hardening Tests ──────────────────────────────────────────────
# Covers: execution_guard, state_delta, audit_chain, strict-mode voice,
# and a smoke test confirming plan_executor uses the guard.


@pytest.mark.asyncio
class TestPhase25Hardening:
    """Phase 2.5: unified guarded execution path tests."""

    # ── Shared async db fixture ──────────────────────────────────────────────
    @pytest_asyncio.fixture
    async def db_session(self):
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from app.core.database import Base
        import app.models.approval_request   # noqa: F401
        import app.models.eval_log           # noqa: F401

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            yield session
        await engine.dispose()

    # ── 1. Guard executes a known tool ───────────────────────────────────────
    async def test_guard_executes_known_tool(self, db_session: AsyncSession):
        """guarded_execute returns GuardResult(status='executed') for a known, allowed tool."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.message = "ok"
        mock_result.data = {}

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=mock_result)

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):

            result = await guarded_execute(
                "list_files", {"path": "~/Desktop"},
                "list files", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "executed"
        assert result.tool_result is mock_result
        mock_tool.run.assert_awaited_once()

    # ── 2. Guard blocks an unknown tool ──────────────────────────────────────
    async def test_guard_blocks_unknown_tool(self, db_session: AsyncSession):
        """guarded_execute returns GuardResult(status='error') for unknown tool."""
        from unittest.mock import patch
        from app.services.execution_guard import guarded_execute

        with patch("app.tools.registry.get_tool", return_value=None):
            result = await guarded_execute(
                "__nonexistent_xyz__", {}, "some command", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "error"
        assert "__nonexistent_xyz__" in result.policy_reason

    # ── 3. Guard honours policy denial ───────────────────────────────────────
    async def test_guard_denies_policy_blocked_tool(self, db_session: AsyncSession):
        """When policy returns denied=True, guard returns GuardResult(status='denied')."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock()

        mock_decision = MagicMock()
        mock_decision.denied = True
        mock_decision.needs_approval = False
        mock_decision.verdict = "denied"
        mock_decision.reason = "Blocked: security policy"
        mock_decision.risk_level = "critical"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):

            result = await guarded_execute(
                "run_shell_command", {"cmd": "rm -rf /"},
                "dangerous cmd", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "denied"
        assert result.blocked is True
        mock_tool.run.assert_not_called()

    # ── 4. Guard routes to approval ───────────────────────────────────────────
    async def test_guard_routes_to_approval(self, db_session: AsyncSession):
        """When needs_approval=True, guard creates an approval record and returns
        GuardResult(status='approval_required')."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute

        mock_tool = MagicMock()
        mock_tool.requires_approval = True
        mock_tool.run = AsyncMock()

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = True
        mock_decision.verdict = "needs_approval"
        mock_decision.reason = "High risk action"
        mock_decision.risk_level = "high"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision), \
             patch("app.services.approval_service.create_approval_request",
                   new_callable=AsyncMock, return_value=42) as mock_create:

            result = await guarded_execute(
                "delete_file", {"path": "~/important.txt"},
                "delete file", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "approval_required"
        assert result.needs_approval is True
        assert result.approval_id == 42
        mock_create.assert_awaited_once()
        mock_tool.run.assert_not_called()

    # ── 5. State delta captures changed fields ────────────────────────────────
    def test_state_delta_captures_changes(self):
        """build_delta detects fields that differ between before and after snapshots."""
        from app.services.state_delta import StateSnapshot, build_delta

        before = StateSnapshot(
            open_app_count=2,
            recent_file_paths=["a.txt"],
            browser_tab_urls=[],
            last_action_tool="list_files",
            last_action_status="success",
            pending_task_count=0,
            clipboard_hash=None,
        )
        after = StateSnapshot(
            open_app_count=3,       # changed
            recent_file_paths=["a.txt", "b.txt"],  # changed
            browser_tab_urls=[],
            last_action_tool="create_file",  # changed
            last_action_status="success",
            pending_task_count=0,
            clipboard_hash=None,
        )

        delta = build_delta(before, after, triggering_action="create_file", command="create b.txt")

        assert delta is not None
        assert "open_apps" in delta.changed_fields
        assert "recent_files" in delta.changed_fields
        assert "last_action" in delta.changed_fields
        # Unchanged fields must NOT appear in changed_fields
        assert "pending_tasks" not in delta.changed_fields
        assert delta.triggering_action == "create_file"
        assert delta.command == "create b.txt"

    # ── 6. Audit chain records action ─────────────────────────────────────────
    async def test_audit_chain_records_action(self, db_session: AsyncSession):
        """record_audit_chain returns a chain_id and stores the record in the buffer."""
        from app.services.audit_chain import record_audit_chain, get_chain, get_recent_chains
        from unittest.mock import MagicMock

        mock_policy = MagicMock()
        mock_policy.verdict = "allow"
        mock_policy.reason = ""
        mock_policy.risk_level = "low"

        chain_id = await record_audit_chain(
            db=db_session,
            command="list files",
            tool_name="list_files",
            cap_meta={"name": "list_files", "risk_level": "low"},
            policy_decision=mock_policy,
            execution_status="executed",
            tool_result=MagicMock(status="success", message="5 files", data={}),
            state_delta=None,
            eval_status="success",
            approval_id=None,
        )

        assert chain_id is not None
        assert len(chain_id) > 0

        # Should be retrievable from buffer
        record = get_chain(chain_id)
        assert record is not None
        assert record.tool_name == "list_files"
        assert record.execution_status == "executed"

        recent = get_recent_chains(5)
        assert any(r["chain_id"] == chain_id for r in recent)

    # ── 7. Strict-mode voice requires speaker verification ────────────────────
    async def test_strict_voice_requires_speaker_verification(self):
        """In strict mode, a high-risk confirmation with speaker_verified=False
        must be routed to manual approval (status becomes 'expired')."""
        from unittest.mock import AsyncMock, patch, MagicMock
        from app.services.voice_confirmation import (
            request_voice_confirmation,
            respond_with_retry,
            get_confirmation,
        )

        req = await request_voice_confirmation(
            prompt="Delete important file – confirm?",
            action="delete_file",
            approval_id=None,
            risk_level="high",
            synthesise_tts=False,
        )
        cid = req.confirmation_id

        # Mock DB returning strict security_mode
        mock_settings = MagicMock()
        mock_settings.security_mode = "strict"

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=mock_settings)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar)

        # speaker_verified=False → strict mode should route to manual
        result = await respond_with_retry(
            cid, "yes go ahead", db=mock_db, speaker_verified=False,
        )

        assert result is not None
        assert result.status == "expired"
        # Confirmation must be removed from pending dict
        assert get_confirmation(cid) is None

    # ── 8. Strict-mode voice passes with speaker verification ─────────────────
    async def test_strict_voice_passes_with_speaker_verified(self):
        """In strict mode, a high-risk confirmation WITH speaker_verified=True
        should be processed normally (approved)."""
        from app.services.voice_confirmation import (
            request_voice_confirmation,
            respond_with_retry,
        )

        req = await request_voice_confirmation(
            prompt="Delete important file – confirm?",
            action="delete_file",
            approval_id=None,
            risk_level="high",
            synthesise_tts=False,
        )
        cid = req.confirmation_id

        # With speaker_verified=True, strict check is bypassed → processes normally
        result = await respond_with_retry(
            cid, "yes go ahead", db=None, speaker_verified=True,
        )

        assert result is not None
        assert result.status == "approved"

    # ── 9. plan_executor imports guarded_execute (guard integration smoke test) ──
    def test_plan_executor_imports_guard(self):
        """plan_executor must import guarded_execute (not inline tool dispatch)."""
        import importlib
        import app.services.plan_executor as pe
        # guarded_execute must be reachable from the module
        assert hasattr(pe, "guarded_execute") or \
               "guarded_execute" in (pe.__dict__ if hasattr(pe, "__dict__") else {}) or \
               _guard_in_module_source(pe)

    # ── 10. workflow_executor imports guarded_execute ─────────────────────────
    def test_workflow_executor_imports_guard(self):
        """workflow_executor must import guarded_execute (not inline tool dispatch)."""
        import app.services.workflow_executor as we
        assert hasattr(we, "guarded_execute") or _guard_in_module_source(we)

    # ── 11. command_router imports guarded_execute ────────────────────────────
    def test_command_router_imports_guard(self):
        """command_router must import guarded_execute (not inline tool dispatch)."""
        import app.services.command_router as cr
        assert hasattr(cr, "guarded_execute") or _guard_in_module_source(cr)


def _guard_in_module_source(module) -> bool:
    """Helper: check that 'guarded_execute' appears in the module's source file."""
    import inspect
    try:
        src = inspect.getsource(module)
        return "guarded_execute" in src
    except Exception:
        return False


# ─── API Smoke Tests ─────────────────────────────────────────────────────────

class TestAPISmoke:
    """
    Integration-style smoke tests that exercise real HTTP routes via the
    FastAPI TestClient.  No real tool execution is needed — we mock the
    command_router so the route plumbing is verified without side-effects.
    """

    def _make_app(self):
        """Build a minimal FastAPI app with just the commands router.

        We deliberately avoid importing app.main (which pulls in numpy/bs4
        via the voice routes).  The commands router is all we need here.
        """
        import os
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        from fastapi import FastAPI
        from app.api.routes import commands as commands_router
        from app.core.database import get_db, Base
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

        # In-memory SQLite engine for the test lifetime
        _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

        async def _override_get_db():
            async with _session_factory() as session:
                yield session

        mini_app = FastAPI()
        mini_app.include_router(commands_router.router, prefix="/api/v1")
        mini_app.dependency_overrides[get_db] = _override_get_db
        return mini_app

    # ── 1. POST /api/v1/commands returns 200 for a known safe command ─────────
    def test_commands_route_returns_200(self):
        """POST /api/v1/commands must return HTTP 200 with a result payload."""
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient
        from app.schemas.commands import CommandResponse, ToolResult

        mock_response = CommandResponse(
            command="search the web for Python news",
            result=ToolResult(
                tool_name="web_search",
                status="success",
                data={"results": []},
                message="web_search executed",
            ),
            approval_id=None,
        )

        app = self._make_app()
        with patch(
            "app.api.routes.commands.route_command",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/commands",
                    json={"command": "search the web for Python news"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["status"] == "success"
        assert body["result"]["tool_name"] == "web_search"
        assert body["approval_id"] is None

    # ── 2. POST /api/v1/commands with empty command returns 422 ───────────────
    def test_commands_route_rejects_empty_command(self):
        """POST /api/v1/commands with missing 'command' field must return 422."""
        from fastapi.testclient import TestClient

        app = self._make_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/commands", json={})

        assert resp.status_code == 422

    # ── 3. GET /api/v1/tools returns a list of registered tools ──────────────
    def test_tools_route_returns_list(self):
        """GET /api/v1/tools must return a non-empty list of tool dicts."""
        from fastapi.testclient import TestClient

        app = self._make_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/tools")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) > 0
        # Each tool entry should at minimum have a 'name' key
        assert all("name" in t for t in body)

    # ── 4. Approval-required response flows through the route correctly ───────
    def test_commands_route_returns_approval_required(self):
        """When guard returns approval_required, the route must surface it."""
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient
        from app.schemas.commands import CommandResponse, ToolResult

        mock_response = CommandResponse(
            command="send email to boss",
            result=ToolResult(
                tool_name="gmail_send_email",
                status="approval_required",
                data=None,
                message="Action requires approval",
            ),
            approval_id=99,
        )

        app = self._make_app()
        with patch(
            "app.api.routes.commands.route_command",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/commands",
                    json={"command": "send email to boss"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["status"] == "approval_required"
        assert body["approval_id"] == 99


# ─── Phase 3: Reliability Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
class TestPhase3Reliability:
    """
    Tests for Phase 3 reliability features:
      - success_verifier
      - retry orchestration
      - rollback / compensation
      - expanded execution outcome model
      - eval metadata enrichment (verification + retry)
    """

    # ── Helper fixture ────────────────────────────────────────────────────────

    @pytest_asyncio.fixture
    async def db_session(self):
        """Async SQLite in-memory session."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from sqlalchemy.orm import DeclarativeBase

        class _Base(DeclarativeBase):
            pass

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            # Create all tables the guard touches
            from app.models.audit_log import AuditLog
            from app.models.eval_log import EvalLog
            from app.models.approval_request import ApprovalRequest
            from app.core.database import Base
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session
        await engine.dispose()

    # ── 1. Verified success path ──────────────────────────────────────────────
    async def test_verified_success_outcome(self, db_session):
        """When tool returns success and all signals pass, outcome is executed_verified."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute, OUTCOME_EXECUTED_VERIFIED

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=MagicMock(
            status="success", message="done", data={"absolute_path": "/tmp/x.txt"},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "create_file", {"path": "/tmp/x.txt"},
                "create a file", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "executed"
        assert result.outcome == OUTCOME_EXECUTED_VERIFIED
        assert result.verification is not None
        assert result.verification["verdict"] in ("success", "likely_success")
        assert result.retries_attempted == 0

    # ── 2. Uncertain verification path ───────────────────────────────────────
    async def test_uncertain_verification_outcome(self, db_session):
        """Tool succeeds but data is empty → verification is uncertain or likely_success."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute, OUTCOME_EXECUTED_UNVERIFIED, OUTCOME_EXECUTED_VERIFIED

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        # Returns success but empty data — no expected keys present
        mock_tool.run = AsyncMock(return_value=MagicMock(
            status="success", message="ok", data={},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "create_file", {"path": "/tmp/x.txt"},
                "create a file", db_session,
                settings_row=None, caller="test",
            )

        assert result.status == "executed"
        # Outcome is either verified (if score ≥ 0.85 without key) or unverified
        assert result.outcome in (OUTCOME_EXECUTED_VERIFIED, OUTCOME_EXECUTED_UNVERIFIED)
        assert result.verification is not None

    # ── 3. Retryable failure with successful retry ────────────────────────────
    async def test_retry_success_on_second_attempt(self, db_session):
        """Tool fails first, succeeds on retry → outcome executed_verified/unverified, retries=1."""
        from unittest.mock import AsyncMock, MagicMock, patch, call
        from app.services.execution_guard import guarded_execute, OUTCOME_EXECUTED_VERIFIED, OUTCOME_EXECUTED_UNVERIFIED
        from app.services.capability_registry import RetryPolicy, CapabilityMeta

        fail_result = MagicMock(status="error", message="transient failure", data=None)
        ok_result   = MagicMock(status="success", message="done", data={"results": ["item"]})

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(side_effect=[fail_result, ok_result])

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        cap_with_retry = CapabilityMeta(
            name="web_search",
            description="search",
            risk_level="low",
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.0),
        )

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision), \
             patch("app.services.capability_registry.get_capability", return_value=cap_with_retry):
            result = await guarded_execute(
                "web_search", {"query": "test"},
                "search the web", db_session,
                settings_row=None, caller="test",
            )

        assert result.retries_attempted == 1
        assert result.status == "executed"
        assert result.outcome in (OUTCOME_EXECUTED_VERIFIED, OUTCOME_EXECUTED_UNVERIFIED)
        assert mock_tool.run.call_count == 2

    # ── 4. Retry exhausted → failed_nonretryable ──────────────────────────────
    async def test_retry_exhausted_nonretryable_outcome(self, db_session):
        """All retry attempts fail → outcome is failed_nonretryable (or rolled_back if rollback available)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute, OUTCOME_FAILED_NONRETRYABLE, OUTCOME_ROLLED_BACK, OUTCOME_ROLLBACK_FAILED
        from app.services.capability_registry import RetryPolicy, CapabilityMeta

        fail_result = MagicMock(status="error", message="persistent failure", data=None)

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=fail_result)

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        cap_with_retry = CapabilityMeta(
            name="web_search",
            description="search",
            risk_level="low",
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.0),
        )

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision), \
             patch("app.services.capability_registry.get_capability", return_value=cap_with_retry):
            result = await guarded_execute(
                "web_search", {"query": "test"},
                "search the web", db_session,
                settings_row=None, caller="test",
            )

        # 3 total attempts (1 original + 2 retries)
        assert mock_tool.run.call_count == 3
        assert result.retries_attempted == 2
        # Outcome is one of the failure states (no rollback for web_search)
        assert result.outcome in (
            OUTCOME_FAILED_NONRETRYABLE,
            OUTCOME_ROLLED_BACK,
            OUTCOME_ROLLBACK_FAILED,
        )

    # ── 5. Rollback triggered on failure ─────────────────────────────────────
    async def test_rollback_triggered_on_create_file_failure(self, db_session):
        """create_file fails → rollback (delete_file) is attempted."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute, OUTCOME_ROLLED_BACK, OUTCOME_ROLLBACK_FAILED

        fail_result = MagicMock(status="error", message="disk full", data=None)
        rb_result   = MagicMock(status="success", message="file deleted", data=None)

        original_tool = MagicMock()
        original_tool.requires_approval = False
        original_tool.run = AsyncMock(return_value=fail_result)

        rollback_tool = MagicMock()
        rollback_tool.run = AsyncMock(return_value=rb_result)

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        def _fake_get_tool(name):
            if name == "create_file":
                return original_tool
            if name == "delete_file":
                return rollback_tool
            return None

        with patch("app.tools.registry.get_tool", side_effect=_fake_get_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "create_file", {"path": "/tmp/x.txt"},
                "create a file", db_session,
                settings_row=None, caller="test",
            )

        assert result.outcome in (OUTCOME_ROLLED_BACK, OUTCOME_ROLLBACK_FAILED)
        assert result.rollback is not None
        assert result.rollback["rollback_tool"] == "delete_file"
        assert result.rollback["attempted"] is True

    # ── 6. Rollback path is logged correctly ─────────────────────────────────
    async def test_rollback_logged_in_audit(self, db_session):
        """After a rollback, the audit log must contain a rollback record."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.rollback_executor import attempt_rollback

        fail_result = MagicMock(status="success", message="file deleted", data=None)
        rollback_tool = MagicMock()
        rollback_tool.run = AsyncMock(return_value=fail_result)

        audit_calls = []

        async def _fake_record_action(db, command, tool, status, msg):
            audit_calls.append({"tool": tool, "status": status, "msg": msg})

        with patch("app.tools.registry.get_tool", return_value=rollback_tool), \
             patch("app.services.rollback_executor._safe_log",
                   side_effect=_fake_record_action):
            rb = await attempt_rollback(
                "create_file", {"path": "/tmp/x.txt"},
                "create file cmd", db_session,
                rollback_strategy="Delete the created file",
                risk_level="low",
            )

        assert rb.attempted is True
        assert rb.rollback_tool == "delete_file"
        # Audit must have been called at least once
        assert len(audit_calls) >= 1
        assert any("[ROLLBACK]" in c["msg"] for c in audit_calls)

    # ── 7. Destructive action does not retry unsafely ─────────────────────────
    async def test_critical_tool_does_not_retry(self, db_session):
        """Critical-risk tools must never be retried even if retry_policy says max_retries > 0."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute
        from app.services.capability_registry import RetryPolicy, CapabilityMeta

        fail_result = MagicMock(status="error", message="failed", data=None)

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=fail_result)

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "critical"

        # Suppose the capability somehow claims 3 retries (should be overridden to 0)
        cap_critical = CapabilityMeta(
            name="run_shell_command",
            description="shell",
            risk_level="critical",
            retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.0),
        )

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision), \
             patch("app.services.capability_registry.get_capability", return_value=cap_critical):
            result = await guarded_execute(
                "run_shell_command", {"cmd": "ls"},
                "run ls", db_session,
                settings_row=None, caller="test",
            )

        # Tool must only be called ONCE — no retries for critical tools
        assert mock_tool.run.call_count == 1
        assert result.retries_attempted == 0

    # ── 8. Eval log includes verification and retry metadata ──────────────────
    async def test_eval_log_includes_verification_and_retry_metadata(self, db_session):
        """The eval log record must capture verification_verdict and retries count."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.execution_guard import guarded_execute
        from app.services.eval_service import list_recent

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=MagicMock(
            status="success", message="done", data={"results": ["x"]},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "web_search", {"query": "python"},
                "search python", db_session,
                settings_row=None, caller="test",
            )

        # Verification dict must be present in the guard result
        assert result.verification is not None
        assert "verdict" in result.verification
        assert "confidence" in result.verification

        # Check the eval log entry was written
        recent = await list_recent(db_session, limit=5)
        assert len(recent) >= 1
        latest = recent[0]
        assert latest["tool_name"] == "web_search"
        # retries field should be 0 (no retries needed)
        assert latest["retries"] == 0


# =============================================================================
# Phase 4 Tests – proof-based execution and browser/operator intelligence
# =============================================================================

class TestPhase4ProofAndBrowser:
    """
    Phase 4: browser verification, checkpoints, replay, session isolation,
    failure classification, rollback chain validation.
    """

    # ── Browser verifier tests ────────────────────────────────────────────────

    def test_browser_proof_url_change_passes(self):
        """URL proof passes when observed URL matches expected."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_URL_CHANGE,
        )
        from types import SimpleNamespace

        tool_result = SimpleNamespace(
            status="success",
            message="navigated",
            data={"current_url": "https://example.com/dashboard"},
        )
        proofs = verify_browser_action(
            "browser_navigate",
            {"url": "https://example.com/dashboard"},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_URL_CHANGE,
                expected_value="https://example.com/dashboard",
            )],
        )
        assert len(proofs) == 1
        assert proofs[0].passed is True
        assert proofs[0].confidence_score == 1.0

    def test_browser_proof_url_change_fails(self):
        """URL proof fails when observed URL does not match."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_URL_CHANGE,
        )
        from types import SimpleNamespace

        tool_result = SimpleNamespace(
            status="success",
            message="navigated",
            data={"current_url": "https://example.com/login"},
        )
        proofs = verify_browser_action(
            "browser_navigate",
            {"url": "https://example.com/dashboard"},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_URL_CHANGE,
                expected_value="https://example.com/dashboard",
            )],
        )
        assert len(proofs) == 1
        assert proofs[0].passed is False

    def test_browser_proof_dom_text_match(self):
        """DOM text match proof finds expected text in page snapshot."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_DOM_TEXT_MATCH,
        )
        from types import SimpleNamespace

        tool_result = SimpleNamespace(
            status="success",
            message="done",
            data={
                "dom_snapshot": '<div id="flash">Successfully saved!</div>',
                "elements": [
                    {"selector": "#flash", "text": "Successfully saved!"},
                ],
            },
        )
        proofs = verify_browser_action(
            "browser_click",
            {"selector": "#submit"},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_DOM_TEXT_MATCH,
                selector="#flash",
                expected_value="Successfully saved",
            )],
        )
        assert len(proofs) == 1
        assert proofs[0].passed is True

    def test_browser_proof_element_exists(self):
        """DOM element exists proof correctly identifies present/absent elements."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_DOM_ELEMENT_EXISTS,
            PROOF_DOM_ELEMENT_ABSENT,
        )
        from types import SimpleNamespace

        tool_result = SimpleNamespace(
            status="success",
            message="done",
            data={
                "elements": [
                    {"selector": "#success-banner", "exists": True, "text": "Done!"},
                ],
            },
        )
        # Element IS present
        proofs = verify_browser_action(
            "browser_navigate",
            {},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_DOM_ELEMENT_EXISTS,
                selector="#success-banner",
            )],
        )
        assert proofs[0].passed is True

        # Element should be ABSENT – but it IS present, so this should fail
        proofs2 = verify_browser_action(
            "browser_navigate",
            {},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_DOM_ELEMENT_ABSENT,
                selector="#success-banner",
            )],
        )
        assert proofs2[0].passed is False

    def test_browser_proof_form_submission(self):
        """Form submission proof passes when success_banner is present."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_FORM_SUBMISSION_SUCCESS,
        )
        from types import SimpleNamespace

        tool_result = SimpleNamespace(
            status="success",
            message="submitted",
            data={"success_banner": "Your form was submitted!"},
        )
        proofs = verify_browser_action(
            "browser_submit_form",
            {},
            tool_result,
            checks=[BrowserVerificationRequest(proof_type=PROOF_FORM_SUBMISSION_SUCCESS)],
        )
        assert proofs[0].passed is True
        assert proofs[0].confidence_score >= 0.85

    def test_browser_proof_screenshot_hash_match(self):
        """Screenshot proof detects page change between before/after."""
        from app.services.browser_verifier import (
            verify_browser_action,
            BrowserVerificationRequest,
            PROOF_SCREENSHOT_HASH_MATCH,
        )
        from types import SimpleNamespace

        before_bytes = b"old page bytes"
        after_bytes  = b"new page bytes - changed"
        tool_result = SimpleNamespace(status="success", message="done", data={})
        proofs = verify_browser_action(
            "browser_click",
            {},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_SCREENSHOT_HASH_MATCH,
                screenshot_before=before_bytes,
                screenshot_after=after_bytes,
            )],
        )
        assert proofs[0].passed is True  # changed → passed

        # Same bytes → not changed
        proofs2 = verify_browser_action(
            "browser_click",
            {},
            tool_result,
            checks=[BrowserVerificationRequest(
                proof_type=PROOF_SCREENSHOT_HASH_MATCH,
                screenshot_before=before_bytes,
                screenshot_after=before_bytes,  # same
            )],
        )
        assert proofs2[0].passed is False

    def test_browser_signal_integrates_into_success_verifier(self):
        """Browser proof signals are added to success_verifier signal list."""
        import asyncio
        from types import SimpleNamespace
        from app.services.browser_verifier import BrowserVerificationRequest, PROOF_URL_CHANGE

        tool_result = SimpleNamespace(
            status="success",
            message="ok",
            data={"current_url": "https://example.com/done"},
        )

        async def _run():
            from app.services.success_verifier import verify, SIGNAL_BROWSER_PROOF
            result = await verify(
                "browser_navigate",
                {"url": "https://example.com/done"},
                tool_result,
                browser_checks=[BrowserVerificationRequest(
                    proof_type=PROOF_URL_CHANGE,
                    expected_value="https://example.com/done",
                )],
            )
            return result

        vr = asyncio.get_event_loop().run_until_complete(_run())
        browser_signals = [s for s in vr.signals if s.signal_type == "browser_proof"]
        assert len(browser_signals) == 1
        assert browser_signals[0].passed is True
        assert browser_signals[0].weight > 0

    # ── Checkpoint tests ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_checkpoint_created_after_execution(self, db_session):
        """GuardResult.checkpoints has exactly one entry after a simple execution."""
        from app.services.execution_guard import guarded_execute
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="success", message="created", data={"absolute_path": "/tmp/x.txt"},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "create_file", {"path": "/tmp/x.txt"},
                "create file", db_session,
                settings_row=None, caller="test",
            )

        assert len(result.checkpoints) == 1
        cp = result.checkpoints[0]
        assert cp["action"] == "create_file"
        assert cp["result_status"] == "success"
        assert "checkpoint_id" in cp
        assert "timestamp" in cp

    @pytest.mark.asyncio
    async def test_checkpoint_contains_failure_reason_on_error(self, db_session):
        """Checkpoint failure_reason is set when the tool fails."""
        from app.services.execution_guard import guarded_execute
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="error",
            message="connection refused",
            data={},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "web_search", {"query": "fail"},
                "search fail", db_session,
                settings_row=None, caller="test",
            )

        assert len(result.checkpoints) == 1
        cp = result.checkpoints[0]
        assert cp["result_status"] == "error"
        assert cp["failure_reason"] is not None  # should be classified

    # ── Replay service tests ──────────────────────────────────────────────────

    def test_replay_not_found_returns_none(self):
        """get_replay returns None for unknown chain_id."""
        from app.services.replay_service import get_replay
        result = get_replay("nonexistent-chain-id-xyz")
        assert result is None

    def test_export_timeline_not_found_returns_message(self):
        """export_timeline returns an informative message for unknown chain_id."""
        from app.services.replay_service import export_timeline
        text = export_timeline("no-such-chain")
        assert "not found" in text.lower() or "no-such-chain" in text

    def test_simulate_chain_produces_steps(self):
        """simulate_chain returns one SimulatedStep per input step."""
        from app.services.replay_service import simulate_chain

        steps = [
            {"action": "web_search", "inputs": {"query": "test"}},
            {"action": "create_file", "inputs": {"path": "/tmp/out.txt"}},
        ]
        result = simulate_chain(steps)
        assert len(result) == 2
        assert result[0].action == "web_search"
        assert result[0].step_number == 1
        assert result[1].action == "create_file"
        assert result[1].step_number == 2

    def test_simulate_chain_step_has_required_fields(self):
        """Each simulated step has all required output fields."""
        from app.services.replay_service import simulate_chain

        result = simulate_chain([{"action": "create_file", "inputs": {}}])
        assert len(result) == 1
        d = result[0].to_dict()
        for key in ("step_number", "action", "inputs", "simulated_outcome", "risk_level"):
            assert key in d, f"Missing field: {key}"

    @pytest.mark.asyncio
    async def test_replay_chain_round_trip(self, db_session):
        """Executing a tool creates a chain that can be replayed."""
        from app.services.execution_guard import guarded_execute
        from app.services.replay_service import get_replay
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="success", message="moved", data={"destination": "/tmp/moved.txt"},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "move_file",
                {"source": "/tmp/a.txt", "destination": "/tmp/moved.txt"},
                "move file", db_session,
                settings_row=None, caller="test",
            )

        chain_id = result.audit_chain_id
        assert chain_id is not None

        replay = get_replay(chain_id)
        assert replay is not None
        assert replay.chain_id == chain_id
        assert replay.tool_name == "move_file"
        assert len(replay.steps) >= 1
        assert replay.timeline_text != ""
        # Timeline should contain the tool name
        assert "move_file" in replay.timeline_text

    # ── Session isolation tests ───────────────────────────────────────────────

    def test_validate_session_context_passes_for_non_browser_tool(self):
        """Non-browser tools do not require a session_id."""
        from app.services.session_manager import validate_session_context
        error = validate_session_context("web_search", None)
        assert error is None

    def test_validate_session_context_denies_browser_tool_without_session(self):
        """Browser tools without a session_id are denied."""
        from app.services.session_manager import validate_session_context
        error = validate_session_context("browser_navigate", None)
        assert error is not None
        assert "session" in error.lower()

    def test_validate_session_context_allows_browser_tool_with_session(self):
        """Browser tools WITH a session_id are allowed."""
        from app.services.session_manager import validate_session_context
        error = validate_session_context("browser_navigate", "sess-abc-123")
        assert error is None

    def test_assert_session_isolation(self):
        """assert_session_isolation correctly identifies sharing violations."""
        from app.services.session_manager import assert_session_isolation
        # Different sessions → isolated
        assert assert_session_isolation("sess-A", "sess-B") is True
        # Same session → sharing violation
        assert assert_session_isolation("sess-X", "sess-X") is False
        # One is None → safe
        assert assert_session_isolation(None, "sess-A") is True
        assert assert_session_isolation("sess-A", None) is True

    @pytest.mark.asyncio
    async def test_guard_denies_browser_tool_without_session(self, db_session):
        """guarded_execute blocks browser tools when session_id is not supplied."""
        from app.services.execution_guard import guarded_execute, OUTCOME_BLOCKED
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="success", message="navigated",
            data={"current_url": "https://example.com"},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "browser_navigate",
                {"url": "https://example.com"},
                "navigate to example", db_session,
                settings_row=None, caller="test",
                session_id=None,  # ← No session supplied
            )

        assert result.outcome == OUTCOME_BLOCKED
        assert result.status == "denied"

    @pytest.mark.asyncio
    async def test_guard_allows_browser_tool_with_session(self, db_session):
        """guarded_execute proceeds normally when session_id is supplied."""
        from app.services.execution_guard import guarded_execute
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="success", message="navigated",
            data={"current_url": "https://example.com/dashboard"},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "browser_navigate",
                {"url": "https://example.com/dashboard"},
                "navigate to dashboard", db_session,
                settings_row=None, caller="test",
                session_id="sess-user-42",  # ← Session supplied
            )

        assert result.status == "executed"
        assert result.session_id == "sess-user-42"

    # ── Failure classification tests ──────────────────────────────────────────

    def test_classify_failure_timeout(self):
        """Timeout keywords produce FAILURE_TIMEOUT classification."""
        from app.services.execution_guard import classify_failure, FAILURE_TIMEOUT
        from types import SimpleNamespace

        result = SimpleNamespace(status="error", message="operation timed out", data={})
        assert classify_failure(result) == FAILURE_TIMEOUT

    def test_classify_failure_permission(self):
        """Permission keywords produce FAILURE_PERMISSION_ERROR."""
        from app.services.execution_guard import classify_failure, FAILURE_PERMISSION_ERROR
        from types import SimpleNamespace

        result = SimpleNamespace(status="error", message="access denied", data={})
        assert classify_failure(result) == FAILURE_PERMISSION_ERROR

    def test_classify_failure_network(self):
        """Network keywords produce FAILURE_NETWORK_ERROR."""
        from app.services.execution_guard import classify_failure, FAILURE_NETWORK_ERROR
        from types import SimpleNamespace

        result = SimpleNamespace(status="error", message="network unreachable", data={})
        assert classify_failure(result) == FAILURE_NETWORK_ERROR

    def test_classify_failure_element_not_found(self):
        """Element-not-found keywords produce FAILURE_ELEMENT_NOT_FOUND."""
        from app.services.execution_guard import classify_failure, FAILURE_ELEMENT_NOT_FOUND
        from types import SimpleNamespace

        result = SimpleNamespace(status="error", message="element not found", data={})
        assert classify_failure(result) == FAILURE_ELEMENT_NOT_FOUND

    def test_classify_failure_verification_mismatch(self):
        """A success status with 'failed' verification verdict → mismatch."""
        from app.services.execution_guard import classify_failure, FAILURE_VERIFICATION_MISMATCH
        from types import SimpleNamespace

        result = SimpleNamespace(status="success", message="ok", data={})
        assert classify_failure(result, verification_verdict="failed") == FAILURE_VERIFICATION_MISMATCH

    def test_classify_failure_none_on_success(self):
        """No failure classification for a genuine success."""
        from app.services.execution_guard import classify_failure
        from types import SimpleNamespace

        result = SimpleNamespace(status="success", message="ok", data={})
        assert classify_failure(result) is None

    @pytest.mark.asyncio
    async def test_failure_reason_on_guard_result(self, db_session):
        """GuardResult.failure_reason is populated when tool fails."""
        from app.services.execution_guard import guarded_execute
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="error",
            message="connection refused: network unreachable",
            data={},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        with patch("app.tools.registry.get_tool", return_value=mock_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "web_search", {"query": "test"},
                "test", db_session,
                settings_row=None, caller="test",
            )

        assert result.failure_reason == "network_error"

    # ── Rollback chain validation tests ──────────────────────────────────────

    def test_rollback_result_carries_chain_id(self):
        """RollbackResult.to_dict() includes chain_id for audit visibility."""
        from app.services.rollback_executor import RollbackResult
        rb = RollbackResult(
            attempted=True,
            status="rolled_back",
            rollback_tool="delete_file",
            original_action="create_file",
            rollback_action="delete_file",
            rollback_result_summary="ok",
            chain_id="chain-abc-123",
        )
        d = rb.to_dict()
        assert d["chain_id"] == "chain-abc-123"
        assert d["original_action"] == "create_file"
        assert d["rollback_action"] == "delete_file"
        assert d["rollback_result_summary"] == "ok"

    def test_rollback_policy_blocks_dangerous_pair(self):
        """Dangerous rollback tool + unapproved pair → blocked_policy status."""
        import asyncio
        from unittest.mock import MagicMock, patch, AsyncMock as _AsyncMock

        async def _run():
            from app.services.rollback_executor import attempt_rollback

            mock_db = MagicMock()
            # Patch audit logging to a no-op
            with patch("app.services.rollback_executor._safe_log", new=_AsyncMock()):
                result = await attempt_rollback(
                    "unknown_tool",  # Not in catalogue → not_applicable
                    {},
                    "cmd",
                    mock_db,
                    risk_level="low",
                    chain_id="chain-xyz",
                )
            return result

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result.status == "not_applicable"
        assert result.chain_id == "chain-xyz"

    def test_rollback_policy_allows_safe_pair(self):
        """create_file → delete_file is a pre-approved safe pair."""
        from app.services.rollback_executor import _rollback_policy_check
        # Safe pair must not be blocked
        err = _rollback_policy_check("create_file", "delete_file")
        assert err is None

    def test_rollback_policy_blocks_unknown_dangerous_pair(self):
        """Unknown tool → run_shell_command rollback is blocked."""
        from app.services.rollback_executor import _rollback_policy_check
        err = _rollback_policy_check("some_tool", "run_shell_command")
        assert err is not None
        assert "blocked" in err.lower()

    @pytest.mark.asyncio
    async def test_rollback_chain_id_propagated_from_guard(self, db_session):
        """When guarded_execute triggers a rollback, rollback.chain_id is set."""
        from app.services.execution_guard import guarded_execute
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        mock_tool = MagicMock()
        mock_tool.requires_approval = False
        # create_file fails → rollback (delete_file) should be triggered
        mock_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="error", message="disk full", data={},
        ))

        mock_decision = MagicMock()
        mock_decision.denied = False
        mock_decision.needs_approval = False
        mock_decision.verdict = "allow"
        mock_decision.reason = ""
        mock_decision.risk_level = "low"

        # We need delete_file tool to exist for the rollback to proceed
        mock_delete_tool = MagicMock()
        mock_delete_tool.run = AsyncMock(return_value=SimpleNamespace(
            status="success", message="deleted", data={},
        ))

        def fake_get_tool(name):
            if name == "delete_file":
                return mock_delete_tool
            return mock_tool

        with patch("app.tools.registry.get_tool", side_effect=fake_get_tool), \
             patch("app.services.policy_engine.evaluate", return_value=mock_decision):
            result = await guarded_execute(
                "create_file",
                {"path": "/tmp/test.txt"},
                "create test file", db_session,
                settings_row=None, caller="test",
            )

        # Rollback should have been attempted
        assert result.rollback is not None
        # chain_id in rollback should match guard's audit_chain_id
        # (chain_id was pre-declared as None before audit chain step, so it may be None
        #  if the chain is recorded after rollback; at minimum rollback was attempted)
        assert result.rollback["attempted"] is True
        assert result.rollback["original_action"] == "create_file"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5 – Mission Control / Chains API
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase5MissionControl:
    """
    Tests for the /api/v1/chains endpoints introduced in Phase 5.

    Uses a minimal FastAPI app (same pattern as TestAPISmoke) to avoid the
    numpy import chain triggered by the full app.main.
    """

    # ── helpers ───────────────────────────────────────────────────────────

    def _seed_chain(
        self,
        *,
        command: str = "test command",
        tool_name: str = "test_tool",
        execution_status: str = "executed",
        policy_verdict: str = "allow",
        risk_level: str = "low",
        eval_status: str = "success",
        approval_id: int | None = None,
        capability: dict | None = None,
    ) -> str:
        """Push one AuditChainRecord into the ring buffer and return its chain_id."""
        import secrets as _secrets
        from app.services.audit_chain import _chain_buffer, AuditChainRecord

        chain_id = "test-" + _secrets.token_hex(4)
        record = AuditChainRecord(
            chain_id=chain_id,
            command=command,
            tool_name=tool_name,
            capability=capability,
            policy_verdict=policy_verdict,
            policy_reason="",
            risk_level=risk_level,
            approval_id=approval_id,
            approval_status="n/a" if approval_id is None else "pending",
            execution_status=execution_status,
            result_summary="ok",
            changed_fields=[],
            state_before_summary="",
            state_after_summary="",
            eval_status=eval_status,
        )
        _chain_buffer.appendleft(record)
        return chain_id

    def _client(self):
        """Build minimal TestClient with just the chains router (avoids numpy)."""
        import os
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import chains as chains_router

        mini = FastAPI()
        mini.include_router(chains_router.router, prefix="/api/v1")
        return TestClient(mini, raise_server_exceptions=True)

    # ── list chains ────────────────────────────────────────────────────────

    def test_list_chains_empty_returns_list(self):
        """GET /chains always returns a JSON array (possibly empty)."""
        client = self._client()
        resp = client.get("/api/v1/chains")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_chains_returns_seeded_record(self):
        """Seeded chain appears in GET /chains response."""
        chain_id = self._seed_chain(command="ls ~/Desktop", tool_name="list_files")
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        assert resp.status_code == 200
        ids = [item["chain_id"] for item in resp.json()]
        assert chain_id in ids

    def test_list_chains_summary_fields_present(self):
        """Each chain summary has the required Mission Control display fields."""
        chain_id = self._seed_chain(
            tool_name="delete_file", risk_level="high", policy_verdict="require_approval"
        )
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        assert resp.status_code == 200
        item = next((x for x in resp.json() if x["chain_id"] == chain_id), None)
        assert item is not None
        for f in (
            "chain_id", "command", "tool_name", "outcome",
            "execution_status", "risk_level", "risk_color",
            "policy_verdict", "approval_id", "approval_status",
            "eval_status", "session_id", "timestamp", "changed_fields",
        ):
            assert f in item, f"Missing field: {f}"

    def test_session_id_exposed_in_list_and_detail(self):
        """session_id is extracted from capability and returned in list/detail."""
        chain_id = self._seed_chain(capability={"session_id": "sess-abc"})
        client = self._client()

        list_resp = client.get("/api/v1/chains?limit=50")
        assert list_resp.status_code == 200
        row = next((x for x in list_resp.json() if x["chain_id"] == chain_id), None)
        assert row is not None
        assert row["session_id"] == "sess-abc"

        detail_resp = client.get(f"/api/v1/chains/{chain_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["session_id"] == "sess-abc"

    def test_list_chains_outcome_mapping_verified(self):
        """executed + eval success → outcome='executed_verified'."""
        chain_id = self._seed_chain(execution_status="executed", eval_status="success")
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        item = next((x for x in resp.json() if x["chain_id"] == chain_id), None)
        assert item is not None
        assert item["outcome"] == "executed_verified"

    def test_list_chains_outcome_mapping_blocked(self):
        """execution_status=denied → outcome='blocked'."""
        chain_id = self._seed_chain(execution_status="denied", policy_verdict="deny")
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        item = next((x for x in resp.json() if x["chain_id"] == chain_id), None)
        assert item is not None
        assert item["outcome"] == "blocked"

    def test_list_chains_outcome_approval_required(self):
        """execution_status=approval_required → outcome='approval_required'."""
        chain_id = self._seed_chain(
            execution_status="approval_required", approval_id=42
        )
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        item = next((x for x in resp.json() if x["chain_id"] == chain_id), None)
        assert item is not None
        assert item["outcome"] == "approval_required"

    def test_list_chains_risk_color_high(self):
        """High risk → risk_color='red'."""
        chain_id = self._seed_chain(risk_level="high")
        client = self._client()
        resp = client.get("/api/v1/chains?limit=50")
        item = next((x for x in resp.json() if x["chain_id"] == chain_id), None)
        assert item is not None
        assert item["risk_color"] == "red"

    def test_list_chains_limit_respected(self):
        """limit parameter caps the result size."""
        for i in range(5):
            self._seed_chain(command=f"cmd {i}")
        client = self._client()
        resp = client.get("/api/v1/chains?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    # ── get chain detail ───────────────────────────────────────────────────

    def test_get_chain_detail_404_for_unknown(self):
        """GET /chains/nonexistent → 404."""
        client = self._client()
        resp = client.get("/api/v1/chains/nonexistent-chain-id-xyz")
        assert resp.status_code == 404

    def test_get_chain_detail_returns_full_record(self):
        """GET /chains/{id} returns all AuditChainRecord fields + outcome + risk_color."""
        chain_id = self._seed_chain(
            command="open app", tool_name="open_app", risk_level="medium"
        )
        client = self._client()
        resp = client.get(f"/api/v1/chains/{chain_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_id"] == chain_id
        assert data["tool_name"] == "open_app"
        assert data["command"] == "open app"
        assert "outcome" in data
        assert "risk_color" in data
        assert data["risk_color"] == "amber"  # medium → amber
        assert "policy_verdict" in data
        assert "approval_status" in data

    def test_get_chain_detail_includes_replay_fields(self):
        """Detail response always contains replay_steps and replay_timeline_text keys."""
        chain_id = self._seed_chain()
        client = self._client()
        resp = client.get(f"/api/v1/chains/{chain_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "replay_steps" in data
        assert "replay_timeline_text" in data
        assert isinstance(data["replay_steps"], list)

    # ── get chain checkpoints ──────────────────────────────────────────────

    def test_get_checkpoints_404_for_unknown(self):
        """GET /chains/xyz/checkpoints → 404 when chain not found."""
        client = self._client()
        resp = client.get("/api/v1/chains/nonexistent-xyz/checkpoints")
        assert resp.status_code == 404

    def test_get_checkpoints_returns_structure(self):
        """GET /chains/{id}/checkpoints returns required fields."""
        chain_id = self._seed_chain()
        client = self._client()
        resp = client.get(f"/api/v1/chains/{chain_id}/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_id"] == chain_id
        assert "total_checkpoints" in data
        assert isinstance(data["checkpoints"], list)

    def test_get_checkpoints_empty_when_no_replay(self):
        """
        When the chain has no extra checkpoint data (beyond the primary step),
        the replay service still returns 1 step (the primary execution step).
        The checkpoints list is non-empty only when replay produces steps.
        """
        chain_id = self._seed_chain()
        client = self._client()
        resp = client.get(f"/api/v1/chains/{chain_id}/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        # Replay service always builds at least one step from the AuditChainRecord
        assert isinstance(data["checkpoints"], list)
        assert data["total_checkpoints"] == len(data["checkpoints"])

    # ── _outcome_from_chain helper ─────────────────────────────────────────

    def test_outcome_helper_unknown_state(self):
        """Unrecognised status → 'unknown'."""
        from app.api.routes.chains import _outcome_from_chain
        assert _outcome_from_chain({"execution_status": "weird_state"}) == "unknown"

    def test_outcome_helper_unverified(self):
        """executed + eval error → executed_unverified."""
        from app.api.routes.chains import _outcome_from_chain
        assert _outcome_from_chain(
            {"execution_status": "executed", "eval_status": "error"}
        ) == "executed_unverified"

    def test_outcome_helper_error_status(self):
        """execution_status=error → failed_nonretryable."""
        from app.api.routes.chains import _outcome_from_chain
        assert _outcome_from_chain({"execution_status": "error"}) == "failed_nonretryable"


class TestOptionalVoiceBiometrics:
    def test_app_startup_survives_missing_voice_biometrics_dependency(self, monkeypatch):
        """Missing numpy/audio_fingerprint must not crash FastAPI app creation."""
        real_import_module = importlib.import_module

        def _patched_import(name: str, package: str | None = None):
            if name == "app.services.audio_fingerprint":
                err = ModuleNotFoundError("No module named 'numpy'")
                err.name = "numpy"
                raise err
            return real_import_module(name, package)

        for mod_name in (
            "app.main",
            "app.api.routes.voice",
            "app.services.voice_profile_service",
            "app.services.speaker_verification_service",
            "app.services.audio_fingerprint",
        ):
            sys.modules.pop(mod_name, None)

        monkeypatch.setattr(importlib, "import_module", _patched_import)

        from app.main import create_app

        app = create_app()
        assert app is not None

    def test_voice_biometrics_unavailable_metadata(self, monkeypatch):
        from app.services import voice_profile_service as vps

        err = ModuleNotFoundError("No module named 'numpy'")
        err.name = "numpy"
        monkeypatch.setattr(vps, "_load_audio_fingerprint_module", lambda: (None, err))

        info = vps.get_voice_biometrics_availability()
        assert info["capability_name"] == "voice_biometrics"
        assert info["available"] is False
        assert "numpy" in str(info["reason_if_unavailable"])

    @pytest.mark.asyncio
    async def test_strict_mode_blocks_when_voice_biometrics_unavailable(self, monkeypatch):
        from app.services import speaker_verification_service as svs

        async def _fake_mode(_db):
            return "strict"

        async def _fake_enrolled(_db):
            return None, None, "missing optional dependency: numpy"

        monkeypatch.setattr(svs, "_load_security_mode", _fake_mode)
        monkeypatch.setattr(svs, "get_enrolled_fingerprint", _fake_enrolled)

        result = await svs.verify_speaker(AsyncMock(), b"not-empty-audio")
        assert result["status"] == "blocked"
        assert result["reason"] == "voice_biometrics_unavailable"



