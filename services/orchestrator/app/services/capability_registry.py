"""
Capability Registry – single source of truth for every tool Lani can execute.

Each capability entry carries:
  • name / description
  • input_schema   – JSON-Schema dict of accepted parameters
  • risk_level     – "low" | "medium" | "high" | "critical"
  • requires_approval – must user confirm before execution?
  • allowed_accounts  – which connector accounts may be used ([] = any)
  • side_effects      – list of human-readable side-effects
  • retry_policy      – max_retries + backoff_seconds

The registry is built lazily at first access from the live tool registry
(app.tools.registry) so it stays in sync with newly registered plugins.

Public API
----------
  get_registry()                  → Dict[str, CapabilityMeta]
  get_capability(name)            → CapabilityMeta | None
  enrich_tool_meta(tool_meta)     → tool_meta dict + capability fields
  list_capabilities()             → list[dict]  (JSON-serialisable)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    max_retries: int = 0
    backoff_seconds: float = 1.0


@dataclass
class CapabilityMeta:
    name: str
    description: str
    risk_level: str                        # low | medium | high | critical
    requires_approval: bool = False
    allowed_accounts: List[str] = field(default_factory=list)  # [] = any
    side_effects: List[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ─── Static override table ────────────────────────────────────────────────────
# Tools listed here get explicit metadata.  Any tool NOT listed falls back to
# sensible defaults derived from its BaseTool attributes.

_STATIC_META: Dict[str, Dict[str, Any]] = {
    # ── File operations ──────────────────────────────────────────────────────
    "create_folder": {
        "risk_level": "low",
        "side_effects": ["creates directory on disk"],
        "retry_policy": RetryPolicy(max_retries=1, backoff_seconds=0.5),
        "category": "filesystem",
    },
    "create_file": {
        "risk_level": "low",
        "side_effects": ["writes file to disk"],
        "retry_policy": RetryPolicy(max_retries=1, backoff_seconds=0.5),
        "category": "filesystem",
    },
    "move_file": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["moves / renames file or directory on disk"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "filesystem",
    },
    "sort_downloads": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["moves multiple files in bulk"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "filesystem",
    },
    "search_files": {
        "risk_level": "low",
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "filesystem",
    },
    # ── Document tools ───────────────────────────────────────────────────────
    "read_document": {
        "risk_level": "low",
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "documents",
    },
    "summarize_document": {
        "risk_level": "low",
        "side_effects": ["calls external LLM API"],
        "retry_policy": RetryPolicy(max_retries=2, backoff_seconds=2.0),
        "category": "documents",
    },
    # ── Research ─────────────────────────────────────────────────────────────
    "web_search": {
        "risk_level": "low",
        "side_effects": ["outbound HTTP request"],
        "retry_policy": RetryPolicy(max_retries=2, backoff_seconds=1.0),
        "category": "research",
    },
    "summarize_web_results": {
        "risk_level": "low",
        "side_effects": ["calls external LLM API"],
        "retry_policy": RetryPolicy(max_retries=2, backoff_seconds=2.0),
        "category": "research",
    },
    "compare_research_results": {
        "risk_level": "low",
        "side_effects": ["calls external LLM API"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "research",
    },
    "research_and_prepare_brief": {
        "risk_level": "low",
        "side_effects": ["outbound HTTP + LLM API"],
        "retry_policy": RetryPolicy(max_retries=1, backoff_seconds=2.0),
        "category": "research",
    },
    # ── Presentations ────────────────────────────────────────────────────────
    "create_presentation": {
        "risk_level": "medium",
        "side_effects": ["writes .pptx file to disk", "calls external LLM API"],
        "retry_policy": RetryPolicy(max_retries=1, backoff_seconds=1.0),
        "category": "documents",
    },
    # ── Gmail ────────────────────────────────────────────────────────────────
    "gmail_list_recent": {
        "risk_level": "low",
        "allowed_accounts": ["gmail"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2, backoff_seconds=1.0),
        "category": "connectors",
    },
    "gmail_get_message": {
        "risk_level": "low",
        "allowed_accounts": ["gmail"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "connectors",
    },
    "gmail_create_draft": {
        "risk_level": "medium",
        "requires_approval": True,
        "allowed_accounts": ["gmail"],
        "side_effects": ["creates email draft in Gmail"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "connectors",
    },
    "gmail_send_email": {
        "risk_level": "critical",
        "requires_approval": True,
        "allowed_accounts": ["gmail"],
        "side_effects": ["sends email immediately"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "connectors",
    },
    # ── Google Drive ─────────────────────────────────────────────────────────
    "drive_list_files": {
        "risk_level": "low",
        "allowed_accounts": ["google_drive"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "connectors",
    },
    "drive_search_files": {
        "risk_level": "low",
        "allowed_accounts": ["google_drive"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "connectors",
    },
    "drive_get_file": {
        "risk_level": "low",
        "allowed_accounts": ["google_drive"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "connectors",
    },
    # ── Calendar ─────────────────────────────────────────────────────────────
    "calendar_list_events": {
        "risk_level": "low",
        "allowed_accounts": ["google_calendar"],
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "connectors",
    },
    "calendar_create_event": {
        "risk_level": "medium",
        "requires_approval": True,
        "allowed_accounts": ["google_calendar"],
        "side_effects": ["creates calendar event"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "connectors",
    },
    "calendar_delete_event": {
        "risk_level": "high",
        "requires_approval": True,
        "allowed_accounts": ["google_calendar"],
        "side_effects": ["deletes calendar event permanently"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "connectors",
    },
    # ── Operator (Desktop) ───────────────────────────────────────────────────
    "operator.list_open_windows": {
        "risk_level": "low",
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "operator",
    },
    "operator.open_app": {
        "risk_level": "low",
        "side_effects": ["opens/focuses an application"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "operator",
    },
    "operator.focus_window": {
        "risk_level": "low",
        "side_effects": ["brings window to foreground"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "operator",
    },
    "operator.type_text": {
        "risk_level": "medium",
        "requires_approval": True,
        "side_effects": ["types text into focused application"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "operator",
    },
    "operator.press_keys": {
        "risk_level": "medium",
        "requires_approval": True,
        "side_effects": ["presses keyboard shortcuts"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "operator",
    },
    "operator.take_screenshot": {
        "risk_level": "low",
        "side_effects": ["captures screen image"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "operator",
    },
    "operator.run_shortcut": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["executes macOS Shortcuts automation"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "operator",
    },
    # ── Browser ──────────────────────────────────────────────────────────────
    "browser_open": {
        "risk_level": "low",
        "side_effects": ["opens URL in browser"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "browser",
    },
    "browser_search": {
        "risk_level": "low",
        "side_effects": ["outbound HTTP"],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "browser",
    },
    "browser_read": {
        "risk_level": "low",
        "side_effects": ["outbound HTTP"],
        "retry_policy": RetryPolicy(max_retries=2),
        "category": "browser",
    },
    "browser_click": {
        "risk_level": "medium",
        "requires_approval": True,
        "side_effects": ["clicks element in browser"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "browser",
    },
    "browser_fill": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["fills form field in browser"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "browser",
    },
    # ── Builder ──────────────────────────────────────────────────────────────
    "create_project_scaffold": {
        "risk_level": "medium",
        "side_effects": ["writes multiple files and directories to disk"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "builder",
    },
    "create_code_file": {
        "risk_level": "medium",
        "side_effects": ["writes source file to disk"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "builder",
    },
    "update_code_file": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["overwrites existing source file"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "builder",
    },
    # ── Self-edit ────────────────────────────────────────────────────────────
    "edit_self": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["modifies Lani's own source code", "may require restart"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "self_edit",
    },
    "restart_backend": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["restarts the backend process"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "self_edit",
    },
    # ── Memory ───────────────────────────────────────────────────────────────
    "save_memory": {
        "risk_level": "low",
        "side_effects": ["persists data to SQLite"],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "memory",
    },
    "search_memory": {
        "risk_level": "low",
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "memory",
    },
    "list_memory": {
        "risk_level": "low",
        "side_effects": [],
        "retry_policy": RetryPolicy(max_retries=1),
        "category": "memory",
    },
    # ── Scheduler ────────────────────────────────────────────────────────────
    "schedule_task": {
        "risk_level": "medium",
        "requires_approval": True,
        "side_effects": ["schedules future automated action"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "scheduler",
    },
    # ── Shell / system ───────────────────────────────────────────────────────
    "run_shell_command": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["executes arbitrary shell command on host OS"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "system",
    },
    "run_python": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["executes arbitrary Python code"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "system",
    },
    "run_javascript": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["executes arbitrary JavaScript"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "system",
    },
    "install_package": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["installs software packages on host OS"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "system",
    },
    "empty_trash": {
        "risk_level": "critical",
        "requires_approval": True,
        "side_effects": ["permanently deletes all items in Trash"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "filesystem",
    },
    # ── Git ──────────────────────────────────────────────────────────────────
    "git_push": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["pushes commits to remote repository"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "git",
    },
    "git_commit": {
        "risk_level": "medium",
        "requires_approval": True,
        "side_effects": ["creates a new git commit"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "git",
    },
    "github_create_pr": {
        "risk_level": "high",
        "requires_approval": True,
        "side_effects": ["creates a pull request on GitHub"],
        "retry_policy": RetryPolicy(max_retries=0),
        "category": "git",
    },
}


# ─── Registry builder ─────────────────────────────────────────────────────────

_registry: Optional[Dict[str, CapabilityMeta]] = None


def _build_registry() -> Dict[str, CapabilityMeta]:
    """Build the registry from live tool list + static overrides."""
    from app.tools.registry import list_tools

    result: Dict[str, CapabilityMeta] = {}
    for tool_meta in list_tools():
        name: str = tool_meta["name"]
        desc: str = tool_meta.get("description", "")
        req_approval: bool = tool_meta.get("requires_approval", False)

        # Build input_schema from parameters list
        params = tool_meta.get("parameters", [])
        props: Dict[str, Any] = {}
        required: List[str] = []
        for p in params:
            props[p["name"]] = {
                "type": "string",
                "description": p.get("description", ""),
            }
            if p.get("required", False):
                required.append(p["name"])
        schema = {"type": "object", "properties": props, "required": required}

        overrides = _STATIC_META.get(name, {})
        retry = overrides.get("retry_policy", RetryPolicy())

        cap = CapabilityMeta(
            name=name,
            description=desc,
            risk_level=overrides.get("risk_level", "low"),
            requires_approval=overrides.get("requires_approval", req_approval),
            allowed_accounts=overrides.get("allowed_accounts", []),
            side_effects=overrides.get("side_effects", []),
            retry_policy=retry if isinstance(retry, RetryPolicy) else RetryPolicy(**retry),
            input_schema=schema,
            category=overrides.get("category", "general"),
        )
        result[name] = cap

    log.info("[capability_registry] loaded %d capabilities", len(result))
    return result


def get_registry() -> Dict[str, CapabilityMeta]:
    """Return (and lazily build) the global capability registry."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_capability(name: str) -> Optional[CapabilityMeta]:
    """Look up a single capability by tool name."""
    return get_registry().get(name)


def refresh_registry() -> None:
    """Force a rebuild of the registry (call after plugin hot-reload)."""
    global _registry
    _registry = None
    get_registry()


def list_capabilities() -> List[Dict[str, Any]]:
    """Return all capabilities as a list of JSON-serialisable dicts."""
    return [cap.to_dict() for cap in get_registry().values()]


def enrich_tool_meta(tool_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge capability metadata into a raw tool_meta dict from list_tools().

    Returns a new dict – original is not mutated.
    """
    cap = get_capability(tool_meta.get("name", ""))
    if cap is None:
        return tool_meta
    enriched = dict(tool_meta)
    enriched["risk_level"] = cap.risk_level
    enriched["allowed_accounts"] = cap.allowed_accounts
    enriched["side_effects"] = cap.side_effects
    enriched["retry_policy"] = asdict(cap.retry_policy)
    enriched["category"] = cap.category
    return enriched
