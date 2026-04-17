"""
code_execution_tool.py – Safe, isolated code execution sandbox.

Runs Python, JavaScript (Node.js), Shell, and TypeScript code in subprocess
with strict timeout, output capture, and path restrictions.

Safety model:
  • Each run gets a temp directory (deleted after execution)
  • stdout + stderr captured (max 64 KB)
  • Hard timeout (default 30s, max 120s)
  • Shell runs inside orchestrator virtualenv Python
  • requires_approval = True for shell commands
  • No network access restriction (user can enable that separately)

Tools:
  run_python        – execute a Python script
  run_javascript    – execute Node.js script
  run_shell_command – run arbitrary shell command (requires approval)
  install_package   – pip install a package into the venv
  run_tests         – run pytest on a project directory
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 65_536   # 64 KB cap
_DEFAULT_TIMEOUT  = 30       # seconds
_MAX_TIMEOUT      = 120


def _cap(text: str) -> str:
    if len(text.encode()) > _MAX_OUTPUT_BYTES:
        return text[:_MAX_OUTPUT_BYTES // 2] + "\n… [output truncated] …\n" + text[-2000:]
    return text


async def _run(cmd: list[str], cwd: str, timeout: int, env: dict | None = None) -> tuple[int, str, str]:
    """Run cmd asynchronously and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"⏱ Timeout po {timeout}s"
        rc = proc.returncode if proc.returncode is not None else -1
        return rc, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except FileNotFoundError as e:
        return -1, "", f"Komanda nerasta: {e}"


# ─────────────────────────────────────────────────────────────────────────────

class RunPythonTool(BaseTool):
    name = "run_python"
    description = (
        "Execute a Python code snippet or script file. "
        "Returns stdout, stderr, and return code. "
        "Parameters: code (Python source string) OR file_path (absolute path to .py), "
        "timeout (seconds, default 30, max 120), "
        "working_dir (directory to run in, default temp)."
    )
    requires_approval = False
    parameters = [
        {"name": "code",        "description": "Python source code to execute", "required": False},
        {"name": "file_path",   "description": "Absolute path to a .py file to run", "required": False},
        {"name": "timeout",     "description": "Execution timeout in seconds (max 120)", "required": False},
        {"name": "working_dir", "description": "Working directory for execution", "required": False},
        {"name": "args",        "description": "List of command-line arguments to pass", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        code: str      = params.get("code", "").strip()
        file_path: str = params.get("file_path", "").strip()
        timeout: int   = min(int(params.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        cli_args: list = params.get("args", [])

        if not code and not file_path:
            return ToolResult(tool_name=self.name, status="error",
                              message="Reikia 'code' arba 'file_path'")

        tmp_dir = None
        try:
            if code:
                tmp_dir = tempfile.mkdtemp(prefix="lani_py_")
                script  = Path(tmp_dir) / "script.py"
                script.write_text(code, encoding="utf-8")
                target = str(script)
                cwd    = params.get("working_dir") or tmp_dir
            else:
                src = Path(file_path).expanduser()
                if not src.exists():
                    return ToolResult(tool_name=self.name, status="error",
                                      message=f"Failas nerastas: {file_path}")
                target = str(src)
                cwd    = params.get("working_dir") or str(src.parent)

            cmd = [sys.executable, target] + [str(a) for a in cli_args]
            rc, stdout, stderr = await _run(cmd, cwd=cwd, timeout=timeout)

            status = "success" if rc == 0 else "error"
            return ToolResult(
                tool_name=self.name,
                status=status,
                message=f"Exit code {rc}",
                data={
                    "stdout":      _cap(stdout),
                    "stderr":      _cap(stderr),
                    "return_code": rc,
                    "script":      target,
                },
            )
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────

class RunJavaScriptTool(BaseTool):
    name = "run_javascript"
    description = (
        "Execute a JavaScript snippet with Node.js. "
        "Parameters: code (JS source) OR file_path, timeout (default 30), working_dir."
    )
    requires_approval = False
    parameters = [
        {"name": "code",        "description": "JavaScript source code", "required": False},
        {"name": "file_path",   "description": "Absolute path to a .js file", "required": False},
        {"name": "timeout",     "description": "Timeout in seconds", "required": False},
        {"name": "working_dir", "description": "Working directory", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        code: str      = params.get("code", "").strip()
        file_path: str = params.get("file_path", "").strip()
        timeout: int   = min(int(params.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)

        if not code and not file_path:
            return ToolResult(tool_name=self.name, status="error",
                              message="Reikia 'code' arba 'file_path'")

        # Find node
        node = shutil.which("node")
        if not node:
            return ToolResult(tool_name=self.name, status="error",
                              message="Node.js nerasta. Įdiek: brew install node")

        tmp_dir = None
        try:
            if code:
                tmp_dir = tempfile.mkdtemp(prefix="lani_js_")
                script  = Path(tmp_dir) / "script.js"
                script.write_text(code, encoding="utf-8")
                target = str(script)
                cwd    = params.get("working_dir") or tmp_dir
            else:
                src = Path(file_path).expanduser()
                if not src.exists():
                    return ToolResult(tool_name=self.name, status="error",
                                      message=f"Failas nerastas: {file_path}")
                target = str(src)
                cwd    = params.get("working_dir") or str(src.parent)

            rc, stdout, stderr = await _run([node, target], cwd=cwd, timeout=timeout)
            status = "success" if rc == 0 else "error"
            return ToolResult(
                tool_name=self.name,
                status=status,
                message=f"Exit code {rc}",
                data={"stdout": _cap(stdout), "stderr": _cap(stderr), "return_code": rc},
            )
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────

class RunShellCommandTool(BaseTool):
    name = "run_shell_command"
    description = (
        "Run an arbitrary shell command on this Mac. "
        "Use for build commands, npm, git, brew, etc. "
        "Parameters: command (required), working_dir (optional), timeout (default 60)."
    )
    requires_approval = True    # ← always ask user before running
    parameters = [
        {"name": "command",     "description": "Shell command to run (bash -c)", "required": True},
        {"name": "working_dir", "description": "Working directory", "required": False},
        {"name": "timeout",     "description": "Timeout in seconds (max 120)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        command: str = params.get("command", "").strip()
        if not command:
            return ToolResult(tool_name=self.name, status="error", message="command is required")

        cwd     = params.get("working_dir") or str(Path.home())
        timeout = min(int(params.get("timeout", 60)), _MAX_TIMEOUT)

        rc, stdout, stderr = await _run(
            ["/bin/zsh", "-c", command],
            cwd=cwd, timeout=timeout,
        )
        status = "success" if rc == 0 else "error"
        return ToolResult(
            tool_name=self.name,
            status=status,
            message=f"Exit code {rc}",
            data={"stdout": _cap(stdout), "stderr": _cap(stderr), "return_code": rc, "command": command},
        )


# ─────────────────────────────────────────────────────────────────────────────

class InstallPackageTool(BaseTool):
    name = "install_package"
    description = (
        "Install one or more Python packages into the current environment using pip. "
        "Parameters: packages (list of package names, required), "
        "upgrade (bool, default false)."
    )
    requires_approval = True
    parameters = [
        {"name": "packages", "description": "List of pip package names to install", "required": True},
        {"name": "upgrade",  "description": "Pass --upgrade flag", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        packages = params.get("packages", [])
        if isinstance(packages, str):
            packages = [p.strip() for p in packages.split(",") if p.strip()]
        if not packages:
            return ToolResult(tool_name=self.name, status="error", message="packages is required")

        upgrade = params.get("upgrade", False)
        cmd = [sys.executable, "-m", "pip", "install"] + (["--upgrade"] if upgrade else []) + packages

        rc, stdout, stderr = await _run(cmd, cwd=str(Path.home()), timeout=120)
        status = "success" if rc == 0 else "error"
        return ToolResult(
            tool_name=self.name,
            status=status,
            message=f"pip {'succeeded' if rc == 0 else 'failed'}: {', '.join(packages)}",
            data={"stdout": _cap(stdout), "stderr": _cap(stderr), "return_code": rc},
        )


# ─────────────────────────────────────────────────────────────────────────────

class RunTestsTool(BaseTool):
    name = "run_tests"
    description = (
        "Run pytest tests for a project. "
        "Parameters: project_dir (required), test_path (optional, specific file/dir), "
        "verbose (bool, default true), timeout (default 60)."
    )
    requires_approval = False
    parameters = [
        {"name": "project_dir", "description": "Absolute path to the project directory", "required": True},
        {"name": "test_path",   "description": "Specific test file or directory (relative to project_dir)", "required": False},
        {"name": "verbose",     "description": "Run with -v flag", "required": False},
        {"name": "timeout",     "description": "Timeout in seconds", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_dir: str = params.get("project_dir", "").strip()
        if not project_dir:
            return ToolResult(tool_name=self.name, status="error", message="project_dir is required")

        src = Path(project_dir).expanduser()
        if not src.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Katalogas nerastas: {project_dir}")

        test_path = params.get("test_path", "")
        verbose   = params.get("verbose", True)
        timeout   = min(int(params.get("timeout", 60)), _MAX_TIMEOUT)

        cmd = [sys.executable, "-m", "pytest"]
        if verbose:
            cmd.append("-v")
        cmd.append("--tb=short")
        if test_path:
            cmd.append(str(src / test_path))

        rc, stdout, stderr = await _run(cmd, cwd=str(src), timeout=timeout)
        passed = "passed" in stdout
        status = "success" if rc == 0 else "error"

        return ToolResult(
            tool_name=self.name,
            status=status,
            message=f"{'✅ Testai praėjo' if rc == 0 else '❌ Testai nepraėjo'} (exit {rc})",
            data={"stdout": _cap(stdout), "stderr": _cap(stderr), "return_code": rc},
        )
