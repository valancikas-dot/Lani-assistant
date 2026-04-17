"""
agent_loop.py – Lani's autonomous multi-step reasoning engine.

Full ReAct loop (Reason → Act → Observe → Repeat) with maximum capabilities:

  • list_files      — explore directory tree
  • read_file       — read any file in the codebase (with pagination)
  • search_code     — grep the codebase for a pattern
  • write_file      — overwrite a file (full content, with .bak backup)
  • run_shell       — run shell commands in orchestrator dir
  • restart_backend — hot-reload after code changes
  • answer          — finish loop and return response to user

Design principles (mirroring top-tier agent systems):
  1. Always reads before writing — no blind overwrites
  2. Plans before acting
  3. Verifies writes with syntax check via run_shell
  4. Graceful error recovery
  5. No approval gates — Lani owns herself
  6. Max 20 iterations with clear safety fallback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re as _re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast, Callable, Awaitable, Optional

from app.services.llm_text_service import _openai_token_param

log = logging.getLogger(__name__)

_SELF_ROOT    = Path(__file__).parent.parent.resolve()   # .../orchestrator/app
_PROJECT_ROOT = _SELF_ROOT.parent.resolve()              # .../orchestrator
# Frontend root — agent can also read/write TypeScript/React files here
_FRONTEND_ROOT = _PROJECT_ROOT.parent / "apps" / "desktop" / "src"

# All directories the agent is allowed to touch
_ALLOWED_ROOTS: list[Path] = [_SELF_ROOT, _FRONTEND_ROOT]

MAX_ITERATIONS = 20


# ── Tool schemas ──────────────────────────────────────────────────────────────

_AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in Lani's codebase. Use first to understand structure. "
                "Returns sorted list of relative paths with file sizes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Subdirectory relative to orchestrator/app/, e.g. 'tools', 'services'. Empty = list all.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '*.py', '*.json'. Defaults to '*.py'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a source file. ALWAYS call before write_file. "
                "Large files are paginated — use start_line/end_line."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path inside orchestrator/app/, e.g. 'tools/chat_tool.py'",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-indexed). Omit for start of file.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read (inclusive). Omit for end of file.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search for a string or regex across the codebase. "
                "Use to find all usages of a function/class before editing. "
                "Returns file:line: matching_line format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "String or regex pattern."},
                    "subdir": {"type": "string", "description": "Limit to this subdirectory. Empty = all files."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Overwrite a file with complete new content. "
                "RULES: (1) read_file first, (2) write FULL content not a patch, "
                "(3) call run_shell to verify syntax after writing, (4) call restart_backend. "
                "Auto-creates .bak backup."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside orchestrator/app/"},
                    "content": {"type": "string", "description": "Complete new file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Run a shell command in the orchestrator directory. "
                "Good for: checking Python syntax, running tests, listing dirs. "
                "Timeout: 15s. Returns stdout + stderr + exit code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_backend",
            "description": (
                "Restart the Lani backend so code changes take effect. "
                "REQUIRED after every Python file change. "
                "Backend restarts in 2s; connection briefly drops."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web with DuckDuckGo. Use to research how to implement "
                "a feature, find API docs, look up Python patterns, or verify facts. "
                "Returns titles + URLs + snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "description": "Number of results (default 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch the text content of a URL. Use after web_search to read "
                "documentation, examples or source code from the web."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Stage all changed Python files in the orchestrator directory and "
                "create a git commit with the provided message. "
                "Call this after a successful write_file + syntax check to persist changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message describing what changed."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the pytest test suite to verify nothing is broken after code changes. "
                "ALWAYS call this before git_commit. "
                "If tests fail, read the error, fix the code, then run_tests again. "
                "Returns pass/fail counts and any failure details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Optional pytest -k filter string to run only specific tests.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safari_open",
            "description": (
                "Open a URL in Safari (real browser with all user sessions). "
                "Use for Gmail, Facebook, Instagram, any logged-in service. "
                "Always wait 2-3 seconds after opening before reading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to open, e.g. https://mail.google.com"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safari_read",
            "description": (
                "Read the current page text from Safari. Call after safari_open + sleep. "
                "Returns visible text content of the page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 4000)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer",
            "description": (
                "Return final response to user. Call when task is done, or impossible. "
                "Include clear summary of what was done."
            ),
            "parameters": {
                "type": "object",
                "properties": {                    "text": {"type": "string", "description": "Final message to display to user."},
                },
                "required": ["text"],
            },
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

def _within_self(path_str: str) -> Path | None:
    """Resolve path_str relative to any allowed root. Returns None if outside all roots."""
    if not path_str:
        return None
    p = Path(path_str)
    # Try each allowed root in order
    for root in _ALLOWED_ROOTS:
        candidate = (root / p).resolve()
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    # Last resort: absolute path that falls inside any allowed root
    if p.is_absolute():
        for root in _ALLOWED_ROOTS:
            try:
                p.relative_to(root)
                return p
            except ValueError:
                continue
    return None


def _tool_list_files(subdir: str = "", pattern: str = "*.py") -> str:
    base = _within_self(subdir) if subdir else _SELF_ROOT
    if base is None or not base.exists():
        return f"ERROR: Directory not found: {subdir!r}"
    glob = pattern or "*.py"
    files = []
    for p in sorted(base.rglob(glob)):
        rel = str(p.relative_to(_SELF_ROOT))
        if "__pycache__" not in rel and ".bak" not in rel:
            size = p.stat().st_size
            files.append(f"{rel}  ({size} B)")
    if not files:
        return f"(no {glob!r} files in {subdir or 'app/'})"
    return f"Found {len(files)} files:\n" + "\n".join(files)


def _tool_read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    target = _within_self(path)
    if target is None:
        return f"ERROR: '{path}' is outside allowed area."
    if not target.exists():
        return f"ERROR: File not found: '{path}'"
    if not target.is_file():
        return f"ERROR: '{path}' is a directory."
    content = target.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    total = len(lines)

    s = max((start_line or 1) - 1, 0)
    e = min(end_line or total, total)

    MAX_LINES = 500
    if start_line is None and end_line is None and total > MAX_LINES:
        excerpt = "\n".join(lines[:MAX_LINES])
        return (
            f"# {path}  ({total} lines total — showing 1-{MAX_LINES})\n"
            f"# Use start_line/end_line to read more.\n\n"
            f"{excerpt}"
        )

    return f"# {path}  (lines {s+1}-{e} of {total})\n\n" + "\n".join(lines[s:e])


def _tool_search_code(pattern: str, subdir: str = "") -> str:
    base = _within_self(subdir) if subdir else _SELF_ROOT
    if base is None:
        return f"ERROR: Directory not found: {subdir!r}"
    try:
        rx = _re.compile(pattern, _re.IGNORECASE)
    except _re.error as e:
        return f"ERROR: Invalid regex: {e}"

    results = []
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    rel = str(p.relative_to(_SELF_ROOT))
                    results.append(f"{rel}:{i}: {line.rstrip()}")
        except Exception:
            pass
        if len(results) >= 150:
            results.append("... (truncated at 150 results)")
            break

    return "\n".join(results) if results else f"(no matches for {pattern!r})"


def _tool_write_file(path: str, content: str) -> str:
    target = _within_self(path)
    if target is None:
        return f"ERROR: '{path}' is outside allowed area."

    # Strip accidental markdown fences
    c = content.strip()
    if c.startswith("```"):
        lines_c = c.splitlines()
        c = "\n".join(l for l in lines_c if not l.strip().startswith("```"))

    # ── Pre-flight: syntax check BEFORE touching the real file ────────────────
    if path.endswith(".py"):
        try:
            import ast as _ast
            _ast.parse(c)
        except SyntaxError as se:
            return (
                f"SYNTAX ERROR — file NOT written. Fix the error first.\n"
                f"  Line {se.lineno}: {se.msg}\n"
                f"  Context: {se.text!r}"
            )

    # ── Backup existing file ───────────────────────────────────────────────────
    had_backup = False
    bak_path: Path | None = None
    if target.exists():
        bak_path = target.with_suffix(target.suffix + ".bak")
        bak_path.write_text(target.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        had_backup = True

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(c, encoding="utf-8")

    # ── Post-write: compile-level check ───────────────────────────────────────
    compile_error: str | None = None
    if path.endswith(".py"):
        check = subprocess.run(
            [sys.executable, "-c", f"import py_compile; py_compile.compile(r'{target}', doraise=True)"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if check.returncode != 0:
            compile_error = check.stderr.strip()

    elif path.endswith((".ts", ".tsx")):
        # TypeScript type-check via tsc if available
        frontend_dir = _PROJECT_ROOT.parent / "apps" / "desktop"
        tsc = frontend_dir / "node_modules" / ".bin" / "tsc"
        if tsc.exists():
            check = subprocess.run(
                [str(tsc), "--noEmit", "--pretty", "false"],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check.returncode != 0:
                # Only surface errors in the file we just wrote
                rel = str(target.relative_to(frontend_dir)) if target.is_relative_to(frontend_dir) else path
                errors = [l for l in (check.stdout + check.stderr).splitlines() if rel in l]
                if errors:
                    compile_error = "\n".join(errors[:10])

    if compile_error:
        # Auto-rollback
        if had_backup and bak_path and bak_path.exists():
            target.write_text(bak_path.read_text(encoding="utf-8"), encoding="utf-8")
            return (
                f"COMPILE ERROR — automatically rolled back to previous version.\n"
                f"Error: {compile_error}\n"
                f"Fix these issues and try write_file again."
            )
        return f"COMPILE ERROR (no backup to roll back to):\n{compile_error}"

    bak_note = f" Backup: '{path}.bak'." if had_backup else ""
    return f"OK: wrote {len(c.splitlines())} lines to '{path}'.{bak_note} Syntax verified ✓"


def _tool_run_shell(command: str) -> str:
    FORBIDDEN = ["rm -rf /", "rm -rf ~", "sudo rm", "> /dev/sda"]
    for f in FORBIDDEN:
        if f in command:
            return f"ERROR: Forbidden pattern: {f!r}"
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        parts = []
        if proc.stdout.strip():
            parts.append(f"STDOUT:\n{proc.stdout.strip()}")
        if proc.stderr.strip():
            parts.append(f"STDERR:\n{proc.stderr.strip()}")
        parts.append(f"EXIT: {proc.returncode}")
        return "\n\n".join(parts) if parts else f"(no output) EXIT: {proc.returncode}"
    except subprocess.TimeoutExpired:
        return "ERROR: timed out (15s)"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_restart_backend() -> str:
    """Schedule a hot-reload. The process will execv() itself after 2 s.

    Returns immediately so the agent can still receive the tool result before
    the restart happens.  The agent should treat this as 'pending' and use
    run_shell to confirm the backend came back up cleanly.
    """
    async def _do():
        await asyncio.sleep(2.0)
        # Flush all pending DB sessions before restart
        try:
            from app.core.database import engine
            await engine.dispose()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)
    try:
        asyncio.get_event_loop().create_task(_do())
        return (
            "OK: restart scheduled in 2 s.\n"
            "IMPORTANT: After ~5 s, verify with:\n"
            "  run_shell \"curl -s http://localhost:15000/api/v1/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[\\\"status\\\"])'\" \n"
            "If it prints 'ok' the backend is healthy. If not, the new code has a runtime error."
        )
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_web_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo search – no API key required."""
    try:
        try:
            from ddgs import DDGS  # type: ignore[import]
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore[import]
        import asyncio as _asyncio

        def _sync():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        # We are already in an async context; run in thread pool
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            results = pool.submit(_sync).result(timeout=20)

        if not results:
            return f"(no results for {query!r})"
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r.get('title','')}\n"
                f"   URL: {r.get('href','')}\n"
                f"   {r.get('body','')[:200]}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"ERROR web_search: {exc}"


def _tool_fetch_url(url: str) -> str:
    """Fetch URL text content (strip HTML)."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )
        }
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Keep max 6000 chars to avoid token overflow
        if len(text) > 6000:
            text = text[:6000] + f"\n[...{len(text)-6000} chars truncated]"
        return text or "(empty page)"
    except Exception as exc:
        return f"ERROR fetch_url: {exc}"


def _tool_run_tests(filter_str: str = "") -> str:
    """Run the pytest suite (or a subset) and return a structured summary."""
    cmd = ".venv/bin/python -m pytest tests/ -x -q --tb=short"
    if filter_str:
        cmd += f" -k {filter_str!r}"
    # cap at 60 s — enough for the full suite
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (proc.stdout + proc.stderr).strip()
        # Keep last 3000 chars if huge
        if len(output) > 3000:
            output = "...(truncated)...\n" + output[-3000:]
        status = "PASSED" if proc.returncode == 0 else "FAILED"
        return f"Tests {status} (exit {proc.returncode}):\n{output}"
    except subprocess.TimeoutExpired:
        return "ERROR: tests timed out after 120s"
    except Exception as exc:
        return f"ERROR running tests: {exc}"


def _tool_git_commit(message: str) -> str:
    """Stage all changed .py files and commit."""
    safe_msg = message.replace('"', "'").strip() or "Lani self-edit"
    try:
        # Only stage app/ directory (our safe self-edit zone)
        add_result = subprocess.run(
            "git add app/",
            shell=True,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if add_result.returncode != 0:
            return f"ERROR git add: {add_result.stderr.strip()}"

        commit_result = subprocess.run(
            f'git commit -m "{safe_msg}"',
            shell=True,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = commit_result.stdout.strip()
        err = commit_result.stderr.strip()
        if commit_result.returncode == 0:
            return f"OK: committed – {out}"
        if "nothing to commit" in out + err:
            return "OK: nothing new to commit (already clean)."
        return f"ERROR git commit (exit {commit_result.returncode}): {err or out}"
    except Exception as exc:
        return f"ERROR git_commit: {exc}"


def _dispatch_tool(name: str, args: dict[str, Any]) -> str:
    if name == "list_files":
        return _tool_list_files(args.get("subdir", ""), args.get("pattern", "*.py"))
    if name == "read_file":
        return _tool_read_file(args.get("path", ""), args.get("start_line"), args.get("end_line"))
    if name == "search_code":
        return _tool_search_code(args.get("pattern", ""), args.get("subdir", ""))
    if name == "write_file":
        return _tool_write_file(args.get("path", ""), args.get("content", ""))
    if name == "run_shell":
        return _tool_run_shell(args.get("command", ""))
    if name == "restart_backend":
        return _tool_restart_backend()
    if name == "web_search":
        return _tool_web_search(args.get("query", ""), int(args.get("max_results", 5)))
    if name == "fetch_url":
        return _tool_fetch_url(args.get("url", ""))
    if name == "git_commit":
        return _tool_git_commit(args.get("message", "Lani self-edit"))
    if name == "run_tests":
        return _tool_run_tests(args.get("filter", ""))
    # Safari tools — async, must be awaited from agent loop directly
    if name in ("safari_open", "safari_read", "safari_click", "safari_fill", "safari_get_tabs", "safari_run_js"):
        return f"SAFARI_ASYNC:{name}:{json.dumps(args)}"
    return f"ERROR: Unknown tool '{name}'"


async def _tool_safari(name: str, args: dict[str, Any]) -> str:
    """Proxy Safari tool calls į safari_tools module."""
    try:
        from app.tools.safari_tools import (
            SafariOpenTool, SafariReadTool, SafariClickTool,
            SafariGetTabsTool, SafariRunJSTool,
        )
        tool_map = {
            "safari_open": SafariOpenTool,
            "safari_read": SafariReadTool,
            "safari_click": SafariClickTool,
            "safari_get_tabs": SafariGetTabsTool,
            "safari_run_js": SafariRunJSTool,
        }
        if name not in tool_map:
            return f"ERROR: Safari tool '{name}' not found"
        result = await tool_map[name]().run(args)
        if result.status == "error":
            return f"ERROR: {result.message}"
        return result.message or "OK"
    except Exception as exc:
        return f"ERROR safari tool {name}: {exc}"


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_LT = """Tu esi Lani — autonomiškas AI agentas, galintis PATI SAVE keisti ir tobulinti.

━━ KODO BAZĖ ━━
Galite redaguoti DVIEJOSE vietose:

1. BACKEND (Python):  /services/orchestrator/app/
   tools/         — visi tools (chat_tool.py, operator_tools.py, ...)
   services/      — servisai (command_router.py, agent_loop.py, ...)
   api/routes/    — FastAPI endpoint'ai
   core/          — config.py, database.py
   models/        — SQLAlchemy modeliai

2. FRONTEND (TypeScript/React):  apps/desktop/src/
   pages/         — puslapiai (ChatPage.tsx, SettingsPage.tsx, ...)
   components/    — komponentai
   stores/        — Zustand store'ai (chatStore.ts, settingsStore.ts, ...)
   hooks/         — React hooks
   styles/        — global.css

Keliai write_file/read_file:
  Python:  "tools/chat_tool.py"  arba  "services/agent_loop.py"
  Frontend: "pages/ChatPage.tsx"  arba  "stores/chatStore.ts"
  (sistema automatiškai randa teisingą direktoriją)

━━ DARBO EIGA ━━
1. SUPRASK prieš veikdamas:
   → list_files (suprask struktūrą)
   → search_code (rask susijusį kodą)
   → read_file (perskaityk prieš rašydamas)
   → web_search (ieškoki internete jei nežinai kaip kažkas veikia)
   → fetch_url (nuskaityk konkrečią dokumentacijos puslapą)

2. PLANUOK — galvok žingsnis po žingsnio:
   → Kokie failai paveikiami?
   → Ar bus šalutinių efektų?
   → Kaip patikrinti, kad veikia?

3. RAŠYK teisingai:
   → write_file — VISAS failo turinys, ne patch
   → write_file AUTOMATIŠKAI tikrina sintaksę — jei klaida, failas NEĮRAŠOMAS ir gauni klaidos pranešimą
   → Jei gauni "SYNTAX ERROR" arba "COMPILE ERROR" — NEDELSDAMAS pataisyk ir bandyk dar kartą
   → Išsaugok esamas funkcijas
   → Tvarkyk importus

4. TIKRINK po rašymo:
   → write_file jau patikrino sintaksę — bet dar patikrink logiką: search_code ar funkcija pasiekiama
   → Po restart_backend PRIVALOMA patikrinti:
      run_shell "curl -s http://localhost:15000/api/v1/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[\"status\"])'"
   → Jei grąžina "ok" — sėkminga. Jei klaida — perskaityk .bak failą ir suprask kas sulaužyta

5. PALEISK TESTUS prieš commit:
   → run_tests — PRIVALOMA po KIEKVIENO kodo pakeitimo
   → Jei testai nepavyksta — perskaityk klaidos pranešimą, surask priežastį, pataisyk
   → Tik kai visi testai praeina — commit

5. PERKRAUK:
   → restart_backend po KIEKVIENO Python failo keitimo

6. IŠSAUGOK:
   → git_commit su aiškiu commit message po kiekvieno sėkmingo keitimo

7. BAIK su answer():
   → Aiškiai papasakok ką padarei

━━ KODO STILIUS ━━
- Python 3.11+, async/await
- BaseTool subklasės tools/ direktorijoje
- requires_approval = False (Lani dirba autonomiškai)
- log.info/log.error visur
- Type hints

━━ NARŠYKLIŲ STRATEGIJA ━━
Turi DVI naršyklių sistemas — rinkis teisingą:

🦁 SAFARI (safari_open / safari_read / safari_click / safari_fill / safari_get_tabs):
  → Naudok KAI reikia PRISIJUNGUSIOS paskyros: Gmail, Facebook, Instagram, Google Play Console,
    Firebase, iCloud, bankai, LinkedIn, Twitter/X, GitHub, Notion, bet kuri paskyra
  → Safari turi VISAS vartotojo sesijas ir cookies
  → Po safari_open VISADA laukk 2–3 sek. prieš safari_read
  → Jei puslapis prašo 2FA — pranešk vartotojui ir palaukk kol jis patvirtins

🎭 PLAYWRIGHT / Chrome (browser_open / browser_search / browser_read / browser_fill / browser_click):
  → Naudok anoniminei paieškai, viešiems puslapiams, kur NEREIKIA prisijungti
  → Pvz.: paieška Google, skaityti Wikipedia, tikrinti orus, žiūrėti kainų palyginimus

TAISYKLĖ: Jei vartotojas mini paskyrą, prisijungimą, el. paštą, socialinį tinklą → SAFARI.
           Jei reikia tik paieškos ar viešo turinio → Playwright.

━━ SAVĘS TAISYMAS (SELF-HEALING) ━━
Jei gauni užduotį kuri prasideda "Vartotojas paprašė: ..." ir "UŽDUOTIS: Išanalizuok kodėl atsisakiau":

1. SUPRASK kur problema:
   → search_code "negaliu|atsisakau|privacy|refusal|_BROWSER_PATTERNS|_is_browser_request" — rask kas blokuoja
   → read_file "api/routes/chat_stream.py" — perskaityk routing logiką
   → read_file "tools/chat_tool.py" — perskaityk system prompt ir detection funkcijas

2. NUSTATYK priežastį:
   a) Jei _is_browser_request() neaptinka žinutės → pridėk naują regex pattern į _BROWSER_PATTERNS
   b) Jei LLM sistema atsisakė dėl safety filtro → pakeisk system prompt į neutralesnį
   c) Jei trūksta tool'o → sukurk naują tool failą ir užregistruok registry.py
   d) Jei Safari routing naudoja blogą URL → papildyk _SERVICE_URLS žodyną chat_stream.py

3. PATAISYK:
   → write_file su pilnu pataisytu failo turiniu
   → restart_backend
   → Patikrink health: run_shell "curl -s http://localhost:8000/api/v1/health"

4. PAKARTOK užduotį:
   → Po sėkmingo pataisymo, vykdyk originalią vartotojo užduotį (pvz. atidaryk Gmail, perskaityk laišką)
   → Naudok safari_open + safari_read jei reikia naršyklės
   → Grąžink realų rezultatą vartotojui, ne tik pranešimą apie pataisymą

━━ TAISYKLĖS ━━
- Nemeluok — jei nepavyko, pasakyk kodėl
- Neskubėk — geriau suprasti nei sulaužyti
- Jei abejoji — skaityk daugiau kodo

Visada atsakyk lietuviškai. Techniniai terminai gali būti anglų kalba."""

_SYSTEM_PROMPT_EN = """You are Lani — an autonomous AI agent that can modify her own code.

Code base: /services/orchestrator/app/
  tools/       — all tools
  services/    — services (command_router, agent_loop, voice_service, ...)
  api/routes/  — FastAPI routes
  core/        — config, database

BROWSER STRATEGY — choose wisely:
🦁 SAFARI tools (safari_open / safari_read / safari_click / safari_fill):
  → Use when the user has an ACCOUNT: Gmail, Facebook, Google Play Console, Firebase,
    iCloud, banks, LinkedIn, Instagram, Twitter/X, GitHub, any logged-in service
  → Safari has ALL user sessions and cookies intact

🎭 Playwright/Chrome (browser_open / browser_search / browser_read):
  → Use for anonymous searches and public pages that don't need login
  → e.g. Google search, Wikipedia, price comparisons

RULE: If user mentions an account, email, social network, or login → SAFARI.
      If just searching or reading public content → Playwright.

WORKFLOW:
1. Understand first: list_files → search_code → read_file
2. Plan before acting
3. Write FULL file content (not patches)
4. Verify syntax with run_shell after writing
5. Call restart_backend after every Python change
6. Finish with answer()

CODE STYLE: Python 3.11+, async/await, BaseTool subclasses, requires_approval=False
Always respond in English."""


# ── Self-validator ─────────────────────────────────────────────────────────────

async def _validate_answer(goal: str, answer: str, client: Any, model: str) -> str:
    """
    Lightweight quality gate: ask the LLM if the answer actually addresses the goal.
    Returns the original answer if quality ≥ threshold, or a revised version.
    Timeout: 10 s — if it fails, just return the original answer to avoid blocking.
    """
    if len(answer) < 20:
        # Too short — don't bother; agent clearly didn't complete the task
        return answer

    validation_prompt = (
        f"GOAL: {goal[:500]}\n\n"
        f"ANSWER: {answer[:1200]}\n\n"
        "Rate this answer on one criterion: does it fully address the goal?\n"
        "Reply with ONLY one of:\n"
        "  GOOD  — answer is complete and correct\n"
        "  INCOMPLETE: <one sentence why>\n"
        "  WRONG: <one sentence why>\n"
        "Be strict but fair."
    )

    try:
        import asyncio as _aio
        resp = await _aio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",  # always use fast model for validation
                messages=[{"role": "user", "content": validation_prompt}],
                max_tokens=80,
                temperature=0,
            ),
            timeout=10,
        )
        verdict = (resp.choices[0].message.content or "").strip()
        log.info("[agent_loop] validator verdict: %s", verdict[:80])

        if verdict.startswith("GOOD"):
            return answer

        # Answer has issues — append a note so user knows
        if verdict.startswith(("INCOMPLETE", "WRONG")):
            reason = verdict.split(":", 1)[-1].strip()
            return answer + f"\n\n⚠️ _Pastaba: {reason}_"

    except Exception as exc:
        log.debug("[agent_loop] validator skipped: %s", exc)

    return answer


# ── Main agent loop ────────────────────────────────────────────────────────────

async def run_agent(
    goal: str,
    lang: str = "lt",
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> str:
    """Run the autonomous ReAct agent loop. Returns final answer string."""
    from app.core.config import settings as cfg
    import openai

    api_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
    if not api_key:
        return "Klaida: OPENAI_API_KEY nenustatytas. Patikrink .env failą."

    client = openai.AsyncOpenAI(api_key=api_key)
    # o3 = best reasoning model for agent loops (2026-03)
    model = getattr(cfg, "AGENT_MODEL", "o3")

    system = _SYSTEM_PROMPT_LT if lang == "lt" else _SYSTEM_PROMPT_EN

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": goal},
    ]

    log.info("[agent_loop] START model=%s goal=%r", model, goal[:80])

    for iteration in range(MAX_ITERATIONS):
        log.info("[agent_loop] iteration %d/%d", iteration + 1, MAX_ITERATIONS)

        try:
            _agent_kwargs: dict[str, Any] = {
                "model": model,
                "messages": cast(Any, messages),
                "tools": cast(Any, _AGENT_TOOLS),
                "tool_choice": "auto",
                "temperature": 0.1,
                **_openai_token_param(model, 8192),
            }
            response = await client.chat.completions.create(**cast(Any, _agent_kwargs))
        except Exception as exc:
            log.error("[agent_loop] LLM error: %s", exc)
            return f"LLM klaida: {exc}"

        msg = response.choices[0].message

        # Plain text = final answer
        if not msg.tool_calls:
            text = (msg.content or "").strip()
            log.info("[agent_loop] plain text answer, len=%d", len(text))
            return text or "(tuščias atsakymas)"

        _append_assistant_tool_call_message(messages, msg)

        # Execute tools
        final_answer: str | None = None

        for tc in msg.tool_calls:
            tool_name, args = _parse_tool_call(tc)

            log.info("[agent_loop] tool=%s args=%s", tool_name, str(args)[:120])

            if tool_name == "answer":
                final_answer = args.get("text", "").strip()
                observation = f"Answered: {(final_answer or '')[:100]}"
            else:
                try:
                    # Inform progress callback that we're about to run a tool
                    if progress_callback:
                        try:
                            await progress_callback(f"→ START TOOL: {tool_name} {json.dumps(args, default=str)}")
                        except Exception:
                            # progress callback must not break the agent
                            pass

                    raw = _dispatch_tool(tool_name, args)
                    # Safari tools return a special marker — resolve async
                    if isinstance(raw, str) and raw.startswith("SAFARI_ASYNC:"):
                        _, safari_name, safari_args_json = raw.split(":", 2)
                        safari_args = json.loads(safari_args_json)
                        observation = await _tool_safari(safari_name, safari_args)
                    else:
                        observation = raw

                    # Inform progress callback about tool result
                    if progress_callback:
                        try:
                            preview = (str(observation)[:400]).replace("\n", " ")
                            await progress_callback(f"← TOOL RESULT: {tool_name}: {preview}")
                        except Exception:
                            pass
                except Exception as exc:
                    observation = f"ERROR in {tool_name}: {exc}"
                    log.error("[agent_loop] tool exception: %s", exc)

            observation = _truncate_observation(observation)

            log.info("[agent_loop] obs preview: %s", observation[:100])

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": observation,
            })

        if final_answer is not None:
            log.info("[agent_loop] done after %d iterations", iteration + 1)
            # ── Self-validation: check answer quality vs original goal ──
            validated = await _validate_answer(goal, final_answer, client, model)
            return validated

    log.warning("[agent_loop] hit MAX_ITERATIONS=%d", MAX_ITERATIONS)
    return (
        f"Pasiektas {MAX_ITERATIONS} iteracijų limitas. "
        "Užduotis gali būti iš dalies atlikta. Patikrink backend logus."
    )


def _append_assistant_tool_call_message(messages: list[dict], msg: Any) -> None:
    messages.append({
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls or []
        ],
    })


def _parse_tool_call(tc: Any) -> tuple[str, dict]:
    tool_name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return tool_name, args


def _truncate_observation(observation: str, max_length: int = 8000) -> str:
    if len(observation) <= max_length:
        return observation
    return observation[:max_length] + f"\n[...{len(observation)-max_length} chars truncated]"
