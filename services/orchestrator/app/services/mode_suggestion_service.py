"""
Mode Suggestion Service (Phase 11).

Analyses recent audit-log history to recommend which built-in modes the user
would benefit from activating.  The heuristic is:

  1. Count how many times each tool_name appears in the last *window* rows.
  2. Map tool names to a capability category using a keyword-based rule set.
  3. For each built-in mode compute a relevance score = fraction of its
     preferred_tools that appear in the top-N most-used tools.
  4. Filter out modes already active for the profile.
  5. Return up to *top_k* suggestions, ordered by score desc.

The service is intentionally lightweight – no ML, no heavy joins – so it can
run synchronously within an API call without noticeable latency.

Public API
──────────
suggest_modes(db, *, profile_id, window, top_k) -> List[ModeSuggestion]
    Returns a list of ModeSuggestion dataclass instances.

ModeSuggestion
    mode        – the Mode ORM object
    score       – float 0..1, higher is more relevant
    reason      – human-readable explanation string
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.mode import Mode, UserMode, MODE_STATUS_ARCHIVED
from app.services.mode_service import list_modes, get_active_modes

log = logging.getLogger(__name__)

# ─── Tool → capability-category mapping ──────────────────────────────────────
# Each entry: (substring_in_tool_name, capability_tag)
# We do a simple "any substring match" scan so partial tool-name variants work.

_TOOL_CAP_MAP: List[tuple[str, str]] = [
    # Code / development
    ("create_file", "code"),
    ("read_document", "code"),
    ("move_file", "code"),
    ("create_folder", "code"),
    ("sort_downloads", "files"),
    # Research
    ("web_search", "research"),
    ("research_and_prepare_brief", "research"),
    ("summarize_document", "research"),
    # Writing / creative
    ("summarize", "writing"),
    ("create_file", "writing"),
    # Communication
    ("safari_open", "communication"),
    ("operator_open_app", "communication"),
    ("operator_press_shortcut", "communication"),
    # Memory / notes
    ("save_memory", "notes"),
    ("recall_memory", "notes"),
    # Data / analysis
    ("read_document", "data"),
    ("summarize_document", "data"),
    # Automation / productivity
    ("operator_", "automation"),
    ("create_folder", "automation"),
    ("move_file", "automation"),
    ("sort_downloads", "automation"),
]

# Capability tag → mode slugs that benefit from it
_CAP_TO_SLUGS: Dict[str, List[str]] = {
    "code":         ["developer"],
    "files":        ["developer", "productivity"],
    "research":     ["researcher", "analyst", "student"],
    "writing":      ["writer", "student"],
    "communication":["communicator"],
    "notes":        ["student", "researcher", "productivity"],
    "data":         ["analyst", "researcher"],
    "automation":   ["productivity", "developer"],
}


def _tool_to_cap_tags(tool_name: str) -> List[str]:
    """Map a tool_name string to zero or more capability tags."""
    tags: List[str] = []
    tl = tool_name.lower()
    for fragment, tag in _TOOL_CAP_MAP:
        if fragment in tl and tag not in tags:
            tags.append(tag)
    return tags


def _score_mode(mode: Mode, cap_counter: Counter) -> float:
    """
    Compute a relevance score ∈ [0.0, 1.0] for *mode* given observed capability
    frequencies.

    Strategy:
      - For each preferred_tool of the mode, check if any of its capability tags
        appear in cap_counter.
      - score = Σ(cap_hits) / max(1, len(preferred_tools))
      - Capped at 1.0.
    """
    preferred: List[str] = mode.preferred_tools or []
    if not preferred:
        return 0.0

    total_count = sum(cap_counter.values()) or 1
    hit_weight = 0.0

    for tool_name in preferred:
        tags = _tool_to_cap_tags(tool_name)
        for tag in tags:
            hit_weight += cap_counter.get(tag, 0) / total_count

    score = hit_weight / len(preferred)
    return min(score, 1.0)


def _build_reason(mode: Mode, score: float, cap_counter: Counter) -> str:
    """Return a human-readable reason string for the suggestion."""
    top_caps = [cap for cap, _ in cap_counter.most_common(3)]
    cap_str = ", ".join(top_caps) if top_caps else "general usage"
    pct = int(round(score * 100))
    return (
        f"{pct}% match based on recent {cap_str} activity. "
        f"{mode.tagline or ''}"
    ).strip()


# ─── Public API ───────────────────────────────────────────────────────────────

@dataclass
class ModeSuggestion:
    mode: Mode
    score: float
    reason: str


async def suggest_modes(
    db: AsyncSession,
    *,
    profile_id: Optional[int] = None,
    window: int = 200,
    top_k: int = 3,
) -> List[ModeSuggestion]:
    """
    Return up to *top_k* mode suggestions for *profile_id*.

    Parameters
    ----------
    db          AsyncSession
    profile_id  Identifies the profile (None = global/legacy)
    window      Number of recent audit-log rows to analyse
    top_k       Maximum number of suggestions to return
    """
    # ── 1. Fetch recent audit rows ────────────────────────────────────────────
    recent_q = (
        select(AuditLog.tool_name)
        .where(AuditLog.status == "success")
        .order_by(AuditLog.timestamp.desc())
        .limit(window)
    )
    rows = (await db.execute(recent_q)).all()
    tool_counts: Counter = Counter(row[0] for row in rows)

    if not tool_counts:
        # No history – return first *top_k* built-ins as a default set
        modes = await list_modes(db, limit=top_k)
        return [
            ModeSuggestion(
                mode=m, score=0.0, reason="No usage history yet — try these to get started."
            )
            for m in modes
        ]

    # ── 2. Build capability-tag counter from tool usage ───────────────────────
    cap_counter: Counter = Counter()
    for tool_name, count in tool_counts.items():
        for tag in _tool_to_cap_tags(tool_name):
            cap_counter[tag] += count

    # ── 3. Find already-active mode ids ──────────────────────────────────────
    active_modes = await get_active_modes(db, profile_id)
    active_ids: Set[int] = {m.id for m in active_modes}

    # ── 4. Score all non-active, non-archived modes ────────────────────────────
    all_modes = await list_modes(db)
    candidates: List[ModeSuggestion] = []

    for mode in all_modes:
        if mode.id in active_ids:
            continue
        if mode.status == MODE_STATUS_ARCHIVED:
            continue
        score = _score_mode(mode, cap_counter)
        if score > 0.0:
            candidates.append(
                ModeSuggestion(
                    mode=mode,
                    score=score,
                    reason=_build_reason(mode, score, cap_counter),
                )
            )

    # ── 5. Sort and cap ───────────────────────────────────────────────────────
    candidates.sort(key=lambda s: s.score, reverse=True)
    result = candidates[:top_k]

    # If not enough non-zero suggestions, pad with unscored built-ins
    if len(result) < top_k:
        existing_ids = {s.mode.id for s in result} | active_ids
        for mode in all_modes:
            if len(result) >= top_k:
                break
            if mode.id in existing_ids or mode.status == MODE_STATUS_ARCHIVED:
                continue
            result.append(
                ModeSuggestion(
                    mode=mode,
                    score=0.0,
                    reason="You haven't used this mode yet — give it a try!",
                )
            )

    log.info(
        "[suggestion] suggested %d modes for profile_id=%s: %s",
        len(result),
        profile_id,
        [s.mode.slug for s in result],
    )
    return result
