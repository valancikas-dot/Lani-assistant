"""
World State Model – tracks live desktop and task context.

Lani maintains a rolling snapshot of the "world" to make better decisions
about what to do next and to surface context to the UI.

Tracked state
─────────────
  open_apps          – applications currently running
  active_windows     – window titles + app names
  recent_files       – last N files touched by Lani
  active_browser_tabs– current browser tab URLs (populated by browser_tools)
  last_actions       – ring-buffer of recent tool executions
  pending_tasks      – tasks that have been scheduled but not yet run
  clipboard          – last clipboard content Lani used (if any)
  last_screenshot    – path to latest screenshot (from vision tool)

All state is in-process (no DB persistence – state is ephemeral desktop
snapshot). The state is exposed via GET /api/v1/state.

Public API
──────────
  get_state()                        → WorldState (singleton)
  record_tool_execution(...)         → None
  update_open_apps(apps)             → None
  update_windows(windows)            → None
  add_browser_tab(url, title)        → None
  remove_browser_tab(url)            → None
  add_pending_task(task)             → None
  complete_pending_task(task_id)     → None
  set_clipboard(text)                → None
  set_last_screenshot(path)          → None
  snapshot()                         → dict  (JSON-serialisable)
"""

from __future__ import annotations

import collections
import datetime
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)

_MAX_RECENT_FILES   = 20
_MAX_LAST_ACTIONS   = 50
_MAX_BROWSER_TABS   = 30


# ─── Sub-models ───────────────────────────────────────────────────────────────

@dataclass
class AppInfo:
    name: str
    pid: Optional[int] = None
    is_frontmost: bool = False


@dataclass
class WindowInfo:
    app_name: str
    title: str
    window_id: Optional[str] = None
    is_minimized: bool = False


@dataclass
class BrowserTab:
    url: str
    title: str = ""
    active: bool = False
    added_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


@dataclass
class RecentFile:
    path: str
    tool: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    operation: str = "read"   # read | write | move | delete


@dataclass
class ActionRecord:
    tool: str
    status: str           # success | error | approval_required
    summary: str = ""
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    duration_ms: Optional[float] = None


@dataclass
class PendingTask:
    task_id: str
    description: str
    tool: str
    params: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())
    scheduled_at: Optional[str] = None


# ─── World State ──────────────────────────────────────────────────────────────

class WorldState:
    """Singleton holding all live world state."""

    def __init__(self) -> None:
        self.open_apps: List[AppInfo] = []
        self.active_windows: List[WindowInfo] = []
        self.recent_files: List[RecentFile] = []
        self.browser_tabs: List[BrowserTab] = []
        self.last_actions: Deque[ActionRecord] = collections.deque(maxlen=_MAX_LAST_ACTIONS)
        self.pending_tasks: Dict[str, PendingTask] = {}
        self.clipboard: Optional[str] = None
        self.last_screenshot: Optional[str] = None
        self.updated_at: str = datetime.datetime.utcnow().isoformat()

    # ── Open apps ─────────────────────────────────────────────────────────

    def update_open_apps(self, apps: List[Dict[str, Any]]) -> None:
        self.open_apps = [
            AppInfo(
                name=a.get("name", ""),
                pid=a.get("pid"),
                is_frontmost=a.get("is_frontmost", False),
            )
            for a in apps
        ]
        self._touch()

    # ── Windows ───────────────────────────────────────────────────────────

    def update_windows(self, windows: List[Dict[str, Any]]) -> None:
        self.active_windows = [
            WindowInfo(
                app_name=w.get("app_name", w.get("owner", "")),
                title=w.get("title", ""),
                window_id=str(w.get("window_id", "")),
                is_minimized=w.get("is_minimized", False),
            )
            for w in windows
        ]
        self._touch()

    # ── Recent files ──────────────────────────────────────────────────────

    def add_recent_file(self, path: str, tool: str, operation: str = "read") -> None:
        # Remove existing entry for same path to avoid duplicates
        self.recent_files = [f for f in self.recent_files if f.path != path]
        self.recent_files.insert(0, RecentFile(path=path, tool=tool, operation=operation))
        self.recent_files = self.recent_files[:_MAX_RECENT_FILES]
        self._touch()

    # ── Browser tabs ──────────────────────────────────────────────────────

    def add_browser_tab(self, url: str, title: str = "", active: bool = False) -> None:
        # Remove existing entry for same URL
        self.browser_tabs = [t for t in self.browser_tabs if t.url != url]
        self.browser_tabs.insert(0, BrowserTab(url=url, title=title, active=active))
        self.browser_tabs = self.browser_tabs[:_MAX_BROWSER_TABS]
        self._touch()

    def remove_browser_tab(self, url: str) -> None:
        self.browser_tabs = [t for t in self.browser_tabs if t.url != url]
        self._touch()

    def update_browser_tabs(self, tabs: List[Dict[str, Any]]) -> None:
        self.browser_tabs = [
            BrowserTab(
                url=t.get("url", ""),
                title=t.get("title", ""),
                active=t.get("active", False),
            )
            for t in tabs
        ][:_MAX_BROWSER_TABS]
        self._touch()

    # ── Last actions ──────────────────────────────────────────────────────

    def record_action(
        self,
        tool: str,
        status: str,
        summary: str = "",
        duration_ms: Optional[float] = None,
    ) -> None:
        self.last_actions.appendleft(
            ActionRecord(tool=tool, status=status, summary=summary, duration_ms=duration_ms)
        )
        self._touch()

    # ── Pending tasks ─────────────────────────────────────────────────────

    def add_pending_task(self, task: PendingTask) -> None:
        self.pending_tasks[task.task_id] = task
        self._touch()

    def complete_pending_task(self, task_id: str) -> None:
        self.pending_tasks.pop(task_id, None)
        self._touch()

    # ── Clipboard / screenshot ────────────────────────────────────────────

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text[:4096]  # cap at 4 KB
        self._touch()

    def set_last_screenshot(self, path: str) -> None:
        self.last_screenshot = path
        self._touch()

    # ── Snapshot ──────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "open_apps": [asdict(a) for a in self.open_apps],
            "active_windows": [asdict(w) for w in self.active_windows],
            "recent_files": [asdict(f) for f in self.recent_files],
            "browser_tabs": [asdict(t) for t in self.browser_tabs],
            "last_actions": [asdict(a) for a in self.last_actions],
            "pending_tasks": [asdict(t) for t in self.pending_tasks.values()],
            "clipboard_preview": (self.clipboard[:200] if self.clipboard else None),
            "last_screenshot": self.last_screenshot,
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _touch(self) -> None:
        self.updated_at = datetime.datetime.utcnow().isoformat()


# ─── Module-level singleton ───────────────────────────────────────────────────

_world_state: Optional[WorldState] = None


def get_state() -> WorldState:
    global _world_state
    if _world_state is None:
        _world_state = WorldState()
    return _world_state


# ─── Convenience helpers called from tool hooks ───────────────────────────────

def record_tool_execution(
    tool: str,
    status: str,
    summary: str = "",
    duration_ms: Optional[float] = None,
    file_paths: Optional[List[str]] = None,
    browser_url: Optional[str] = None,
    browser_title: str = "",
) -> None:
    """
    One-stop hook to update world state after any tool execution.

    Call this from command_router, plan_executor, workflow_executor.
    """
    ws = get_state()
    ws.record_action(tool=tool, status=status, summary=summary, duration_ms=duration_ms)

    if file_paths:
        operation = "write" if tool in {
            "create_file", "create_folder", "move_file", "sort_downloads",
            "create_project_scaffold", "create_code_file", "update_code_file",
            "create_presentation",
        } else "read"
        for path in file_paths:
            ws.add_recent_file(path=path, tool=tool, operation=operation)

    if browser_url:
        ws.add_browser_tab(url=browser_url, title=browser_title)
