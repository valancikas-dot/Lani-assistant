"""Voice response shaper – adapts text for natural TTS playback.

Goals
─────
1. **Brevity** – Strip boilerplate phrases that look fine on screen but sound
   verbose when spoken ("I have successfully completed…" → "Done.").
2. **Clarity** – Remove markdown formatting, bullet points, code ticks.
3. **Confirmation prompts** – Produce short, natural confirmation questions
   for actions that require approval before execution.
4. **Localization** – Use the assistant language from settings when building
   confirmation copy (basic EN / LT support; falls back to EN).

This module intentionally has *no* external dependencies so it stays fast and
testable without an LLM call.  A real deployment can swap in an LLM-based
shaper by replacing the functions here.
"""

from __future__ import annotations

import re
from typing import Optional


# ─── Public API ───────────────────────────────────────────────────────────────

def shape_for_voice(
    text: str,
    max_chars: int = 300,
    language: str = "en",
) -> str:
    """Return a TTS-friendly version of *text*.

    Applies in order:
      1. Strip markdown (bold, italic, code, headers, bullets, links).
      2. Collapse whitespace and line breaks to single spaces.
      3. Apply brevity rewrites (verbose → terse English phrases).
      4. Truncate to *max_chars* at a sentence boundary where possible.

    Parameters
    ----------
    text:
        Raw text (may contain markdown).
    max_chars:
        Hard cap on output length.  Default 300 chars ≈ ~20 s of speech.
    language:
        BCP-47 tag for the target language (currently only affects
        the brevity rewrites list).
    """
    if not text:
        return ""

    result = _strip_markdown(text)
    result = _collapse_whitespace(result)
    result = _apply_brevity_rewrites(result, language)
    result = _truncate_at_sentence(result, max_chars)
    return result.strip()


def shape_confirmation(
    action: str,
    description: str = "",
    language: str = "en",
) -> str:
    """Return a spoken confirmation question for *action*.

    Examples
    --------
    >>> shape_confirmation("gmail_send_email", "to alice@example.com", "en")
    "Ready to send that email to alice@example.com. Shall I go ahead?"

    >>> shape_confirmation("calendar_delete_event", "Team standup", "lt")
    "Ar tikrai norite ištrinti „Team standup" įvykį?"
    """
    detail = f" {description.strip()}" if description.strip() else ""
    templates = _CONFIRMATION_TEMPLATES.get(language[:2], _CONFIRMATION_TEMPLATES["en"])
    template = templates.get(action, templates["__default__"])
    return template.format(detail=detail).strip()


def shape_approval_confirmation(
    tool_name: str,
    params: dict,
    language: str = "en",
) -> str:
    """Build a spoken confirmation prompt from tool_name + params dict.

    Extracts a human-readable description from params and delegates to
    shape_confirmation().
    """
    description = _describe_params(tool_name, params)
    return shape_confirmation(tool_name, description, language)


def is_interrupt_command(transcript: str) -> bool:
    """Return True if *transcript* is a voice interrupt command.

    Matches: stop, enough, cancel, quiet, silence, shut up, wait
    Case-insensitive, trims punctuation.
    """
    cleaned = transcript.strip().lower().rstrip("!.,;?")
    return cleaned in _INTERRUPT_PHRASES


# ─── Brevity rewrite tables ───────────────────────────────────────────────────

_EN_BREVITY: list[tuple[str, str]] = [
    # Long → short
    (r"I have successfully (completed|finished|done)", "Done."),
    (r"I've successfully (completed|finished|done)", "Done."),
    (r"Successfully (completed|finished|done|created|moved|sorted|opened|closed)", r"Done."),
    (r"The (file|folder|document|email|event|window) has been (created|moved|deleted|sorted|opened|closed|sent)", "Done."),
    (r"I (was able to|managed to|have) (complete|finish|execute|run|perform|do)", "I"),
    (r"Please note that ", ""),
    (r"I would like to (inform|let) you (know|that) ", ""),
    (r"It's worth mentioning that ", ""),
    (r"I need your (approval|confirmation) before I can (continue|proceed)\.", "Needs your approval."),
    (r"I need your approval\.", "Needs approval."),
    (r"Something went wrong\.", "That failed."),
    (r"An error occurred\.", "That failed."),
    (r"I didn't recognise that command\.", "I didn't understand that."),
    (r"I didn't recognize that command\.", "I didn't understand that."),
]

_LT_BREVITY: list[tuple[str, str]] = [
    (r"Sėkmingai (baigta|sukurta|perkelta|ištrinta|atidaryta|uždaryta)\.", "Atlikta."),
    (r"Prašome patvirtinti prieš tęsiant\.", "Reikia patvirtinimo."),
]

_BREVITY_BY_LANG: dict[str, list[tuple[str, str]]] = {
    "en": _EN_BREVITY,
    "lt": _LT_BREVITY,
}


def _apply_brevity_rewrites(text: str, language: str) -> str:
    rewrites = _BREVITY_BY_LANG.get(language[:2], _EN_BREVITY)
    result = text
    for pattern, replacement in rewrites:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


# ─── Markdown stripping ───────────────────────────────────────────────────────

_MD_PATTERNS: list[tuple[str, str]] = [
    (r"\*\*(.+?)\*\*", r"\1"),      # **bold**
    (r"\*(.+?)\*", r"\1"),          # *italic*
    (r"__(.+?)__", r"\1"),          # __bold__
    (r"_(.+?)_", r"\1"),            # _italic_
    (r"`{1,3}(.+?)`{1,3}", r"\1"),  # `code` / ```block```
    (r"#{1,6}\s+", ""),             # ## Heading
    (r"^\s*[-*+]\s+", "", ),        # - bullet
    (r"^\s*\d+\.\s+", ""),          # 1. numbered list
    (r"\[(.+?)\]\(.+?\)", r"\1"),   # [link text](url)
    (r"!\[.*?\]\(.+?\)", ""),       # ![image](url)
    (r"\|.*?\|", ""),               # table cells
    (r"-{3,}", ""),                 # --- hr
]


def _strip_markdown(text: str) -> str:
    result = text
    for pattern, replacement in _MD_PATTERNS:
        flags = re.MULTILINE if "^" in pattern else 0
        result = re.sub(pattern, replacement, result, flags=flags)
    return result


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    # Try to cut at a sentence boundary
    chunk = text[:max_chars]
    for sep in (".", "!", "?"):
        idx = chunk.rfind(sep)
        if idx > max_chars // 2:
            return chunk[: idx + 1]
    # Fall back: cut at last space
    idx = chunk.rfind(" ")
    if idx > 0:
        return chunk[:idx] + "…"
    return chunk[:max_chars] + "…"


# ─── Param description extractor ─────────────────────────────────────────────

_PARAM_KEYS_BY_TOOL: dict[str, list[str]] = {
    "gmail_send_email": ["to", "subject", "recipient"],
    "calendar_delete_event": ["title", "event_id", "summary"],
    "calendar_create_event": ["title", "summary", "start"],
    "close_window": ["window_title", "title"],
    "move_file": ["source", "destination"],
    "create_folder": ["path", "name"],
    "operator.type_text": ["text"],
    "operator.press_shortcut": ["keys"],
    "propose_terminal_commands": ["commands"],
}


def _describe_params(tool_name: str, params: dict) -> str:
    keys = _PARAM_KEYS_BY_TOOL.get(tool_name, [])
    for key in keys:
        val = params.get(key)
        if val:
            if isinstance(val, list):
                return " + ".join(str(k) for k in val[:3])
            return str(val)[:80]
    return ""


# ─── Interrupt command set ────────────────────────────────────────────────────

_INTERRUPT_PHRASES: frozenset[str] = frozenset({
    "stop", "enough", "cancel", "quiet", "silence",
    "shut up", "wait", "pause", "nevermind", "never mind",
    "stop that", "stop speaking", "stop talking", "be quiet",
    # Lithuanian
    "sustok", "tylėk", "atšaukti", "palaukite",
})


# ─── Confirmation templates ───────────────────────────────────────────────────

_CONFIRMATION_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "__default__": "Ready to do that{detail}. Shall I go ahead?",
        "gmail_send_email": "Ready to send that email{detail}. Shall I go ahead?",
        "calendar_delete_event": "Ready to delete that event{detail}. Are you sure?",
        "calendar_create_event": "Ready to create that event{detail}. Shall I go ahead?",
        "close_window": "Ready to close{detail}. Shall I?",
        "operator.close_window": "Ready to close{detail}. Shall I?",
        "operator.type_text": "Ready to type{detail}. Shall I go ahead?",
        "operator.press_shortcut": "Ready to press{detail}. Confirm?",
        "propose_terminal_commands": "Ready to run those terminal commands{detail}. Confirm?",
        "move_file": "Ready to move that file{detail}. Shall I?",
    },
    "lt": {
        "__default__": "Ar norite tęsti{detail}?",
        "gmail_send_email": "Ar tikrai norite išsiųsti laišką{detail}?",
        "calendar_delete_event": "Ar tikrai norite ištrinti įvykį{detail}?",
        "calendar_create_event": "Ar norite sukurti įvykį{detail}?",
        "close_window": "Ar norite uždaryti{detail}?",
        "operator.close_window": "Ar norite uždaryti{detail}?",
        "operator.type_text": "Ar norite įvesti tekstą{detail}?",
        "operator.press_shortcut": "Ar norite paspausti{detail}?",
        "propose_terminal_commands": "Ar norite vykdyti terminalo komandas{detail}?",
        "move_file": "Ar norite perkelti failą{detail}?",
    },
}
