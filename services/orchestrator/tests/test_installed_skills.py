"""
Tests for Phase 9: Installed Skills Registry + Versioning.

Coverage
────────
• finalize_install: fresh install, upgrade path, precondition failures
• enable / disable lifecycle
• revoke (terminal, idempotent)
• rollback to previous version
• is_skill_executable gate
• API endpoints: list, get, enable, disable, rollback, revoke, versions
• GET /installed-skills/capabilities
• POST /skill-drafts/{id}/finalize
"""

import pytest

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.approval_request import ApprovalRequest
from app.models.installed_skill import (
    InstalledSkill,
    INSTALLED_STATUS_INSTALLED,
    INSTALLED_STATUS_DISABLED,
    INSTALLED_STATUS_REVOKED,
    INSTALLED_STATUS_SUPERSEDED,
)
from app.models.installed_skill_version import InstalledSkillVersion
from app.models.skill_draft import SkillDraft
from app.models.skill_proposal import SkillProposal
from app.services import installed_skill_service as iss


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _clean():
    """Truncate all Phase-9 rows for test isolation."""
    async with AsyncSessionLocal() as s:
        await s.execute(delete(InstalledSkillVersion))
        await s.execute(delete(InstalledSkill))
        await s.execute(delete(SkillDraft))
        await s.execute(delete(ApprovalRequest))
        await s.execute(delete(SkillProposal))
        await s.commit()


async def _setup_draft_with_approved_install(name: str) -> tuple[int, int]:
    """
    Create a SkillProposal → SkillDraft → ApprovalRequest (approved) chain.
    Returns (draft_id, skill_id_placeholder).
    The draft will have status='install_requested' and approval_request_id set.
    """
    async with AsyncSessionLocal() as s:
        proposal = SkillProposal(
            pattern_id=f"pat-{name}",
            title=name,
            description="Test proposal",
            steps=[],
            status="approved",
        )
        s.add(proposal)
        await s.flush()

        draft = SkillDraft(
            proposal_id=proposal.id,
            name=name,
            description=f"Test skill {name}",
            spec_json={"steps": [], "required_tools": [], "expected_inputs": [], "expected_outputs": []},
            scaffold_json={"metadata": {}, "steps": []},
            scaffold_type="workflow",
            risk_level="low",
            status="install_requested",
        )
        s.add(draft)
        await s.flush()

        approval = ApprovalRequest(
            tool_name="skill_installer",
            command="install_skill",
            params={"draft_id": draft.id},
            status="approved",
        )
        s.add(approval)
        await s.flush()

        draft.approval_request_id = approval.id
        await s.commit()

        return draft.id, proposal.id


async def _setup_draft_pending(name: str) -> int:
    """Like _setup_draft_with_approved_install but approval stays 'pending'."""
    async with AsyncSessionLocal() as s:
        proposal = SkillProposal(
            pattern_id=f"pat-pend-{name}",
            title=name,
            description="Pending proposal",
            steps=[],
            status="approved",
        )
        s.add(proposal)
        await s.flush()

        draft = SkillDraft(
            proposal_id=proposal.id,
            name=name,
            description="Pending skill",
            spec_json={},
            scaffold_json={},
            scaffold_type="workflow",
            risk_level="low",
            status="install_requested",
        )
        s.add(draft)
        await s.flush()

        approval = ApprovalRequest(
            tool_name="skill_installer",
            command="install_skill",
            params={},
            status="pending",
        )
        s.add(approval)
        await s.flush()

        draft.approval_request_id = approval.id
        await s.commit()

        return draft.id


async def _finalize(draft_id: int) -> InstalledSkill:
    """Run finalize_install in its own session and return the skill."""
    async with AsyncSessionLocal() as s:
        skill = await iss.finalize_install(s, draft_id)
        await s.commit()
        assert skill is not None, f"finalize_install returned None for draft {draft_id}"
        return skill


# ─── Unit: finalize_install ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_finalize_fresh_install(async_client):
    """finalize_install creates a new InstalledSkill v1.0.0."""
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("test_skill")
    skill = await _finalize(draft_id)

    assert skill.name == "test_skill"
    assert skill.current_version == "1.0.0"
    assert skill.status == INSTALLED_STATUS_INSTALLED
    assert skill.enabled is True


@pytest.mark.asyncio
async def test_finalize_creates_version_row(async_client):
    """finalize_install appends an InstalledSkillVersion row."""
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("versioned_skill")
    skill = await _finalize(draft_id)

    async with AsyncSessionLocal() as s:
        versions = await iss.get_version_history(s, skill.id)

    assert len(versions) == 1
    assert versions[0].version == "1.0.0"
    assert versions[0].action == "install"


@pytest.mark.asyncio
async def test_finalize_fails_when_not_install_requested(async_client):
    """finalize_install must reject drafts not in install_requested status."""
    await _clean()
    async with AsyncSessionLocal() as s:
        proposal = SkillProposal(
            pattern_id="pat-bad",
            title="bad_draft",
            description="",
            steps=[],
            status="approved",
        )
        s.add(proposal)
        await s.flush()

        draft = SkillDraft(
            proposal_id=proposal.id,
            name="bad_draft",
            description="",
            spec_json={},
            scaffold_json={},
            scaffold_type="workflow",
            risk_level="low",
            status="draft",  # wrong status
        )
        s.add(draft)
        await s.commit()
        draft_id = draft.id

    async with AsyncSessionLocal() as s:
        result = await iss.finalize_install(s, draft_id)
    assert result is None


@pytest.mark.asyncio
async def test_finalize_fails_when_approval_not_approved(async_client):
    """finalize_install must reject when the linked approval is still pending."""
    await _clean()
    draft_id = await _setup_draft_pending("pending_skill")

    async with AsyncSessionLocal() as s:
        result = await iss.finalize_install(s, draft_id)
    assert result is None


@pytest.mark.asyncio
async def test_finalize_upgrade_bumps_version(async_client):
    """Re-installing the same skill name bumps the minor version."""
    await _clean()
    draft1_id, _ = await _setup_draft_with_approved_install("upgradeable_skill")
    skill_v1 = await _finalize(draft1_id)
    assert skill_v1.current_version == "1.0.0"

    draft2_id, _ = await _setup_draft_with_approved_install("upgradeable_skill")
    skill_v2 = await _finalize(draft2_id)

    assert skill_v2.current_version == "1.1.0"
    assert skill_v2.rollback_version == "1.0.0"


# ─── Unit: enable / disable ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disable_and_enable(async_client):
    """disable → disabled, enable → installed."""
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("toggle_skill")
    skill = await _finalize(draft_id)

    async with AsyncSessionLocal() as s:
        disabled = await iss.disable_skill(s, skill.id)
        await s.commit()

    assert disabled is not None
    assert disabled.status == INSTALLED_STATUS_DISABLED
    assert disabled.enabled is False
    assert not iss.is_skill_executable(disabled)

    async with AsyncSessionLocal() as s:
        enabled = await iss.enable_skill(s, skill.id)
        await s.commit()

    assert enabled is not None
    assert enabled.status == INSTALLED_STATUS_INSTALLED
    assert enabled.enabled is True
    assert iss.is_skill_executable(enabled)


# ─── Unit: is_skill_executable gate ──────────────────────────────────────────

def test_is_skill_executable_only_installed_and_enabled():
    """Safety gate: disabled / revoked / superseded must not execute."""
    def _make(status, enabled):
        s = InstalledSkill()
        s.status = status
        s.enabled = enabled
        return s

    assert iss.is_skill_executable(_make(INSTALLED_STATUS_INSTALLED,  True))  is True
    assert iss.is_skill_executable(_make(INSTALLED_STATUS_INSTALLED,  False)) is False
    assert iss.is_skill_executable(_make(INSTALLED_STATUS_DISABLED,   True))  is False
    assert iss.is_skill_executable(_make(INSTALLED_STATUS_DISABLED,   False)) is False
    assert iss.is_skill_executable(_make(INSTALLED_STATUS_REVOKED,    False)) is False
    assert iss.is_skill_executable(_make(INSTALLED_STATUS_SUPERSEDED, False)) is False


# ─── Unit: revoke ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revoke_is_terminal(async_client):
    """Revoked skill cannot be re-enabled."""
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("revoke_skill")
    skill = await _finalize(draft_id)

    async with AsyncSessionLocal() as s:
        revoked = await iss.revoke_skill(s, skill.id, reason="security issue")
        await s.commit()

    assert revoked is not None
    assert revoked.status == INSTALLED_STATUS_REVOKED
    assert not iss.is_skill_executable(revoked)

    async with AsyncSessionLocal() as s:
        result = await iss.enable_skill(s, skill.id)
        await s.commit()
    assert result is None  # cannot re-enable revoked skill


# ─── Unit: rollback ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_restores_previous_version(async_client):
    """Rollback returns skill to rollback_version and records a rollback row."""
    await _clean()
    draft1_id, _ = await _setup_draft_with_approved_install("rollback_skill")
    await _finalize(draft1_id)

    draft2_id, _ = await _setup_draft_with_approved_install("rollback_skill")
    skill_v2 = await _finalize(draft2_id)

    assert skill_v2.current_version == "1.1.0"
    assert skill_v2.rollback_version == "1.0.0"

    async with AsyncSessionLocal() as s:
        rolled = await iss.rollback_skill(s, skill_v2.id)
        await s.commit()

    assert rolled is not None
    assert rolled.current_version == "1.0.0"

    async with AsyncSessionLocal() as s:
        versions = await iss.get_version_history(s, rolled.id)
    assert any(v.action == "rollback" for v in versions)


# ─── API: list installed skills ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_installed_skills_empty(async_client):
    await _clean()
    r = await async_client.get("/api/v1/installed-skills")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["skills"] == []


@pytest.mark.asyncio
async def test_api_list_installed_skills_after_install(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("api_skill")
    await _finalize(draft_id)

    r = await async_client.get("/api/v1/installed-skills")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    names = [s["name"] for s in data["skills"]]
    assert "api_skill" in names


# ─── API: enable / disable ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_disable_and_enable(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("api_toggle")
    skill = await _finalize(draft_id)

    r = await async_client.post(f"/api/v1/installed-skills/{skill.id}/disable")
    assert r.status_code == 200
    assert r.json()["skill"]["status"] == "disabled"

    r = await async_client.post(f"/api/v1/installed-skills/{skill.id}/enable")
    assert r.status_code == 200
    assert r.json()["skill"]["status"] == "installed"


# ─── API: revoke ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_revoke(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("api_revoke")
    skill = await _finalize(draft_id)

    r = await async_client.post(
        f"/api/v1/installed-skills/{skill.id}/revoke",
        json={"reason": "test revoke"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["skill"]["status"] == "revoked"
    assert body["skill"]["revoke_reason"] == "test revoke"


# ─── API: version history ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_version_history(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("versioned_api_skill")
    skill = await _finalize(draft_id)

    r = await async_client.get(f"/api/v1/installed-skills/{skill.id}/versions")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert len(data["versions"]) >= 1
    assert data["versions"][0]["action"] == "install"


# ─── API: capabilities endpoint ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_installed_capabilities(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("cap_skill")
    await _finalize(draft_id)

    r = await async_client.get("/api/v1/installed-skills/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    names = [c["name"] for c in data["capabilities"]]
    assert "cap_skill" in names
    assert all(c["source"] == "installed" for c in data["capabilities"])


# ─── API: finalize via /skill-drafts/{id}/finalize ───────────────────────────

@pytest.mark.asyncio
async def test_api_finalize_endpoint(async_client):
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("endpoint_finalize_skill")

    r = await async_client.post(f"/api/v1/skill-drafts/{draft_id}/finalize")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["draft"]["status"] == "installed"
    assert data["skill"]["name"] == "endpoint_finalize_skill"
    assert data["skill"]["current_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_api_finalize_fails_without_approval(async_client):
    await _clean()
    draft_id = await _setup_draft_pending("no_approval_skill")

    r = await async_client.post(f"/api/v1/skill-drafts/{draft_id}/finalize")
    assert r.status_code == 422


# ─── API: rollback ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_rollback(async_client):
    await _clean()
    draft1_id, _ = await _setup_draft_with_approved_install("api_rollback_skill")
    await _finalize(draft1_id)

    draft2_id, _ = await _setup_draft_with_approved_install("api_rollback_skill")
    skill_v2 = await _finalize(draft2_id)

    r = await async_client.post(f"/api/v1/installed-skills/{skill_v2.id}/rollback")
    assert r.status_code == 200
    data = r.json()
    assert data["skill"]["current_version"] == "1.0.0"


# ─── Disabled skill cannot execute gate ──────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_skill_not_executable(async_client):
    """is_skill_executable returns False for a disabled skill."""
    await _clean()
    draft_id, _ = await _setup_draft_with_approved_install("gate_skill")
    skill = await _finalize(draft_id)
    assert iss.is_skill_executable(skill) is True

    async with AsyncSessionLocal() as s:
        disabled = await iss.disable_skill(s, skill.id)
        await s.commit()

    assert disabled is not None
    assert iss.is_skill_executable(disabled) is False



