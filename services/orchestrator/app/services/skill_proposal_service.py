"""
Skill Proposal Service – Phase 6 / 6.5 Skill Proposal Engine.

Converts ``DetectedPattern`` objects into persisted ``SkillProposal`` DB rows
and manages the proposal lifecycle (proposed → approved | rejected).

Phase 6.5 additions
───────────────────
• ``record_feedback()`` – capture useful / not_useful / ignored signals and
  update a running average ``feedback_score``.
• ``dismiss_proposal()`` – soft-hide a proposal without rejecting it.
• ``compute_relevance_score()`` – composite metric used for ranking.
• ``rank_proposals()`` – refresh scores and sort descending.
• ``list_proposals()`` – exclude dismissed by default; sort by relevance.

Design constraints
──────────────────
• NO automatic execution – approval only marks the row.
• NO code generation – proposals are observability artefacts only.
• Idempotent – re-scanning the same patterns does not create duplicate rows
  (keyed on ``pattern_id``).
• Read-only towards the guard – does NOT touch execution_guard behaviour.
"""

from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_proposal import SkillProposal
from app.services.pattern_detector import DetectedPattern, detect_patterns

log = logging.getLogger(__name__)


# ─── Title / description / why-suggested generation ──────────────────────────

def _make_title(pattern: DetectedPattern) -> str:
    """Generate a concise, human-readable proposal title."""
    tool = pattern.tool_name.replace("_", " ").title()
    # Shorten command template to first 60 chars for readability
    cmd = pattern.command_template.strip()
    cmd_short = cmd[:57] + "…" if len(cmd) > 60 else cmd
    return f"Automate: {tool} — \"{cmd_short}\""


def _make_description(pattern: DetectedPattern) -> str:
    """Generate a short explanation of the proposal."""
    lines = [
        f'Lani detected that you ran "{pattern.command_template}" '
        f"using **{pattern.tool_name}** {pattern.frequency} times "
        f"(confidence {pattern.confidence:.0%}).",
        "",
        "Approving this proposal marks it as accepted so Lani can "
        "suggest a shortcut or one-click automation in the future. "
        "No code will be generated or executed automatically.",
    ]
    return "\n".join(lines)


def _make_why_suggested(pattern: DetectedPattern) -> str:
    """
    Generate a concise machine-readable explanation of why this pattern was
    surfaced.  Shown in the UI under "Why Lani suggested this".
    """
    parts: List[str] = []
    parts.append(
        f"Detected {pattern.frequency} executions of "
        f"\"{pattern.command_template[:60]}\" via {pattern.tool_name}."
    )
    parts.append(f"Confidence score: {pattern.confidence:.0%}.")
    if pattern.risk_level and pattern.risk_level != "low":
        parts.append(f"Risk level: {pattern.risk_level}.")
    parts.append(
        "Approving lets Lani streamline this workflow — no code runs automatically."
    )
    return " ".join(parts)


def _estimate_time_saved(frequency: int) -> str:
    """Very rough heuristic: assume ~2 min per manual invocation."""
    minutes = frequency * 2
    if minutes < 60:
        return f"~{minutes} min based on {frequency} occurrences"
    hours = minutes // 60
    rem = minutes % 60
    if rem:
        return f"~{hours}h {rem}min based on {frequency} occurrences"
    return f"~{hours}h based on {frequency} occurrences"


# ─── Relevance scoring ────────────────────────────────────────────────────────

def compute_relevance_score(proposal: SkillProposal) -> float:
    """
    Composite relevance score in [0.0, 1.0].

    Formula
    -------
    base = confidence × log(1 + frequency) × feedback_boost
    normalised = base / log(1 + 10)   (10 occurrences ≈ max frequency bucket)
    clamped to [0.0, 1.0]

    feedback_boost = 1 + 0.5 × clamp(feedback_score, -1, 1)
      → ranges from 0.5 (feedback_score=-1) to 1.5 (feedback_score=+1)

    Zero if the proposal is dismissed, rejected, or has a suppressor.
    """
    if proposal.dismissed or proposal.status == "rejected":
        return 0.0
    if getattr(proposal, "suppressed_by", None):
        return 0.0

    confidence = float(proposal.confidence or 0.0)
    frequency = max(int(proposal.frequency or 0), 1)
    feedback_score = float(proposal.feedback_score or 0.0)

    feedback_boost = 1.0 + 0.5 * max(-1.0, min(1.0, feedback_score))
    base = confidence * math.log(1 + frequency) * feedback_boost
    normalised = base / math.log(1 + 10)
    return round(min(max(normalised, 0.0), 1.0), 4)


def rank_proposals(proposals: List[SkillProposal]) -> List[SkillProposal]:
    """
    Refresh ``relevance_score`` on each proposal and return them sorted
    by relevance descending (highest relevance first).

    Does NOT flush to DB — caller is responsible for persisting if needed.
    """
    for p in proposals:
        p.relevance_score = compute_relevance_score(p)
    proposals.sort(key=lambda p: p.relevance_score, reverse=True)
    return proposals


# ─── CRUD helpers ─────────────────────────────────────────────────────────────

async def _get_by_pattern_id(
    db: AsyncSession, pattern_id: str
) -> Optional[SkillProposal]:
    result = await db.execute(
        select(SkillProposal).where(SkillProposal.pattern_id == pattern_id)
    )
    return result.scalar_one_or_none()


async def _get_by_id(db: AsyncSession, proposal_id: int) -> Optional[SkillProposal]:
    result = await db.execute(
        select(SkillProposal).where(SkillProposal.id == proposal_id)
    )
    return result.scalar_one_or_none()


# ─── Public service API ────────────────────────────────────────────────────────

async def run_detection_and_propose(
    db: AsyncSession,
    chains: Optional[List[Dict[str, Any]]] = None,
    min_frequency: int = 3,
    min_confidence: float = 0.0,
) -> List[SkillProposal]:
    """
    Detect patterns and persist any new proposals.

    • Existing proposals (same ``pattern_id``) are NOT duplicated.
    • Only patterns in status 'proposed' are left untouched; rejected/approved
      ones are not re-created unless a new scan yields a different pattern_id.

    Parameters
    ----------
    db:
        Async DB session.
    chains:
        Optional list of chain dicts; pass ``None`` to use the ring buffer.
    min_frequency:
        Minimum chain count to surface a pattern.
    min_confidence:
        Discard patterns with confidence below this threshold.

    Returns
    -------
    List of newly created ``SkillProposal`` objects.
    """
    patterns = detect_patterns(
        chains=chains,
        min_frequency=min_frequency,
        min_confidence=min_confidence,
    )
    created: List[SkillProposal] = []

    for pattern in patterns:
        existing = await _get_by_pattern_id(db, pattern.pattern_id)
        if existing is not None:
            log.debug(
                "skill_proposals: pattern %s already has proposal id=%s (status=%s) – skipping",
                pattern.pattern_id,
                existing.id,
                existing.status,
            )
            continue

        suppressed_by = getattr(pattern, "suppressed_by", None)

        proposal = SkillProposal(
            pattern_id=pattern.pattern_id,
            title=_make_title(pattern),
            description=_make_description(pattern),
            steps=[s.__dict__ for s in pattern.steps],
            estimated_time_saved=_estimate_time_saved(pattern.frequency),
            risk_level=pattern.risk_level,
            status="proposed",
            chain_ids=pattern.chain_ids,
            frequency=pattern.frequency,
            confidence=pattern.confidence,
            # Phase 6.5 fields
            why_suggested=_make_why_suggested(pattern),
            suppressed_by=suppressed_by,
        )
        proposal.relevance_score = compute_relevance_score(proposal)
        db.add(proposal)
        created.append(proposal)

    if created:
        await db.flush()
        log.info("skill_proposals: created %d new proposals", len(created))

    return created


async def record_feedback(
    db: AsyncSession,
    proposal_id: int,
    signal: Literal["useful", "not_useful", "ignored"],
) -> Optional[SkillProposal]:
    """
    Record a user feedback signal on a proposal and update running stats.

    Signals
    -------
    ``useful``      → +1 toward feedback_score
    ``not_useful``  → -1 toward feedback_score
    ``ignored``     → no numeric change, but increments feedback_count and
                      updates last_feedback_at (records passive non-engagement)

    ``feedback_score`` is a running average clamped to [-1.0, +1.0].

    Returns the updated proposal, or None if not found.
    """
    proposal = await _get_by_id(db, proposal_id)
    if proposal is None:
        return None

    now = datetime.datetime.utcnow()
    proposal.last_feedback_at = now
    proposal.feedback_count = (proposal.feedback_count or 0) + 1

    if signal == "useful":
        delta = 1.0
    elif signal == "not_useful":
        delta = -1.0
    else:  # ignored
        delta = 0.0

    if delta != 0.0:
        # Exponential moving average with α = 1/feedback_count keeps score
        # in [-1, +1] without unbounded accumulation.
        count = proposal.feedback_count
        current = float(proposal.feedback_score or 0.0)
        proposal.feedback_score = round(
            current + (delta - current) / count, 4
        )

    # Refresh relevance after feedback
    proposal.relevance_score = compute_relevance_score(proposal)
    await db.flush()

    log.info(
        "skill_proposals: feedback '%s' recorded for proposal %d "
        "(score=%.3f, count=%d)",
        signal,
        proposal_id,
        proposal.feedback_score,
        proposal.feedback_count,
    )
    return proposal


async def dismiss_proposal(
    db: AsyncSession, proposal_id: int
) -> Optional[SkillProposal]:
    """
    Soft-hide a proposal.

    Sets ``dismissed=True`` and zeroes ``relevance_score`` so it is excluded
    from ranked lists by default.  Does NOT change ``status``.

    Returns the updated proposal, or None if not found.
    """
    proposal = await _get_by_id(db, proposal_id)
    if proposal is None:
        return None

    proposal.dismissed = True
    proposal.relevance_score = 0.0
    await db.flush()
    log.info("skill_proposals: proposal %d dismissed", proposal_id)
    return proposal


async def list_proposals(
    db: AsyncSession,
    status: Optional[str] = None,
    limit: int = 50,
    include_dismissed: bool = False,
    profile_id: Optional[int] = None,
) -> List[SkillProposal]:
    """
    Return proposals, optionally filtered by *status* and/or *profile_id*.

    Ordered by ``relevance_score`` descending (most relevant first).
    Dismissed proposals are excluded unless *include_dismissed* is True.
    """
    q = select(SkillProposal).limit(limit)
    if status:
        q = q.where(SkillProposal.status == status)
    if not include_dismissed:
        q = q.where(SkillProposal.dismissed.is_(False))
    if profile_id is not None:
        q = q.where(SkillProposal.profile_id == profile_id)
    result = await db.execute(q)
    proposals = list(result.scalars().all())
    return rank_proposals(proposals)


async def approve_proposal(
    db: AsyncSession, proposal_id: int
) -> Optional[SkillProposal]:
    """
    Mark a proposal as 'approved'.

    Safety: does NOT execute, install, or generate code.
    Returns the updated proposal, or None if not found.
    """
    proposal = await _get_by_id(db, proposal_id)
    if proposal is None:
        return None
    if proposal.status not in ("proposed",):
        log.warning(
            "skill_proposals: cannot approve proposal %d (current status=%s)",
            proposal_id,
            proposal.status,
        )
        return proposal  # return as-is; caller decides how to respond

    proposal.status = "approved"
    await db.flush()
    log.info("skill_proposals: proposal %d approved", proposal_id)
    return proposal


async def reject_proposal(
    db: AsyncSession, proposal_id: int
) -> Optional[SkillProposal]:
    """
    Mark a proposal as 'rejected'.

    Returns the updated proposal, or None if not found.
    """
    proposal = await _get_by_id(db, proposal_id)
    if proposal is None:
        return None
    proposal.status = "rejected"
    proposal.relevance_score = 0.0  # zero out so it sinks in any remaining lists
    await db.flush()
    log.info("skill_proposals: proposal %d rejected", proposal_id)
    return proposal


def proposal_to_dict(p: SkillProposal) -> Dict[str, Any]:
    """Serialise a SkillProposal to a plain dict for the API response."""
    return {
        "id": p.id,
        "pattern_id": p.pattern_id,
        "title": p.title,
        "description": p.description,
        "steps": p.steps,
        "estimated_time_saved": p.estimated_time_saved,
        "risk_level": p.risk_level,
        "status": p.status,
        "chain_ids": p.chain_ids,
        "frequency": p.frequency,
        "confidence": p.confidence,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        # Phase 6.5 fields
        "why_suggested": p.why_suggested,
        "dismissed": bool(p.dismissed),
        "feedback_score": float(p.feedback_score or 0.0),
        "feedback_count": int(p.feedback_count or 0),
        "last_feedback_at": (
            p.last_feedback_at.isoformat() if p.last_feedback_at else None
        ),
        "relevance_score": float(p.relevance_score or 0.0),
        "suppressed_by": p.suppressed_by,
    }
