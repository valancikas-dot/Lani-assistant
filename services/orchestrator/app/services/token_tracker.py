"""
Token Tracker – counts OpenAI API token usage and warns when nearing limits.

All usage is stored in memory_entries (category='token_usage') and in a
fast in-memory accumulator for the current process.

Public API
──────────
  record_usage(model, prompt_tokens, completion_tokens, operation)
  get_usage_today()           → TokenUsageSummary
  get_usage_total()           → TokenUsageSummary
  check_limit_warning()       → str | None  (warning message or None)
  set_daily_limit(tokens)     – set soft daily cap
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger(__name__)

# Pricing per 1M tokens (USD, approximate 2026-03)
_PRICING: Dict[str, Dict[str, float]] = {
    # OpenAI – reasoning
    "o3":                        {"input": 10.00, "output": 40.00},
    "o3-mini":                   {"input": 1.10,  "output": 4.40},
    "o1":                        {"input": 15.00, "output": 60.00},
    # OpenAI – chat
    "gpt-4.5-preview":           {"input": 75.00, "output": 150.00},
    "gpt-4o":                    {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":               {"input": 0.15,  "output": 0.60},
    "gpt-4-turbo":               {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo":             {"input": 0.50,  "output": 1.50},
    # Embeddings
    "text-embedding-3-large":    {"input": 0.13,  "output": 0.00},
    "text-embedding-3-small":    {"input": 0.02,  "output": 0.00},
    # Voice
    "whisper-1":                 {"input": 0.006, "output": 0.00},
    "tts-1":                     {"input": 0.015, "output": 0.00},
    "tts-1-hd":                  {"input": 0.030, "output": 0.00},
    # Anthropic
    "claude-3-7-sonnet-20250219":{"input": 3.00,  "output": 15.00},
    "claude-3-5-sonnet-20241022":{"input": 3.00,  "output": 15.00},
    "claude-3-haiku-20240307":   {"input": 0.25,  "output": 1.25},
    # Google
    "gemini-2.0-flash":          {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro":            {"input": 1.25,  "output": 5.00},
}

_DEFAULT_DAILY_LIMIT = 100_000   # tokens per day (soft cap)
_daily_limit: int = _DEFAULT_DAILY_LIMIT

# In-memory accumulators (reset on restart)
@dataclass
class _Accumulator:
    prompt: int = 0
    completion: int = 0
    requests: int = 0
    estimated_usd: float = 0.0
    by_model: Dict[str, Dict[str, int]] = field(default_factory=dict)

_TODAY_ACC = _Accumulator()
_TOTAL_ACC = _Accumulator()
_TODAY_DATE: str = ""


def _reset_if_new_day() -> None:
    global _TODAY_DATE, _TODAY_ACC
    today = datetime.date.today().isoformat()
    if today != _TODAY_DATE:
        _TODAY_DATE = today
        _TODAY_ACC = _Accumulator()


def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _PRICING.get(model, {"input": 5.0, "output": 15.0})
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


@dataclass
class TokenUsageSummary:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    requests: int
    estimated_usd: float
    by_model: Dict[str, Dict[str, int]]
    daily_limit: int
    pct_of_daily_limit: float


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    operation: str = "chat",
) -> None:
    """
    Record token usage for one API call.
    Call this after every LLM / embedding / TTS invocation.
    """
    _reset_if_new_day()

    cost = _cost_usd(model, prompt_tokens, completion_tokens)

    for acc in (_TODAY_ACC, _TOTAL_ACC):
        acc.prompt += prompt_tokens
        acc.completion += completion_tokens
        acc.requests += 1
        acc.estimated_usd += cost
        if model not in acc.by_model:
            acc.by_model[model] = {"prompt": 0, "completion": 0, "requests": 0}
        acc.by_model[model]["prompt"] += prompt_tokens
        acc.by_model[model]["completion"] += completion_tokens
        acc.by_model[model]["requests"] += 1

    log.debug(
        "[token_tracker] %s | +%d prompt +%d completion | $%.4f | op=%s",
        model, prompt_tokens, completion_tokens, cost, operation,
    )

    # Warn if nearing daily limit
    warning = check_limit_warning()
    if warning:
        log.warning("[token_tracker] %s", warning)


def get_usage_today() -> TokenUsageSummary:
    _reset_if_new_day()
    total = _TODAY_ACC.prompt + _TODAY_ACC.completion
    pct = round(total / _daily_limit * 100, 1) if _daily_limit else 0.0
    return TokenUsageSummary(
        prompt_tokens=_TODAY_ACC.prompt,
        completion_tokens=_TODAY_ACC.completion,
        total_tokens=total,
        requests=_TODAY_ACC.requests,
        estimated_usd=round(_TODAY_ACC.estimated_usd, 4),
        by_model=dict(_TODAY_ACC.by_model),
        daily_limit=_daily_limit,
        pct_of_daily_limit=pct,
    )


def get_usage_total() -> TokenUsageSummary:
    total = _TOTAL_ACC.prompt + _TOTAL_ACC.completion
    pct = round(total / _daily_limit * 100, 1) if _daily_limit else 0.0
    return TokenUsageSummary(
        prompt_tokens=_TOTAL_ACC.prompt,
        completion_tokens=_TOTAL_ACC.completion,
        total_tokens=total,
        requests=_TOTAL_ACC.requests,
        estimated_usd=round(_TOTAL_ACC.estimated_usd, 4),
        by_model=dict(_TOTAL_ACC.by_model),
        daily_limit=_daily_limit,
        pct_of_daily_limit=pct,
    )


def check_limit_warning() -> Optional[str]:
    """Return a warning string if daily usage exceeds 80% or 100% of limit."""
    _reset_if_new_day()
    used = _TODAY_ACC.prompt + _TODAY_ACC.completion
    pct = used / _daily_limit * 100 if _daily_limit else 0
    if pct >= 100:
        return (
            f"Pasiektas dienos token limitas ({used:,}/{_daily_limit:,}). "
            "AI atsakymai gali būti lėtesni arba blokuojami."
        )
    if pct >= 80:
        return (
            f"Beveik pasiektas dienos token limitas ({used:,}/{_daily_limit:,}, {pct:.0f}%). "
            "Apsvarstykite padidinti limitą arba sumažinti AI naudojimą."
        )
    return None


def set_daily_limit(tokens: int) -> None:
    """Update the soft daily token cap."""
    global _daily_limit
    _daily_limit = max(0, tokens)
    log.info("[token_tracker] Daily limit set to %d tokens.", _daily_limit)
