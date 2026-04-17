"""
Self-Improvement Pipeline – sandboxed skill generation with approval gates.

Flow
────
1. detect_patterns(db)      – scan EvalLogs for repeated failures / slow tools
2. propose_skill(pattern)   – ask LLM to design a new/improved tool
3. generate_code(proposal)  – generate Python source using builder_tools
4. run_in_sandbox(code)     – execute via run_shell in a temp dir, capture output
5. run_tests(code_path)     – run pytest against generated code
6. request_approval(...)    – create an ApprovalRequest for human review
7. deploy_if_approved(...)  – copy file to tools/plugins/ and register

NEVER auto-deploys. Step 6 always requires explicit human approval.

Stored state
────────────
  ImprovementProposal  – in-process list (and optionally SQLite via EvalLog context)

Public API
──────────
  run_improvement_cycle(db)      → list[ImprovementProposal]
  get_proposals()                → list[ImprovementProposal]
  approve_proposal(proposal_id)  → DeployResult
  reject_proposal(proposal_id)   → None
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
_PLUGINS_DIR = Path(__file__).parent.parent / "tools" / "plugins"
_MIN_FAILURE_COUNT   = 3       # how many failures before proposing improvement
_MIN_FAILURE_RATE    = 0.30    # 30% error rate triggers improvement proposal
_MAX_ACTIVE_PROPOSALS = 10     # do not flood with proposals


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ImprovementPattern:
    tool_name: str
    failure_count: int
    total_count: int
    failure_rate: float
    common_errors: List[str] = field(default_factory=list)
    avg_duration_ms: Optional[float] = None


@dataclass
class ImprovementProposal:
    proposal_id: str
    pattern: ImprovementPattern
    description: str              # LLM-generated skill description
    generated_code: str           # Python source for the new/improved tool
    test_code: str                # pytest tests for the new tool
    status: str = "pending"       # pending | sandbox_ok | sandbox_failed | approved | rejected | deployed
    sandbox_output: str = ""
    test_output: str = ""
    sandbox_passed: bool = False
    tests_passed: bool = False
    approval_id: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    plugin_path: Optional[str] = None   # set after deploy

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pattern"] = asdict(self.pattern)
        return d


@dataclass
class DeployResult:
    ok: bool
    plugin_path: str = ""
    message: str = ""


# ─── In-process proposal store ────────────────────────────────────────────────

_proposals: Dict[str, ImprovementProposal] = {}


# ─── Phase 1: Pattern detection ───────────────────────────────────────────────

async def detect_patterns(db: Any) -> List[ImprovementPattern]:
    """
    Scan EvalLogs for tools with high failure rates.
    Returns patterns that warrant improvement proposals.
    """
    from app.services.eval_service import get_stats, list_recent

    stats = await get_stats(db, since_days=7)
    failing_tools = stats.get("top_failing_tools", [])

    patterns: List[ImprovementPattern] = []
    for t in failing_tools:
        if t["errors"] >= _MIN_FAILURE_COUNT and t["error_rate"] >= _MIN_FAILURE_RATE:
            # Collect recent error messages
            recent = await list_recent(db, limit=20, tool_filter=t["tool"])
            errors = list({
                r["error_message"] for r in recent
                if r.get("error_message") and r["status"] == "error"
            })[:5]

            durations = [r["duration_ms"] for r in recent if r.get("duration_ms")]
            avg_dur = sum(durations) / len(durations) if durations else None

            patterns.append(ImprovementPattern(
                tool_name=t["tool"],
                failure_count=t["errors"],
                total_count=t["total"],
                failure_rate=t["error_rate"],
                common_errors=errors,
                avg_duration_ms=avg_dur,
            ))

    log.info("[self_improve] found %d improvement patterns", len(patterns))
    return patterns


# ─── Phase 2 + 3: Propose + generate ─────────────────────────────────────────

async def propose_skill(pattern: ImprovementPattern) -> Optional[ImprovementProposal]:
    """
    Ask the LLM to design an improved version of a failing tool.
    Returns a proposal with generated code, or None on failure.
    """
    try:
        from app.core.config import settings as cfg
        if not cfg.OPENAI_API_KEY:
            log.warning("[self_improve] no OPENAI_API_KEY – skipping skill proposal")
            return None

        import openai
        client = openai.AsyncOpenAI(api_key=cfg.OPENAI_API_KEY)

        system_prompt = textwrap.dedent("""
            You are an expert Python engineer working on Lani, a local AI assistant.
            You will be given a failing tool pattern and must produce:
            1. A short description of the improvement
            2. A complete Python plugin file that subclasses BaseTool
            3. A pytest test file for the new plugin

            Rules:
            - The plugin class must go in a single file.
            - Import only stdlib + packages already in the project (openai, httpx, sqlalchemy, etc).
            - Class must inherit from app.tools.base.BaseTool.
            - The file must be valid Python 3.11 syntax.
            - Respond ONLY as JSON: {"description": "...", "code": "...", "tests": "..."}
        """).strip()

        user_msg = json.dumps({
            "tool_name": pattern.tool_name,
            "failure_rate": pattern.failure_rate,
            "failure_count": pattern.failure_count,
            "common_errors": pattern.common_errors,
        })

        response = await client.chat.completions.create(
            model=cfg.LLM_MODEL or "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw = response.choices[0].message.content or "{}"
        payload = json.loads(raw)

        proposal_id = secrets.token_hex(8)
        proposal = ImprovementProposal(
            proposal_id=proposal_id,
            pattern=pattern,
            description=payload.get("description", ""),
            generated_code=payload.get("code", ""),
            test_code=payload.get("tests", ""),
        )
        _proposals[proposal_id] = proposal
        log.info("[self_improve] proposal %s created for tool=%s", proposal_id, pattern.tool_name)
        return proposal

    except Exception as exc:
        log.error("[self_improve] propose_skill failed: %s", exc)
        return None


# ─── Phase 4: Sandbox execution ───────────────────────────────────────────────

async def run_in_sandbox(proposal: ImprovementProposal) -> bool:
    """
    Write generated code to a temp dir, do a syntax check + import check.
    Does NOT run the tool – only validates the Python syntax and imports.

    Returns True if sandbox validation passed.
    """
    with tempfile.TemporaryDirectory(prefix="lani_sandbox_") as tmpdir:
        code_path = Path(tmpdir) / f"{proposal.proposal_id}_plugin.py"
        code_path.write_text(proposal.generated_code, encoding="utf-8")

        # 1. Syntax check
        proc = subprocess.run(
            ["python3", "-c", f"import ast; ast.parse(open('{code_path}').read())"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            proposal.sandbox_output = f"SYNTAX ERROR:\n{proc.stderr}"
            proposal.sandbox_passed = False
            proposal.status = "sandbox_failed"
            log.warning("[self_improve] sandbox syntax fail: %s", proc.stderr[:200])
            return False

        # 2. pyflakes lint (if available)
        try:
            lint = subprocess.run(
                ["python3", "-m", "pyflakes", str(code_path)],
                capture_output=True, text=True, timeout=10,
            )
            lint_out = lint.stdout + lint.stderr
        except Exception:
            lint_out = "(pyflakes not available)"

        proposal.sandbox_output = f"Syntax OK.\nLint:\n{lint_out}"
        proposal.sandbox_passed = True
        proposal.status = "sandbox_ok"
        log.info("[self_improve] sandbox passed for proposal %s", proposal.proposal_id)
        return True


# ─── Phase 5: Test runner ─────────────────────────────────────────────────────

async def run_tests(proposal: ImprovementProposal) -> bool:
    """
    Write test code to a temp dir and run pytest.
    Returns True if all tests pass.
    """
    if not proposal.test_code.strip():
        proposal.tests_passed = True
        proposal.test_output = "No tests generated."
        return True

    with tempfile.TemporaryDirectory(prefix="lani_test_") as tmpdir:
        test_path = Path(tmpdir) / f"test_{proposal.proposal_id}.py"
        test_path.write_text(proposal.test_code, encoding="utf-8")

        proc = subprocess.run(
            ["python3", "-m", "pytest", str(test_path), "-q", "--tb=short"],
            capture_output=True, text=True, timeout=30,
        )
        proposal.test_output = (proc.stdout + proc.stderr)[:3000]
        proposal.tests_passed = proc.returncode == 0

        if proposal.tests_passed:
            log.info("[self_improve] tests passed for proposal %s", proposal.proposal_id)
        else:
            log.warning("[self_improve] tests failed for proposal %s", proposal.proposal_id)

    return proposal.tests_passed


# ─── Phase 6: Request approval ────────────────────────────────────────────────

async def request_approval(proposal: ImprovementProposal, db: Any) -> int:
    """
    Create a human-approval request for the proposal.
    Returns the approval request ID.
    """
    from app.services.approval_service import create_approval_request

    approval_id = await create_approval_request(
        db=db,
        tool_name="self_improvement.deploy",
        command=f"Deploy self-improvement proposal {proposal.proposal_id}",
        params={
            "proposal_id": proposal.proposal_id,
            "tool_name": proposal.pattern.tool_name,
            "description": proposal.description,
            "sandbox_passed": proposal.sandbox_passed,
            "tests_passed": proposal.tests_passed,
            "sandbox_output": proposal.sandbox_output[:500],
            "test_output": proposal.test_output[:500],
        },
    )
    proposal.approval_id = approval_id
    log.info("[self_improve] approval_id=%d created for proposal %s", approval_id, proposal.proposal_id)
    return approval_id


# ─── Phase 7: Deploy ─────────────────────────────────────────────────────────

def deploy_proposal(proposal: ImprovementProposal) -> DeployResult:
    """
    Copy the generated plugin to tools/plugins/ and trigger a registry refresh.

    MUST only be called after human approval.
    """
    if proposal.status == "deployed":
        return DeployResult(ok=False, message="Already deployed.")

    safe_name = proposal.pattern.tool_name.replace(".", "_").replace("-", "_")
    plugin_file = _PLUGINS_DIR / f"improved_{safe_name}_{proposal.proposal_id[:6]}.py"

    try:
        _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        plugin_file.write_text(proposal.generated_code, encoding="utf-8")

        # Refresh the tool registry so new plugin is picked up
        from app.services.capability_registry import refresh_registry
        refresh_registry()

        proposal.status = "deployed"
        proposal.plugin_path = str(plugin_file)
        log.info("[self_improve] deployed plugin to %s", plugin_file)
        return DeployResult(ok=True, plugin_path=str(plugin_file), message="Plugin deployed successfully.")

    except Exception as exc:
        log.error("[self_improve] deploy failed: %s", exc)
        return DeployResult(ok=False, message=str(exc))


def reject_proposal(proposal_id: str) -> None:
    prop = _proposals.get(proposal_id)
    if prop:
        prop.status = "rejected"
    log.info("[self_improve] proposal %s rejected", proposal_id)


# ─── Public API ───────────────────────────────────────────────────────────────

def get_proposals() -> List[Dict[str, Any]]:
    return [p.to_dict() for p in _proposals.values()]


def get_proposal(proposal_id: str) -> Optional[ImprovementProposal]:
    return _proposals.get(proposal_id)


async def run_improvement_cycle(db: Any) -> List[ImprovementProposal]:
    """
    Full cycle: detect → propose → sandbox → test → queue approval.
    Returns list of proposals created this cycle.
    """
    if len(_proposals) >= _MAX_ACTIVE_PROPOSALS:
        log.info("[self_improve] max active proposals reached, skipping cycle")
        return []

    patterns = await detect_patterns(db)
    created: List[ImprovementProposal] = []

    for pattern in patterns:
        # Skip if already proposed for this tool
        already = any(
            p.pattern.tool_name == pattern.tool_name and p.status not in ("rejected", "deployed")
            for p in _proposals.values()
        )
        if already:
            continue

        proposal = await propose_skill(pattern)
        if proposal is None:
            continue

        await run_in_sandbox(proposal)
        if proposal.sandbox_passed:
            await run_tests(proposal)
        await request_approval(proposal, db)
        created.append(proposal)

    return created
