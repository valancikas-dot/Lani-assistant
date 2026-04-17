"""Wake-word service – phrase matching and provider abstraction.

Current implementation supports four wake modes:

    manual                 – no passive listening; activation is explicit (button press).
    push_to_talk           – same as manual but labelled differently for UI clarity.
    wake_phrase_placeholder – text keyword matching against an STT transcript.
                             NOT true always-on audio detection. Clearly labelled.
    provider_ready         – reserved for future integration with a real wake-word
                             provider (Picovoice Porcupine, openWakeWord, etc.).

The service returns a dict describing whether activation should proceed. Callers
can then use voice_session_service to manage the unlock lifecycle.
"""

from __future__ import annotations

from typing import Optional

from app.schemas.wake import WakeMode


# ─── Phrase normalisation ─────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    return text.strip().lower()


def _phrase_matches(heard: str, phrase: str) -> bool:
    """Return True if the phrase appears anywhere in the heard text."""
    return _normalise(phrase) in _normalise(heard)


# ─── Mode description ─────────────────────────────────────────────────────────

_MODE_LABELS: dict[WakeMode, str] = {
    WakeMode.manual: "Manual activation (button/API only)",
    WakeMode.push_to_talk: "Push-to-talk activation",
    WakeMode.wake_phrase_placeholder: (
        "⚠️ Keyword match mode (NOT always-on — requires STT transcript first)"
    ),
    WakeMode.keyword_live: (
        "🎙 Always-on keyword detection (browser SpeechRecognition)"
    ),
    WakeMode.provider_ready: "Always-on wake-word provider",
}


def describe_mode(mode: WakeMode) -> str:
    return _MODE_LABELS.get(mode, str(mode))


# ─── Activation check ─────────────────────────────────────────────────────────

def check_wake_activation(
    mode: WakeMode,
    wake_word_enabled: bool,
    primary_phrase: str,
    secondary_phrase: str,
    phrase_heard: Optional[str] = None,
) -> dict:
    """Decide whether a wake activation is valid.

    Returns:
        {
            "allowed": bool,
            "reason": str,
            "mode": str,
        }
    """
    if not wake_word_enabled:
        return {
            "allowed": False,
            "reason": "wake_word_disabled",
            "mode": mode.value,
        }

    if mode in (WakeMode.manual, WakeMode.push_to_talk):
        # Always allow – caller has already performed the explicit gesture.
        return {
            "allowed": True,
            "reason": "manual_trigger",
            "mode": mode.value,
        }

    if mode in (WakeMode.wake_phrase_placeholder, WakeMode.keyword_live):
        # keyword_live: frontend SpeechRecognition already matched the phrase;
        # it sends phrase_heard so we can double-check here.
        if not phrase_heard:
            return {
                "allowed": False,
                "reason": "no_phrase_provided",
                "mode": mode.value,
            }
        if _phrase_matches(phrase_heard, primary_phrase) or _phrase_matches(
            phrase_heard, secondary_phrase
        ):
            return {
                "allowed": True,
                "reason": "phrase_matched",
                "mode": mode.value,
            }
        # In keyword_live mode the frontend already validated the phrase –
        # allow activation even if our simple string match misses it.
        if mode == WakeMode.keyword_live:
            return {
                "allowed": True,
                "reason": "frontend_keyword_match",
                "mode": mode.value,
            }
        return {
            "allowed": False,
            "reason": "phrase_not_matched",
            "mode": mode.value,
        }

    if mode == WakeMode.provider_ready:
        # Placeholder: provider integration not yet wired in.
        return {
            "allowed": False,
            "reason": "provider_not_integrated",
            "mode": mode.value,
        }

    return {
        "allowed": False,
        "reason": "unknown_mode",
        "mode": mode.value,
    }
