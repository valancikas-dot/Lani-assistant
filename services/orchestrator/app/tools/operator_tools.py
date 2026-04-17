"""Computer Operator tool wrappers.

Each OperatorTool wraps one OperatorActionName, delegating execution to the
platform-specific operator while respecting the approval / audit pipeline.
"""

from __future__ import annotations

from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.services.operator import get_operator
from app.services.operator.macos_operator import DESTRUCTIVE_SHORTCUT_COMBOS
from app.tools.base import BaseTool


# ─── Shared base ─────────────────────────────────────────────────────────────

class _OperatorTool(BaseTool):
    """Wraps a single OperatorActionName as a BaseTool."""

    _action: str = ""

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        operator = get_operator()
        result = await operator.execute(self._action, params)  # type: ignore[arg-type]
        status = "success" if result.ok else "error"
        return ToolResult(
            tool_name=self.name,
            status=status,
            data=result.data,
            message=result.message,
        )


# ─── One class per action ─────────────────────────────────────────────────────

class ListOpenWindowsTool(_OperatorTool):
    name = "operator.list_open_windows"
    description = "List all visible application windows currently open on the desktop."
    requires_approval = False
    _action = "list_open_windows"


class OpenAppTool(_OperatorTool):
    name = "operator.open_app"
    description = "Open or bring to front an installed application by name (e.g. Safari, Chrome, Spotify, Mail, Terminal)."
    requires_approval = False
    _action = "open_app"
    parameters = [{"name": "app_name", "description": "The exact application name, e.g. 'Safari', 'Chrome', 'Spotify'", "required": True}]


class FocusWindowTool(_OperatorTool):
    name = "operator.focus_window"
    description = "Bring an application's windows to the foreground."
    requires_approval = False
    _action = "focus_window"
    parameters = [{"name": "app_name", "description": "Application name to focus", "required": True}]


class MinimizeWindowTool(_OperatorTool):
    name = "operator.minimize_window"
    description = "Minimise all windows belonging to an application."
    requires_approval = False
    _action = "minimize_window"
    parameters = [{"name": "app_name", "description": "Application name to minimize", "required": True}]


class CloseWindowTool(_OperatorTool):
    name = "operator.close_window"
    description = "Close all windows belonging to an application. Requires approval."
    requires_approval = True
    _action = "close_window"
    parameters = [{"name": "app_name", "description": "Application name to close", "required": True}]


class OpenPathTool(_OperatorTool):
    name = "operator.open_path"
    description = "Open a file or folder with its default application."
    requires_approval = False
    _action = "open_path"
    parameters = [{"name": "path", "description": "Absolute or ~ path to open", "required": True}]


class RevealFileTool(_OperatorTool):
    name = "operator.reveal_file"
    description = "Reveal a file or folder in Finder without opening it."
    requires_approval = False
    _action = "reveal_file"
    parameters = [{"name": "path", "description": "Absolute or ~ path to reveal", "required": True}]


class CopyToClipboardTool(_OperatorTool):
    name = "operator.copy_to_clipboard"
    description = "Copy provided text to the system clipboard."
    requires_approval = False
    _action = "copy_to_clipboard"
    parameters = [{"name": "text", "description": "Text to copy to clipboard", "required": True}]


class PasteClipboardTool(_OperatorTool):
    name = "operator.paste_clipboard"
    description = "Simulate Cmd+V in the currently focused window."
    requires_approval = False
    _action = "paste_clipboard"
    parameters = []



class TypeTextTool(_OperatorTool):
    name = "operator.type_text"
    description = "Type arbitrary text into the currently focused input field. Requires approval."
    requires_approval = True
    _action = "type_text"
    parameters = [{"name": "text", "description": "Text to type into the focused field", "required": True}]


class PressShortcutTool(_OperatorTool):
    """Approval requirement is determined dynamically based on the key combo."""

    name = "operator.press_shortcut"
    description = "Press a keyboard shortcut, e.g. cmd+c to copy, cmd+v to paste, cmd+space for Spotlight."
    requires_approval = False  # base default; route checks dynamically
    _action = "press_shortcut"
    parameters = [{"name": "keys", "description": "List of keys to press together, e.g. ['cmd', 'c'] or 'cmd+space'", "required": True}]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        raw_keys = params.get("keys", [])
        if isinstance(raw_keys, str):
            raw_keys = [k.strip() for k in raw_keys.replace("+", ",").split(",")]
        key_set = frozenset(k.lower().strip() for k in raw_keys if str(k).strip())
        if key_set in DESTRUCTIVE_SHORTCUT_COMBOS:
            return ToolResult(
                tool_name=self.name,
                status="approval_required",
                message=f"Shortcut {'+'.join(sorted(key_set))!r} requires approval before execution.",
            )
        return await super().run(params)


class TakeScreenshotTool(_OperatorTool):
    name = "operator.take_screenshot"
    description = "Capture the screen and save it as a PNG file on the Desktop."
    requires_approval = False
    _action = "take_screenshot"
    parameters = [{"name": "path", "description": "Optional save path. Defaults to ~/Desktop/screenshot.png", "required": False}]


# ─── Exported list for registry ───────────────────────────────────────────────

OPERATOR_TOOLS = [
    ListOpenWindowsTool(),
    OpenAppTool(),
    FocusWindowTool(),
    MinimizeWindowTool(),
    CloseWindowTool(),
    OpenPathTool(),
    RevealFileTool(),
    CopyToClipboardTool(),
    PasteClipboardTool(),
    TypeTextTool(),
    PressShortcutTool(),
    TakeScreenshotTool(),
]
