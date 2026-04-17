"""
Skill Spec Generator – Phase 7: Proposal → Skill Scaffold Generator.

Converts an approved ``SkillProposal`` into a structured ``SkillSpec``
dataclass that describes *what* the skill should do without specifying
*how* it is executed.

The SkillSpec is the intermediate representation between a fuzzy proposal
and the concrete scaffold JSON / Python stub produced by scaffold_generator.

Design constraints
──────────────────
• Pure function – no DB I/O, no network, no execution.
• Deterministic – same proposal always produces equivalent spec.
• Observable – all fields are plain Python primitives (JSON-serialisable).
• Safe – generates descriptions and metadata only; no code runs.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.models.skill_proposal import SkillProposal


# ─── SkillSpec data model ─────────────────────────────────────────────────────

@dataclass
class SkillSpecStep:
    """A single normalised step in the skill workflow."""
    step_index: int
    tool_name: str
    command_template: str
    description: str
    is_required: bool = True


@dataclass
class SkillSpec:
    """
    Structured specification for a skill derived from a SkillProposal.

    All fields are plain primitives so the spec is trivially JSON-serialisable
    via ``asdict(spec)``.

    Fields
    ------
    skill_id:
        Stable identifier derived from the proposal's pattern_id.
    name:
        Short human-readable name (≤ 60 chars).
    description:
        Longer explanation of what the skill does.
    steps:
        Ordered list of SkillSpecStep objects.
    required_tools:
        Deduplicated list of tool_name values that the skill depends on.
    risk_level:
        Inherited from the source proposal.
    expected_inputs:
        List of free-text strings describing what the skill needs to run
        (e.g. "file path", "search query").  Derived heuristically from
        the command template.
    expected_outputs:
        List of free-text strings describing what the skill produces.
    rationale:
        Short human-readable justification for why this skill was proposed
        (sourced from why_suggested or synthesised).
    source_proposal_id:
        FK back to the SkillProposal row.
    source_pattern_id:
        The pattern_id string from the detector.
    estimated_time_saved:
        Passed through from the proposal.
    """

    skill_id: str
    name: str
    description: str
    steps: List[SkillSpecStep]
    required_tools: List[str]
    risk_level: str
    expected_inputs: List[str]
    expected_outputs: List[str]
    rationale: str
    source_proposal_id: int
    source_pattern_id: str
    estimated_time_saved: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Internal helpers ─────────────────────────────────────────────────────────

# Common argument tokens that indicate an input parameter
_INPUT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(~|/)[^\s]+\.(pdf|txt|csv|json|py|sh|md|log|xml|yaml|toml)", re.I),
     "file path"),
    (re.compile(r"(https?://|www\.)\S+", re.I),
     "URL"),
    (re.compile(r"\b(search|query|find|look up|lookup)\b", re.I),
     "search query"),
    (re.compile(r"\b(user|username|name|email|id)\b", re.I),
     "user identifier"),
    (re.compile(r"\b(date|time|when|from|until|since)\b", re.I),
     "date/time parameter"),
    (re.compile(r"\b(directory|folder|path|dir)\b", re.I),
     "directory path"),
]


def _infer_expected_inputs(command_template: str) -> List[str]:
    """
    Heuristically extract likely inputs from a command template string.

    Returns deduplicated list of human-readable input descriptions.
    """
    found: list[str] = []
    for pattern, label in _INPUT_PATTERNS:
        if pattern.search(command_template) and label not in found:
            found.append(label)
    if not found:
        found.append("command arguments")
    return found


def _infer_expected_outputs(tool_name: str) -> List[str]:
    """
    Heuristically guess the kind of output this tool produces.
    """
    tool = tool_name.lower()
    if any(kw in tool for kw in ("file", "read", "write", "pdf", "doc")):
        return ["file content or transformed file"]
    if any(kw in tool for kw in ("web", "search", "browse", "http", "fetch")):
        return ["web content or search results"]
    if any(kw in tool for kw in ("shell", "bash", "cmd", "run", "exec", "python")):
        return ["stdout/stderr text", "exit code"]
    if any(kw in tool for kw in ("db", "sql", "query", "database")):
        return ["query result rows"]
    if any(kw in tool for kw in ("email", "mail", "calendar", "notify")):
        return ["confirmation or message id"]
    return ["tool output"]


def _make_skill_name(proposal: SkillProposal) -> str:
    """
    Derive a short ≤60-char skill name from the proposal title.
    Strip the "Automate: " prefix that _make_title() adds.
    """
    title = proposal.title or ""
    # Strip leading "Automate: " prefix if present
    title = re.sub(r"^Automate:\s*", "", title, flags=re.I)
    # Remove surrounding quotes from the command part
    title = title.strip().strip('"').strip()
    return title[:60]


def _make_step_description(tool_name: str, command_template: str) -> str:
    tool = tool_name.replace("_", " ").title()
    cmd_short = command_template[:60] + ("…" if len(command_template) > 60 else "")
    return f"Run {tool}: {cmd_short}"


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_spec(proposal: SkillProposal) -> SkillSpec:
    """
    Convert an approved ``SkillProposal`` into a ``SkillSpec``.

    Parameters
    ----------
    proposal:
        A SkillProposal ORM instance.  The proposal does not need to have
        ``status == 'approved'`` — callers may generate specs for any status
        (the caller is responsible for enforcing business rules).

    Returns
    -------
    A fully-populated ``SkillSpec`` dataclass.
    """
    raw_steps: list[dict] = proposal.steps or []

    # Normalise steps from the stored JSON list of {tool_name, command_template}
    spec_steps: List[SkillSpecStep] = []
    for i, step in enumerate(raw_steps):
        tool = step.get("tool_name", proposal.title or "unknown_tool")
        cmd = step.get("command_template", "")
        spec_steps.append(
            SkillSpecStep(
                step_index=i,
                tool_name=tool,
                command_template=cmd,
                description=_make_step_description(tool, cmd),
                is_required=True,
            )
        )

    # If no steps in the proposal, synthesise one from the pattern metadata
    if not spec_steps:
        # Best-effort: derive from title / description
        inferred_tool = "unknown_tool"
        inferred_cmd = ""
        if proposal.title:
            # "Automate: File Tool — "some command"" → extract
            m = re.search(r"—\s*\"?(.+?)\"?\s*$", proposal.title)
            if m:
                inferred_cmd = m.group(1)
            tm = re.search(r"Automate:\s*(.+?)\s*—", proposal.title)
            if tm:
                inferred_tool = tm.group(1).lower().replace(" ", "_")
        spec_steps = [
            SkillSpecStep(
                step_index=0,
                tool_name=inferred_tool,
                command_template=inferred_cmd,
                description=_make_step_description(inferred_tool, inferred_cmd),
                is_required=True,
            )
        ]

    required_tools = list(dict.fromkeys(s.tool_name for s in spec_steps))

    # Aggregate inputs/outputs across all steps
    all_inputs: list[str] = []
    for step in spec_steps:
        for inp in _infer_expected_inputs(step.command_template):
            if inp not in all_inputs:
                all_inputs.append(inp)

    all_outputs: list[str] = []
    for tool in required_tools:
        for out in _infer_expected_outputs(tool):
            if out not in all_outputs:
                all_outputs.append(out)

    rationale = (
        proposal.why_suggested
        or f"Detected {proposal.frequency} repeated executions with "
           f"{round((proposal.confidence or 0) * 100)}% confidence."
    )

    skill_id = f"skill_{proposal.pattern_id}"

    return SkillSpec(
        skill_id=skill_id,
        name=_make_skill_name(proposal),
        description=proposal.description or "",
        steps=spec_steps,
        required_tools=required_tools,
        risk_level=proposal.risk_level or "low",
        expected_inputs=all_inputs,
        expected_outputs=all_outputs,
        rationale=rationale,
        source_proposal_id=proposal.id,
        source_pattern_id=proposal.pattern_id,
        estimated_time_saved=proposal.estimated_time_saved,
    )
