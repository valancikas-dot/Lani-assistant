"""
Error Explainer – converts raw tool errors into friendly, actionable messages.

Uses GPT-4o (or Anthropic) to explain what went wrong and suggest a fix.
Falls back gracefully to the original error message if no LLM is available.

Public API
──────────
  explain_error(tool_name, error_msg, command, language) → str
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.llm_text_service import complete_text

log = logging.getLogger(__name__)

# Known error patterns with pre-written explanations (no LLM token cost)
_STATIC_HINTS: list[tuple[str, str, str]] = [
    # (tool_prefix_or_name, error_substring, lt_message)
    ("gmail", "credentials", "Gmail nėra prijungtas. Eik į Settings → Connectors ir prijunk Google paskyrą."),
    ("gmail", "token", "Gmail prieigos raktas pasibaigė. Eik į Settings → Connectors ir iš naujo prijunk Google."),
    ("google_drive", "credentials", "Google Drive nėra prijungtas. Eik į Settings → Connectors."),
    ("google_drive", "token", "Google Drive prieigos raktas pasibaigė. Eik į Settings → Connectors."),
    ("google_calendar", "credentials", "Google Calendar nėra prijungtas. Eik į Settings → Connectors."),
    ("", "openai", "OpenAI API raktas neteisingas arba nenustatytas. Patikrink .env failą (OPENAI_API_KEY)."),
    ("", "rate limit", "Pasiektas API limitas. Palaukite minutę ir bandykite dar kartą."),
    ("", "connection", "Nėra interneto ryšio arba serveris nepasiekiamas."),
    ("", "ollama", "Offline modelis (Ollama) nepasiekiamas. Įsitikink, kad Ollama veikia (ollama serve) arba prisijunk prie interneto."),
    ("", "No LLM configured", "Nenustatytas joks AI modelis. Patikrink OPENAI_API_KEY / ANTHROPIC_API_KEY .env faile arba paleisk Ollama."),
    ("", "permission denied", "Prieiga uždrausta. Patikrink ar failas/aplankas yra leistinuose kataloguose (Settings → Directories)."),
    ("", "not found", "Failas ar aplankas nerastas. Patikrink kelią."),
    ("", "No module", "Trūksta Python paketo. Paleisk: pip install [paketo pavadinimas]."),
]


def _static_hint(tool_name: str, error_msg: str) -> Optional[str]:
    """Return a pre-written hint if the error matches a known pattern."""
    tool_lower = tool_name.lower()
    err_lower = error_msg.lower()
    for tool_prefix, err_substr, hint in _STATIC_HINTS:
        if tool_prefix and tool_prefix not in tool_lower:
            continue
        if err_substr.lower() in err_lower:
            return hint
    return None


async def explain_error(
    tool_name: str,
    error_msg: str,
    command: str = "",
    language: str = "lt",
) -> str:
    """
    Return a human-friendly explanation of an error + suggested fix.

    Priority:
      1. Static hint table (instant, no cost)
      2. LLM explanation (GPT-4o / Anthropic)
      3. Formatted original error (fallback)
    """
    # 1. Static hint
    hint = _static_hint(tool_name, error_msg)
    if hint:
        return hint

    # 2. LLM explanation
    try:
        return await _llm_explain(tool_name, error_msg, command, language)
    except Exception as exc:
        log.debug("[error_explainer] LLM failed: %s", exc)

    # 3. Friendly fallback
    if language == "lt":
        return f"Klaida vykdant '{tool_name}': {error_msg}"
    return f"Error running '{tool_name}': {error_msg}"


async def _llm_explain(
    tool_name: str,
    error_msg: str,
    command: str,
    language: str,
) -> str:
    from app.core.config import settings as cfg

    lang_str = "Lithuanian (lietuvių kalba)" if language == "lt" else "English"
    system = (
        "You are a helpful assistant that explains technical errors to non-technical users. "
        "Be concise (max 2 sentences). Give a clear reason + one actionable fix. "
        f"Always respond in {lang_str}."
    )
    user_msg = (
        f"The user ran the command: {command!r}\n"
        f"Tool '{tool_name}' failed with this error: {error_msg}\n\n"
        "Explain what went wrong and how to fix it in plain language."
    )

    anthropic_key = getattr(cfg, "ANTHROPIC_API_KEY", "") or ""
    openai_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
    if openai_key or anthropic_key:
        try:
            return await complete_text(
                openai_api_key=openai_key,
                anthropic_api_key=anthropic_key,
                openai_model=getattr(cfg, "LLM_MODEL", "gpt-4o"),
                anthropic_model=getattr(cfg, "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
                openai_messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                anthropic_messages=[{"role": "user", "content": user_msg}],
                system_prompt=system,
                max_tokens=256,
                temperature=0.3,
                provider_preference="anthropic_first" if anthropic_key else "openai_first",
            )
        except Exception as exc:
            log.debug("[error_explainer] LLM failed: %s", exc)

    raise RuntimeError("No LLM available for error explanation.")
