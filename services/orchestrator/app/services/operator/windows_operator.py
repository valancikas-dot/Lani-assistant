"""Windows operator stub — returns honest 'not supported' messages."""

from __future__ import annotations

from typing import Any, Dict, List

from app.schemas.operator import OperatorCapability, OperatorActionName, Platform
from app.services.operator.base import OperatorBase, OperatorResult, register_operator

_ALL_ACTIONS: List[OperatorActionName] = [
    "list_open_windows", "open_app", "focus_window", "minimize_window",
    "close_window", "open_path", "reveal_file", "copy_to_clipboard",
    "paste_clipboard", "type_text", "press_shortcut", "take_screenshot",
]

_DESCRIPTIONS: Dict[OperatorActionName, str] = {
    "list_open_windows": "List all visible windows (not yet supported on Windows).",
    "open_app": "Open an application (not yet supported on Windows).",
    "focus_window": "Focus a window (not yet supported on Windows).",
    "minimize_window": "Minimise a window (not yet supported on Windows).",
    "close_window": "Close a window (not yet supported on Windows).",
    "open_path": "Open a path (not yet supported on Windows).",
    "reveal_file": "Reveal a file in Explorer (not yet supported on Windows).",
    "copy_to_clipboard": "Copy text to clipboard (not yet supported on Windows).",
    "paste_clipboard": "Paste clipboard (not yet supported on Windows).",
    "type_text": "Type text (not yet supported on Windows).",
    "press_shortcut": "Press a shortcut (not yet supported on Windows).",
    "take_screenshot": "Take a screenshot (not yet supported on Windows).",
}


class WindowsOperator(OperatorBase):
    sys_platform = "win32"
    platform_display: Platform = "windows"

    def get_capabilities(self) -> List[OperatorCapability]:
        return [
            OperatorCapability(
                name=action,
                description=_DESCRIPTIONS[action],
                requires_approval=False,
                risk_level="low",
                params_schema={},
                supported_on=["windows"],  # planned, not yet implemented
            )
            for action in _ALL_ACTIONS
        ]

    def build_manifest(self):  # type: ignore[override]
        from app.schemas.operator import OperatorManifest
        return OperatorManifest(
            platform="windows",
            platform_available=False,
            capabilities=self.get_capabilities(),
        )

    async def execute(
        self, action: OperatorActionName, params: Dict[str, Any]
    ) -> OperatorResult:
        return OperatorResult(
            ok=False,
            message="Computer Operator is not yet supported on Windows.",
        )


register_operator(WindowsOperator())
