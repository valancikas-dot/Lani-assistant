"""
Stream route – Server-Sent Events (SSE) endpoint for long-running tasks.

POST /api/v1/stream
    Submit a command and receive a real-time stream of progress events.
    Each event is a JSON object with a ``type`` field:

    {"type": "start",    "goal": "...", "step_count": N}
    {"type": "step",     "index": 0, "tool": "web_search", "description": "..."}
    {"type": "result",   "index": 0, "status": "completed", "message": "...", "data": {...}}
    {"type": "done",     "overall_status": "completed", "tts_text": "..."}
    {"type": "error",    "message": "..."}

This allows the frontend to show a live progress bar / step list without
blocking on a single long HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import UserSettings
from app.schemas.commands import CommandRequest
from app.services.plan_executor import _load_allowed_dirs, _pipe_research_urls
from app.services.task_planner import plan_command
from app.services.workflow_planner import plan_workflow
from app.services import memory_service
from app.services.approval_service import create_approval_request
from app.services.audit_service import record_action
from app.services.voice_shaper import shape_for_voice
from app.tools.file_tools import set_runtime_allowed_dirs
from app.tools.registry import get_tool

log = logging.getLogger(__name__)
router = APIRouter()


def _sse(data: dict) -> str:
    """Format a single SSE message."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _get_language(db: AsyncSession) -> str:
    row_res = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = row_res.scalar_one_or_none()
    lang = getattr(row, "assistant_language", None) or "en"
    return lang.split("-")[0].lower()


async def _stream_plan(command: str, db: AsyncSession) -> AsyncGenerator[str, None]:
    """
    Core generator: build plan → stream step-by-step progress via SSE.
    """
    try:
        # ── Build plan ──────────────────────────────────────────────────────
        plan = plan_workflow(command)

        yield _sse({
            "type": "start",
            "goal": plan.goal,
            "step_count": len(plan.steps),
        })

        # ── Load context ────────────────────────────────────────────────────
        db_dirs = await _load_allowed_dirs(db)
        set_runtime_allowed_dirs(db_dirs)
        mem_ctx = await memory_service.get_context_for_command(db, plan.goal)

        step_results = []
        step_summaries = []

        # ── Group steps into parallel batches ──────────────────────────────
        # Steps that need data from previous steps (URL piping from web_search)
        # must run after them. Steps with no such dependency can run in parallel.
        # Simple rule: batch consecutive independent steps together.
        _URL_PRODUCING_TOOLS = {"web_search", "research_and_prepare_brief"}
        _URL_CONSUMING_TOOLS = {"summarize_web_results", "compare_research_results", "fetch_url"}

        def _build_batches(steps):
            """Group plan steps into sequential batches of parallel-safe steps."""
            batches: list[list] = []
            current_batch: list = []
            has_url_producer = False
            for s in steps:
                is_consumer = s.tool in _URL_CONSUMING_TOOLS
                if is_consumer and has_url_producer:
                    # Must run after producer batch — flush current and start new solo batch
                    if current_batch:
                        batches.append(current_batch)
                    batches.append([s])
                    current_batch = []
                    has_url_producer = False
                else:
                    current_batch.append(s)
                    if s.tool in _URL_PRODUCING_TOOLS:
                        has_url_producer = True
            if current_batch:
                batches.append(current_batch)
            return batches

        batches = _build_batches(plan.steps)
        log.info("[stream] %d steps → %d batch(es)", len(plan.steps), len(batches))

        for batch in batches:
            if len(batch) == 1:
                # Single step — run normally (keeps existing sequential behaviour)
                steps_to_run = batch
            else:
                # Announce all steps in this batch upfront
                for step in batch:
                    yield _sse({
                        "type": "step",
                        "index": step.index,
                        "tool": step.tool,
                        "description": step.description,
                        "parallel": True,
                    })
                await asyncio.sleep(0)

                # Pre-batch approval check: if any step requires approval,
                # fall back to sequential processing (which has a proper approval gate).
                _any_needs_approval = False
                for _s in batch:
                    _t = get_tool(_s.tool)
                    if _t is not None and getattr(_t, "requires_approval", False):
                        _any_needs_approval = True
                        break
                if _any_needs_approval:
                    steps_to_run = batch
                    # Skip parallel path — let sequential loop handle approval gates
                    # (we must NOT enter the asyncio.gather block below)
                    pass
                else:
                    # Run the batch concurrently
                    from app.services.execution_guard import guarded_execute

                    async def _run_step(step):
                        effective_args = memory_service.apply_memory_to_args(step.args, mem_ctx)
                        effective_args = _pipe_research_urls(step, effective_args, step_results)
                        tool = get_tool(step.tool)
                        if tool is None:
                            from app.schemas.plan import StepResult
                            return step, StepResult(
                                step_index=step.index, tool=step.tool,
                                status="failed",
                                message=f"Tool '{step.tool}' not found in registry.",
                            ), effective_args, None
                        guard = await guarded_execute(
                            step.tool, effective_args, plan.goal, db,
                            execution_context={"executor_type": "stream_parallel"},
                            caller="stream_parallel",
                        )
                        raw = guard.tool_result
                        from app.schemas.plan import StepResult
                        sr = StepResult(
                            step_index=step.index,
                            tool=step.tool,
                            status="completed" if (raw is not None and raw.status == "success") else "failed",
                            message=(raw.message if raw else guard.policy_reason or "Blocked."),
                            data=(raw.data if raw else None),
                        )
                        return step, sr, effective_args, raw

                    parallel_results = await asyncio.gather(*[_run_step(s) for s in batch])

                    for step, sr, effective_args, tool_result in parallel_results:
                        status = sr.status
                        step_results.append(sr)
                        step_summaries.append({
                            "tool": step.tool,
                            "args": effective_args,
                            "status": status,
                            "result": sr.data,
                        })
                        if tool_result:
                            await record_action(db, plan.goal, step.tool, tool_result.status, tool_result.message or "")
                        yield _sse({
                            "type": "result",
                            "index": step.index,
                            "status": status,
                            "message": sr.message,
                            "data": sr.data,
                        })
                        await asyncio.sleep(0)

                    # If any step failed, abort
                    for _, sr, _, _ in parallel_results:
                        if sr.status == "failed":
                            lang = await _get_language(db)
                            tts = shape_for_voice(sr.message or "Failed.", language=lang)
                            yield _sse({"type": "done", "overall_status": "failed", "tts_text": tts})
                            return

                    continue  # Next batch — skip the single-step loop below

            for step in steps_to_run:
                # Announce step start
                yield _sse({
                    "type": "step",
                    "index": step.index,
                    "tool": step.tool,
                    "description": step.description,
                })
                await asyncio.sleep(0)  # allow event loop to flush

                # Apply memory + pipe
                effective_args = memory_service.apply_memory_to_args(step.args, mem_ctx)
                effective_args = _pipe_research_urls(step, effective_args, step_results)

                tool = get_tool(step.tool)
                if tool is None:
                    yield _sse({
                        "type": "result",
                        "index": step.index,
                        "status": "failed",
                        "message": f"Tool '{step.tool}' not found in registry.",
                    })
                    yield _sse({"type": "done", "overall_status": "failed", "tts_text": "Failed."})
                    return

                # Approval gate
                if tool.requires_approval:
                    approval_id = await create_approval_request(
                        db, tool_name=step.tool, command=plan.goal, params=effective_args
                    )
                    yield _sse({
                        "type": "approval_required",
                        "index": step.index,
                        "tool": step.tool,
                        "approval_id": approval_id,
                        "message": f"Step '{step.description}' needs your approval (#{approval_id}).",
                    })
                    yield _sse({"type": "done", "overall_status": "approval_required", "tts_text": "Approval required."})
                    return

                # Execute
                tool_result = await tool.run(effective_args)
                await record_action(db, plan.goal, step.tool, tool_result.status, tool_result.message or "")

                status = "completed" if tool_result.status == "success" else "failed"
                from app.schemas.plan import StepResult
                sr = StepResult(
                    step_index=step.index,
                    tool=step.tool,
                    status=status,
                    message=tool_result.message,
                    data=tool_result.data,
                )
                step_results.append(sr)
                step_summaries.append({
                    "tool": step.tool,
                    "args": effective_args,
                    "status": status,
                    "result": tool_result.data,
                })

                yield _sse({
                    "type": "result",
                    "index": step.index,
                    "status": status,
                    "message": tool_result.message,
                    "data": tool_result.data,
                })
                await asyncio.sleep(0)

                if tool_result.status != "success":
                    lang = await _get_language(db)
                    try:
                        from app.services.error_explainer import explain_error
                        friendly = await explain_error(
                            tool_name=step.tool,
                            error_msg=tool_result.message or "",
                            command=plan.goal,
                            language=lang,
                        )
                    except Exception:
                        friendly = tool_result.message or "Nepavyko."
                    tts = shape_for_voice(friendly, language=lang)
                    yield _sse({"type": "done", "overall_status": "failed", "tts_text": tts,
                                 "error_detail": friendly})
                    return

        # ── Finished ────────────────────────────────────────────────────────
        try:
            await memory_service.record_task_history(
                db, command=plan.goal, plan_goal=plan.goal,
                step_summaries=step_summaries, overall_status="completed",
                memory_hints=mem_ctx.hints,
            )
            await memory_service.generate_suggestions(db)
        except Exception:
            pass

        lang = await _get_language(db)
        last_msg = step_results[-1].message if step_results else ""
        tts = shape_for_voice(last_msg or "Done.", language=lang) if last_msg else (
            "Atlikta." if lang == "lt" else "Done."
        )
        yield _sse({"type": "done", "overall_status": "completed", "tts_text": tts})

    except Exception as exc:
        log.exception("[stream] unexpected error: %s", exc)
        yield _sse({"type": "error", "message": str(exc)})


@router.post("/stream")
async def stream_command(
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Execute a command with real-time SSE progress streaming.

    Connect with ``EventSource`` or ``fetch`` + ``ReadableStream`` on the frontend.
    Each event is a JSON payload; the stream closes after ``{"type": "done"}``
    or ``{"type": "error"}``.
    """
    async def generator():
        async for chunk in _stream_plan(request.command, db):
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
