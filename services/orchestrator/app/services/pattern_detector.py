"""
Pattern Detector – scan execution chains and surface repeated behaviour.

Design
──────
Works entirely on the in-memory audit-chain ring buffer so it is:
  • read-only  (never mutates guard state)
  • fast       (no DB I/O during detection)
  • testable   (can be called with an arbitrary chain list)

A *pattern* is a group of ≥ MIN_FREQUENCY chains that share:
  1.  The same ``tool_name``              (exact match)
  2.  Similar ``command`` text            (word-prefix overlap ≥ SIMILARITY_THRESHOLD)
  3.  The same ``execution_status``       (e.g. all "executed")

Confidence is computed from:
  - frequency (more occurrences → higher confidence)
  - command similarity within the group
  - recency (patterns from the last RECENCY_WINDOW_HOURS hours score higher)

Phase 6.5 additions
───────────────────
• ``ScanConfig`` dataclass for configurable thresholds (min_frequency,
  min_confidence, per_tool_min_frequency overrides).
• ``suppress_near_duplicates()`` post-scan pass that marks lower-ranked
  patterns as suppressed when two patterns share > DUPLICATE_SIMILARITY
  command overlap (prevents near-identical proposals cluttering the UI).

Output: a list of ``DetectedPattern`` dataclasses, sorted by confidence desc.
"""

from __future__ import annotations

import datetime
import hashlib
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ─── Tuning constants ─────────────────────────────────────────────────────────

MIN_FREQUENCY: int = 3          # minimum occurrences to form a pattern
SIMILARITY_THRESHOLD: float = 0.55   # word-overlap ratio required
RECENCY_WINDOW_HOURS: int = 72   # weight recent chains more heavily
MAX_PATTERNS: int = 20          # cap on patterns returned per scan
DUPLICATE_SIMILARITY: float = 0.80   # Phase 6.5: suppress near-duplicate patterns


# ─── Scan configuration ───────────────────────────────────────────────────────

@dataclass
class ScanConfig:
    """
    Configurable thresholds for a single detect_patterns() call.

    Attributes
    ----------
    min_frequency:
        Minimum chain count for a pattern to be surfaced.
        Defaults to ``MIN_FREQUENCY`` (3).
    min_confidence:
        Patterns with confidence below this threshold are discarded.
        Defaults to 0.0 (no filtering).
    per_tool_min_frequency:
        Override ``min_frequency`` for specific tool names.
        E.g. ``{"bash": 5, "python": 2}`` requires 5 bash runs but only 2
        python runs before a proposal is surfaced.
    """
    min_frequency: int = MIN_FREQUENCY
    min_confidence: float = 0.0
    per_tool_min_frequency: Dict[str, int] = field(default_factory=dict)


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class PatternStep:
    """One representative step in a detected pattern."""
    tool_name: str
    command_template: str   # representative / most-common command in this slot


@dataclass
class DetectedPattern:
    """
    A statistically significant recurring behaviour in the execution history.

    ``pattern_id`` is deterministic (SHA-1 of tool_name + command_template)
    so repeated scans do not generate duplicate proposals for the same pattern.
    """
    pattern_id: str
    tool_name: str
    command_template: str       # representative command (most common in group)
    steps: List[PatternStep]
    frequency: int              # number of matching chains in the scan window
    confidence: float           # 0.0 – 1.0
    risk_level: str             # inherited from most-common risk_level in group
    chain_ids: List[str]        # IDs of the chains that form this pattern
    first_seen: str             # ISO timestamp of oldest chain in group
    last_seen: str              # ISO timestamp of newest chain in group

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _word_tokens(text: str) -> set[str]:
    """Lower-cased words, stripping punctuation."""
    import re
    return set(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _similarity(a: str, b: str) -> float:
    """Jaccard-like word-overlap similarity between two command strings."""
    ta, tb = _word_tokens(a), _word_tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _stable_id(tool_name: str, command_template: str) -> str:
    """Deterministic pattern identifier that survives across restarts."""
    raw = f"{tool_name}::{command_template.strip().lower()[:120]}"
    return "pat_" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _most_common(values: list[str]) -> str:
    if not values:
        return ""
    return max(set(values), key=values.count)


def _recency_weight(ts_iso: str, now: datetime.datetime) -> float:
    """
    Returns a weight in [0.5, 1.0].
    Chains within RECENCY_WINDOW_HOURS get weight 1.0; older chains get 0.5.
    """
    try:
        ts = datetime.datetime.fromisoformat(ts_iso)
        age_hours = (now - ts).total_seconds() / 3600
        if age_hours <= RECENCY_WINDOW_HOURS:
            return 1.0
        # Linearly decay to 0.5 over the second RECENCY_WINDOW_HOURS period
        excess = age_hours - RECENCY_WINDOW_HOURS
        decay = max(0.0, 1.0 - excess / RECENCY_WINDOW_HOURS)
        return 0.5 + 0.5 * decay
    except Exception:
        return 0.5


def _compute_confidence(
    group: list[dict],
    now: datetime.datetime,
) -> float:
    """
    Confidence formula:
      freq_score    = min(frequency / 10, 1.0)        (10+ occurrences → max)
      recency_score = mean recency weight of chains in group
      similarity_score = mean pairwise similarity sampled from group
    Confidence = 0.4 * freq_score + 0.35 * recency_score + 0.25 * similarity_score
    """
    frequency = len(group)
    freq_score = min(frequency / 10.0, 1.0)

    timestamps = [c.get("timestamp", "") for c in group]
    recency_score = sum(_recency_weight(t, now) for t in timestamps) / max(len(timestamps), 1)

    commands = [c.get("command", "") for c in group]
    if len(commands) < 2:
        similarity_score = 1.0
    else:
        # Sample at most 10 pairs to keep O(n) for large groups
        pairs: list[tuple[str, str]] = []
        step = max(1, len(commands) // 5)
        for i in range(0, len(commands) - 1, step):
            pairs.append((commands[i], commands[i + 1]))
        pairs = pairs[:10]
        similarity_score = sum(_similarity(a, b) for a, b in pairs) / len(pairs)

    confidence = (
        0.40 * freq_score
        + 0.35 * recency_score
        + 0.25 * similarity_score
    )
    return round(min(confidence, 1.0), 4)


# ─── Grouping logic ───────────────────────────────────────────────────────────

def _group_chains(
    chains: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group chains by (tool_name, execution_status) then merge groups whose
    representative commands are similar enough.

    Returns a dict mapping a representative key → list of chain dicts.
    """
    # Phase 1 – bucket by tool + status
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for c in chains:
        tool = c.get("tool_name", "unknown")
        status = c.get("execution_status", "")
        # Only consider successfully executed chains for skill proposals
        if status not in ("executed", "success"):
            continue
        key = f"{tool}||{status}"
        buckets.setdefault(key, []).append(c)

    # Phase 2 – within each bucket, merge chains with similar commands
    merged: Dict[str, List[Dict[str, Any]]] = {}
    for bucket_key, items in buckets.items():
        # Keep list of (representative_command, group_list)
        groups: List[tuple[str, List[Dict[str, Any]]]] = []
        for chain in items:
            cmd = chain.get("command", "")
            placed = False
            for idx, (rep_cmd, grp) in enumerate(groups):
                if _similarity(cmd, rep_cmd) >= SIMILARITY_THRESHOLD:
                    grp.append(chain)
                    # Update representative to the most common command in the group
                    groups[idx] = (_most_common([c.get("command", "") for c in grp]), grp)
                    placed = True
                    break
            if not placed:
                groups.append((cmd, [chain]))
        for rep_cmd, grp in groups:
            key = _stable_id(grp[0].get("tool_name", ""), rep_cmd)
            merged[key] = grp

    return merged


# ─── Public API ───────────────────────────────────────────────────────────────

def suppress_near_duplicates(
    patterns: List[DetectedPattern],
    threshold: float = DUPLICATE_SIMILARITY,
) -> List[DetectedPattern]:
    """
    Post-scan pass: mark lower-ranked patterns as suppressed when their
    command template overlaps > *threshold* with a higher-ranked pattern of
    the same tool.

    Adds a ``suppressed_by`` attribute to the ``DetectedPattern`` dataclass
    instances (the attribute does not exist on the frozen dataclass schema –
    it is set dynamically here and picked up by the service layer).

    The input list is assumed to be sorted by confidence descending.
    Returns the same list (mutated in-place) for chaining convenience.
    """
    for i, pat in enumerate(patterns):
        if getattr(pat, "suppressed_by", None):
            continue  # already suppressed by an earlier pattern
        for j in range(i + 1, len(patterns)):
            other = patterns[j]
            if getattr(other, "suppressed_by", None):
                continue
            if pat.tool_name != other.tool_name:
                continue
            sim = _similarity(pat.command_template, other.command_template)
            if sim >= threshold:
                object.__setattr__(other, "suppressed_by", pat.pattern_id)
                log.debug(
                    "pattern_detector: suppressed near-duplicate pattern %s "
                    "(sim=%.2f) by %s",
                    other.pattern_id,
                    sim,
                    pat.pattern_id,
                )
    return patterns


def detect_patterns(
    chains: Optional[List[Dict[str, Any]]] = None,
    min_frequency: int = MIN_FREQUENCY,
    min_confidence: float = 0.0,
    config: Optional[ScanConfig] = None,
) -> List[DetectedPattern]:
    """
    Scan *chains* (or the live audit ring buffer if None) and return a sorted
    list of ``DetectedPattern`` objects with frequency ≥ *min_frequency*.

    Parameters
    ----------
    chains:
        List of chain record dicts (same shape as ``audit_chain.get_recent_chains()``).
        Pass ``None`` to use the live ring buffer.
    min_frequency:
        Minimum number of matching chains required to surface a pattern.
        Ignored when *config* is supplied.
    min_confidence:
        Discard patterns with confidence < this value.
        Ignored when *config* is supplied.
    config:
        A ``ScanConfig`` instance that bundles all threshold parameters.
        When supplied, *min_frequency* and *min_confidence* kwargs are ignored.

    Returns
    -------
    List of ``DetectedPattern``, sorted by confidence descending, with
    near-duplicate patterns annotated via ``suppressed_by`` attribute.
    """
    if config is not None:
        _min_freq = config.min_frequency
        _min_conf = config.min_confidence
        _per_tool = config.per_tool_min_frequency
    else:
        _min_freq = min_frequency
        _min_conf = min_confidence
        _per_tool = {}

    if chains is None:
        from app.services.audit_chain import get_recent_chains
        chains = get_recent_chains(200)

    if not chains:
        return []

    now = datetime.datetime.utcnow()
    groups = _group_chains(chains)
    patterns: List[DetectedPattern] = []

    for pat_key, group in groups.items():
        tool_name_rep = _most_common([c.get("tool_name", "unknown") for c in group])
        freq_threshold = _per_tool.get(tool_name_rep, _min_freq)
        if len(group) < freq_threshold:
            continue

        tool_names = [c.get("tool_name", "unknown") for c in group]
        commands = [c.get("command", "") for c in group]
        risk_levels = [c.get("risk_level", "low") for c in group]
        chain_ids = [c.get("chain_id", "") for c in group if c.get("chain_id")]
        timestamps = sorted(
            [c.get("timestamp", "") for c in group if c.get("timestamp")]
        )

        tool_name = _most_common(tool_names)
        command_template = _most_common(commands)
        risk_level = _most_common(risk_levels)

        confidence = _compute_confidence(group, now)
        if confidence < _min_conf:
            log.debug(
                "pattern_detector: skipping pattern %s (confidence=%.3f < min=%.3f)",
                pat_key,
                confidence,
                _min_conf,
            )
            continue

        pattern = DetectedPattern(
            pattern_id=pat_key,
            tool_name=tool_name,
            command_template=command_template,
            steps=[PatternStep(tool_name=tool_name, command_template=command_template)],
            frequency=len(group),
            confidence=confidence,
            risk_level=risk_level,
            chain_ids=chain_ids,
            first_seen=timestamps[0] if timestamps else now.isoformat(),
            last_seen=timestamps[-1] if timestamps else now.isoformat(),
        )
        patterns.append(pattern)

    patterns.sort(key=lambda p: p.confidence, reverse=True)
    patterns = patterns[:MAX_PATTERNS]

    # Phase 6.5: annotate near-duplicates (lower-ranked patterns with the same
    # tool and high command overlap are suppressed by the higher-confidence one)
    suppress_near_duplicates(patterns)

    return patterns
