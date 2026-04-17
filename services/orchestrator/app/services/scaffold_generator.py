"""
Scaffold Generator – Phase 7: Proposal → Skill Scaffold Generator.

Converts a ``SkillSpec`` into two concrete artefacts:

1. **JSON workflow definition** – a machine-readable workflow that describes
   the skill's steps, tool bindings, inputs, outputs, and metadata.
   This is the canonical artefact stored in ``SkillDraft.scaffold_json``.

2. **Python wrapper stub** (optional) – a human-readable Python module
   skeleton that shows how the skill *would* be called if installed.
   Stored as a string field inside ``scaffold_json["python_stub"]``.

Design constraints
──────────────────
• Pure function – no DB I/O, no network, no subprocess, no execution.
• No side effects – reads only from the SkillSpec; writes only to memory.
• Deterministic – same SkillSpec always produces equivalent scaffold.
• Inspectable – all output is plain JSON-serialisable Python.
• Safe – the generated Python stub is a COMMENT-HEAVY skeleton with no
  runnable logic; it must not be importable or executable without explicit
  user action.
"""

from __future__ import annotations

import textwrap
from dataclasses import asdict
from typing import Any, Dict, List

from app.services.skill_spec_generator import SkillSpec, SkillSpecStep


# ─── Constants ────────────────────────────────────────────────────────────────

SCAFFOLD_VERSION = "1.0"
SCAFFOLD_TYPE_JSON = "json_workflow"
SCAFFOLD_TYPE_PYTHON = "python_stub"


# ─── Workflow step builder ────────────────────────────────────────────────────

def _build_workflow_step(step: SkillSpecStep) -> Dict[str, Any]:
    """Serialise a SkillSpecStep into a workflow step dict."""
    return {
        "step_index": step.step_index,
        "tool_name": step.tool_name,
        "command_template": step.command_template,
        "description": step.description,
        "is_required": step.is_required,
        # Placeholder bindings – filled by the user before installation
        "input_bindings": {
            inp: f"${{input.{inp.replace(' ', '_')}}}"
            for inp in []  # populated by sandbox step, not here
        },
    }


# ─── Python stub generator ────────────────────────────────────────────────────

def _sanitise_identifier(name: str) -> str:
    """Convert a human name into a valid Python identifier."""
    import re
    ident = re.sub(r"[^\w]", "_", name.lower())
    ident = re.sub(r"_+", "_", ident).strip("_")
    return ident or "skill"


def _build_python_stub(spec: SkillSpec) -> str:
    """
    Generate a human-readable Python stub for the skill.

    The stub is intentionally NON-RUNNABLE without user modifications:
    - all tool calls are represented as ``# TODO: implement`` comments
    - no imports point to real execution primitives
    - a prominent safety banner is included at the top
    """
    fn_name = _sanitise_identifier(spec.name)
    tool_list = ", ".join(f'"{t}"' for t in spec.required_tools)

    input_params = ", ".join(
        _sanitise_identifier(i) + ": str"
        for i in spec.expected_inputs
    )
    if not input_params:
        input_params = "**kwargs"

    step_comments = "\n".join(
        f"    # Step {s.step_index}: [{s.tool_name}] {s.command_template[:60]}"
        for s in spec.steps
    )

    stub = textwrap.dedent(f"""\
        # ============================================================
        # LANI SKILL STUB – GENERATED DRAFT (NOT EXECUTABLE AS-IS)
        # Skill:   {spec.name}
        # Risk:    {spec.risk_level}
        # Source:  proposal_id={spec.source_proposal_id}
        #
        # THIS FILE IS A PREVIEW ONLY.
        # It will not run until you:
        #   1. Review and approve it
        #   2. Install it via Lani's skill installer
        #   3. Provide real tool bindings
        # ============================================================

        from __future__ import annotations

        # Required tools: {tool_list}
        # TODO: Import your real tool adapters here before installation.


        def {fn_name}({input_params}) -> dict:
            \"\"\"
            {spec.description[:200]}

            Expected inputs:  {spec.expected_inputs}
            Expected outputs: {spec.expected_outputs}
            Estimated savings: {spec.estimated_time_saved or 'unknown'}
            \"\"\"
{step_comments}

            # TODO: Replace the comments above with real tool calls.
            # Return a dict with the skill's outputs.
            raise NotImplementedError(
                "This skill stub has not been configured yet. "
                "Install it via Lani before calling."
            )
        """)
    return stub


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_scaffold(spec: SkillSpec) -> Dict[str, Any]:
    """
    Convert a ``SkillSpec`` into a JSON-serialisable scaffold dict.

    The scaffold is the canonical artefact stored as
    ``SkillDraft.scaffold_json``.  It contains:

    ``metadata``
        Version, skill_id, name, risk_level, source references.
    ``workflow``
        Ordered list of workflow step dicts.
    ``inputs``
        Declared input parameters.
    ``outputs``
        Declared output descriptions.
    ``python_stub``
        Human-readable Python skeleton (non-executable preview).

    Parameters
    ----------
    spec:
        A fully-populated ``SkillSpec`` dataclass.

    Returns
    -------
    A plain ``dict`` that is JSON-serialisable and storable in
    ``SkillDraft.scaffold_json``.
    """
    workflow_steps = [_build_workflow_step(s) for s in spec.steps]
    python_stub = _build_python_stub(spec)

    scaffold: Dict[str, Any] = {
        "scaffold_version": SCAFFOLD_VERSION,
        "scaffold_type": SCAFFOLD_TYPE_JSON,
        "metadata": {
            "skill_id": spec.skill_id,
            "name": spec.name,
            "description": spec.description[:400],
            "risk_level": spec.risk_level,
            "source_proposal_id": spec.source_proposal_id,
            "source_pattern_id": spec.source_pattern_id,
            "estimated_time_saved": spec.estimated_time_saved,
            "rationale": spec.rationale[:400],
        },
        "required_tools": spec.required_tools,
        "inputs": [
            {"name": inp, "type": "string", "required": True}
            for inp in spec.expected_inputs
        ],
        "outputs": [
            {"name": out, "type": "string"}
            for out in spec.expected_outputs
        ],
        "workflow": {
            "steps": workflow_steps,
        },
        # Python stub is stored as a plain string field – not executed
        "python_stub": python_stub,
        # Installation gate: must be False until user explicitly approves
        "installation_approved": False,
        "auto_execute": False,  # safety flag – MUST remain False
    }

    return scaffold


def scaffold_to_summary(scaffold: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a lightweight summary of a scaffold for API list responses.
    Strips the verbose python_stub and workflow step details.
    """
    meta = scaffold.get("metadata", {})
    return {
        "scaffold_version": scaffold.get("scaffold_version"),
        "scaffold_type": scaffold.get("scaffold_type"),
        "skill_id": meta.get("skill_id"),
        "name": meta.get("name"),
        "description": meta.get("description", "")[:120],
        "risk_level": meta.get("risk_level"),
        "required_tools": scaffold.get("required_tools", []),
        "step_count": len(scaffold.get("workflow", {}).get("steps", [])),
        "input_count": len(scaffold.get("inputs", [])),
        "output_count": len(scaffold.get("outputs", [])),
        "installation_approved": scaffold.get("installation_approved", False),
        "auto_execute": scaffold.get("auto_execute", False),
    }
