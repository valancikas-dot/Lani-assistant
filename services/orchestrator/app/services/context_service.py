"""
Context Service – tracks the current session's "working objects" so the user
can refer to them implicitly: "tą patį", "šį failą", "tą URL", etc.

What is tracked (per session):
  - last_file      : most recent file path mentioned or created
  - last_url       : most recent URL fetched/researched
  - last_command   : the previous user command
  - last_result    : last tool result message
  - last_tool      : which tool ran last
  - entities       : dict of named objects {"jonas_email": "jonas@email.com", ...}

Public API
──────────
  update_context(session_id, **kwargs)          – update after each command
  get_context(session_id)                       → SessionContext
  resolve_references(command, session_id)       → str  (command with refs resolved)
  clear_context(session_id)                     – reset session
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# In-memory store (session_id → SessionContext)
# TTL-style: contexts are cleared on server restart (acceptable for a local app)
_CONTEXTS: Dict[str, "SessionContext"] = {}


@dataclass
class SessionContext:
    """Holds the current working state for one session."""
    session_id: str = "default"
    last_file: Optional[str] = None
    last_url: Optional[str] = None
    last_command: Optional[str] = None
    last_result: Optional[str] = None
    last_tool: Optional[str] = None
    last_topic: Optional[str] = None          # last research/search topic
    entities: Dict[str, str] = field(default_factory=dict)
    """Named entities: {"jonas_email": "jonas@example.com", …}"""


def get_context(session_id: str = "default") -> SessionContext:
    """Return the context for *session_id*, creating it if it doesn't exist."""
    if session_id not in _CONTEXTS:
        _CONTEXTS[session_id] = SessionContext(session_id=session_id)
    return _CONTEXTS[session_id]


def update_context(
    session_id: str = "default",
    *,
    last_file: Optional[str] = None,
    last_url: Optional[str] = None,
    last_command: Optional[str] = None,
    last_result: Optional[str] = None,
    last_tool: Optional[str] = None,
    last_topic: Optional[str] = None,
    entities: Optional[Dict[str, str]] = None,
) -> None:
    """Update tracked fields. None values are ignored (not overwritten)."""
    ctx = get_context(session_id)
    if last_file is not None:
        ctx.last_file = last_file
    if last_url is not None:
        ctx.last_url = last_url
    if last_command is not None:
        ctx.last_command = last_command
    if last_result is not None:
        ctx.last_result = last_result[:300]
    if last_tool is not None:
        ctx.last_tool = last_tool
    if last_topic is not None:
        ctx.last_topic = last_topic
    if entities:
        ctx.entities.update(entities)


def clear_context(session_id: str = "default") -> None:
    """Reset a session's context."""
    _CONTEXTS.pop(session_id, None)


# ── Reference resolution ──────────────────────────────────────────────────────

# Pronoun / deictic expressions to resolve
_FILE_REFS_LT = re.compile(
    r"\b(šį failą|tą failą|šitą failą|tą patį failą|tą dokumentą|šį dokumentą)\b",
    re.IGNORECASE,
)
_FILE_REFS_EN = re.compile(
    r"\b(this file|that file|the file|this document|that document|the same file)\b",
    re.IGNORECASE,
)
_URL_REFS_LT = re.compile(
    r"\b(šį URL|tą URL|šitą puslapį|tą puslapį|šį puslapį)\b",
    re.IGNORECASE,
)
_URL_REFS_EN = re.compile(
    r"\b(this URL|that URL|this page|that page|this link|the same URL)\b",
    re.IGNORECASE,
)
_REPEAT_REFS_LT = re.compile(
    r"\b(tą patį|pakartok|dar kartą|vėl|tą pačią komandą)\b",
    re.IGNORECASE,
)
_REPEAT_REFS_EN = re.compile(
    r"\b(the same|repeat|do it again|again|same command|same thing)\b",
    re.IGNORECASE,
)
_TOPIC_REFS_LT = re.compile(
    r"\b(tą temą|tą patį klausimą|ta tema|apie tai)\b",
    re.IGNORECASE,
)
_TOPIC_REFS_EN = re.compile(
    r"\b(that topic|the same topic|about this|on the same subject)\b",
    re.IGNORECASE,
)


def resolve_references(command: str, session_id: str = "default") -> str:
    """
    Replace implicit references in *command* with the actual tracked values.

    Example:
      last_file = "~/Desktop/report.pdf"
      command   = "atidaryk šį failą"
      result    = "atidaryk ~/Desktop/report.pdf"
    """
    ctx = get_context(session_id)
    result = command

    # File references
    if ctx.last_file:
        result = _FILE_REFS_LT.sub(ctx.last_file, result)
        result = _FILE_REFS_EN.sub(ctx.last_file, result)

    # URL references
    if ctx.last_url:
        result = _URL_REFS_LT.sub(ctx.last_url, result)
        result = _URL_REFS_EN.sub(ctx.last_url, result)

    # Repeat last command
    if ctx.last_command:
        result = _REPEAT_REFS_LT.sub(ctx.last_command, result)
        result = _REPEAT_REFS_EN.sub(ctx.last_command, result)

    # Topic references
    if ctx.last_topic:
        result = _TOPIC_REFS_LT.sub(ctx.last_topic, result)
        result = _TOPIC_REFS_EN.sub(ctx.last_topic, result)

    return result


def extract_context_from_result(
    tool_name: str,
    args: Dict[str, Any],
    result_msg: str,
    session_id: str = "default",
) -> None:
    """
    Called after every tool execution to harvest context clues.
    Extracts file paths, URLs, topics, etc. from tool args / results.
    """
    file_tools = {
        "create_file", "move_file", "delete_file", "open_file",
        "read_pdf", "read_docx", "sort_downloads",
    }
    url_tools = {"fetch_url", "web_search", "summarize_web_results", "research_deep"}
    topic_tools = {"web_search", "research_deep", "research_brief"}

    updates: Dict[str, Any] = {
        "last_tool": tool_name,
        "last_result": result_msg,
    }

    if tool_name in file_tools:
        for key in ("path", "source", "destination", "file_path"):
            if v := args.get(key):
                updates["last_file"] = str(v)
                break

    if tool_name in url_tools:
        for key in ("url", "urls"):
            v = args.get(key)
            if isinstance(v, list) and v:
                updates["last_url"] = v[0]
                break
            elif isinstance(v, str) and v:
                updates["last_url"] = v
                break

    if tool_name in topic_tools:
        for key in ("query", "topic", "q"):
            if v := args.get(key):
                updates["last_topic"] = str(v)
                break

    update_context(session_id, **updates)
