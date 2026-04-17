"""
Tests for Phase 6: Skill Proposal Engine.

Covers:
  1. Pattern detection (unit) – correctness, deduplication, confidence
  2. Proposal service (unit) – creation, idempotency, approve/reject
  3. API endpoints (integration) – list, scan, approve, reject
  4. Safety invariants – guard not touched, nothing executed
  5. Phase 6.5 – feedback, dismiss, relevance scoring, near-duplicate suppression,
     configurable thresholds, new API endpoints
"""
from __future__ import annotations

import datetime
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import init_db, AsyncSessionLocal
from app.models.skill_proposal import SkillProposal
from app.services.pattern_detector import (
    DetectedPattern,
    ScanConfig,
    detect_patterns,
    suppress_near_duplicates,
    _similarity,
    _stable_id,
    _group_chains,
    MIN_FREQUENCY,
)
from app.services.skill_proposal_service import (
    approve_proposal,
    compute_relevance_score,
    dismiss_proposal,
    list_proposals,
    proposal_to_dict,
    rank_proposals,
    record_feedback,
    reject_proposal,
    run_detection_and_propose,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_chain(
    tool_name: str = "file_tool",
    command: str = "read ~/Desktop/report.pdf",
    execution_status: str = "executed",
    chain_id: str | None = None,
    ts: str | None = None,
    risk_level: str = "low",
) -> dict:
    return {
        "chain_id": chain_id or f"chain-{tool_name}-{command[:8]}",
        "tool_name": tool_name,
        "command": command,
        "execution_status": execution_status,
        "risk_level": risk_level,
        "timestamp": ts or datetime.datetime.utcnow().isoformat(),
    }


def _repeat(n: int, **kwargs) -> list[dict]:
    return [_make_chain(chain_id=f"c{i}", **kwargs) for i in range(n)]


async def _truncate_proposals() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SkillProposal))
        await session.commit()


# ─── 1. Pattern Detector – unit tests ────────────────────────────────────────

class TestSimilarity:
    def test_identical(self):
        assert _similarity("read file foo.txt", "read file foo.txt") == 1.0

    def test_completely_different(self):
        assert _similarity("alpha beta", "gamma delta") == 0.0

    def test_partial_overlap(self):
        s = _similarity("open file report.pdf", "open document report.pdf")
        assert 0.0 < s < 1.0

    def test_empty_strings(self):
        assert _similarity("", "") == 1.0

    def test_one_empty(self):
        assert _similarity("hello world", "") == 0.0


class TestStableId:
    def test_deterministic(self):
        a = _stable_id("file_tool", "read ~/Desktop/report.pdf")
        b = _stable_id("file_tool", "read ~/Desktop/report.pdf")
        assert a == b

    def test_different_tools_differ(self):
        a = _stable_id("file_tool", "read ~/Desktop/report.pdf")
        b = _stable_id("other_tool", "read ~/Desktop/report.pdf")
        assert a != b

    def test_prefix(self):
        assert _stable_id("x", "y").startswith("pat_")


class TestGroupChains:
    def test_groups_similar_commands(self):
        chains = _repeat(4, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        groups = _group_chains(chains)
        assert len(groups) == 1
        key = next(iter(groups))
        assert len(groups[key]) == 4

    def test_ignores_non_executed(self):
        chains = _repeat(5, execution_status="denied")
        assert _group_chains(chains) == {}

    def test_separates_different_tools(self):
        chains = (
            _repeat(4, tool_name="file_tool", command="read file.pdf")
            + _repeat(4, tool_name="web_tool", command="search duckduckgo")
        )
        groups = _group_chains(chains)
        assert len(groups) == 2


class TestDetectPatterns:
    def test_returns_empty_for_no_chains(self):
        assert detect_patterns(chains=[]) == []

    def test_below_min_frequency_no_pattern(self):
        chains = _repeat(2, tool_name="file_tool", command="read foo.txt")
        result = detect_patterns(chains=chains, min_frequency=3)
        assert result == []

    def test_above_min_frequency_detects_pattern(self):
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        result = detect_patterns(chains=chains, min_frequency=3)
        assert len(result) == 1
        p = result[0]
        assert isinstance(p, DetectedPattern)
        assert p.frequency == 5
        assert 0.0 < p.confidence <= 1.0
        assert p.tool_name == "file_tool"
        assert len(p.steps) >= 1

    def test_sorted_by_confidence_descending(self):
        # Two distinct patterns – one more frequent than the other
        chains = (
            _repeat(8, tool_name="file_tool", command="read ~/Desktop/report.pdf")
            + _repeat(3, tool_name="web_tool", command="search something else query")
        )
        result = detect_patterns(chains=chains, min_frequency=3)
        if len(result) >= 2:
            assert result[0].confidence >= result[1].confidence

    def test_different_tools_give_separate_patterns(self):
        chains = (
            _repeat(4, tool_name="file_tool", command="read invoice.pdf")
            + _repeat(4, tool_name="web_tool", command="search duckduckgo news")
        )
        result = detect_patterns(chains=chains, min_frequency=3)
        tool_names = {p.tool_name for p in result}
        assert "file_tool" in tool_names
        assert "web_tool" in tool_names

    def test_pattern_id_stable(self):
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        r1 = detect_patterns(chains=chains, min_frequency=3)
        r2 = detect_patterns(chains=chains, min_frequency=3)
        assert r1[0].pattern_id == r2[0].pattern_id

    def test_chain_ids_included(self):
        chains = _repeat(4, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        result = detect_patterns(chains=chains, min_frequency=3)
        assert len(result) == 1
        assert len(result[0].chain_ids) == 4


# ─── 2. Proposal Service – unit tests ────────────────────────────────────────

@pytest_asyncio.fixture()
async def clean_db():
    await init_db()
    await _truncate_proposals()
    yield
    await _truncate_proposals()


@pytest.mark.asyncio
async def test_run_detection_creates_proposals(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
    assert len(created) == 1
    p = created[0]
    assert p.status == "proposed"
    assert p.frequency == 5
    assert "file_tool" in p.title or "File" in p.title


@pytest.mark.asyncio
async def test_run_detection_idempotent(clean_db):
    """Running detection twice on same chains must not duplicate proposals."""
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        first = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
    async with AsyncSessionLocal() as session:
        second = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
    assert len(first) == 1
    assert len(second) == 0   # no duplicate


@pytest.mark.asyncio
async def test_approve_proposal(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        proposal_id = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await approve_proposal(session, proposal_id)
        await session.commit()

    assert updated is not None
    assert updated.status == "approved"


@pytest.mark.asyncio
async def test_reject_proposal(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        proposal_id = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await reject_proposal(session, proposal_id)
        await session.commit()

    assert updated is not None
    assert updated.status == "rejected"


@pytest.mark.asyncio
async def test_approve_nonexistent_returns_none(clean_db):
    async with AsyncSessionLocal() as session:
        result = await approve_proposal(session, proposal_id=99999)
    assert result is None


@pytest.mark.asyncio
async def test_list_proposals_filtered(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id
        await approve_proposal(session, pid)
        await session.commit()

    async with AsyncSessionLocal() as session:
        approved_list = await list_proposals(session, status="approved")
        proposed_list = await list_proposals(session, status="proposed")

    assert len(approved_list) == 1
    assert len(proposed_list) == 0


@pytest.mark.asyncio
async def test_proposal_to_dict_shape(clean_db):
    chains = _repeat(4, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        d = proposal_to_dict(created[0])

    assert "id" in d
    assert "title" in d
    assert "steps" in d
    assert "risk_level" in d
    assert "status" in d
    assert "chain_ids" in d
    assert isinstance(d["chain_ids"], list)


# ─── 3. API Endpoints – integration tests ─────────────────────────────────────

from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.settings import UserSettings
from app.models.audit_log import AuditLog


@pytest_asyncio.fixture()
async def api_client():
    await init_db()
    await _truncate_proposals()
    # Clear settings and audit rows for a clean app state
    async with AsyncSessionLocal() as session:
        await session.execute(delete(UserSettings))
        await session.execute(delete(AuditLog))
        await session.commit()

    # ── Clear the shared in-memory audit-chain ring buffer ────────────────
    # _chain_buffer is a module-level deque that persists across the whole
    # pytest process.  TestPhase5MissionControl (test_new_layers.py) seeds
    # it with ≥ MIN_FREQUENCY identical "test_tool / test command / executed"
    # entries; if those tests run first, the /scan endpoint finds real
    # patterns and test_scan_no_chains fails with proposals_created > 0.
    from app.services.audit_chain import _chain_buffer
    _chain_buffer.clear()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await _truncate_proposals()
    _chain_buffer.clear()   # restore isolation for any tests that follow


@pytest.mark.asyncio
async def test_list_skill_proposals_empty(api_client):
    resp = await api_client.get("/api/v1/skill-proposals")
    assert resp.status_code == 200
    data = resp.json()
    assert "proposals" in data
    assert "total" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_scan_no_chains(api_client):
    """Scan with no chains in ring buffer returns ok with 0 created."""
    resp = await api_client.post("/api/v1/skill-proposals/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["proposals_created"] == 0


@pytest.mark.asyncio
async def test_approve_nonexistent_proposal(api_client):
    resp = await api_client.post("/api/v1/skill-proposals/99999/approve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_nonexistent_proposal(api_client):
    resp = await api_client.post("/api/v1/skill-proposals/99999/reject")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_reject_via_api(api_client):
    """Create a proposal directly and approve / reject it via the API."""
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")

    # Seed a proposal via service, bypassing the ring buffer
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        proposal_id = created[0].id

    # Approve via API
    resp = await api_client.post(f"/api/v1/skill-proposals/{proposal_id}/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["proposal"]["status"] == "approved"

    # Get via list endpoint – should show approved
    resp2 = await api_client.get("/api/v1/skill-proposals?status=approved")
    assert resp2.status_code == 200
    assert resp2.json()["total"] == 1


@pytest.mark.asyncio
async def test_reject_via_api(api_client):
    chains = _repeat(5, tool_name="web_tool", command="search duckduckgo daily news")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        proposal_id = created[0].id

    resp = await api_client.post(f"/api/v1/skill-proposals/{proposal_id}/reject")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["proposal"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_get_single_proposal(api_client):
    chains = _repeat(4, tool_name="pdf_tool", command="extract text invoice.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        proposal_id = created[0].id

    resp = await api_client.get(f"/api/v1/skill-proposals/{proposal_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal"]["id"] == proposal_id


@pytest.mark.asyncio
async def test_get_nonexistent_proposal(api_client):
    resp = await api_client.get("/api/v1/skill-proposals/88888")
    assert resp.status_code == 404


# ─── 4. Safety invariants ─────────────────────────────────────────────────────

class TestSafetyInvariants:
    """Approve must NEVER trigger execution.  This is tested by confirming that
    the approve service only mutates the `status` column."""

    @pytest.mark.asyncio
    async def test_approve_only_changes_status(self, clean_db):
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        async with AsyncSessionLocal() as session:
            created = await run_detection_and_propose(
                session, chains=chains, min_frequency=3
            )
            await session.commit()
            original = created[0]
            original_title = original.title
            original_steps = list(original.steps)
            original_chain_ids = list(original.chain_ids)
            pid = original.id

        async with AsyncSessionLocal() as session:
            updated = await approve_proposal(session, pid)
            await session.commit()

        # Only status changes; everything else stays the same
        assert updated is not None
        assert updated.status == "approved"
        assert updated.title == original_title
        assert updated.steps == original_steps
        assert updated.chain_ids == original_chain_ids

    @pytest.mark.asyncio
    async def test_proposal_has_no_generated_code(self, clean_db):
        """Proposals must not carry generated_code or executable payloads."""
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        async with AsyncSessionLocal() as session:
            created = await run_detection_and_propose(
                session, chains=chains, min_frequency=3
            )
            await session.commit()
            d = proposal_to_dict(created[0])

        # These fields should NOT exist – safe mode only
        assert "generated_code" not in d
        assert "executable" not in d
        assert "plugin_path" not in d


# ─── 5. Phase 6.5 – feedback, dismiss, relevance, suppression ────────────────

class TestNearDuplicateSuppression:
    """Unit tests for suppress_near_duplicates()."""

    def _make_pattern(self, pid: str, tool: str, cmd: str, freq: int = 5, conf: float = 0.8) -> DetectedPattern:
        now = datetime.datetime.utcnow().isoformat()
        return DetectedPattern(
            pattern_id=pid,
            tool_name=tool,
            command_template=cmd,
            steps=[],
            frequency=freq,
            confidence=conf,
            risk_level="low",
            chain_ids=[],
            first_seen=now,
            last_seen=now,
        )

    def test_identical_commands_suppressed(self):
        a = self._make_pattern("pat_a", "bash", "ls -la /home/user", conf=0.9)
        b = self._make_pattern("pat_b", "bash", "ls -la /home/user", conf=0.6)
        result = suppress_near_duplicates([a, b])
        assert getattr(result[1], "suppressed_by", None) == "pat_a"
        assert getattr(result[0], "suppressed_by", None) is None

    def test_different_tools_not_suppressed(self):
        a = self._make_pattern("pat_a", "bash", "ls -la /home/user", conf=0.9)
        b = self._make_pattern("pat_b", "python", "ls -la /home/user", conf=0.6)
        result = suppress_near_duplicates([a, b])
        assert getattr(result[1], "suppressed_by", None) is None

    def test_dissimilar_commands_not_suppressed(self):
        a = self._make_pattern("pat_a", "bash", "git commit -m update", conf=0.9)
        b = self._make_pattern("pat_b", "bash", "docker ps --all containers", conf=0.6)
        result = suppress_near_duplicates([a, b])
        assert getattr(result[1], "suppressed_by", None) is None

    def test_returns_same_list(self):
        patterns = [self._make_pattern("p1", "bash", "echo hello world", conf=0.8)]
        result = suppress_near_duplicates(patterns)
        assert result is patterns


class TestScanConfig:
    """Unit tests for ScanConfig + detect_patterns() threshold integration."""

    def test_min_confidence_filters_low_confidence(self):
        # 3 chains → frequency passes but confidence will be modest
        chains = _repeat(3, tool_name="file_tool", command="read foo.txt")
        # Force very high min_confidence — should filter everything
        result = detect_patterns(chains=chains, min_frequency=3, min_confidence=0.99)
        assert result == []

    def test_min_confidence_zero_keeps_patterns(self):
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        result = detect_patterns(chains=chains, min_frequency=3, min_confidence=0.0)
        assert len(result) >= 1

    def test_scan_config_overrides_kwargs(self):
        chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
        cfg = ScanConfig(min_frequency=10, min_confidence=0.0)
        result = detect_patterns(chains=chains, config=cfg)
        assert result == []

    def test_per_tool_min_frequency_override(self):
        chains = _repeat(4, tool_name="special_tool", command="run special task now")
        # Default min_frequency=3 would match, but per-tool override requires 6
        cfg = ScanConfig(min_frequency=3, per_tool_min_frequency={"special_tool": 6})
        result = detect_patterns(chains=chains, config=cfg)
        assert result == []

    def test_per_tool_override_allows_lower_threshold(self):
        chains = _repeat(2, tool_name="rare_tool", command="do rare thing once more")
        cfg = ScanConfig(min_frequency=3, per_tool_min_frequency={"rare_tool": 2})
        result = detect_patterns(chains=chains, config=cfg)
        assert len(result) == 1


class TestComputeRelevanceScore:
    """Unit tests for the relevance scoring formula."""

    def _make_proposal(self, **kwargs) -> SkillProposal:
        defaults = dict(
            pattern_id="pat_test",
            title="Test",
            description="Test",
            steps=[],
            estimated_time_saved="~6 min",
            risk_level="low",
            status="proposed",
            chain_ids=[],
            frequency=5,
            confidence=0.7,
            why_suggested=None,
            dismissed=False,
            feedback_score=0.0,
            feedback_count=0,
            last_feedback_at=None,
            relevance_score=0.0,
            suppressed_by=None,
        )
        defaults.update(kwargs)
        p = SkillProposal(**defaults)
        return p

    def test_dismissed_proposal_scores_zero(self):
        p = self._make_proposal(dismissed=True)
        assert compute_relevance_score(p) == 0.0

    def test_rejected_proposal_scores_zero(self):
        p = self._make_proposal(status="rejected")
        assert compute_relevance_score(p) == 0.0

    def test_higher_frequency_scores_higher(self):
        low = self._make_proposal(frequency=3, confidence=0.6)
        high = self._make_proposal(frequency=10, confidence=0.6)
        assert compute_relevance_score(high) > compute_relevance_score(low)

    def test_positive_feedback_boosts_score(self):
        neutral = self._make_proposal(feedback_score=0.0)
        positive = self._make_proposal(feedback_score=1.0)
        assert compute_relevance_score(positive) > compute_relevance_score(neutral)

    def test_negative_feedback_lowers_score(self):
        neutral = self._make_proposal(feedback_score=0.0)
        negative = self._make_proposal(feedback_score=-1.0)
        assert compute_relevance_score(negative) < compute_relevance_score(neutral)

    def test_score_clamped_to_zero_one(self):
        p = self._make_proposal(confidence=1.0, frequency=100, feedback_score=1.0)
        score = compute_relevance_score(p)
        assert 0.0 <= score <= 1.0

    def test_rank_proposals_sorted_desc(self):
        low = self._make_proposal(frequency=3, confidence=0.4)
        high = self._make_proposal(frequency=10, confidence=0.9)
        ranked = rank_proposals([low, high])
        assert ranked[0].relevance_score >= ranked[1].relevance_score


@pytest.mark.asyncio
async def test_record_feedback_useful_increases_score(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await record_feedback(session, pid, "useful")
        await session.commit()

    assert updated is not None
    assert updated.feedback_score > 0.0
    assert updated.feedback_count == 1


@pytest.mark.asyncio
async def test_record_feedback_not_useful_decreases_score(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/invoice.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await record_feedback(session, pid, "not_useful")
        await session.commit()

    assert updated is not None
    assert updated.feedback_score < 0.0
    assert updated.feedback_count == 1


@pytest.mark.asyncio
async def test_record_feedback_ignored_increments_count_only(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/notes.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await record_feedback(session, pid, "ignored")
        await session.commit()

    assert updated is not None
    assert updated.feedback_score == 0.0
    assert updated.feedback_count == 1


@pytest.mark.asyncio
async def test_record_feedback_nonexistent_returns_none(clean_db):
    async with AsyncSessionLocal() as session:
        result = await record_feedback(session, 99999, "useful")
    assert result is None


@pytest.mark.asyncio
async def test_dismiss_proposal(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    async with AsyncSessionLocal() as session:
        updated = await dismiss_proposal(session, pid)
        await session.commit()

    assert updated is not None
    assert updated.dismissed is True
    assert updated.relevance_score == 0.0


@pytest.mark.asyncio
async def test_dismissed_excluded_from_default_list(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id
        await dismiss_proposal(session, pid)
        await session.commit()

    async with AsyncSessionLocal() as session:
        proposals = await list_proposals(session, include_dismissed=False)

    assert len(proposals) == 0


@pytest.mark.asyncio
async def test_dismissed_included_when_requested(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id
        await dismiss_proposal(session, pid)
        await session.commit()

    async with AsyncSessionLocal() as session:
        proposals = await list_proposals(session, include_dismissed=True)

    assert len(proposals) == 1
    assert proposals[0].dismissed is True


@pytest.mark.asyncio
async def test_proposal_to_dict_includes_phase65_fields(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        d = proposal_to_dict(created[0])

    for field in (
        "why_suggested", "dismissed", "feedback_score",
        "feedback_count", "last_feedback_at", "relevance_score", "suppressed_by",
    ):
        assert field in d, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_why_suggested_populated(clean_db):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()

    assert created[0].why_suggested is not None
    assert len(created[0].why_suggested) > 10


# ─── Phase 6.5 API endpoint tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_api_endpoint_useful(api_client):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    resp = await api_client.post(
        f"/api/v1/skill-proposals/{pid}/feedback",
        json={"signal": "useful"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["proposal"]["feedback_count"] == 1
    assert data["proposal"]["feedback_score"] > 0.0


@pytest.mark.asyncio
async def test_feedback_api_invalid_signal(api_client):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    resp = await api_client.post(
        f"/api/v1/skill-proposals/{pid}/feedback",
        json={"signal": "INVALID"},
    )
    assert resp.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_dismiss_api_endpoint(api_client):
    chains = _repeat(5, tool_name="file_tool", command="read ~/Desktop/report.pdf")
    async with AsyncSessionLocal() as session:
        created = await run_detection_and_propose(session, chains=chains, min_frequency=3)
        await session.commit()
        pid = created[0].id

    resp = await api_client.post(f"/api/v1/skill-proposals/{pid}/dismiss")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["proposal"]["dismissed"] is True

    # Should not appear in default list
    list_resp = await api_client.get("/api/v1/skill-proposals")
    assert list_resp.json()["total"] == 0

    # Should appear with include_dismissed=true
    list_resp2 = await api_client.get("/api/v1/skill-proposals?include_dismissed=true")
    assert list_resp2.json()["total"] == 1


@pytest.mark.asyncio
async def test_scan_with_min_confidence_param(api_client):
    """Scan endpoint accepts min_confidence query param without error."""
    resp = await api_client.post("/api/v1/skill-proposals/scan?min_confidence=0.5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_feedback_nonexistent_proposal(api_client):
    resp = await api_client.post(
        "/api/v1/skill-proposals/99999/feedback",
        json={"signal": "useful"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dismiss_nonexistent_proposal(api_client):
    resp = await api_client.post("/api/v1/skill-proposals/99999/dismiss")
    assert resp.status_code == 404
