"""
model_router.py – Smart LLM routing based on task complexity.

Routes tasks to the cheapest model that can handle them well:
  • gpt-4o-mini   – simple questions, summaries, formatting, translation
  • gpt-4o        – complex reasoning, coding, analysis, planning
  • o3-mini       – mathematical/logical reasoning (when available)
  • o3            – maximum intelligence, slow tasks, deep planning
  • claude-opus-4 – alternative for long-context, document analysis

Selection logic:
  1. Check explicit 'model' parameter
  2. Check task COMPLEXITY_SIGNALS (keywords)
  3. Check token count (>8K context → stronger model)
  4. Fall back to configured default

Config (.env):
  LLM_MODEL=gpt-4o           (default model)
  LLM_FAST_MODEL=gpt-4o-mini (fast/cheap model)
  LLM_SMART_MODEL=gpt-4o     (complex tasks)
  LLM_REASONING_MODEL=o3-mini (math/logic)
  ANTHROPIC_API_KEY=...       (optional, for Claude)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Complexity signals – if any found in prompt → use smart model
# ─────────────────────────────────────────────────────────────────────────────

_FAST_SIGNALS = [
    "translate", "vertink", "summary", "santrauka", "format", "formatuok",
    "spell", "grammar", "list", "bullet", "simple", "quick", "paprasta",
    "define", "what is", "kas yra", "rephrase", "parafrazuok",
    "shorter", "longer", "sutrumpink", "išplėsk",
]

_SMART_SIGNALS = [
    "write code", "debug", "fix bug", "klaidą", "architecture",
    "design", "plan", "strategija", "analyze", "analizuok",
    "compare", "palygink", "research", "tyrinėk", "optimize",
    "refactor", "create a", "sukurk", "implement", "įgyvendink",
    "marketing campaign", "reklamos kampanija", "explain why",
    "step by step", "žingsnis po žingsnio", "complex", "sudėtinga",
    "multi-step", "workflow",
]

_REASONING_SIGNALS = [
    "calculate", "apskaičiuok", "math", "matematika", "logic", "logika",
    "proof", "įrodyk", "algorithm", "puzzle", "solve", "probability",
    "statistics", "how many", "kiek", "equation", "formula",
]

_LONG_CONTEXT_SIGNALS = [
    "entire file", "whole document", "all the code", "visą failą",
    "full codebase", "long document", "visa dokumentacija",
]


def _count_tokens_approx(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars for English, 3.5 for Lithuanian."""
    return len(text) // 4


def route_model(
    prompt: str,
    system_prompt: str = "",
    explicit_model: str | None = None,
    context_tokens: int = 0,
) -> str:
    """
    Choose the best LLM model for the given prompt.

    Returns the model name string (e.g. 'gpt-4o-mini', 'gpt-4o', 'o3-mini').
    """
    from app.core.config import settings as cfg

    # 1. Explicit override
    if explicit_model:
        return explicit_model

    fast_model      = getattr(cfg, "LLM_FAST_MODEL",      "gpt-4o-mini")
    smart_model     = getattr(cfg, "LLM_SMART_MODEL",     "gpt-4o")
    reasoning_model = getattr(cfg, "LLM_REASONING_MODEL", "o3-mini")
    default_model   = getattr(cfg, "LLM_MODEL",           "gpt-4o-mini")

    full_text = (prompt + " " + system_prompt).lower()
    total_tokens = context_tokens or _count_tokens_approx(full_text)

    # 2. Long context → smart model
    if total_tokens > 12_000:
        log.debug("[router] long context (%d tokens) → %s", total_tokens, smart_model)
        return smart_model

    # 3. Reasoning tasks
    if any(sig in full_text for sig in _REASONING_SIGNALS):
        log.debug("[router] reasoning signals → %s", reasoning_model)
        return reasoning_model

    # 4. Complex tasks → smart model
    if any(sig in full_text for sig in _SMART_SIGNALS):
        log.debug("[router] complex signals → %s", smart_model)
        return smart_model

    # 5. Simple tasks → fast model
    if any(sig in full_text for sig in _FAST_SIGNALS):
        log.debug("[router] fast signals → %s", fast_model)
        return fast_model

    # 6. Default
    log.debug("[router] default → %s", default_model)
    return default_model


def route_for_agent_loop(messages: list[dict]) -> str:
    """
    Choose model for the autonomous agent loop.
    Agent loop is always complex → use smart model.
    """
    from app.core.config import settings as cfg
    return getattr(cfg, "LLM_SMART_MODEL", getattr(cfg, "LLM_MODEL", "gpt-4o"))


def route_for_task_planning(command: str) -> str:
    """
    Choose model for task planning.
    Multi-step planning needs smart model.
    """
    from app.core.config import settings as cfg
    smart = getattr(cfg, "LLM_SMART_MODEL", getattr(cfg, "LLM_MODEL", "gpt-4o"))
    fast  = getattr(cfg, "LLM_FAST_MODEL", "gpt-4o-mini")
    # If command is very short and simple → fast
    if len(command.split()) < 8 and not any(sig in command.lower() for sig in _SMART_SIGNALS):
        return fast
    return smart


def route_for_voice_response(text_length: int) -> str:
    """
    Voice responses should be fast (low latency).
    Always use fast model unless the response is very complex.
    """
    from app.core.config import settings as cfg
    return getattr(cfg, "LLM_FAST_MODEL", "gpt-4o-mini")


def route_for_creative(task: str) -> str:
    """
    Creative tasks (marketing, scripts, content) benefit from gpt-4o.
    """
    from app.core.config import settings as cfg
    return getattr(cfg, "LLM_SMART_MODEL", getattr(cfg, "LLM_MODEL", "gpt-4o"))


# ─────────────────────────────────────────────────────────────────────────────
# Cost tracker
# ─────────────────────────────────────────────────────────────────────────────

# Approximate costs per 1M tokens (input/output) as of April 2026
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini":  (0.15,  0.60),
    "gpt-4o":       (2.50, 10.00),
    "o3-mini":      (1.10,  4.40),
    "o3":          (10.00, 40.00),
    "gpt-image-1":  (0.00,  0.00),  # separate pricing
    "dall-e-3":     (0.00,  0.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in USD."""
    costs = _MODEL_COSTS.get(model, (5.0, 15.0))
    return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000
