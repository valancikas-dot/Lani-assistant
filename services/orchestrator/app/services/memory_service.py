"""
Memory service – the single point of truth for reading, writing, and deriving
structured memory entries.

Public API
──────────
  write_memory(db, create)                  → MemoryEntryOut
  get_all(db, category?, status?)           → list[MemoryEntryOut]
  get_by_id(db, id)                         → MemoryEntryOut | None
  update_memory(db, id, patch)              → MemoryEntryOut | None
  delete_memory(db, id)                     → bool
  get_context_for_command(db, command)      → MemoryContext
  generate_suggestions(db)                  → list[SuggestionOut]
  record_task_history(db, command, plan, results, hints) → MemoryEntryOut
  apply_memory_to_args(step_args, context)  → dict (merged args)

Design notes
────────────
• Every upsert uses (category, key) as a logical primary key – writing the
  same key twice updates the value instead of inserting a duplicate.
• The suggestion engine scans task_history for repeated patterns and emits
  suggestions entries (status='active', source='inferred_from_repeated_actions').
• get_context_for_command uses semantic embedding search (OpenAI text-embedding-3-small)
  when OPENAI_API_KEY is available, falling back gracefully to keyword scan otherwise.
• Embeddings are stored as JSON float arrays in the memory_entry.embedding column.
  They are generated lazily on first write and kept up-to-date on every update.
"""

from __future__ import annotations

import datetime
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_entry import MemoryEntry
from app.schemas.memory import (
    MemoryContext,
    MemoryEntryCreate,
    MemoryEntryOut,
    MemoryEntryUpdate,
    SuggestionOut,
)

log = logging.getLogger(__name__)


def _utcnow() -> datetime.datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.datetime.now(datetime.timezone.utc)

# ─── In-process embedding cache ───────────────────────────────────────────────
# Avoids calling the OpenAI Embeddings API multiple times for identical text.
# Uses an ordered dict so we can cheaply evict the oldest entry when full.
# Keys are the first 512 chars of the text (unique enough for memory entries).
from collections import OrderedDict  # noqa: E402 – placed here for locality

_EMBEDDING_CACHE: OrderedDict[str, List[float]] = OrderedDict()
_EMBEDDING_CACHE_MAX = 2048  # max entries (~4 MB at 1536-dim float32)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

async def write_memory(
    db: AsyncSession,
    payload: MemoryEntryCreate,
) -> MemoryEntryOut:
    """
    Upsert a memory entry by (category, key).

    If a row with the same category + key already exists it is updated in-place
    rather than creating a duplicate.  Embeddings are generated lazily so the
    entry is always searchable via semantic similarity.
    """
    result = await db.execute(
        select(MemoryEntry).where(
            and_(
                MemoryEntry.category == payload.category,
                MemoryEntry.key == payload.key,
            )
        )
    )
    existing: MemoryEntry | None = result.scalar_one_or_none()

    if existing:
        existing.value = payload.value
        existing.source = payload.source
        existing.confidence = payload.confidence
        existing.pinned = payload.pinned
        existing.status = "active"
        existing.updated_at = _utcnow()
        entry = existing
    else:
        entry = MemoryEntry(
            category=payload.category,
            key=payload.key,
            value=payload.value,
            source=payload.source,
            confidence=payload.confidence,
            pinned=payload.pinned,
            status="active",
        )
        db.add(entry)

    # Generate embedding for semantic search (skip task_history to save tokens)
    if payload.category != "task_history":
        embedding = await _embed_text(_entry_text(entry))
        if embedding:
            entry.embedding = embedding

    await db.flush()
    return MemoryEntryOut.model_validate(entry)


async def get_all(
    db: AsyncSession,
    category: Optional[str] = None,
    status: Optional[str] = None,
) -> List[MemoryEntryOut]:
    """Return all entries, optionally filtered by category and/or status."""
    q = select(MemoryEntry)
    if category:
        q = q.where(MemoryEntry.category == category)
    if status:
        q = q.where(MemoryEntry.status == status)
    q = q.order_by(MemoryEntry.pinned.desc(), MemoryEntry.updated_at.desc())

    result = await db.execute(q)
    return [MemoryEntryOut.model_validate(r) for r in result.scalars().all()]


async def get_by_id(db: AsyncSession, entry_id: int) -> Optional[MemoryEntryOut]:
    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.id == entry_id)
    )
    row = result.scalar_one_or_none()
    return MemoryEntryOut.model_validate(row) if row else None


async def update_memory(
    db: AsyncSession,
    entry_id: int,
    patch: MemoryEntryUpdate,
) -> Optional[MemoryEntryOut]:
    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.id == entry_id)
    )
    row: MemoryEntry | None = result.scalar_one_or_none()
    if row is None:
        return None

    if patch.value is not None:
        row.value = patch.value
    if patch.confidence is not None:
        row.confidence = patch.confidence
    if patch.pinned is not None:
        row.pinned = patch.pinned
    if patch.status is not None:
        row.status = patch.status

    row.updated_at = _utcnow()
    await db.flush()
    return MemoryEntryOut.model_validate(row)


async def delete_memory(db: AsyncSession, entry_id: int) -> bool:
    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.id == entry_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


# ─── Task history recorder ────────────────────────────────────────────────────

async def record_task_history(
    db: AsyncSession,
    command: str,
    plan_goal: str,
    step_summaries: List[Dict[str, Any]],
    overall_status: str,
    memory_hints: Optional[List[str]] = None,
) -> MemoryEntryOut:
    """
    Write a task_history entry after a plan execution finishes.

    The key is a sanitized slug of the command so repeated identical commands
    can be detected by the suggestion engine later.
    Appends to a rolling list (max 20 runs per key) instead of overwriting.
    """
    key = _slugify(command)[:100]
    run_value: Dict[str, Any] = {
        "command": command,
        "goal": plan_goal,
        "steps": step_summaries,
        "overall_status": overall_status,
        "memory_hints": memory_hints or [],
        "executed_at": _utcnow().isoformat(),
    }

    existing = await db.execute(
        select(MemoryEntry).where(
            and_(
                MemoryEntry.category == "task_history",
                MemoryEntry.key == key,
            )
        )
    )
    row: MemoryEntry | None = existing.scalar_one_or_none()
    if row:
        history: list = row.value.get("history", [row.value])
        history.append(run_value)
        row.value = {"history": history[-20:]}
        row.updated_at = _utcnow()
        entry = row
    else:
        entry = MemoryEntry(
            category="task_history",
            key=key,
            value={"history": [run_value]},
            source="executor_outcome",
            confidence=1.0,
            pinned=False,
            status="active",
        )
        db.add(entry)

    await db.flush()
    return MemoryEntryOut.model_validate(entry)


# ─── Embedding helpers ────────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _embed_text(text: str) -> Optional[List[float]]:
    """
    Generate an embedding vector for *text* using OpenAI text-embedding-3-small.

    Returns None when no API key is configured or the call fails, so callers
    can gracefully fall back to keyword search.

    Results are cached in-process by text content so repeated calls for the
    same string (e.g. the same memory entry key) never hit the API twice.
    """
    # ── In-memory text-level cache ─────────────────────────────────────────────
    # Key = first 512 chars of text (long enough to be unique, cheap to hash).
    cache_key = text[:512]
    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        from app.core.config import settings as cfg
        if not getattr(cfg, "OPENAI_API_KEY", ""):
            return None
        import openai
        client = openai.AsyncOpenAI(api_key=cfg.OPENAI_API_KEY)
        response = await client.embeddings.create(
            model=getattr(cfg, "EMBEDDING_MODEL", "text-embedding-3-large"),
            input=text[:8000],  # API limit safety
        )
        # Track token usage (approx: 1 token ≈ 4 chars)
        try:
            from app.services.token_tracker import record_usage
            est_tokens = max(1, len(text) // 4)
            record_usage(
                getattr(cfg, "EMBEDDING_MODEL", "text-embedding-3-large"),
                est_tokens, 0, "embedding"
            )
        except Exception:
            pass
        vector = response.data[0].embedding
        # Store in cache (evict oldest if cache grows too large)
        if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
            oldest_key = next(iter(_EMBEDDING_CACHE))
            del _EMBEDDING_CACHE[oldest_key]
        _EMBEDDING_CACHE[cache_key] = vector
        return vector
    except Exception as exc:
        log.warning("[memory] embedding failed: %s", exc)
        return None


def _entry_text(entry: MemoryEntry) -> str:
    """Build a searchable text representation of a memory entry."""
    parts = [entry.key.replace(".", " ").replace("_", " ")]
    if isinstance(entry.value, dict):
        for v in entry.value.values():
            if isinstance(v, str) and not v.startswith("_"):
                parts.append(v)
    return " ".join(parts)


# ─── Context retrieval for planner/executor ────────────────────────────────────

# Keyword → memory key patterns used as fast-path fallback
_CONTEXT_KEYWORDS: Dict[str, List[str]] = {
    "presentation": [
        "preferred_output_folder",
        "preferred_presentation_tone",
        "preferred_presentation_style",
    ],
    "download": [
        "sort_downloads.group_by",
        "sort_downloads.approval_threshold",
    ],
    "sort": [
        "sort_downloads.group_by",
        "sort_downloads.approval_threshold",
    ],
    "folder": ["preferred_output_folder"],
    "language": ["preferred_language", "preferred_response_style"],
    "voice": ["preferred_voice", "preferred_language"],
    "summarize": ["preferred_output_folder", "preferred_response_style"],
    "file": ["preferred_file_naming_style"],
    "move": ["preferred_file_naming_style", "sort_downloads.approval_threshold"],
}

_HINT_TEMPLATES: Dict[str, str] = {
    "preferred_output_folder":           "Used your default output folder: {path}.",
    "preferred_presentation_tone":       "Applied your preferred presentation tone: {tone}.",
    "preferred_presentation_style":      "Using your preferred presentation style: {style}.",
    "sort_downloads.group_by":           "Sorting downloads by: {group_by}.",
    "sort_downloads.approval_threshold": "Will ask approval when moving more than {n} files.",
    "preferred_language":                "Responding in your preferred language: {lang}.",
    "preferred_response_style":          "Using your preferred response style: {style}.",
    "preferred_voice":                   "Using your preferred voice: {voice}.",
    "preferred_file_naming_style":       "Using your preferred file naming style: {style}.",
}

# Minimum cosine similarity to include an entry in semantic search results
_SEMANTIC_THRESHOLD = 0.40


async def get_context_for_command(
    db: AsyncSession,
    command: str,
) -> MemoryContext:
    """
    Retrieve relevant memory entries for *command*.

    Strategy (two-tier):
      1. Semantic search – embed the command with OpenAI text-embedding-3-small,
         compare against stored embeddings (cosine similarity ≥ 0.40).
         Works across all active non-history categories and finds conceptually
         similar entries even when keywords don't match exactly.
      2. Keyword fallback – used when embeddings are unavailable (no API key,
         or all stored entries lack embeddings).  Same keyword→key mapping as
         before so existing behaviour is fully preserved.
    """
    # ── Fetch all active non-history entries (small table, cached by SQLite) ──
    result = await db.execute(
        select(MemoryEntry).where(
            and_(
                MemoryEntry.category.in_(
                    ["user_preferences", "workflow_preferences", "facts", "suggestions"]
                ),
                MemoryEntry.status == "active",
            )
        )
    )
    all_rows: List[MemoryEntry] = list(result.scalars().all())

    if not all_rows:
        return MemoryContext(entries=[], hints=[])

    # ── Try semantic search ────────────────────────────────────────────────────
    cmd_embedding = await _embed_text(command)
    matched_rows: List[MemoryEntry] = []

    if cmd_embedding:
        # Back-fill missing embeddings (lazy generation) – fire-and-forget
        for row in all_rows:
            if row.embedding is None:
                row.embedding = await _embed_text(_entry_text(row)) or []
        try:
            await db.flush()
        except Exception:
            pass  # non-critical

        # Score and rank
        scored: List[tuple[float, MemoryEntry]] = []
        for row in all_rows:
            if row.embedding:
                sim = _cosine_similarity(cmd_embedding, row.embedding)
                if sim >= _SEMANTIC_THRESHOLD:
                    scored.append((sim, row))
        scored.sort(key=lambda t: t[0], reverse=True)
        matched_rows = [r for _, r in scored[:10]]

    # ── Keyword fallback when no embeddings available ──────────────────────────
    if not matched_rows:
        cmd_lower = command.lower()
        wanted_keys: set[str] = set()
        for keyword, keys in _CONTEXT_KEYWORDS.items():
            if keyword in cmd_lower:
                wanted_keys.update(keys)
        if wanted_keys:
            matched_rows = [r for r in all_rows if r.key in wanted_keys]

    entries = [MemoryEntryOut.model_validate(r) for r in matched_rows]

    hints: List[str] = []
    for entry in entries:
        template = _HINT_TEMPLATES.get(entry.key)
        if template:
            try:
                hints.append(template.format(**entry.value))
            except KeyError:
                # Fallback: show key + value summary
                summary = ", ".join(f"{k}={v}" for k, v in entry.value.items() if not k.startswith("_"))
                if summary:
                    hints.append(f"{entry.key}: {summary}")
        elif entry.category == "facts":
            # Facts category: show the stored text verbatim
            fact_text = entry.value.get("text") or entry.value.get("content", "")
            if fact_text:
                hints.append(f"Remembered: {fact_text}")

    return MemoryContext(entries=entries, hints=hints)


# ─── Suggestion engine ────────────────────────────────────────────────────────

async def generate_suggestions(db: AsyncSession) -> List[SuggestionOut]:
    """
    Scan task_history entries for repeated patterns and emit suggestion entries.

    Currently detects:
      1. Repeated use of the same output folder in presentation commands
      2. Repeated sort_downloads usage → suggest default grouping preference
    """
    hist_result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.category == "task_history")
    )
    hist_rows = hist_result.scalars().all()

    pptx_folders: List[str] = []
    sort_commands_count = 0

    for row in hist_rows:
        runs = row.value.get("history", [row.value])
        for run in runs:
            cmd: str = run.get("command", "").lower()
            steps: list = run.get("steps", [])

            for step in steps:
                if step.get("tool") == "create_presentation":
                    args = step.get("args", {}) or {}
                    path = args.get("output_path", "")
                    if path and isinstance(path, str):
                        folder = os.path.dirname(path)
                        if folder:
                            pptx_folders.append(folder)

            if "sort" in cmd or "download" in cmd:
                sort_commands_count += 1

    # Pattern 1: suggest default output folder
    folder_counter = Counter(pptx_folders)
    for folder, count in folder_counter.most_common(1):
        if count >= 2 and folder:
            await _upsert_suggestion(
                db,
                key="preferred_output_folder",
                value={"path": folder},
                explanation=(
                    f"You've saved presentations to '{folder}' {count} times. "
                    "Set this as your default output folder?"
                ),
                confidence=min(0.5 + count * 0.15, 0.95),
            )

    # Pattern 2: suggest sort style after 3 sort_downloads uses
    if sort_commands_count >= 3:
        await _upsert_suggestion(
            db,
            key="sort_downloads.group_by",
            value={"group_by": "extension"},
            explanation=(
                f"You've sorted downloads {sort_commands_count} times. "
                "Set 'group by extension' as your default sorting style?"
            ),
            confidence=min(0.4 + sort_commands_count * 0.1, 0.9),
        )

    # Return all active suggestions
    all_sugg = await db.execute(
        select(MemoryEntry).where(
            and_(
                MemoryEntry.category == "suggestions",
                MemoryEntry.status == "active",
            )
        )
    )
    out: List[SuggestionOut] = []
    for row in all_sugg.scalars().all():
        out.append(SuggestionOut(
            entry_id=row.id,
            category=row.category,
            key=row.key,
            value=row.value,
            confidence=row.confidence,
            explanation=row.value.get("_explanation", f"Suggested: {row.key}"),
        ))
    return out


async def _upsert_suggestion(
    db: AsyncSession,
    key: str,
    value: Dict[str, Any],
    explanation: str,
    confidence: float,
) -> MemoryEntryOut:
    payload_value = {**value, "_explanation": explanation}
    return await write_memory(
        db,
        MemoryEntryCreate(
            category="suggestions",
            key=key,
            value=payload_value,
            source="inferred_from_repeated_actions",
            confidence=confidence,
            pinned=False,
        ),
    )


# ─── Apply memory defaults to plan step args ──────────────────────────────────

def apply_memory_to_args(
    step_args: Dict[str, Any],
    context: MemoryContext,
) -> Dict[str, Any]:
    """
    Merge relevant memory values into step args WITHOUT overriding
    values that the user explicitly specified.

    Only fills in keys that are absent or empty in step_args.
    """
    merged = dict(step_args)
    for entry in context.entries:
        if entry.key == "preferred_output_folder":
            if not merged.get("output_path"):
                folder = entry.value.get("path", "")
                if folder:
                    existing = merged.get("output_path", "")
                    if existing:
                        merged["output_path"] = os.path.join(
                            folder, os.path.basename(existing)
                        )
                    else:
                        merged["output_path"] = folder

        elif entry.key == "preferred_language":
            if not merged.get("language"):
                merged["language"] = entry.value.get("lang", "")

        elif entry.key == "sort_downloads.group_by":
            if not merged.get("group_by"):
                merged["group_by"] = entry.value.get("group_by", "extension")

    return merged


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")
