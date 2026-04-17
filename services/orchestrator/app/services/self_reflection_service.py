"""
self_reflection_service.py – Lani's self-improvement engine.

After a negative feedback event, Lani:
  1. Reads the failed command + response
  2. Asks o3 to analyse what went wrong and suggest a concrete improvement
  3. Saves the reflection to episodic memory (type="reflection")
  4. Appends the lesson to a persistent "behaviour guidelines" memory entry
     so future prompts benefit from the learning

Triggered automatically when a negative feedback is submitted.

Public API
──────────
  reflect_on_failure(command, response, tool, comment) → str  (reflection text)
  get_behaviour_guidelines()                            → str  (all accumulated lessons)
"""

from __future__ import annotations

import logging

from app.services.llm_text_service import complete_text

log = logging.getLogger(__name__)

_GUIDELINES_KEY = "self_improvement_guidelines"
_GUIDELINES_CATEGORY = "system"


async def reflect_on_failure(
    command: str,
    response: str,
    tool: str = "chat",
    comment: str = "",
    session_id: str = "default",
) -> str:
    """
    Ask o3 to analyse the failure and return a concise lesson.
    Saves the lesson to episodic memory and appends to behaviour guidelines.
    """
    from app.core.config import settings as cfg

    api_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
    anthropic_key = getattr(cfg, "ANTHROPIC_API_KEY", "") or ""
    if not api_key and not anthropic_key:
        return ""

    prompt = f"""You are analysing a failed AI assistant interaction to extract a lesson.

USER COMMAND: {command}

ASSISTANT RESPONSE: {response[:800]}

TOOL USED: {tool}
USER FEEDBACK: negative (thumbs down)
USER COMMENT: {comment or "(no comment)"}

In 2-3 concise sentences answer:
1. What went wrong?
2. What should Lani do differently next time?

Be specific and actionable. Focus on the root cause."""

    reflection = ""
    try:
        reflection = await complete_text(
            openai_api_key=api_key,
            anthropic_api_key=anthropic_key,
            openai_model=getattr(cfg, "AGENT_MODEL", "o3"),
            anthropic_model=getattr(cfg, "ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219"),
            openai_messages=[{"role": "user", "content": prompt}],
            anthropic_messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            provider_preference="openai_first" if api_key else "anthropic_first",
            tracking_operation="reflection",
        )
    except Exception as exc:
        log.warning("[reflection] LLM call failed: %s", exc)
        return ""

    if not reflection:
        return ""

    # Save to episodic memory as a reflection event
    try:
        from app.services.episodic_memory_service import log_reflection
        await log_reflection(
            session_id=session_id,
            text=f"[Lesson from failure on '{command[:60]}']: {reflection}",
            importance=0.9,  # Reflections are highly important – keep them
        )
    except Exception as exc:
        log.debug("[reflection] episodic log failed: %s", exc)

    # Append lesson to persistent behaviour guidelines in memory
    await _append_guideline(
        f"• [{tool}] {reflection}"
    )

    log.info("[reflection] new lesson saved for command: %r", command[:60])
    return reflection


async def get_behaviour_guidelines() -> str:
    """
    Return all accumulated self-improvement lessons as a formatted string.
    These are injected into the system prompt to improve future responses.
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.memory_entry import MemoryEntry
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MemoryEntry).where(
                    MemoryEntry.category == _GUIDELINES_CATEGORY,
                    MemoryEntry.key == _GUIDELINES_KEY,
                )
            )
            entry = result.scalar_one_or_none()
            if entry and entry.value:
                return str(entry.value)
    except Exception as exc:
        log.debug("[reflection] guidelines load failed: %s", exc)
    return ""


async def _append_guideline(lesson: str) -> None:
    """Append a new lesson to the persistent guidelines memory entry."""
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.memory_entry import MemoryEntry
        from sqlalchemy import select
        import datetime

        now_utc = datetime.datetime.now(datetime.timezone.utc)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MemoryEntry).where(
                    MemoryEntry.category == _GUIDELINES_CATEGORY,
                    MemoryEntry.key == _GUIDELINES_KEY,
                )
            )
            entry = result.scalar_one_or_none()
            if entry:
                current = str(entry.value or "")
                lines = [l for l in current.split("\n") if l.strip()]
                # Keep last 50 lessons to avoid unbounded growth
                lines = lines[-49:] + [lesson]
                entry.value = {"text": "\n".join(lines)}
                entry.updated_at = now_utc
            else:
                db.add(MemoryEntry(
                    category=_GUIDELINES_CATEGORY,
                    key=_GUIDELINES_KEY,
                    value={"text": lesson},
                    status="active",
                    source="self_reflection",
                ))
            await db.commit()
    except Exception as exc:
        log.warning("[reflection] guideline save failed: %s", exc)
