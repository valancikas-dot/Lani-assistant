"""Pydantic schemas for the Computer Operator feature.

Design principles
─────────────────
- All actions are identified by a string literal type, never free-form shell.
- Every action carries structured, typed params (no raw command strings).
- The ``requires_approval`` flag is set per-action in the capability manifest
  and enforced at the route level before any action is executed.
- Risk levels are included so the frontend can render appropriate warnings:
    low    – purely informational / read-only (list_open_windows, take_screenshot)
    medium – side-effectful but recoverable (open_app, focus_window, clipboard)
    high   – potentially destructive (close_window, type_text, press_shortcut)
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ─── Action name literals ─────────────────────────────────────────────────────

OperatorActionName = Literal[
    # Window / app management
    "list_open_windows",
    "open_app",
    "focus_window",
    "minimize_window",
    "close_window",
    # File-system reveal
    "open_path",
    "reveal_file",
    # Clipboard
    "copy_to_clipboard",
    "paste_clipboard",
    # Keyboard
    "type_text",
    "press_shortcut",
    # Screen
    "take_screenshot",
]

RiskLevel = Literal["low", "medium", "high"]

Platform = Literal["macos", "windows", "linux", "unknown"]


# ─── Capability manifest ──────────────────────────────────────────────────────

class OperatorCapability(BaseModel):
    """Describes one supported operator action."""
    name: OperatorActionName
    description: str
    requires_approval: bool
    risk_level: RiskLevel
    params_schema: Dict[str, str] = Field(default_factory=dict)
    """Human-readable param name → description mapping for the UI."""
    supported_on: List[Platform]


class OperatorManifest(BaseModel):
    """Returned by GET /operator/capabilities."""
    platform: Platform
    platform_available: bool
    capabilities: List[OperatorCapability]


# ─── Action request ───────────────────────────────────────────────────────────

class OperatorActionRequest(BaseModel):
    """POST /operator/action body."""
    action: OperatorActionName
    params: Dict[str, Any] = Field(default_factory=dict)
    """
    Per-action params.  Expected shapes:

    open_app           : {"app_name": str}
    focus_window       : {"window_title": str}
    minimize_window    : {"window_title": str}
    close_window       : {"window_title": str}
    open_path          : {"path": str}
    reveal_file        : {"path": str}
    copy_to_clipboard  : {"text": str}
    paste_clipboard    : {}
    type_text          : {"text": str}
    press_shortcut     : {"keys": list[str]}   e.g. ["cmd", "shift", "4"]
    take_screenshot    : {"output_path": str?}  defaults to ~/Desktop/screenshot.png
    list_open_windows  : {}
    """


# ─── Action response ──────────────────────────────────────────────────────────

class OperatorActionResponse(BaseModel):
    ok: bool
    action: OperatorActionName
    message: str
    data: Optional[Any] = None
    """
    Action-specific result data.

    list_open_windows  → List[WindowInfo]
    take_screenshot    → {"path": str}
    paste_clipboard    → {"text": str}
    """
    requires_approval: bool = False
    approval_id: Optional[int] = None
    platform: Platform = "unknown"


# ─── Window info ──────────────────────────────────────────────────────────────

class WindowInfo(BaseModel):
    title: str
    app: str
    is_minimized: bool = False
    is_focused: bool = False


# ─── Screenshot result ────────────────────────────────────────────────────────

class ScreenshotResult(BaseModel):
    path: str
    taken_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow
    )
    width: Optional[int] = None
    height: Optional[int] = None
