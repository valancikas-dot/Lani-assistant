"""
example_plugin.py – Template / reference plugin for Lani.

Copy this file, rename it, and adjust the class to create your own tool.
This file is intentionally inactive – the class name starts with "_Example"
so it is NOT picked up by the auto-loader (which skips names with leading _).
"""

from __future__ import annotations

from app.tools.base import BaseTool
from app.schemas.commands import ToolResult


class _ExamplePlugin(BaseTool):
    """
    A minimal working example.  Rename to e.g. `JokePlugin` and remove
    the leading underscore to activate it.
    """

    name = "_example_plugin"
    description = "Example plugin – rename and activate to use."
    parameters = [
        {"name": "text", "type": "str", "required": True,
         "description": "Any text to echo back."},
    ]

    async def run(self, **kwargs) -> ToolResult:
        text = str(kwargs.get("text", ""))
        return ToolResult(ok=True, message=f"[example_plugin] echoed: {text}")
