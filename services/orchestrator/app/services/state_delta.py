"""
State Delta – lightweight before/after world-state change tracking.

Captures a compact snapshot before and after each tool execution so
the audit trail can show exactly what changed.

Usage::

    before = capture_before()
    await tool.run(params)
    after = capture_after()
    delta = build_delta(before, after, triggering_action="delete_file", command="...")
    persist_delta(delta)  # stored in-memory ring buffer

Deltas are intentionally compact – only high-signal fields are compared.
"""

from __future__ import annotations

import collections
import datetime
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)

_MAX_DELTAS = 100  # in-memory ring buffer size


# ─── Snapshot ────────────────────────────────────────────────────────────────

@dataclass
class StateSnapshot:
    """Compact world-state snapshot for diff purposes."""
    open_app_count: int = 0
    recent_file_paths: List[str] = field(default_factory=list)
    browser_tab_urls: List[str] = field(default_factory=list)
    last_action_tool: Optional[str] = None
    last_action_status: Optional[str] = None
    pending_task_count: int = 0
    clipboard_hash: Optional[str] = None
    captured_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


# ─── Delta ────────────────────────────────────────────────────────────────────

@dataclass
class StateDelta:
    """Structured diff between two world-state snapshots."""
    triggering_action: str
    command: str
    before_summary: str
    after_summary: str
    changed_fields: List[str]
    before: Dict[str, Any]
    after: Dict[str, Any]
    recorded_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── In-memory ring buffer ────────────────────────────────────────────────────

_delta_buffer: Deque[StateDelta] = collections.deque(maxlen=_MAX_DELTAS)


def get_recent_deltas(n: int = 20) -> List[Dict[str, Any]]:
    """Return the n most recent state deltas as dicts."""
    return [d.to_dict() for d in list(_delta_buffer)[:n]]


def persist_delta(delta: StateDelta) -> None:
    """Append a delta to the in-memory ring buffer."""
    _delta_buffer.appendleft(delta)


# ─── Capture helpers ─────────────────────────────────────────────────────────

def capture_before() -> StateSnapshot:
    """Capture a lightweight world-state snapshot before tool execution."""
    return _snapshot_world_state()


def capture_after() -> StateSnapshot:
    """Capture a lightweight world-state snapshot after tool execution."""
    return _snapshot_world_state()


def _snapshot_world_state() -> StateSnapshot:
    try:
        from app.services.world_state import get_state
        ws = get_state()
        clipboard_hash: Optional[str] = None
        if ws.clipboard:
            import hashlib
            clipboard_hash = hashlib.md5(ws.clipboard.encode(), usedforsecurity=False).hexdigest()[:8]
        return StateSnapshot(
            open_app_count=len(ws.open_apps),
            recent_file_paths=[f.path for f in ws.recent_files[:5]],
            browser_tab_urls=[t.url for t in ws.browser_tabs[:5]],
            last_action_tool=ws.last_actions[0].tool if ws.last_actions else None,
            last_action_status=ws.last_actions[0].status if ws.last_actions else None,
            pending_task_count=len(ws.pending_tasks),
            clipboard_hash=clipboard_hash,
        )
    except Exception as exc:
        log.warning("[state_delta] snapshot failed: %s", exc)
        return StateSnapshot()


# ─── Builder ─────────────────────────────────────────────────────────────────

def build_delta(
    before: StateSnapshot,
    after: StateSnapshot,
    *,
    triggering_action: str,
    command: str,
) -> StateDelta:
    """Compare two snapshots and produce a ``StateDelta``."""
    changed: List[str] = []

    if before.open_app_count != after.open_app_count:
        changed.append("open_apps")
    if before.recent_file_paths != after.recent_file_paths:
        changed.append("recent_files")
    if before.browser_tab_urls != after.browser_tab_urls:
        changed.append("browser_tabs")
    if before.last_action_tool != after.last_action_tool:
        changed.append("last_action")
    if before.pending_task_count != after.pending_task_count:
        changed.append("pending_tasks")
    if before.clipboard_hash != after.clipboard_hash:
        changed.append("clipboard")

    def _summary(snap: StateSnapshot) -> str:
        parts = [f"apps={snap.open_app_count}"]
        if snap.last_action_tool:
            parts.append(f"last={snap.last_action_tool}({snap.last_action_status})")
        if snap.recent_file_paths:
            parts.append(f"files={snap.recent_file_paths[0]!r}")
        return " ".join(parts)

    delta = StateDelta(
        triggering_action=triggering_action,
        command=command,
        before_summary=_summary(before),
        after_summary=_summary(after),
        changed_fields=changed,
        before=asdict(before),
        after=asdict(after),
    )
    persist_delta(delta)
    return delta
