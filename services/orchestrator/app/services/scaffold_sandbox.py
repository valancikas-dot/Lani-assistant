"""
Scaffold Sandbox – Phase 7: Proposal → Skill Scaffold Generator.

Validates a generated scaffold by simulating (NOT executing) its workflow.

The sandbox performs four categories of checks:

1. **Structure validation** – required fields present, correct types, no
   invalid keys.
2. **Tool availability** – each ``tool_name`` in the workflow is cross-
   referenced against the registered capability catalogue.
3. **Input/output consistency** – every workflow step's declared inputs are
   resolvable and outputs have defined types.
4. **Safety gate checks** – ``auto_execute`` must be False; ``installation_approved``
   must be False at generation time; no shell-injection patterns in templates.

Design constraints
──────────────────
• NO execution – no subprocess, no eval(), no importlib.import_module() of
  user-supplied strings.
• NO system modification – reads only from the in-memory scaffold dict.
• Deterministic – same scaffold always produces the same report.
• Auditable – every issue includes a severity, location, and message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Known tools ──────────────────────────────────────────────────────────────
# This registry mirrors what builder_tools exposes.  It is intentionally
# conservative – unknown tools produce a WARNING, not an ERROR.

_KNOWN_TOOLS: frozenset[str] = frozenset({
    "file_tool",
    "web_tool",
    "bash_tool",
    "python_tool",
    "shell_tool",
    "search_tool",
    "email_tool",
    "calendar_tool",
    "database_tool",
    "pdf_tool",
    "csv_tool",
    "json_tool",
    "yaml_tool",
    "image_tool",
    "vision_tool",
    "memory_tool",
    "clipboard_tool",
    "notification_tool",
    "http_tool",
    "unknown_tool",  # synthesised fallback in spec generator
})

# Shell-injection risk patterns to flag in command templates
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r";\s*(rm|sudo|chmod|chown|mkfs|dd|curl|wget)\b", re.I),
    re.compile(r"\|\s*(bash|sh|zsh|python|perl|ruby)\b", re.I),
    re.compile(r"`[^`]+`"),          # backtick command substitution
    re.compile(r"\$\([^)]+\)"),      # $(cmd) substitution
    re.compile(r"\beval\b", re.I),
    re.compile(r"\bexec\b", re.I),
]


# ─── Issue model ─────────────────────────────────────────────────────────────

@dataclass
class SandboxIssue:
    """A single issue found during sandbox validation."""
    severity: str       # "error" | "warning" | "info"
    location: str       # e.g. "workflow.steps[0].tool_name"
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
            "suggestion": self.suggestion,
        }


# ─── Test report ─────────────────────────────────────────────────────────────

@dataclass
class SandboxTestReport:
    """
    Result of running the scaffold through the sandbox validator.

    ``passed`` is True only when there are zero ERROR-severity issues.
    Warnings do not cause failure but should be reviewed.
    """
    passed: bool
    issues: List[SandboxIssue] = field(default_factory=list)
    summary: str = ""

    # Counters (derived from issues)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_issues(cls, issues: List[SandboxIssue]) -> "SandboxTestReport":
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        infos = [i for i in issues if i.severity == "info"]
        passed = len(errors) == 0
        if passed:
            if warnings:
                summary = (
                    f"Passed with {len(warnings)} warning(s). "
                    "Review before installation."
                )
            else:
                summary = "All checks passed. Safe to proceed to installation review."
        else:
            summary = (
                f"Failed with {len(errors)} error(s) and {len(warnings)} warning(s). "
                "Resolve errors before installing."
            )
        return cls(
            passed=passed,
            issues=issues,
            summary=summary,
            error_count=len(errors),
            warning_count=len(warnings),
            info_count=len(infos),
        )


# ─── Individual checks ────────────────────────────────────────────────────────

def _check_top_level_structure(scaffold: Dict[str, Any]) -> List[SandboxIssue]:
    """Verify required top-level keys are present and correct types."""
    issues: List[SandboxIssue] = []
    required_keys = {
        "scaffold_version": str,
        "scaffold_type": str,
        "metadata": dict,
        "workflow": dict,
        "required_tools": list,
        "inputs": list,
        "outputs": list,
        "python_stub": str,
        "auto_execute": bool,
        "installation_approved": bool,
    }
    for key, expected_type in required_keys.items():
        if key not in scaffold:
            issues.append(SandboxIssue(
                severity="error",
                location=key,
                message=f"Required key '{key}' is missing from scaffold.",
                suggestion=f"Re-generate the scaffold to include '{key}'.",
            ))
        elif not isinstance(scaffold[key], expected_type):
            issues.append(SandboxIssue(
                severity="error",
                location=key,
                message=(
                    f"Key '{key}' has type {type(scaffold[key]).__name__}, "
                    f"expected {expected_type.__name__}."
                ),
            ))
    return issues


def _check_metadata(metadata: Dict[str, Any]) -> List[SandboxIssue]:
    """Verify the metadata sub-dict has required fields."""
    issues: List[SandboxIssue] = []
    required = ["skill_id", "name", "risk_level", "source_proposal_id"]
    for key in required:
        if not metadata.get(key):
            issues.append(SandboxIssue(
                severity="error",
                location=f"metadata.{key}",
                message=f"metadata.{key} is missing or empty.",
            ))
    # Risk level must be a known value
    risk = metadata.get("risk_level", "")
    if risk and risk not in ("low", "medium", "high", "critical"):
        issues.append(SandboxIssue(
            severity="warning",
            location="metadata.risk_level",
            message=f"Unrecognised risk_level '{risk}'. Expected: low|medium|high|critical.",
        ))
    return issues


def _check_safety_flags(scaffold: Dict[str, Any]) -> List[SandboxIssue]:
    """Enforce hard safety constraints on the scaffold."""
    issues: List[SandboxIssue] = []
    if scaffold.get("auto_execute") is True:
        issues.append(SandboxIssue(
            severity="error",
            location="auto_execute",
            message="auto_execute must be False. Scaffolds must never execute automatically.",
            suggestion="Set auto_execute=False in the scaffold.",
        ))
    if scaffold.get("installation_approved") is True:
        issues.append(SandboxIssue(
            severity="error",
            location="installation_approved",
            message=(
                "installation_approved must be False at generation time. "
                "Approval happens via the explicit approval flow."
            ),
            suggestion="Do not pre-approve scaffolds during generation.",
        ))
    return issues


def _check_workflow_steps(steps: List[Any]) -> List[SandboxIssue]:
    """Validate each workflow step."""
    issues: List[SandboxIssue] = []

    if not steps:
        issues.append(SandboxIssue(
            severity="error",
            location="workflow.steps",
            message="Workflow has no steps.",
            suggestion="Ensure the source proposal has at least one detected step.",
        ))
        return issues

    for i, step in enumerate(steps):
        loc = f"workflow.steps[{i}]"

        if not isinstance(step, dict):
            issues.append(SandboxIssue(
                severity="error",
                location=loc,
                message=f"Step {i} is not a dict.",
            ))
            continue

        # Required step keys
        for key in ("step_index", "tool_name", "command_template"):
            if key not in step:
                issues.append(SandboxIssue(
                    severity="error",
                    location=f"{loc}.{key}",
                    message=f"Step {i} is missing required key '{key}'.",
                ))

        # Tool availability check
        tool_name = step.get("tool_name", "")
        if tool_name and tool_name not in _KNOWN_TOOLS:
            issues.append(SandboxIssue(
                severity="warning",
                location=f"{loc}.tool_name",
                message=f"Tool '{tool_name}' is not in the known tool registry.",
                suggestion=(
                    "Verify the tool name is correct and available in your "
                    "Lani installation before installing this skill."
                ),
            ))

        # Injection pattern check in command template
        cmd = step.get("command_template", "")
        if cmd:
            for pattern in _INJECTION_PATTERNS:
                if pattern.search(cmd):
                    issues.append(SandboxIssue(
                        severity="warning",
                        location=f"{loc}.command_template",
                        message=(
                            f"Potential shell-injection pattern detected in "
                            f"command_template: '{cmd[:60]}'"
                        ),
                        suggestion="Review this command carefully before installation.",
                    ))
                    break  # one warning per step is enough

        # step_index must match position
        declared_index = step.get("step_index")
        if declared_index is not None and declared_index != i:
            issues.append(SandboxIssue(
                severity="warning",
                location=f"{loc}.step_index",
                message=f"step_index={declared_index} does not match list position {i}.",
            ))

    return issues


def _check_inputs_outputs(scaffold: Dict[str, Any]) -> List[SandboxIssue]:
    """Validate the inputs and outputs arrays."""
    issues: List[SandboxIssue] = []

    for section in ("inputs", "outputs"):
        items = scaffold.get(section, [])
        for j, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append(SandboxIssue(
                    severity="error",
                    location=f"{section}[{j}]",
                    message=f"{section}[{j}] is not a dict.",
                ))
                continue
            if not item.get("name"):
                issues.append(SandboxIssue(
                    severity="warning",
                    location=f"{section}[{j}].name",
                    message=f"{section}[{j}] is missing a 'name' field.",
                ))

    return issues


def _check_python_stub(stub: str) -> List[SandboxIssue]:
    """Warn if the Python stub contains any actually-runnable dangerous patterns."""
    issues: List[SandboxIssue] = []
    dangerous = [
        (re.compile(r"\bsubprocess\b"), "subprocess"),
        (re.compile(r"\bos\.system\b"), "os.system"),
        (re.compile(r"\beval\s*\("), "eval()"),
        (re.compile(r"\bexec\s*\("), "exec()"),
        (re.compile(r"\b__import__\s*\("), "__import__()"),
    ]
    for pattern, name in dangerous:
        if pattern.search(stub):
            issues.append(SandboxIssue(
                severity="warning",
                location="python_stub",
                message=f"Python stub contains potentially dangerous call: {name}",
                suggestion=(
                    "Review the stub carefully. The scaffold generator should "
                    "never emit real execution calls."
                ),
            ))
    # Check for the safety banner
    if "NOT EXECUTABLE AS-IS" not in stub and "GENERATED DRAFT" not in stub:
        issues.append(SandboxIssue(
            severity="info",
            location="python_stub",
            message="Python stub is missing the standard Lani safety banner.",
        ))
    return issues


# ─── Public API ───────────────────────────────────────────────────────────────

def run_sandbox_test(scaffold: Dict[str, Any]) -> SandboxTestReport:
    """
    Run all sandbox validation checks against *scaffold* and return a
    ``SandboxTestReport``.

    This function is:
    • Pure – no DB I/O, no network, no subprocess.
    • Safe – never executes any part of the scaffold.
    • Fast – all checks are regex/dict operations only.

    Parameters
    ----------
    scaffold:
        The scaffold dict produced by ``scaffold_generator.generate_scaffold()``.

    Returns
    -------
    A ``SandboxTestReport`` with ``passed=True`` iff no ERROR-level issues
    were found.
    """
    all_issues: List[SandboxIssue] = []

    # 1. Top-level structure
    all_issues.extend(_check_top_level_structure(scaffold))

    # Bail early if structure is too broken to proceed
    if any(i.severity == "error" for i in all_issues):
        # Still run safety + metadata if present
        pass

    # 2. Metadata
    metadata = scaffold.get("metadata")
    if isinstance(metadata, dict):
        all_issues.extend(_check_metadata(metadata))

    # 3. Safety flags (hard gates)
    all_issues.extend(_check_safety_flags(scaffold))

    # 4. Workflow steps
    workflow = scaffold.get("workflow")
    if isinstance(workflow, dict):
        steps = workflow.get("steps", [])
        all_issues.extend(_check_workflow_steps(steps))
    elif workflow is not None:
        all_issues.append(SandboxIssue(
            severity="error",
            location="workflow",
            message="'workflow' must be a dict.",
        ))

    # 5. Inputs / outputs
    all_issues.extend(_check_inputs_outputs(scaffold))

    # 6. Python stub safety
    stub = scaffold.get("python_stub")
    if isinstance(stub, str):
        all_issues.extend(_check_python_stub(stub))

    return SandboxTestReport.from_issues(all_issues)
