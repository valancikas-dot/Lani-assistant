"""
Plan executor – runs an ExecutionPlan step-by-step.

Responsibilities
────────────────
• Load allowed directories from DB (same as command_router)
• Fetch relevant memory context (preferred folders, languages, etc.)
• Apply memory defaults to step args (non-destructive – only fills blanks)
• Iterate plan.steps sequentially
• For each step:
    – look up the tool in the registry
    – if requires_approval → create an approval request, pause, return
    – else → call tool.run(step.args), record audit entry
• Record completed plan in task_history memory
• Collect StepResult objects for every completed/paused step
• Return a PlanExecutionResponse with overall_status + memory_hints

The executor is intentionally *synchronous in terms of ordering*:
steps run one after another (not in parallel) so that earlier results
can feed into later steps (future: pipe data between steps).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import UserSettings
from app.schemas.plan import (
    ExecutionPlan,
    PlanExecutionResponse,
    PlanStep,
    StepResult,
    StepStatus,
)
from app.services import memory_service
from app.services.context_service import resolve_references, extract_context_from_result, update_context
from app.services.execution_guard import guarded_execute
from app.tools.file_tools import set_runtime_allowed_dirs


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _load_allowed_dirs(db: AsyncSession) -> List[str]:
    """Fetch allowed_directories from the settings row."""
    row = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    settings = row.scalar_one_or_none()
    if settings and settings.allowed_directories:
        return json.loads(settings.allowed_directories)
    return []


def _overall_status(results: List[StepResult], plan_len: int) -> StepStatus:
    """
    Derive an aggregate status string from the step results collected so far.

    Rules (in priority order):
      1. Any step 'approval_required' → 'approval_required'
      2. Any step 'failed'            → 'failed'
      3. All steps 'completed'        → 'completed'
      4. Otherwise                    → 'running'  (partial progress)
    """
    statuses = {r.status for r in results}
    if "approval_required" in statuses:
        return "approval_required"
    if "failed" in statuses:
        return "failed"
    if all(r.status == "completed" for r in results) and len(results) == plan_len:
        return "completed"
    return "running"


def _pipe_research_urls(
    step: PlanStep,
    args: Dict[str, Any],
    previous_results: List[StepResult],
) -> Dict[str, Any]:
    """
    If this step is 'summarize_web_results' or 'compare_research_results'
    and its 'urls' arg is empty, fill it from the most recent 'web_search'
    step result so steps compose automatically without manual wiring.
    """
    if step.tool not in ("summarize_web_results", "compare_research_results"):
        return args
    if args.get("urls"):          # already supplied explicitly — don't override
        return args

    # Find the latest completed web_search step
    for sr in reversed(previous_results):
        if sr.tool == "web_search" and sr.status == "completed" and sr.data:
            results_list = sr.data.get("results", [])
            urls = [r["url"] for r in results_list if r.get("url")]
            if urls:
                return {**args, "urls": urls}
    return args


# ─── Public API ───────────────────────────────────────────────────────────────

async def execute_plan(
    plan: ExecutionPlan,
    db: AsyncSession,
    *,
    start_from_step: int = 0,
) -> PlanExecutionResponse:
    """
    Execute *plan* starting from *start_from_step* (default 0).

    Parameters
    ----------
    plan            : The ExecutionPlan produced by task_planner.plan_command().
    db              : Active async DB session (injected by FastAPI).
    start_from_step : Allow resuming after an approval; steps before this index
                      are marked 'skipped' in the response (not re-executed).

    Returns
    -------
    PlanExecutionResponse with per-step results, overall_status, and memory_hints.
    """
    # ── Load allowed dirs ──
    db_dirs = await _load_allowed_dirs(db)
    set_runtime_allowed_dirs(db_dirs)

    # ── Load settings row (passed into guarded_execute) ──
    settings_row = (await db.execute(select(UserSettings).where(UserSettings.id == 1))).scalar_one_or_none()

    # ── Resolve implicit references ("tą patį", "šį failą", …) ──
    resolved_goal = resolve_references(plan.goal)
    if resolved_goal != plan.goal:
        plan = ExecutionPlan(
            goal=resolved_goal,
            steps=plan.steps,
            is_multi_step=plan.is_multi_step,
        )

    # ── Track command in context ──
    update_context(last_command=plan.goal)

    # ── Fetch memory context ──
    mem_ctx = await memory_service.get_context_for_command(db, plan.goal)

    step_results: List[StepResult] = []
    step_summaries: List[Dict[str, Any]] = []

    for step in plan.steps:
        # ── Skip already-completed steps when resuming ──
        if step.index < start_from_step:
            step_results.append(StepResult(
                step_index=step.index,
                tool=step.tool,
                status="skipped",
                message="Skipped (already executed before approval resume).",
            ))
            continue

        # ── Apply memory defaults to this step's args ──
        effective_args = memory_service.apply_memory_to_args(step.args, mem_ctx)

        # ── Pipe URLs from previous web_search step into summarize/compare ──
        effective_args = _pipe_research_urls(step, effective_args, step_results)

        # ── Central execution guard (tool lookup + policy + approval + execute +
        #    world state update + state delta + audit chain + eval) ──
        exec_ctx = {
            "plan": plan.model_dump(),
            "start_from_step": step.index,
            "executor_type": "plan",
        }
        guard_result = await guarded_execute(
            step.tool,
            effective_args,
            plan.goal,
            db,
            settings_row=settings_row,
            execution_context=exec_ctx,
            caller="plan",
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
            return PlanExecutionResponse(
                command=plan.goal,
                plan=plan,
                step_results=step_results,
                overall_status="approval_required",
                message=(
                    f"Plan paused at step {step.index + 1}/{len(plan.steps)}: "
                    f"'{step.description}' needs your approval "
                    f"(approval ID #{guard_result.approval_id})."
                ),
                memory_hints=mem_ctx.hints,
            )

        if guard_result.blocked:
            step_results.append(StepResult(
                step_index=step.index,
                tool=step.tool,
                status="failed",
                message=guard_result.policy_reason or "Policy denied.",
            ))
            break

        tool_result = guard_result.tool_result  # ToolResult from tool.run()
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

        # ── Update session context (file paths, URLs, topics) ──
        extract_context_from_result(step.tool, effective_args, tool_result.message or "")

        # ── Log to episodic memory ──
        try:
            from app.services.episodic_memory_service import log_tool_call
            await log_tool_call(
                session_id="default",
                tool_name=step.tool,
                args=effective_args,
                result=(tool_result.message or "")[:500],
                success=(tool_result.status == "success"),
                importance=0.7 if tool_result.status != "success" else 0.4,
            )
        except Exception:
            pass

        if tool_result.status != "success":
            # Get a friendly, human-readable explanation
            try:
                from app.services.error_explainer import explain_error
                from app.services.memory_service import _get_language  # type: ignore[attr-defined]
                lang = "lt"
                try:
                    lang = await _get_language(db)
                except Exception:
                    pass
                friendly_msg = await explain_error(
                    tool_name=step.tool,
                    error_msg=tool_result.message or "",
                    command=plan.goal,
                    language=lang,
                )
            except Exception:
                friendly_msg = tool_result.message

            return PlanExecutionResponse(
                command=plan.goal,
                plan=plan,
                step_results=step_results,
                overall_status="failed",
                message=(
                    f"Plan stopped at step {step.index + 1}/{len(plan.steps)}: "
                    f"{friendly_msg}"
                ),
                memory_hints=mem_ctx.hints,
            )

    # ── All steps completed (or empty plan) ──
    overall = _overall_status(step_results, len(plan.steps))
    completed = sum(1 for r in step_results if r.status == "completed")
    total = len(plan.steps)

    # ── Record task history for future suggestions ──
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
        pass  # never let history recording break a successful plan

    # ── Refresh suggestion engine after every completed plan ──
    # Fire-and-forget: errors here must not fail the response.
    try:
        await memory_service.generate_suggestions(db)
    except Exception:
        pass

    return PlanExecutionResponse(
        command=plan.goal,
        plan=plan,
        step_results=step_results,
        overall_status=overall,
        message=f"Plan finished: {completed}/{total} step(s) completed successfully.",
        memory_hints=mem_ctx.hints,
    )
