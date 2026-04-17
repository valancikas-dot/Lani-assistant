"""
Self-edit tools – let Lani read and modify her own source code.

These tools are restricted to the orchestrator's own directory tree so Lani
cannot accidentally modify unrelated files on the system.

Tools:
  read_self         – read any file inside the orchestrator source tree
  edit_self         – write/replace a file inside the orchestrator source tree
                      (uses LLM to generate the new content if instruction given)
  restart_backend   – gracefully restart the backend process so changes take effect
  list_self         – list files inside a given subdirectory of the orchestrator
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.services.llm_text_service import complete_text
from app.tools.base import BaseTool

# Root of the orchestrator source – all writes are confined here.
_SELF_ROOT = Path(__file__).parent.parent.resolve()  # .../services/orchestrator/app


def _within_self(path_str: str) -> Path | None:
    """Return resolved Path only if it stays within the orchestrator app tree."""
    target = (_SELF_ROOT / path_str).resolve()
    try:
        target.relative_to(_SELF_ROOT)
        return target
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────

class ReadSelfTool(BaseTool):
    name = "read_self"
    description = (
        "Read the content of one of Lani's own source files so you can understand "
        "what the code currently does before suggesting changes."
    )
    requires_approval = False
    parameters = [
        {"name": "path", "description": "Relative path inside the orchestrator app, e.g. 'tools/operator_tools.py' or 'services/voice_service.py'", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        rel = str(params.get("path", "")).strip()
        if not rel:
            return ToolResult(tool_name=self.name, status="error", message="'path' is required.")

        target = _within_self(rel)
        if target is None:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Path '{rel}' is outside the allowed area.")
        if not target.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"File not found: {rel}")
        if not target.is_file():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"'{rel}' is a directory, not a file.")

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        # Truncate very long files to avoid token overflow
        MAX_LINES = 300
        truncated = len(lines) > MAX_LINES
        preview = "\n".join(lines[:MAX_LINES])
        if truncated:
            preview += f"\n\n... [{len(lines) - MAX_LINES} more lines truncated]"

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"Read {len(lines)} lines from '{rel}'.",
            data={"path": rel, "content": preview, "total_lines": len(lines), "truncated": truncated},
        )


class ListSelfTool(BaseTool):
    name = "list_self"
    description = (
        "List Lani's own source files in a given subdirectory. "
        "Use this to explore the codebase before reading or editing."
    )
    requires_approval = False
    parameters = [
        {"name": "subdir", "description": "Subdirectory to list, e.g. 'tools', 'services', 'api/routes'. Defaults to root.", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        subdir = str(params.get("subdir", "")).strip() or "."
        target = _within_self(subdir)
        if target is None:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"'{subdir}' is outside the allowed area.")
        if not target.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Directory not found: {subdir}")

        files = []
        for p in sorted(target.rglob("*.py")):
            try:
                rel = str(p.relative_to(_SELF_ROOT))
                if "__pycache__" not in rel:
                    files.append(rel)
            except ValueError:
                pass

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"Found {len(files)} Python file(s) in '{subdir}'.",
            data={"subdir": subdir, "files": files},
        )


class EditSelfTool(BaseTool):
    name = "edit_self"
    description = (
        "Modify or update one of Lani's own Python source files based on a plain-language instruction. "
        "Lani uses GPT-4o to rewrite the file. Use this when asked to: "
        "change her behavior, add a new tool, fix a bug in her code, or improve how she works. "
        "Always requires user approval before writing."
    )
    requires_approval = True
    parameters = [
        {"name": "path", "description": "Relative path of the file to edit inside the orchestrator, e.g. 'tools/operator_tools.py' or 'services/voice_service.py'", "required": True},
        {"name": "instruction", "description": "Plain-language description of the change, e.g. 'add a new GreetTool class that says hello' or 'make the TTS voice default to shimmer'", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        rel = str(params.get("path", "")).strip()
        instruction = str(params.get("instruction", "")).strip()

        if not rel or not instruction:
            return ToolResult(tool_name=self.name, status="error",
                              message="Both 'path' and 'instruction' are required.")

        target = _within_self(rel)
        if target is None:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Path '{rel}' is outside the allowed area.")
        if not target.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"File not found: {rel}")

        current_code = target.read_text(encoding="utf-8", errors="replace")

        try:
            from app.core.config import settings as cfg
            new_code = await complete_text(
                openai_api_key=getattr(cfg, "OPENAI_API_KEY", "") or "",
                openai_model=getattr(cfg, "AGENT_MODEL", "o3"),
                openai_messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Lani's code editor. You receive an existing Python file and an instruction. "
                            "Return ONLY the complete updated Python file content, no markdown, no explanation, no ```python blocks. "
                            "Preserve all existing functionality unless the instruction says to remove it. "
                            "Keep the same code style and imports."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"File: {rel}\n\n"
                            f"Current content:\n{current_code}\n\n"
                            f"Instruction: {instruction}\n\n"
                            "Return the complete updated file:"
                        ),
                    },
                ],
                max_tokens=8192,
                temperature=0.1,
            )
            # Strip accidental markdown fences
            if new_code.startswith("```"):
                lines = new_code.splitlines()
                new_code = "\n".join(
                    l for l in lines
                    if not l.strip().startswith("```")
                )

            # Make a backup
            backup_path = target.with_suffix(target.suffix + ".bak")
            backup_path.write_text(current_code, encoding="utf-8")

            target.write_text(new_code, encoding="utf-8")

            return ToolResult(
                tool_name=self.name,
                status="success",
                message=(
                    f"Updated '{rel}' successfully. "
                    f"Backup saved as '{backup_path.name}'. "
                    f"Run restart_backend to apply changes."
                ),
                data={"path": rel, "backup": str(backup_path.name), "lines_written": len(new_code.splitlines())},
            )

        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=f"Edit failed: {exc}")


class RestartBackendTool(BaseTool):
    name = "restart_backend"
    description = (
        "Restart the Lani backend server so that any code changes take effect immediately. "
        "Use this after edit_self."
    )
    requires_approval = True
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        try:
            # Schedule restart after a short delay so this response can be sent first
            async def _do_restart() -> None:
                await asyncio.sleep(1.5)
                os.execv(sys.executable, [sys.executable] + sys.argv)

            asyncio.create_task(_do_restart())

            return ToolResult(
                tool_name=self.name,
                status="success",
                message="Backend is restarting in 1.5 seconds. Reconnect in a moment.",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))
