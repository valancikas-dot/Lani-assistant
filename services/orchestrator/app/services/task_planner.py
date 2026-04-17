"""
Task Planner – converts a natural-language command into an ordered ExecutionPlan.

Design
──────
The planner is intentionally *rule-based* so it is:
  • deterministic (same input → same plan, always)
  • zero-latency (no LLM round-trip required)
  • easy to test

Upgrade path
────────────
Replace ``plan_command()`` with an LLM-powered version when an API key is
available.  The ``ExecutionPlan`` schema is the stable contract between the
planner and the executor – the executor doesn't care how the plan was produced.

Multi-step detection
────────────────────
The planner first checks if the command matches any *composite* pattern
(phrases that imply more than one tool).  If it does, it returns a multi-step
plan.  Otherwise it delegates to the single-step fast path which wraps the
existing _classify_intent() logic into a one-step plan.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.schemas.plan import ExecutionPlan, PlanStep
from app.tools.registry import get_tool


# ─── Helper ───────────────────────────────────────────────────────────────────

def _make_step(
    index: int,
    tool: str,
    description: str,
    args: Dict[str, Any] | None = None,
) -> PlanStep:
    """Build a PlanStep, auto-filling requires_approval from the registry."""
    t = get_tool(tool)
    return PlanStep(
        index=index,
        tool=tool,
        description=description,
        args=args or {},
        requires_approval=t.requires_approval if t else False,
    )


# ─── Composite pattern matchers ───────────────────────────────────────────────
# Each entry is (pattern, builder) where builder(match, cmd) → List[PlanStep]

def _build_sort_summarize_present(m: re.Match, cmd: str) -> List[PlanStep]:
    """sort downloads  →  summarize PDFs  →  create presentation"""
    dl_path = "~/Downloads"
    title = "Summary Presentation"
    # try to extract a custom title from "create a presentation called X"
    t = re.search(r"presentation\s+(?:called\s+|titled\s+|named\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if t:
        title = t.group(1).strip()
    return [
        _make_step(0, "sort_downloads",       "Sort Downloads folder",                 {"base_path": dl_path}),
        _make_step(1, "summarize_document",    "Summarize discovered documents",        {}),
        _make_step(2, "create_presentation",   f"Create presentation: {title}",         {
            "title": title,
            "outline": ["Overview", "Key Findings", "Next Steps"],
            "output_path": f"~/Desktop/{title}.pptx",
        }),
    ]


def _build_sort_and_summarize(m: re.Match, cmd: str) -> List[PlanStep]:
    """sort downloads  →  summarize PDFs"""
    dl_path = "~/Downloads"
    return [
        _make_step(0, "sort_downloads",    "Sort Downloads folder",          {"base_path": dl_path}),
        _make_step(1, "summarize_document", "Summarize discovered documents", {}),
    ]


def _build_read_and_summarize(m: re.Match, cmd: str) -> List[PlanStep]:
    """read document  →  summarize it"""
    path = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
    steps = []
    if path:
        steps.append(_make_step(0, "read_document",     f"Read {path}",     {"path": path}))
        steps.append(_make_step(1, "summarize_document", f"Summarize {path}", {"path": path}))
    else:
        steps.append(_make_step(0, "read_document",     "Read document",    {}))
        steps.append(_make_step(1, "summarize_document", "Summarize document", {}))
    return steps


def _build_summarize_and_present(m: re.Match, cmd: str) -> List[PlanStep]:
    """summarize document  →  create presentation"""
    path = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
    title_m = re.search(r"presentation\s+(?:called\s+|titled\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    title = title_m.group(1).strip() if title_m else "Summary Presentation"
    steps = []
    if path:
        steps.append(_make_step(0, "summarize_document", f"Summarize {path}", {"path": path}))
    else:
        steps.append(_make_step(0, "summarize_document", "Summarize document", {}))
    steps.append(_make_step(1, "create_presentation", f"Create presentation: {title}", {
        "title": title,
        "outline": ["Introduction", "Key Points", "Conclusion"],
        "output_path": f"~/Desktop/{title}.pptx",
    }))
    return steps


def _build_create_folder_and_file(m: re.Match, cmd: str) -> List[PlanStep]:
    """create folder  →  create file inside it"""
    folder = m.group(1).strip()
    file_m = re.search(r"(?:and|then)\s+(?:a\s+)?file\s+['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    file_path = file_m.group(1).strip() if file_m else f"{folder}/new_file.txt"
    return [
        _make_step(0, "create_folder", f"Create folder {folder}", {"path": folder}),
        _make_step(1, "create_file",   f"Create file {file_path}", {"path": file_path, "content": ""}),
    ]


# ─── Research composite builders ─────────────────────────────────────────────

def _extract_research_query(cmd: str) -> str:
    """Pull the topic/query from a research command string."""
    # "research X", "find information about X", "compare X"
    for pat in [
        r"research\s+(?:the\s+)?(?:best\s+)?(.+?)(?:\s+and\s+|\s*$)",
        r"find\s+(?:information\s+about|info\s+on|sources\s+(?:on|about))\s+(.+?)(?:\s+and\s+|\s*$)",
        r"compare\s+(?:top\s+)?(?:tools\s+for\s+|options\s+for\s+)?(.+?)(?:\s+and\s+|\s*$)",
        r"look\s+up\s+(.+?)(?:\s+and\s+|\s*$)",
        r"summarize\s+(?:findings\s+on\s+|results\s+(?:on|about)\s+)?(.+?)(?:\s+and\s+|\s*$)",
    ]:
        m = re.search(pat, cmd, re.I)
        if m:
            return m.group(1).strip()
    # Fallback: use everything after the first verb
    parts = re.split(r"\b(?:research|find|compare|search|look up|summarize)\b", cmd, maxsplit=1, flags=re.I)
    return parts[-1].strip() if len(parts) > 1 else cmd.strip()


def _build_research_only(m: re.Match, cmd: str) -> List[PlanStep]:
    """search  →  summarize"""
    query = _extract_research_query(cmd)
    return [
        _make_step(0, "web_search", f"Search: {query}", {"query": query, "max_results": 8}),
        _make_step(1, "summarize_web_results", f"Summarize results for: {query}", {
            "query": query,
            "urls": [],          # executor fills this from previous step output
            "max_sources": 5,
        }),
    ]


def _build_research_and_compare(m: re.Match, cmd: str) -> List[PlanStep]:
    """search  →  summarize  →  compare"""
    query = _extract_research_query(cmd)
    return [
        _make_step(0, "web_search", f"Search: {query}", {"query": query, "max_results": 8}),
        _make_step(1, "summarize_web_results", f"Summarize results for: {query}", {
            "query": query,
            "urls": [],
            "max_sources": 5,
        }),
        _make_step(2, "compare_research_results", f"Compare results for: {query}", {
            "topic": query,
            "urls": [],
            "max_sources": 5,
        }),
    ]


def _build_research_and_present(m: re.Match, cmd: str) -> List[PlanStep]:
    """search  →  summarize  →  compare  →  create presentation"""
    query = _extract_research_query(cmd)
    title = f"Research: {query}"
    title_m = re.search(r"presentation\s+(?:called\s+|titled\s+|named\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if title_m:
        title = title_m.group(1).strip()
    return [
        _make_step(0, "web_search", f"Search: {query}", {"query": query, "max_results": 8}),
        _make_step(1, "summarize_web_results", f"Summarize results for: {query}", {
            "query": query,
            "urls": [],
            "max_sources": 5,
        }),
        _make_step(2, "compare_research_results", f"Compare results for: {query}", {
            "topic": query,
            "urls": [],
            "max_sources": 5,
        }),
        _make_step(3, "create_presentation", f"Create presentation: {title}", {
            "title": title,
            "outline": ["Overview", "Key Findings", "Comparison", "Conclusion"],
            "output_path": f"~/Desktop/{title}.pptx",
        }),
    ]


def _build_brief_and_present(m: re.Match, cmd: str) -> List[PlanStep]:
    """research_brief (all-in-one)  →  create presentation"""
    query = _extract_research_query(cmd)
    title = f"Research: {query}"
    return [
        _make_step(0, "research_and_prepare_brief", f"Research brief: {query}", {
            "query": query,
            "max_sources": 5,
            "include_comparison": True,
        }),
        _make_step(1, "create_presentation", f"Create presentation: {title}", {
            "title": title,
            "outline": ["Overview", "Key Findings", "Sources"],
            "output_path": f"~/Desktop/{title}.pptx",
        }),
    ]


# ─── Builder composite builders ───────────────────────────────────────────────

_TEMPLATE_MAP = {
    "react": "react-ts",
    "react-ts": "react-ts",
    "next": "nextjs",
    "nextjs": "nextjs",
    "next.js": "nextjs",
    "fastapi": "fastapi",
    "python": "fastapi",
    "django": "fastapi",
    "flask": "fastapi",
    "express": "node-express",
    "node": "node-express",
    "node-express": "node-express",
    "expo": "mobile-expo",
    "mobile": "mobile-expo",
    "react native": "mobile-expo",
    "html": "static-html",
    "static": "static-html",
    "landing": "static-html",
    "script": "python-script",
}


def _detect_template(cmd: str) -> str:
    cmd_lower = cmd.lower()
    for key, tpl in _TEMPLATE_MAP.items():
        if key in cmd_lower:
            return tpl
    return "generic"


def _detect_project_name(cmd: str) -> str:
    for pat in [
        r"(?:called?|named?|for)\s+['\"]?([A-Za-z0-9_\- ]+?)['\"]?(?:\s|$)",
        r"(?:project|app|application|api|site|backend)\s+['\"]([A-Za-z0-9_\- ]+?)['\"]",
    ]:
        m = re.search(pat, cmd, re.I)
        if m:
            return m.group(1).strip().replace(" ", "-").lower()
    return "my-project"


def _build_scaffold_project(m: re.Match, cmd: str) -> List[PlanStep]:
    """scaffold → readme → propose commands  (multi-step builder task)"""
    template = _detect_template(cmd)
    name = _detect_project_name(cmd)
    return [
        _make_step(0, "create_project_scaffold", f"Scaffold {template} project '{name}'", {
            "name": name,
            "template": template,
            "base_dir": "~/Desktop",
        }),
        _make_step(1, "create_readme", f"Generate README for '{name}'", {
            "project_name": name,
            "template": template,
        }),
        _make_step(2, "propose_terminal_commands", f"Propose setup commands for {template}", {
            "template": template,
        }),
    ]


def _build_add_feature(m: re.Match, cmd: str) -> List[PlanStep]:
    """generate feature files for an existing project"""
    template = _detect_template(cmd)
    feature = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else "new-feature"
    return [
        _make_step(0, "generate_feature_files", f"Generate files for feature '{feature}'", {
            "feature_description": feature,
            "template": template,
        }),
    ]


# ─── Connector composite builders ────────────────────────────────────────────

def _extract_drive_query(cmd: str) -> str:
    for pat in [
        r"(?:find|search|look\s+for|locate)\s+(.+?)\s+(?:in|on|from)\s+(?:my\s+)?(?:google\s+)?drive",
        r"(?:find|search|look\s+for|locate)\s+(.+?)\s*$",
        r"drive\s+(?:for|query)\s+(.+?)\s*$",
    ]:
        m = re.search(pat, cmd, re.I)
        if m:
            return m.group(1).strip()
    return cmd.strip()


def _extract_email_subject(cmd: str) -> str:
    for pat in [
        r"(?:about|regarding|re:?|subject:?)\s+['\"]?(.+?)['\"]?(?:\s+to\s+|\s*$)",
        r"email\s+(?:about|on)\s+['\"]?(.+?)['\"]?\s*$",
    ]:
        m = re.search(pat, cmd, re.I)
        if m:
            return m.group(1).strip()
    return "Draft"


def _extract_email_to(cmd: str) -> str:
    m = re.search(r"\bto\s+([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", cmd, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\bto\s+([A-Za-z][A-Za-z\s]+?)(?:\s+about|\s+regarding|\s*$)", cmd, re.I)
    if m:
        return m.group(1).strip()
    return ""


def _extract_event_summary(cmd: str) -> str:
    for pat in [
        r"(?:create|schedule|add|set\s+up)\s+(?:a\s+)?(?:meeting|event|appointment|call|invite)\s+"
        r"(?:called?|named?|titled?|about)\s+['\"]?(.+?)['\"]?(?:\s+(?:on|at|for|tomorrow|next)\b|\s*$)",
        r"(?:create|schedule|add|set\s+up)\s+(?:a\s+)?(.+?)\s+(?:meeting|event|appointment|call)",
    ]:
        m = re.search(pat, cmd, re.I)
        if m:
            return m.group(1).strip()
    return "Meeting"


def _build_drive_search(m: re.Match, cmd: str) -> List[PlanStep]:
    """Drive search → single step."""
    query = _extract_drive_query(cmd)
    return [
        _make_step(0, "drive_search_files", f"Search Drive for: {query}", {
            "query": query,
            "page_size": 10,
        }),
    ]


def _build_drive_list(m: re.Match, cmd: str) -> List[PlanStep]:
    """List recent Drive files → single step."""
    return [
        _make_step(0, "drive_list_files", "List recent Google Drive files", {
            "page_size": 10,
        }),
    ]


def _build_gmail_list(m: re.Match, cmd: str) -> List[PlanStep]:
    """List recent inbox messages → single step."""
    return [
        _make_step(0, "gmail_list_recent", "List recent Gmail messages", {
            "max_results": 10,
            "label_ids": ["INBOX"],
        }),
    ]


def _build_gmail_draft(m: re.Match, cmd: str) -> List[PlanStep]:
    """Draft an email (approval-gated)."""
    subject = _extract_email_subject(cmd)
    to = _extract_email_to(cmd)
    return [
        _make_step(0, "gmail_create_draft", f"Create Gmail draft: {subject}", {
            "to": to,
            "subject": subject,
            "body": "",
        }),
    ]


def _build_gmail_send(m: re.Match, cmd: str) -> List[PlanStep]:
    """Draft then send an email (both approval-gated)."""
    subject = _extract_email_subject(cmd)
    to = _extract_email_to(cmd)
    return [
        _make_step(0, "gmail_create_draft", f"Create Gmail draft: {subject}", {
            "to": to,
            "subject": subject,
            "body": "",
        }),
        _make_step(1, "gmail_send_email", f"Send email: {subject}", {
            "to": to,
            "subject": subject,
            "body": "",
        }),
    ]


def _build_calendar_list(m: re.Match, cmd: str) -> List[PlanStep]:
    """List upcoming calendar events → single step."""
    return [
        _make_step(0, "calendar_list_events", "List upcoming calendar events", {
            "max_results": 10,
        }),
    ]


def _build_calendar_create(m: re.Match, cmd: str) -> List[PlanStep]:
    """Create a calendar event (approval-gated)."""
    summary = _extract_event_summary(cmd)
    return [
        _make_step(0, "calendar_create_event", f"Create calendar event: {summary}", {
            "summary": summary,
            "start": "",   # frontend / LLM fills in ISO datetime
            "end": "",
        }),
    ]


# ─── Operator composite builders ──────────────────────────────────────────────

def _build_open_app(m: re.Match, cmd: str) -> List[PlanStep]:
    app_name = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else cmd

    # Jei app_name yra žinoma web paslauga arba turi "my X" formą → safari_open
    _WEB_SERVICES = {
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "twitter": "https://twitter.com",
        "x.com": "https://x.com",
        "tiktok": "https://www.tiktok.com",
        "youtube": "https://www.youtube.com",
        "linkedin": "https://www.linkedin.com",
        "reddit": "https://www.reddit.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "google drive": "https://drive.google.com",
        "github": "https://github.com",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.com",
        "chatgpt": "https://chatgpt.com",
        "snapchat": "https://www.snapchat.com",
        "pinterest": "https://www.pinterest.com",
        "outlook": "https://outlook.live.com",
        "twitch": "https://www.twitch.tv",
        "spotify": None,  # native app, ne web
    }
    # Pašaliname "my " prefiksą
    import re as _re
    name_clean = _re.sub(r"^my\s+", "", app_name, flags=_re.I).strip().lower()
    if name_clean in _WEB_SERVICES and _WEB_SERVICES[name_clean] is not None:
        url = _WEB_SERVICES[name_clean]
        return [_make_step(0, "safari_open", f"Open {app_name} in Safari", {"url": url})]

    return [
        _make_step(0, "operator.open_app", f"Open {app_name}", {"app_name": app_name}),
    ]


def _build_focus_window(m: re.Match, cmd: str) -> List[PlanStep]:
    app_name = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else cmd
    return [
        _make_step(0, "operator.focus_window", f"Focus {app_name}", {"window_title": app_name}),
    ]


def _build_screenshot(m: re.Match, cmd: str) -> List[PlanStep]:
    return [
        _make_step(0, "operator.take_screenshot", "Take screenshot", {}),
    ]


def _build_list_windows(m: re.Match, cmd: str) -> List[PlanStep]:
    return [
        _make_step(0, "operator.list_open_windows", "List open windows", {}),
    ]


def _build_copy_clipboard(m: re.Match, cmd: str) -> List[PlanStep]:
    # Extract text between 'copy' and 'to clipboard' if present.
    text_m = re.search(r"copy\s+['\"]?(.+?)['\"]?\s+to\s+(?:the\s+)?clipboard", cmd, re.I)
    text = text_m.group(1).strip() if text_m else ""
    return [
        _make_step(0, "operator.copy_to_clipboard", "Copy text to clipboard", {"text": text}),
    ]


def _build_open_path(m: re.Match, cmd: str) -> List[PlanStep]:
    # Try to extract a specific folder name.
    folder_m = re.search(r"(?:open|show|reveal)\s+(?:my\s+)?(?:the\s+)?([A-Za-z~/][^\s]*)", cmd, re.I)
    path = folder_m.group(1) if folder_m else "~"
    return [
        _make_step(0, "operator.open_path", f"Open path: {path}", {"path": path}),
    ]


def _build_press_shortcut(m: re.Match, cmd: str) -> List[PlanStep]:
    keys_raw = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
    keys = [k.strip() for k in re.split(r"[+\-,]", keys_raw) if k.strip()]
    return [
        _make_step(0, "operator.press_shortcut", f"Press shortcut: {'+'.join(keys)}", {"keys": keys}),
    ]


# Registry of composite patterns → builder functions
# Patterns are checked in order; first match wins.
_COMPOSITE_PATTERNS: List[Tuple[re.Pattern, Any]] = [
    # ── Computer Operator ─────────────────────────────────────────────────

    # "take/capture/grab a screenshot"
    (re.compile(r"(?:take|capture|grab)\s+(?:a\s+)?screenshot", re.I), _build_screenshot),

    # "list/show/what are the open windows"
    (re.compile(
        r"(?:list|show|what(?:'s|\s+are|\s+is))\s+(?:all\s+)?(?:the\s+)?(?:open\s+)?windows?",
        re.I,
    ), _build_list_windows),

    # "open/launch/start Chrome/Safari/VS Code/etc."
    (re.compile(
        r"(?:open|launch|start)\s+(?:up\s+)?([A-Za-z][A-Za-z0-9\s.\-]+?)(?:\s+app(?:lication)?)?(?:\s*$|\s+and\b)",
        re.I,
    ), _build_open_app),

    # "focus/switch to/bring up Chrome/Firefox/VS Code"
    (re.compile(
        r"(?:focus|switch\s+to|bring\s+up)\s+([A-Za-z][A-Za-z0-9\s.\-]+?)(?:\s*$|\s+and\b)",
        re.I,
    ), _build_focus_window),

    # "copy X to clipboard"
    (re.compile(r"copy\s+.+\s+to\s+(?:the\s+)?clipboard", re.I), _build_copy_clipboard),

    # "open my Downloads/Desktop/Documents" or "open ~/path"
    (re.compile(
        r"(?:open|show|reveal)\s+(?:my\s+)?(?:the\s+)?(?:downloads|desktop|documents|folder|~/)",
        re.I,
    ), _build_open_path),

    # "press Command+Shift+4" / "press Cmd+C" / "press ctrl+z"
    (re.compile(
        r"press\s+(?:the\s+)?(?:shortcut\s+)?([A-Za-z][A-Za-z0-9\+\-]+)",
        re.I,
    ), _build_press_shortcut),

    # ── Connector: Google Drive ────────────────────────────────────────────

    # "find X in my drive" / "search drive for X" / "look for X on drive"
    (re.compile(
        r"(?:find|search|look\s+for|locate)\s+.+(?:in|on|from)\s+(?:my\s+)?(?:google\s+)?drive",
        re.I,
    ), _build_drive_search),

    # "search drive for X" / "drive search"
    (re.compile(
        r"(?:drive\s+(?:search|find|query)|search\s+(?:my\s+)?(?:google\s+)?drive)",
        re.I,
    ), _build_drive_search),

    # "list/show my drive files" / "what's in my drive"
    (re.compile(
        r"(?:list|show|display|what.+in)\s+(?:my\s+)?(?:google\s+)?drive\s+(?:files|documents|docs)?",
        re.I,
    ), _build_drive_list),

    # ── Connector: Gmail ──────────────────────────────────────────────────

    # "send an email to X" / "send email about Y"
    (re.compile(
        r"(?:send|email)\s+(?:an?\s+)?(?:email|mail|message)\s+(?:to|about)\b",
        re.I,
    ), _build_gmail_send),

    # "draft/write an email to X about Y"
    (re.compile(
        r"(?:draft|write|compose|prepare)\s+(?:an?\s+)?(?:email|mail|message)",
        re.I,
    ), _build_gmail_draft),

    # "check my email" / "list my inbox" / "show recent emails"
    (re.compile(
        r"(?:check|list|show|read|view)\s+(?:my\s+)?(?:email|inbox|gmail|mail)",
        re.I,
    ), _build_gmail_list),

    # ── Connector: Google Calendar ────────────────────────────────────────

    # "create/schedule/add a meeting/event/appointment"
    (re.compile(
        r"(?:create|schedule|add|set\s+up|book)\s+(?:a\s+)?(?:new\s+)?"
        r"(?:meeting|event|appointment|call|calendar\s+invite)",
        re.I,
    ), _build_calendar_create),

    # "check/list/show my calendar/events"
    (re.compile(
        r"(?:check|list|show|view|display)\s+(?:my\s+)?(?:calendar|events?|schedule|agenda)",
        re.I,
    ), _build_calendar_list),

    # ── Research patterns (checked before generic sort/summarize) ──────────

    # "research/find … and (make/create) a presentation"
    (re.compile(
        r"(?:research|find|look up|compare).+(?:and|then).+(?:present|presentation|slides|deck)",
        re.I,
    ), _build_research_and_present),

    # "research/find … and compare"
    (re.compile(
        r"(?:research|find|look up).+(?:and|then).+compar",
        re.I,
    ), _build_research_and_compare),

    # "compare top tools/options for …" (implicitly: search + compare)
    (re.compile(
        r"compare\s+(?:top\s+|best\s+)?(?:tools|options|products|services|solutions)\s+(?:for|on|about)",
        re.I,
    ), _build_research_and_compare),

    # "research X" / "find information about X" / "find sources …"
    (re.compile(
        r"(?:research|find\s+(?:information|info|sources)|look\s+up)\s+\w",
        re.I,
    ), _build_research_only),

    # ── Builder patterns ──────────────────────────────────────────────────

    # "create/scaffold/build/generate/set up a (new) React/Next/FastAPI/etc. project/app"
    (re.compile(
        r"(?:create|scaffold|build|generate|set\s+up|initialise|initialize)\s+(?:a\s+)?(?:new\s+)?"
        r"(?:react|next\.?js|nextjs|fastapi|express|node|expo|mobile|react\s*native|"
        r"python|django|flask|html|static|landing|vite)\s+"
        r"(?:app|project|application|backend|api|site|page|landing\s+page)",
        re.I,
    ), _build_scaffold_project),

    # "create a new project called X" / "scaffold a project named Y"
    (re.compile(
        r"(?:create|scaffold|build|generate|set\s+up)\s+(?:a\s+)?(?:new\s+)?project\b",
        re.I,
    ), _build_scaffold_project),

    # "add/generate a (new) feature/component/page X to/for …"
    (re.compile(
        r"(?:add|generate|create)\s+(?:a\s+)?(?:new\s+)?(?:feature|component|page|route|endpoint)\s+"
        r"['\"]?([A-Za-z0-9_\- ]+?)['\"]?\s+(?:to|for|in)\b",
        re.I,
    ), _build_add_feature),

    # ── Existing patterns ─────────────────────────────────────────────────

    # "sort … summarize … present/presentation"
    (re.compile(
        r"sort.+(?:summar|summarize|summarise).+(?:present|presentation|slides)",
        re.I,
    ), _build_sort_summarize_present),

    # "sort … and summarize" (without presentation)
    (re.compile(
        r"sort.+(?:and|then|,).+(?:summar|summarize|summarise)",
        re.I,
    ), _build_sort_and_summarize),

    # "summarize … and create a presentation"
    (re.compile(
        r"summar(?:ize|ise)\s+['\"]?(.+?)['\"]?\s+(?:and|then).*(?:present|presentation|slides)",
        re.I,
    ), _build_summarize_and_present),

    # "read … and summarize"
    (re.compile(
        r"read\s+(?:and\s+)?['\"]?(.+?)['\"]?\s+(?:and|then).*summar",
        re.I,
    ), _build_read_and_summarize),

    # "create folder … and (a) file"
    (re.compile(
        r"create\s+(?:a\s+)?folder\s+['\"]?(.+?)['\"]?\s+(?:and|then)",
        re.I,
    ), _build_create_folder_and_file),
]


# ─── Single-step fall-through ─────────────────────────────────────────────────

def _single_step_plan(command: str) -> ExecutionPlan | None:
    """
    Try to build a one-step plan using the same patterns as command_router.

    Returns None when the command is completely unrecognised.
    """
    # Import here to avoid circular dep (command_router imports task_planner)
    from app.services.command_router import _classify_with_regex  # type: ignore[import]

    tool_name, params = _classify_with_regex(command)
    if tool_name == "unknown":
        return None

    step = _make_step(0, tool_name, f"Run {tool_name}", params)
    return ExecutionPlan(
        goal=command,
        steps=[step],
        is_multi_step=False,
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def plan_command(command: str) -> ExecutionPlan:
    """
    Analyse *command* and return an ExecutionPlan.

    The planner first checks composite (multi-step) patterns, then falls
    back to single-step classification, and finally to a chat step so that
    *every* command always produces a valid plan (never returns None).

    Swapping in an LLM
    ──────────────────
    Replace this function body with::

        async def plan_command(command: str) -> ExecutionPlan:
            steps_json = await llm_planner.plan(command, tools=list_tools())
            return ExecutionPlan(goal=command, steps=steps_json, is_multi_step=True)

    The rest of the system (executor, route, frontend) remains unchanged.
    """
    cmd = command.strip()

    # 1. Try composite patterns first
    for pattern, builder in _COMPOSITE_PATTERNS:
        m = pattern.search(cmd)
        if m:
            steps = builder(m, cmd)
            if steps:
                return ExecutionPlan(goal=cmd, steps=steps, is_multi_step=True)

    # 2. Fall back to single-step classification
    single = _single_step_plan(cmd)
    if single is not None:
        return single

    # 3. Ultimate fallback: route to chat so no command is ever left unanswered
    chat_step = _make_step(0, "chat", "Answer via conversational AI", {"message": cmd})
    return ExecutionPlan(goal=cmd, steps=[chat_step], is_multi_step=False)
