"""
Workflow Executor – runs a WorkflowPlan and produces a WorkflowResult.

Key responsibilities
────────────────────
1. **Artifact piping**: resolve ``__pipe_from_step_N__`` placeholder args
   by reading structured data from previously-completed step results.
2. **Artifact collection**: inspect each step's ``tool_result.data`` and
   classify it into a ``WorkflowArtifact`` (file, email_draft, etc.).
3. **Approval gate**: pause execution and return ``approval_required`` when a
   tool requires human approval, storing the plan state for resumption.
4. **Partial-success handling**: return ``partial`` status when some steps
   completed before a failure, so the frontend can still surface artifacts.
5. **Workflow summary**: compose a human-readable + TTS-ready summary.

Artifact piping contracts
─────────────────────────
  web_search            → data["urls"]       (list[str])
  drive_search_files    → data["file_id"]    (str, first result)
                          data["files"]      (list[dict])
  drive_get_file        → data["content"]    (str)
                          data["name"]       (str)
  read_document         → data["content"]    (str)
  summarize_document    → data["summary"]    (str)
  summarize_web_results → data["summary"]    (str)
                          data["urls"]       (list[str], passthrough)
  create_presentation   → data["path"]       (str)
  create_project_scaffold → data["project_path"] (str)
  calendar_create_event → data["event_id"]   (str)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.plan import ExecutionPlan, PlanStep, StepResult
from app.schemas.workflow import (
    WorkflowArtifact,
    WorkflowArtifactType,
    WorkflowResult,
    WorkflowStepSummary,
)
from app.services.execution_guard import guarded_execute
from app.services import memory_service

log = logging.getLogger(__name__)


# ── Artifact classification map ───────────────────────────────────────────────
# tool → (artifact_type, name_template, path_key, url_key, content_key)
_ARTIFACT_MAP: Dict[str, Dict[str, str]] = {
    "create_presentation":       {"type": "presentation",     "name": "Presentation",      "path": "path"},
    "create_project_scaffold":   {"type": "project_scaffold", "name": "Project",           "path": "project_path"},
    "create_file":               {"type": "file",             "name": "File",              "path": "path"},
    "create_folder":             {"type": "file",             "name": "Folder",            "path": "path"},
    "gmail_create_draft":        {"type": "email_draft",      "name": "Email Draft",       "url": "draft_url"},
    "gmail_send_email":          {"type": "email_draft",      "name": "Email Sent",        "url": "message_url"},
    "calendar_create_event":     {"type": "calendar_event",   "name": "Calendar Event",    "url": "event_url"},
    "drive_search_files":        {"type": "drive_file",       "name": "Drive Files",       "url": "file_url"},
    "drive_get_file":            {"type": "drive_file",       "name": "Drive Document",    "content": "content"},
    "summarize_document":        {"type": "text_summary",     "name": "Summary",           "content": "summary"},
    "summarize_web_results":     {"type": "text_summary",     "name": "Research Summary",  "content": "summary"},
    "web_search":                {"type": "url_list",         "name": "Research Sources",  "content": "urls"},
    "research_and_prepare_brief":{"type": "text_summary",     "name": "Research Brief",    "content": "brief"},
    "compare_research_results":  {"type": "comparison",       "name": "Comparison",        "content": "comparison"},
}


def _collect_artifact(step_index: int, tool: str, data: Any) -> Optional[WorkflowArtifact]:
    """
    Inspect a tool's output data and return a WorkflowArtifact if applicable.
    Returns None for tools that don't produce tracked artifacts.
    """
    if not data or tool not in _ARTIFACT_MAP:
        return None

    spec = _ARTIFACT_MAP[tool]
    artifact_type = cast(WorkflowArtifactType, spec["type"])
    name = spec.get("name", tool)
    path: Optional[str] = None
    url: Optional[str] = None
    content: Optional[str] = None
    metadata: Dict[str, Any] = {}

    if isinstance(data, dict):
        path = data.get(spec.get("path", "")) if spec.get("path") else None
        url = data.get(spec.get("url", "")) if spec.get("url") else None
        raw_content = data.get(spec.get("content", "")) if spec.get("content") else None

        if raw_content is not None:
            if isinstance(raw_content, list):
                # URL list → join for content field
                content = "\n".join(str(u) for u in raw_content[:10])
                metadata["url_count"] = len(raw_content)
            else:
                content = str(raw_content)

        # Enrich name with dynamic data
        if tool == "gmail_create_draft" and "subject" in data:
            name = f"Email Draft: {data['subject']}"
        elif tool == "calendar_create_event" and "summary" in data:
            name = f"Event: {data['summary']}"
        elif tool == "create_presentation" and path:
            name = f"Presentation: {path.rsplit('/', 1)[-1]}"
        elif tool == "create_project_scaffold" and "project_name" in data:
            name = f"Project: {data['project_name']}"
        elif tool == "drive_get_file" and "name" in data:
            name = f"Drive: {data['name']}"

        # Carry extra metadata
        for key in ("subject", "to", "event_id", "draft_id", "project_name", "template"):
            if key in data:
                metadata[key] = data[key]

    return WorkflowArtifact(
        type=artifact_type,
        name=name,
        step_index=step_index,
        path=path or None,
        url=url or None,
        content=content,
        metadata=metadata,
    )


# ── Argument piping ───────────────────────────────────────────────────────────

def _resolve_pipe(value: Any, step_results: List[StepResult]) -> Any:
    """
    Replace ``__pipe_from_step_N__`` sentinel with the relevant data from
    step N's result.  Returns the original value unchanged if it is not a
    pipe sentinel or the source step hasn't completed.
    """
    if not isinstance(value, str) or not value.startswith("__pipe_from_step_"):
        return value

    # Extract step index
    try:
        src_idx = int(value.replace("__pipe_from_step_", "").replace("__", ""))
    except ValueError:
        return value

    # Find the source step result
    src = next((r for r in step_results if r.step_index == src_idx), None)
    if src is None or src.status != "completed" or src.data is None:
        return value  # sentinel remains; executor will skip gracefully

    data = src.data
    if not isinstance(data, dict):
        return str(data)

    # Determine what to pipe based on the source tool
    tool = src.tool

    if tool == "web_search":
        return data.get("urls", [])
    if tool in ("drive_search_files",):
        # For drive_get_file the next step needs a file_id
        files = data.get("files", [])
        return files[0]["id"] if files else data.get("file_id", "")
    if tool == "drive_get_file":
        return data.get("content", "")
    if tool == "read_document":
        return data.get("content", "")
    if tool in ("summarize_document", "summarize_web_results"):
        return data.get("summary", "")
    if tool == "research_and_prepare_brief":
        return data.get("brief", "")
    if tool == "create_presentation":
        return data.get("path", "")
    if tool == "create_project_scaffold":
        return data.get("project_path", "")
    if tool == "calendar_create_event":
        return data.get("event_id", "")

    # Generic fallback: return full data dict
    return data


def _resolve_args(args: Dict[str, Any], step_results: List[StepResult]) -> Dict[str, Any]:
    """Resolve all pipe sentinels in an args dict."""
    resolved: Dict[str, Any] = {}
    for key, val in args.items():
        resolved[key] = _resolve_pipe(val, step_results)
    return resolved


# ── Legacy URL piping (kept for backward compat with base task_planner plans) ─

def _pipe_research_urls(
    step: PlanStep,
    args: Dict[str, Any],
    previous_results: List[StepResult],
) -> Dict[str, Any]:
    """
    Original URL-piping logic retained so workflow_executor can execute plans
    produced by the base task_planner that use list["urls"] directly.
    """
    if step.tool not in ("summarize_web_results", "compare_research_results"):
        return args
    if args.get("urls"):
        return args  # already populated
    for r in previous_results:
        if r.tool == "web_search" and r.status == "completed" and r.data:
            urls = r.data.get("urls") if isinstance(r.data, dict) else None
            if urls:
                return {**args, "urls": urls}
    return args


# ── Workflow summary builder ──────────────────────────────────────────────────

def _build_summary(
    goal: str,
    step_results: List[StepResult],
    artifacts: List[WorkflowArtifact],
    overall_status: str,
) -> str:
    """Compose a concise human-readable summary of the workflow run."""
    completed = sum(1 for r in step_results if r.status == "completed")
    total = len(step_results)

    if overall_status == "completed":
        lines = [f"Workflow complete: {completed}/{total} step(s) succeeded."]
    elif overall_status == "approval_required":
        lines = [f"Workflow paused: approval required to continue."]
    elif overall_status == "partial":
        lines = [f"Workflow partially complete: {completed}/{total} step(s) succeeded."]
    else:
        lines = [f"Workflow failed after {completed}/{total} step(s)."]

    if artifacts:
        artifact_lines = []
        for a in artifacts:
            if a.path:
                artifact_lines.append(f"  • {a.name}: {a.path}")
            elif a.url:
                artifact_lines.append(f"  • {a.name}: {a.url}")
            elif a.content:
                preview = a.content[:80].replace("\n", " ")
                artifact_lines.append(f"  • {a.name}: {preview}…" if len(a.content) > 80 else f"  • {a.name}: {a.content}")
        if artifact_lines:
            lines.append("Artifacts produced:")
            lines.extend(artifact_lines)

    return "\n".join(lines)


def _build_tts_summary(
    goal: str,
    artifacts: List[WorkflowArtifact],
    overall_status: str,
) -> str:
    """Compose a short TTS-friendly sentence."""
    if overall_status == "completed":
        if artifacts:
            names = ", ".join(a.name for a in artifacts[:3])
            return f"Done! I completed your workflow and produced: {names}."
        return "Your workflow completed successfully."
    if overall_status == "approval_required":
        return "I've paused your workflow and I'm waiting for your approval to continue."
    if overall_status == "partial":
        return "I completed part of your workflow. Some steps could not finish."
    return "Your workflow encountered an error. Please check the details."


def _overall_status(results: List[StepResult], plan_len: int) -> str:
    """Derive overall workflow status from step results."""
    if any(r.status == "approval_required" for r in results):
        return "approval_required"
    completed = sum(1 for r in results if r.status == "completed")
    failed = sum(1 for r in results if r.status == "failed")
    if failed and completed:
        return "partial"
    if failed:
        return "failed"
    if completed == plan_len:
        return "completed"
    return "partial"


# ── Main executor ─────────────────────────────────────────────────────────────

async def execute_workflow(
    plan: ExecutionPlan,
    db: AsyncSession,
    *,
    tts_response: bool = False,
    start_from_step: int = 0,
) -> WorkflowResult:
    """
    Execute a workflow plan, collecting artifacts and piping data between steps.

    Args:
        plan:            The ExecutionPlan from the workflow_planner.
        db:              Database session for approvals / audit logging.
        tts_response:    If True, include a TTS-friendly text in the result.
        start_from_step: Resume from this step index (used after approval).

    Returns:
        WorkflowResult with steps, artifacts, overall_status, and summary.
    """
    workflow_id = str(uuid.uuid4())
    step_results: List[StepResult] = []
    artifacts: List[WorkflowArtifact] = []
    step_summaries: List[Dict[str, Any]] = []

    # ── Memory context injection ──
    mem_ctx = await memory_service.get_context_for_command(db, plan.goal)

    # ── Load allowed directories ──
    try:
        from app.services.plan_executor import _load_allowed_dirs
        allowed_dirs = await _load_allowed_dirs(db)
    except Exception:
        allowed_dirs = []

    # ── Load settings for policy context ──
    try:
        from sqlalchemy import select
        from app.models.settings import UserSettings
        _sr = await db.execute(select(UserSettings).where(UserSettings.id == 1))
        _settings_row = _sr.scalar_one_or_none()
    except Exception:
        _settings_row = None

    for step in plan.steps:
        # Skip already-completed steps (approval resume path)
        if step.index < start_from_step:
            continue

        # ── Resolve pipe sentinels in args ──
        effective_args = _resolve_args(step.args, step_results)

        # ── Legacy URL piping (for plans from base task_planner) ──
        effective_args = _pipe_research_urls(step, effective_args, step_results)

        # ── Memory context injection ──
        effective_args = memory_service.apply_memory_to_args(effective_args, mem_ctx)

        # ── Inject allowed_dirs for file tools ──
        if step.tool in (
            "create_file", "create_folder", "move_file",
            "sort_downloads", "read_document", "summarize_document",
        ) and "allowed_dirs" not in effective_args:
            effective_args["allowed_dirs"] = allowed_dirs

        # ── Central execution guard (tool lookup + policy + approval + execute +
        #    world state + state delta + audit chain + eval) ──
        exec_ctx = {
            "plan": plan.model_dump(),
            "start_from_step": step.index,
            "executor_type": "workflow",
        }
        guard_result = await guarded_execute(
            step.tool,
            effective_args,
            plan.goal,
            db,
            settings_row=_settings_row,
            execution_context=exec_ctx,
            caller="workflow",
        )

        if guard_result.status == "error":
            step_results.append(StepResult(
                step_index=step.index,
                tool=step.tool,
                status="failed",
                message=guard_result.policy_reason or f"Tool '{step.tool}' not found or guard error.",
            ))
            break

        if guard_result.needs_approval:
            step_results.append(StepResult(
                step_index=step.index,
                tool=step.tool,
                status="approval_required",
                message=f"Approval #{guard_result.approval_id} required before '{step.tool}' can run.",
                approval_id=guard_result.approval_id,
            ))
            overall = "approval_required"
            msg = _build_summary(plan.goal, step_results, artifacts, overall)
            return WorkflowResult(
                workflow_id=workflow_id,
                goal=plan.goal,
                overall_status=overall,
                steps=_to_step_summaries(plan.steps, step_results, artifacts),
                artifacts=artifacts,
                message=msg,
                tts_text=_build_tts_summary(plan.goal, artifacts, overall) if tts_response else None,
                memory_hints=mem_ctx.hints,
                requires_approval=True,
                approval_id=guard_result.approval_id,
            )

        if guard_result.blocked:
            step_results.append(StepResult(
                step_index=step.index,
                tool=step.tool,
                status="failed",
                message=guard_result.policy_reason or "Policy denied.",
            ))
            break

        tool_result = guard_result.tool_result


        sr = StepResult(
            step_index=step.index,
            tool=step.tool,
            status="completed" if tool_result.status == "success" else "failed",
            message=tool_result.message,
            data=tool_result.data,
        )
        step_results.append(sr)
        step_summaries.append({
            "tool": step.tool,
            "args": effective_args,
            "status": sr.status,
            "result": tool_result.data,
        })

        # ── Collect artifact ──
        if sr.status == "completed":
            artifact = _collect_artifact(step.index, step.tool, tool_result.data)
            if artifact:
                artifacts.append(artifact)

        if tool_result.status != "success":
            overall = _overall_status(step_results, len(plan.steps))
            msg = _build_summary(plan.goal, step_results, artifacts, overall)
            return WorkflowResult(
                workflow_id=workflow_id,
                goal=plan.goal,
                overall_status=overall,
                steps=_to_step_summaries(plan.steps, step_results, artifacts),
                artifacts=artifacts,
                message=msg,
                tts_text=_build_tts_summary(plan.goal, artifacts, overall) if tts_response else None,
                memory_hints=mem_ctx.hints,
            )

    # ── All steps completed ──
    overall = _overall_status(step_results, len(plan.steps))

    # ── Record task history ──
    try:
        await memory_service.record_task_history(
            db,
            command=plan.goal,
            plan_goal=plan.goal,
            step_summaries=step_summaries,
            overall_status=overall,
            memory_hints=mem_ctx.hints,
        )
    except Exception:
        pass

    msg = _build_summary(plan.goal, step_results, artifacts, overall)
    return WorkflowResult(
        workflow_id=workflow_id,
        goal=plan.goal,
        overall_status=overall,
        steps=_to_step_summaries(plan.steps, step_results, artifacts),
        artifacts=artifacts,
        message=msg,
        tts_text=_build_tts_summary(plan.goal, artifacts, overall) if tts_response else None,
        memory_hints=mem_ctx.hints,
    )


def _to_step_summaries(
    plan_steps: List[PlanStep],
    step_results: List[StepResult],
    artifacts: List[WorkflowArtifact],
) -> List[WorkflowStepSummary]:
    """
    Merge plan steps with their execution results into WorkflowStepSummary objects.
    """
    result_map = {r.step_index: r for r in step_results}
    artifact_map = {a.step_index: a for a in artifacts}

    summaries: List[WorkflowStepSummary] = []
    for ps in plan_steps:
        sr = result_map.get(ps.index)
        summaries.append(WorkflowStepSummary(
            index=ps.index,
            tool=ps.tool,
            description=ps.description,
            status=sr.status if sr else "pending",
            message=sr.message if sr else None,
            artifact=artifact_map.get(ps.index),
        ))
    return summaries
