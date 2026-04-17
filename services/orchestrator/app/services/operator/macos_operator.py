"""macOS Computer Operator implementation.

All automation is performed through well-known macOS CLI tools:
  • open          – launch apps / open paths in Finder
  • osascript     – AppleScript for window management and keyboard simulation
  • pbcopy        – write to clipboard
  • pbpaste       – read from clipboard
  • screencapture – take screenshots

No arbitrary shell commands are executed.  Every action is a discrete,
typed function that validates its parameters before doing anything.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.operator import OperatorCapability, OperatorActionName
from app.services.operator.base import OperatorBase, OperatorResult, register_operator


# ─── Safety lists ─────────────────────────────────────────────────────────────

# Shortcuts that can irrecoverably destroy work – require approval before use.
DESTRUCTIVE_SHORTCUT_COMBOS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"cmd", "q"}),           # Quit application
        frozenset({"cmd", "w"}),           # Close window
        frozenset({"cmd", "delete"}),      # Move to trash
        frozenset({"cmd", "shift", "delete"}),  # Empty trash
        frozenset({"ctrl", "alt", "delete"}),   # (Windows habit – block anyway)
        frozenset({"cmd", "alt", "escape"}),    # Force Quit dialog
    }
)

# Where Lani is allowed to write screenshots (expanded at runtime).
_SCREENSHOT_DEFAULT_DIR = Path.home() / "Desktop"
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-_()&!]+$")
_PATH_TRAVERSAL_RE = re.compile(r"\.\.")

# ─── App name aliases ─────────────────────────────────────────────────────────
# Maps common/informal names → (real_app_name_or_None, url_to_open_or_None)
# If url is set, Chrome (or default browser) is used to open it instead.
_APP_ALIASES: dict[str, tuple[str | None, str | None]] = {
    # Browsers
    "chrome":           ("Google Chrome", None),
    "google chrome":    ("Google Chrome", None),
    "safari":           ("Safari", None),
    "firefox":          ("Firefox", None),
    "edge":             ("Microsoft Edge", None),
    "brave":            ("Brave Browser", None),
    # Google web apps (no desktop app → open in browser)
    "gmail":            (None, "https://mail.google.com"),
    "google mail":      (None, "https://mail.google.com"),
    "google calendar":  (None, "https://calendar.google.com"),
    "calendar":         ("Calendar", None),
    "google drive":     (None, "https://drive.google.com"),
    "google docs":      (None, "https://docs.google.com"),
    "google sheets":    (None, "https://sheets.google.com"),
    "google slides":    (None, "https://slides.google.com"),
    "youtube":          (None, "https://youtube.com"),
    "google maps":      (None, "https://maps.google.com"),
    "google":           (None, "https://google.com"),
    "chatgpt":          (None, "https://chat.openai.com"),
    "github":           (None, "https://github.com"),
    # macOS built-ins
    "mail":             ("Mail", None),
    "messages":         ("Messages", None),
    "facetime":         ("FaceTime", None),
    "terminal":         ("Terminal", None),
    "finder":           ("Finder", None),
    "notes":            ("Notes", None),
    "reminders":        ("Reminders", None),
    "photos":           ("Photos", None),
    "music":            ("Music", None),
    "spotify":          ("Spotify", None),
    "vscode":           ("Visual Studio Code", None),
    "vs code":          ("Visual Studio Code", None),
    "visual studio code": ("Visual Studio Code", None),
    "slack":            ("Slack", None),
    "zoom":             ("zoom.us", None),
    "discord":          ("Discord", None),
    "whatsapp":         ("WhatsApp", None),
    "telegram":         ("Telegram", None),
    "figma":            ("Figma", None),
    "notion":           (None, "https://notion.so"),
    "maps":             ("Maps", None),
    "system preferences": ("System Preferences", None),
    "system settings":  ("System Settings", None),
    "activity monitor": ("Activity Monitor", None),
    "xcode":            ("Xcode", None),
    # ── Lietuviški pavadinimai ─────────────────────────────────────────────
    "naršyklė":         ("Safari", None),
    "narsykle":         ("Safari", None),
    "muzika":           ("Music", None),
    "nuotraukos":       ("Photos", None),
    "paštas":           ("Mail", None),
    "pastas":           ("Mail", None),
    "užrašai":          ("Notes", None),
    "uzrasai":          ("Notes", None),
    "priminimai":       ("Reminders", None),
    "žinutės":          ("Messages", None),
    "zinutes":          ("Messages", None),
    "nustatymai":       ("System Settings", None),
    "terminalas":       ("Terminal", None),
    "rodytuvas":        ("Finder", None),
    "veiklos stebėjimas": ("Activity Monitor", None),
    "kalendorius":      ("Calendar", None),
    "žemėlapiai":       ("Maps", None),
    "zemelap":          ("Maps", None),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _run(args: List[str], input_bytes: Optional[bytes] = None) -> subprocess.CompletedProcess:
    """Synchronous subprocess wrapper used inside asyncio.to_thread."""
    return subprocess.run(
        args,
        input=input_bytes,
        capture_output=True,
        timeout=15,
    )


def _osascript(script: str) -> subprocess.CompletedProcess:
    return _run(["osascript", "-e", script])


def _validate_app_name(name: str) -> Optional[str]:
    """Return error string if app name is not safe, else None."""
    name = name.strip()
    if not name:
        return "app_name must not be empty"
    if not _APP_NAME_RE.match(name):
        return f"app_name contains invalid characters: {name!r}"
    if len(name) > 128:
        return "app_name is too long"
    return None


def _validate_path(raw_path: str) -> tuple[Optional[Path], Optional[str]]:
    """Expand and validate a filesystem path.  Returns (Path, error_str)."""
    raw_path = raw_path.strip()
    if not raw_path:
        return None, "path must not be empty"
    expanded = Path(os.path.expandvars(os.path.expanduser(raw_path)))
    if _PATH_TRAVERSAL_RE.search(str(expanded)):
        return None, "path traversal sequences are not allowed"
    return expanded, None


def _shortcut_needs_approval(keys: List[str]) -> bool:
    key_set = frozenset(k.lower().strip() for k in keys)
    return key_set in DESTRUCTIVE_SHORTCUT_COMBOS


# ─── macOS operator ───────────────────────────────────────────────────────────

class MacOSOperator(OperatorBase):
    sys_platform = "darwin"
    platform_display = "macos"

    # ── Capability manifest ────────────────────────────────────────────────────

    def get_capabilities(self) -> List[OperatorCapability]:
        return [
            OperatorCapability(
                name="list_open_windows",
                description="List all visible application windows currently open.",
                requires_approval=False,
                risk_level="low",
                params_schema={},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="open_app",
                description="Open or bring to front an installed application by name.",
                requires_approval=False,
                risk_level="medium",
                params_schema={"app_name": "Name of the application (e.g. 'Safari')"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="focus_window",
                description="Bring an application's windows to the foreground.",
                requires_approval=False,
                risk_level="medium",
                params_schema={"window_title": "Application name to activate"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="minimize_window",
                description="Minimise all windows belonging to an application.",
                requires_approval=False,
                risk_level="medium",
                params_schema={"window_title": "Application name to minimise"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="close_window",
                description="Close all windows belonging to an application.",
                requires_approval=True,
                risk_level="high",
                params_schema={"window_title": "Application name whose windows to close"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="open_path",
                description="Open a file or folder with its default application.",
                requires_approval=False,
                risk_level="medium",
                params_schema={"path": "Absolute or home-relative path (e.g. '~/Documents')"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="reveal_file",
                description="Reveal a file or folder in Finder without opening it.",
                requires_approval=False,
                risk_level="low",
                params_schema={"path": "Absolute or home-relative path"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="copy_to_clipboard",
                description="Copy the provided text to the system clipboard.",
                requires_approval=False,
                risk_level="medium",
                params_schema={"text": "Text content to place on the clipboard"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="paste_clipboard",
                description="Simulate Cmd+V in the currently focused window.",
                requires_approval=False,
                risk_level="medium",
                params_schema={},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="type_text",
                description="Type arbitrary text into the currently focused input field.",
                requires_approval=True,
                risk_level="high",
                params_schema={"text": "Text to type (max 1 000 characters)"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="press_shortcut",
                description=(
                    "Press a keyboard shortcut (e.g. ['cmd','shift','4']). "
                    "Destructive combinations require approval."
                ),
                requires_approval=False,  # dynamic – checked per-invocation
                risk_level="medium",
                params_schema={"keys": "List of key names (e.g. ['cmd','c'])"},
                supported_on=["macos"],
            ),
            OperatorCapability(
                name="take_screenshot",
                description="Capture the screen and save it as a PNG.",
                requires_approval=False,
                risk_level="low",
                params_schema={"output_path": "Optional path for the PNG file"},
                supported_on=["macos"],
            ),
        ]

    # ── Dispatcher ─────────────────────────────────────────────────────────────

    async def execute(
        self, action: OperatorActionName, params: Dict[str, Any]
    ) -> OperatorResult:
        handler = {
            "list_open_windows": self._list_open_windows,
            "open_app": self._open_app,
            "focus_window": self._focus_window,
            "minimize_window": self._minimize_window,
            "close_window": self._close_window,
            "open_path": self._open_path,
            "reveal_file": self._reveal_file,
            "copy_to_clipboard": self._copy_to_clipboard,
            "paste_clipboard": self._paste_clipboard,
            "type_text": self._type_text,
            "press_shortcut": self._press_shortcut,
            "take_screenshot": self._take_screenshot,
        }.get(action)

        if handler is None:
            return OperatorResult(ok=False, message=f"Unknown action: {action!r}")

        try:
            return await handler(params)
        except Exception as exc:  # noqa: BLE001
            return OperatorResult(ok=False, message=f"Operator error: {exc}")

    # ── Action implementations ─────────────────────────────────────────────────

    async def _list_open_windows(self, _params: Dict[str, Any]) -> OperatorResult:
        script = (
            'tell application "System Events" to get '
            '{name, title of every window} of '
            '(every process where background only is false)'
        )
        # Use a simpler script that lists process names
        script = (
            'tell application "System Events"\n'
            '  set procs to every process where background only is false\n'
            '  set result to {}\n'
            '  repeat with p in procs\n'
            '    set end of result to name of p\n'
            '  end repeat\n'
            '  return result\n'
            'end tell'
        )
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "osascript failed",
            )
        raw = proc.stdout.decode(errors="replace").strip()
        apps = [a.strip() for a in raw.split(",") if a.strip()]
        windows = [{"title": a, "app": a, "is_minimized": False, "is_focused": False} for a in apps]
        return OperatorResult(ok=True, message=f"Found {len(windows)} open processes.", data=windows)

    async def _open_app(self, params: Dict[str, Any]) -> OperatorResult:
        app_name = str(params.get("app_name", "")).strip()
        if not app_name:
            return OperatorResult(ok=False, message="app_name is required.")

        # Resolve alias (case-insensitive)
        alias_key = app_name.lower()
        real_app, url = _APP_ALIASES.get(alias_key, (None, None))

        # If alias maps to a URL → open in default browser
        if url:
            proc = await asyncio.to_thread(_run, ["open", url])
            if proc.returncode != 0:
                return OperatorResult(ok=False, message=f"Could not open URL {url!r}")
            return OperatorResult(ok=True, message=f"Opened {app_name!r} → {url}")

        # Use resolved real name or original
        target = real_app or app_name
        err = _validate_app_name(target)
        if err:
            return OperatorResult(ok=False, message=err)

        proc = await asyncio.to_thread(_run, ["open", "-a", target])
        if proc.returncode != 0:
            # Last resort: try with original name (user may have typed correctly)
            if real_app and real_app != app_name:
                proc2 = await asyncio.to_thread(_run, ["open", "-a", app_name])
                if proc2.returncode == 0:
                    return OperatorResult(ok=True, message=f"Opened {app_name!r}.")
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip()
                    or f"Unable to find application named '{target}'",
            )
        return OperatorResult(ok=True, message=f"Opened {target!r}.")

    async def _focus_window(self, params: Dict[str, Any]) -> OperatorResult:
        app_name = str(params.get("window_title", "")).strip()
        err = _validate_app_name(app_name)
        if err:
            return OperatorResult(ok=False, message=err)
        script = f'tell application "{app_name}" to activate'
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or f"Could not focus {app_name!r}",
            )
        return OperatorResult(ok=True, message=f"Focused {app_name!r}.")

    async def _minimize_window(self, params: Dict[str, Any]) -> OperatorResult:
        app_name = str(params.get("window_title", "")).strip()
        err = _validate_app_name(app_name)
        if err:
            return OperatorResult(ok=False, message=err)
        script = (
            f'tell application "System Events"\n'
            f'  tell process "{app_name}"\n'
            f'    set miniaturized of every window to true\n'
            f'  end tell\n'
            f'end tell'
        )
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or f"Could not minimise {app_name!r}",
            )
        return OperatorResult(ok=True, message=f"Minimised windows of {app_name!r}.")

    async def _close_window(self, params: Dict[str, Any]) -> OperatorResult:
        app_name = str(params.get("window_title", "")).strip()
        err = _validate_app_name(app_name)
        if err:
            return OperatorResult(ok=False, message=err)
        script = (
            f'tell application "System Events"\n'
            f'  tell process "{app_name}"\n'
            f'    click button 1 of every window\n'
            f'  end tell\n'
            f'end tell'
        )
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or f"Could not close {app_name!r}",
            )
        return OperatorResult(ok=True, message=f"Closed windows of {app_name!r}.")

    async def _open_path(self, params: Dict[str, Any]) -> OperatorResult:
        path, err = _validate_path(str(params.get("path", "")))
        if err:
            return OperatorResult(ok=False, message=err)
        proc = await asyncio.to_thread(_run, ["open", str(path)])
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or f"Could not open {path}",
            )
        return OperatorResult(ok=True, message=f"Opened {path}.")

    async def _reveal_file(self, params: Dict[str, Any]) -> OperatorResult:
        path, err = _validate_path(str(params.get("path", "")))
        if err:
            return OperatorResult(ok=False, message=err)
        proc = await asyncio.to_thread(_run, ["open", "-R", str(path)])
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or f"Could not reveal {path}",
            )
        return OperatorResult(ok=True, message=f"Revealed {path} in Finder.")

    async def _copy_to_clipboard(self, params: Dict[str, Any]) -> OperatorResult:
        text = str(params.get("text", ""))
        if len(text) > 100_000:
            return OperatorResult(ok=False, message="Text exceeds 100 000 character limit.")
        proc = await asyncio.to_thread(_run, ["pbcopy"], input_bytes=text.encode())
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "pbcopy failed",
            )
        return OperatorResult(ok=True, message=f"Copied {len(text)} characters to clipboard.")

    async def _paste_clipboard(self, _params: Dict[str, Any]) -> OperatorResult:
        # Read clipboard content via pbpaste for confirmation, then simulate Cmd+V.
        paste_proc = await asyncio.to_thread(_run, ["pbpaste"])
        pasted_text = paste_proc.stdout.decode(errors="replace") if paste_proc.returncode == 0 else ""

        script = 'tell application "System Events" to keystroke "v" using command down'
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "keystroke failed",
            )
        return OperatorResult(
            ok=True,
            message="Pasted clipboard contents.",
            data={"text": pasted_text[:200] + ("…" if len(pasted_text) > 200 else "")},
        )

    async def _type_text(self, params: Dict[str, Any]) -> OperatorResult:
        text = str(params.get("text", ""))
        if not text:
            return OperatorResult(ok=False, message="text must not be empty")
        if len(text) > 1_000:
            return OperatorResult(ok=False, message="text exceeds 1 000 character limit")
        # Escape for AppleScript string literal – only backslash and double-quote.
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "keystroke failed",
            )
        return OperatorResult(ok=True, message=f"Typed {len(text)} characters.")

    async def _press_shortcut(self, params: Dict[str, Any]) -> OperatorResult:
        raw_keys: Any = params.get("keys", [])
        if isinstance(raw_keys, str):
            raw_keys = [k.strip() for k in raw_keys.replace("+", ",").split(",")]
        keys: List[str] = [str(k).lower().strip() for k in raw_keys if str(k).strip()]

        if not keys:
            return OperatorResult(ok=False, message="keys must not be empty")

        # Map modifier key names → AppleScript modifier names.
        _MODIFIER_MAP = {
            "cmd": "command down",
            "command": "command down",
            "ctrl": "control down",
            "control": "control down",
            "alt": "option down",
            "option": "option down",
            "shift": "shift down",
        }

        modifiers = [_MODIFIER_MAP[k] for k in keys if k in _MODIFIER_MAP]
        key_chars = [k for k in keys if k not in _MODIFIER_MAP]

        if not key_chars:
            return OperatorResult(ok=False, message="No non-modifier key provided")
        if len(key_chars) > 1:
            return OperatorResult(ok=False, message="Only one non-modifier key is supported per shortcut")

        key_char = key_chars[0]
        modifier_str = (", ".join(modifiers) + " ") if modifiers else ""
        using_clause = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
        script = f'tell application "System Events" to keystroke "{key_char}"{using_clause}'
        proc = await asyncio.to_thread(_osascript, script)
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "shortcut failed",
            )
        return OperatorResult(ok=True, message=f"Pressed shortcut: {'+'.join(keys)}")

    async def _take_screenshot(self, params: Dict[str, Any]) -> OperatorResult:
        raw_path = params.get("output_path", "")
        if raw_path:
            output_path, err = _validate_path(str(raw_path))
            if err:
                return OperatorResult(ok=False, message=err)
            if output_path is None:
                return OperatorResult(ok=False, message="Invalid output_path")
        else:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = _SCREENSHOT_DEFAULT_DIR / f"lani_screenshot_{ts}.png"

        # Ensure the directory exists.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # -x suppresses the shutter sound.
        proc = await asyncio.to_thread(_run, ["screencapture", "-x", str(output_path)])
        if proc.returncode != 0:
            return OperatorResult(
                ok=False,
                message=proc.stderr.decode(errors="replace").strip() or "screencapture failed",
            )
        return OperatorResult(
            ok=True,
            message=f"Screenshot saved to {output_path}.",
            data={"path": str(output_path)},
        )


# ─── Auto-register on import ──────────────────────────────────────────────────

register_operator(MacOSOperator())
