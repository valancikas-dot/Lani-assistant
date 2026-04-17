"""
Workflow Planner – detects the 5 cross-tool workflow archetypes and builds
ordered ExecutionPlan objects with rich dependency metadata.

The workflow planner extends the base task_planner with patterns that span
multiple subsystems (Drive + Gmail, Builder + Operator, Research + Slides, etc.).

Each builder returns a list of PlanStep objects; the workflow executor converts
these into a WorkflowResult with structured artifact piping between steps.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.plan import ExecutionPlan, PlanStep
from app.services.task_planner import (
    _make_step,
    _extract_research_query,
    _extract_drive_query,
    _extract_email_subject,
    _extract_email_to,
    _extract_event_summary,
    _detect_template,
    _detect_project_name,
    plan_command,          # fall-through for non-workflow commands
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_folder_hint(cmd: str) -> str:
    """Extract a preferred save folder from the command, if mentioned."""
    m = re.search(
        r"(?:save|store|put|export)\s+(?:it\s+)?(?:to|in|into)\s+([~/][^\s,]+|my\s+\w+\s+folder)",
        cmd, re.I,
    )
    if m:
        return m.group(1).strip()
    return "~/Desktop"


def _extract_doc_path(cmd: str) -> str:
    """Extract a local document path from a command like 'summarize ~/docs/report.pdf'."""
    # Quoted path
    m = re.search(r"['\"]([^'\"]+\.(pdf|docx?|txt|md))['\"]", cmd, re.I)
    if m:
        return m.group(1)
    # Bare path starting with ~ or /
    m = re.search(r"(~/\S+|/\S+)", cmd)
    if m:
        return m.group(1)
    return ""


def _extract_presentation_title(cmd: str) -> str:
    """Extract presentation title from command."""
    m = re.search(
        r"presentation\s+(?:called|titled|named)\s+['\"]?(.+?)['\"]?(?:\s+and|\s*$)",
        cmd, re.I,
    )
    if m:
        return m.group(1).strip()
    # Try topic after "about" or "on"
    m = re.search(r"presentation\s+(?:about|on)\s+(.+?)(?:\s+and|\s*$)", cmd, re.I)
    if m:
        return m.group(1).strip()
    return "Presentation"


# ─── Workflow 1: Drive → Summarize → Draft Email ──────────────────────────────

def _build_drive_summarize_email(m: re.Match, cmd: str) -> List[PlanStep]:
    """
    Find file(s) on Google Drive  →  summarize content  →  draft Gmail message.

    Artifact flow:
      drive_get_file.data["content"] → summarize_document args["text"]
      summarize_document.data["summary"] → gmail_create_draft args["body"]
    """
    query = _extract_drive_query(cmd)
    to_addr = _extract_email_to(cmd)
    subject = _extract_email_subject(cmd)
    if not subject:
        subject = f"Summary: {query}" if query else "Summary"

    return [
        _make_step(0, "drive_search_files",
                   f"Search Drive for: {query}",
                   {"query": query, "max_results": 5}),
        _make_step(1, "drive_get_file",
                   "Retrieve Drive file content",
                   {"file_id": "__pipe_from_step_0__"}),
        _make_step(2, "summarize_document",
                   "Summarize the Drive document",
                   {"path": "__pipe_from_step_1__"}),
        _make_step(3, "gmail_create_draft",
                   f"Draft email to {to_addr or 'recipient'}: {subject}",
                   {"to": to_addr or "", "subject": subject, "body": "__pipe_from_step_2__"}),
    ]


# ─── Workflow 2: Research → Present → Open File ───────────────────────────────

def _build_research_present_open(m: re.Match, cmd: str) -> List[PlanStep]:
    """
    Web search + summarize  →  create presentation  →  open the file.

    Artifact flow:
      web_search.data["urls"] → summarize_web_results args["urls"]
      summarize_web_results.data["summary"] → create_presentation args["outline"]
      create_presentation.data["path"] → operator.open_path args["path"]
    """
    query = _extract_research_query(cmd)
    title = _extract_presentation_title(cmd)
    if title == "Presentation" and query:
        title = f"{query.title()} Overview"
    save_path = _extract_folder_hint(cmd)

    return [
        _make_step(0, "web_search",
                   f"Research: {query}",
                   {"query": query, "num_results": 5}),
        _make_step(1, "summarize_web_results",
                   "Summarize research findings",
                   {"urls": "__pipe_from_step_0__", "query": query}),
        _make_step(2, "create_presentation",
                   f"Create presentation: {title}",
                   {
                       "title": title,
                       "outline": "__pipe_from_step_1__",
                       "output_path": f"{save_path}/{title}.pptx",
                   }),
        _make_step(3, "operator.open_path",
                   "Open the presentation",
                   {"path": "__pipe_from_step_2__"}),
    ]


# ─── Workflow 3: Builder → Create Project → Open VS Code ─────────────────────

def _build_scaffold_open_editor(m: re.Match, cmd: str) -> List[PlanStep]:
    """
    Scaffold project  →  create README  →  open project in VS Code.

    Artifact flow:
      create_project_scaffold.data["project_path"] → create_readme args["project_path"]
      create_project_scaffold.data["project_path"] → operator.open_path args["path"]
    """
    template = _detect_template(cmd)
    name = _detect_project_name(cmd) or "my-project"

    return [
        _make_step(0, "create_project_scaffold",
                   f"Scaffold {template} project: {name}",
                   {"template": template, "project_name": name, "base_path": "~/Projects"}),
        _make_step(1, "create_readme",
                   f"Generate README for {name}",
                   {"project_path": "__pipe_from_step_0__", "project_name": name}),
        _make_step(2, "propose_terminal_commands",
                   "Suggest setup commands",
                   {"project_path": "__pipe_from_step_0__", "template": template}),
        _make_step(3, "operator.open_path",
                   "Open project in editor",
                   {"path": "__pipe_from_step_0__"}),
    ]


# ─── Workflow 4: Local Docs → Summarize → Presentation → Save ────────────────

def _build_docs_summarize_present_save(m: re.Match, cmd: str) -> List[PlanStep]:
    """
    Read local document  →  summarize  →  create presentation  →  save to folder.

    Artifact flow:
      read_document.data["content"] → summarize_document args["text"]
      summarize_document.data["summary"] → create_presentation args["outline"]
      create_presentation.data["path"] → (artifact recorded; path is the save location)
    """
    doc_path = _extract_doc_path(cmd)
    title = _extract_presentation_title(cmd)
    save_path = _extract_folder_hint(cmd)

    steps: List[PlanStep] = []
    if doc_path:
        steps.append(_make_step(0, "read_document",
                                f"Read document: {doc_path}",
                                {"path": doc_path}))
        steps.append(_make_step(1, "summarize_document",
                                "Summarize the document",
                                {"path": "__pipe_from_step_0__"}))
        steps.append(_make_step(2, "create_presentation",
                                f"Create presentation: {title}",
                                {
                                    "title": title,
                                    "outline": "__pipe_from_step_1__",
                                    "output_path": f"{save_path}/{title}.pptx",
                                }))
    else:
        # No path found – summarize then present
        steps.append(_make_step(0, "summarize_document",
                                "Summarize document",
                                {}))
        steps.append(_make_step(1, "create_presentation",
                                f"Create presentation: {title}",
                                {
                                    "title": title,
                                    "outline": "__pipe_from_step_0__",
                                    "output_path": f"{save_path}/{title}.pptx",
                                }))
    return steps


# ─── Workflow 5: Calendar Create + Draft Invitation Email ─────────────────────

def _build_calendar_and_email_invite(m: re.Match, cmd: str) -> List[PlanStep]:
    """
    Create calendar event (approval-gated)  →  draft invitation email.

    Artifact flow:
      calendar_create_event.data["event_id"] → gmail_create_draft metadata
      (email body is auto-composed from event summary / attendees)
    """
    summary = _extract_event_summary(cmd)
    to_addr = _extract_email_to(cmd)
    subject = f"Invitation: {summary}" if summary else "Meeting Invitation"

    return [
        _make_step(0, "calendar_create_event",
                   f"Create calendar event: {summary}",
                   {"summary": summary, "start": "", "end": ""}),
        _make_step(1, "gmail_create_draft",
                   f"Draft invitation email to {to_addr or 'attendees'}: {subject}",
                   {
                       "to": to_addr or "",
                       "subject": subject,
                       "body": f"Hi,\n\nYou are invited to: {summary}\n\nPlease confirm your attendance.",
                   }),
    ]


# ─── Workflow Pattern Registry ────────────────────────────────────────────────

_WORKFLOW_PATTERNS: List[Tuple[re.Pattern, Any]] = [

    # ── Workflow 5: Calendar + email invite ───────────────────────────────
    # Must appear BEFORE generic "schedule" patterns
    (re.compile(
        r"(?:create|schedule|add|set\s+up|book)\s+(?:a\s+)?(?:meeting|event|appointment|call|standup|stand-?up)"
        r".*(?:and|then|also)\s+(?:send|draft|email|invite)",
        re.I,
    ), _build_calendar_and_email_invite),

    (re.compile(
        r"(?:schedule|book|create)\s+.+(?:meeting|event|standup|stand-?up)"
        r"\s+and\s+(?:send|draft|email)\s+(?:an?\s+)?(?:invite|invitation|email)",
        re.I,
    ), _build_calendar_and_email_invite),

    (re.compile(
        r"(?:invite|send\s+(?:an?\s+)?invite|send\s+(?:an?\s+)?invitation)"
        r".+(?:calendar|meeting|event)",
        re.I,
    ), _build_calendar_and_email_invite),

    # ── Workflow 1: Drive → summarize → email ─────────────────────────────
    (re.compile(
        r"(?:find|get|search|look\s+for).+(?:drive|google\s+drive)"
        r".+(?:and|then)\s+(?:email|draft|send|summarize|summarise)",
        re.I,
    ), _build_drive_summarize_email),

    (re.compile(
        r"(?:summarize|summarise|summarize\s+and\s+email|email\s+summary\s+of)"
        r".+(?:drive|google\s+drive)",
        re.I,
    ), _build_drive_summarize_email),

    (re.compile(
        r"(?:find|get).+drive.+(?:send|email|draft).+(?:to|for)\s+\S+@\S+",
        re.I,
    ), _build_drive_summarize_email),

    # ── Workflow 2: Research → present → open ─────────────────────────────
    (re.compile(
        r"(?:research|find|look\s+up).+"
        r"(?:and|then).+(?:presentation|slides|deck)"
        r".+(?:and|then).+(?:open|show|launch|display)",
        re.I,
    ), _build_research_present_open),

    (re.compile(
        r"(?:research|find|look\s+up).+"
        r"(?:present|presentation|slides)"
        r".*(?:then\s+)?(?:open\s+(?:it|the\s+file)|launch\s+it)",
        re.I,
    ), _build_research_present_open),

    # ── Workflow 3: Builder → scaffold → open in editor ───────────────────
    (re.compile(
        r"(?:create|scaffold|build|generate|set\s+up)\s+(?:a\s+)?(?:new\s+)?"
        r"(?:react|next\.?js|nextjs|fastapi|express|node|expo|react\s*native|"
        r"python|django|flask|html|vite)\s+"
        r"(?:app|project|application|api|site)"
        r".+(?:and|then).+(?:open|launch|start|show).+(?:vs\s*code|vscode|code|editor)",
        re.I,
    ), _build_scaffold_open_editor),

    (re.compile(
        r"(?:scaffold|create|build)\s+(?:a\s+)?(?:new\s+)?project\b"
        r".+(?:and|then).+(?:open|launch|code|editor)",
        re.I,
    ), _build_scaffold_open_editor),

    # ── Workflow 4: Local docs → summarize → presentation → save ─────────
    (re.compile(
        r"(?:read|load|open)\s+(?:my\s+)?(?:local\s+)?"
        r"(?:document|doc|file|pdf|report|notes?)"
        r".+(?:and|then)\s+(?:summar|present|slides)",
        re.I,
    ), _build_docs_summarize_present_save),

    (re.compile(
        r"summar(?:ize|ise)\s+(?:my\s+)?(?:local\s+)?(?:document|doc|file|pdf|report)"
        r".+(?:and|then|,)\s+(?:create|make|generate)\s+(?:a\s+)?(?:presentation|slides)",
        re.I,
    ), _build_docs_summarize_present_save),
]


# ─── Public API ───────────────────────────────────────────────────────────────

def plan_workflow(command: str) -> ExecutionPlan:
    """
    Try to match *command* against workflow patterns first, then fall back
    to the base task_planner.

    Priority:
      1. User-defined custom workflows (loaded from DB on each call)
      2. Built-in workflow patterns
      3. Base task_planner (single-tool + composite)

    Always returns a valid ExecutionPlan – never None.
    """
    cmd = command.strip()
    cmd_lower = cmd.lower()

    # 1. Check user-defined custom workflows (from DB)
    custom_plan = _match_custom_workflow(cmd_lower, cmd)
    if custom_plan is not None:
        return custom_plan

    # 2. Try dedicated workflow patterns (multi-subsystem)
    for pattern, builder in _WORKFLOW_PATTERNS:
        match = pattern.search(cmd)
        if match:
            steps = builder(match, cmd)
            if steps:
                return ExecutionPlan(goal=cmd, steps=steps, is_multi_step=True)

    # 3. Fall back to existing task_planner (covers single-tool + simpler composites)
    return plan_command(cmd)


def _match_custom_workflow(cmd_lower: str, original_cmd: str) -> Optional[ExecutionPlan]:
    """
    Load active custom workflows from DB (synchronously via a thread pool)
    and return the first one whose trigger phrase matches the command.
    Returns None if no match or DB is unavailable.
    """
    import asyncio
    import concurrent.futures

    async def _load() -> list:
        try:
            from app.core.database import AsyncSessionLocal
            from app.services import memory_service
            async with AsyncSessionLocal() as db:
                return await memory_service.get_all(db, category="custom_workflows", status="active")
        except Exception:
            return []

    try:
        # If we are already inside an event loop (FastAPI), run in executor
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Use a new thread with its own event loop
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(lambda: asyncio.run(_load()))
                entries = future.result(timeout=2)
        else:
            entries = loop.run_until_complete(_load())
    except Exception:
        return None

    for entry in entries:
        v = entry.value
        trigger_phrases = v.get("trigger_phrases", [])
        for phrase in trigger_phrases:
            if str(phrase).lower() in cmd_lower:
                # Build ExecutionPlan from stored steps
                raw_steps = v.get("steps", [])
                plan_steps = [
                    PlanStep(
                        index=s.get("index", i),
                        tool=s["tool"],
                        description=s.get("description", f"Run {s['tool']}"),
                        args=s.get("args", {}),
                        requires_approval=False,
                    )
                    for i, s in enumerate(raw_steps)
                    if s.get("tool")
                ]
                if plan_steps:
                    return ExecutionPlan(
                        goal=original_cmd,
                        steps=plan_steps,
                        is_multi_step=len(plan_steps) > 1,
                    )
    return None
