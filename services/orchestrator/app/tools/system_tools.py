"""
system_tools.py – macOS system integration tools.

Tools:
  send_notification   – send a macOS native notification
  get_clipboard       – read current clipboard text
  set_clipboard       – write text to clipboard
  get_screen_info     – get screen resolution, display count
  take_screenshot     – screenshot of full screen or specific app window
  list_running_apps   – list all running applications
  get_battery_status  – battery level and charging status
  get_wifi_info       – current WiFi network info
  speak_text          – macOS text-to-speech (say command)
  set_volume          – set system volume 0–100
  open_url_in_browser – open URL in default browser
  empty_trash         – empty trash (requires approval)
  get_disk_usage      – disk usage for a path
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


async def _osascript(script: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run AppleScript via osascript."""
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Timeout"


async def _shell(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Timeout"


# ─────────────────────────────────────────────────────────────────────────────

class SendNotificationTool(BaseTool):
    name = "send_notification"
    description = (
        "Send a native macOS notification with title and message. "
        "Parameters: title (required), message (required), subtitle (optional), "
        "sound (bool, default true)."
    )
    requires_approval = False
    parameters = [
        {"name": "title",    "description": "Notification title",    "required": True},
        {"name": "message",  "description": "Notification body text", "required": True},
        {"name": "subtitle", "description": "Subtitle text", "required": False},
        {"name": "sound",    "description": "Play sound (default true)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        title   = params.get("title", "Lani").replace('"', '\\"')
        message = params.get("message", "").replace('"', '\\"')
        subtitle = params.get("subtitle", "").replace('"', '\\"')
        sound   = params.get("sound", True)

        sub_part = f'subtitle "{subtitle}"' if subtitle else ""
        sound_part = "sound name \"Glass\"" if sound else ""
        script = f'display notification "{message}" with title "{title}" {sub_part} {sound_part}'

        rc, _, err = await _osascript(script)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or "Klaida")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Pranešimas išsiųstas: {title}",
            data={"title": title, "message": message},
        )


class GetClipboardTool(BaseTool):
    name = "get_clipboard"
    description = "Read the current macOS clipboard contents. Returns the text on the clipboard."
    requires_approval = False
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        rc, out, err = await _shell(["pbpaste"])
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err)
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"Clipboard: {len(out)} simboliai",
            data={"text": out, "length": len(out)},
        )


class SetClipboardTool(BaseTool):
    name = "set_clipboard"
    description = (
        "Write text to the macOS clipboard. "
        "Parameters: text (required)."
    )
    requires_approval = False
    parameters = [{"name": "text", "description": "Text to copy to clipboard", "required": True}]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        text: str = params.get("text", "")
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(input=text.encode()), timeout=5)
            return ToolResult(
                tool_name=self.name, status="success",
                message=f"✅ Clipboard atnaujintas ({len(text)} simboliai)",
                data={"length": len(text)},
            )
        except Exception as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))


class TakeScreenshotTool(BaseTool):
    name = "take_screenshot"
    description = (
        "Take a screenshot of the full screen or a specific app window and save to Desktop. "
        "Parameters: filename (optional, auto-generated), window (app name for window shot, optional). "
        "Returns the saved file path."
    )
    requires_approval = False
    parameters = [
        {"name": "filename", "description": "Output filename without extension", "required": False},
        {"name": "window",   "description": "App name for window screenshot", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = params.get("filename") or f"screenshot_{ts}"
        out_path = str(Path.home() / "Desktop" / f"{base}.png")
        window = params.get("window", "").strip()

        if window:
            script = (
                f'tell application "{window}" to activate\n'
                f'delay 0.3\n'
                f'do shell script "screencapture -l $(osascript -e \'tell app \\\"{window}\\\"\nreturn id of window 1\nend tell\') {out_path}"'
            )
            rc, _, err = await _osascript(script)
        else:
            rc, _, err = await _shell(["screencapture", "-x", out_path])

        if rc != 0 or not Path(out_path).exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Screenshot klaida: {err}")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Screenshot išsaugotas: {out_path}",
            data={"path": out_path},
        )


class GetScreenInfoTool(BaseTool):
    name = "get_screen_info"
    description = "Get screen resolution, display count, and system info."
    requires_approval = False
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        script = (
            "tell application \"System Events\"\n"
            "  set res to {}\n"
            "  repeat with d in desktops\n"
            "    set end of res to name of d\n"
            "  end repeat\n"
            "  return res\n"
            "end tell"
        )
        _, info_out, _ = await _shell(["system_profiler", "SPDisplaysDataType", "-json"])

        import json as _json
        try:
            display_data = _json.loads(info_out)
            displays = display_data.get("SPDisplaysDataType", [])
            resolutions = [
                {
                    "model": d.get("sppci_model", "Unknown"),
                    "resolution": d.get("_spdisplays_resolution", "Unknown"),
                }
                for d in displays
                if "_spdisplays_resolution" in d
            ]
        except Exception:
            resolutions = [{"model": "Unknown", "resolution": "Unknown"}]

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"{len(resolutions)} display(s) rasta",
            data={"displays": resolutions, "count": len(resolutions)},
        )


class ListRunningAppsTool(BaseTool):
    name = "list_running_apps"
    description = "List all currently running applications on macOS."
    requires_approval = False
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        script = (
            'tell application "System Events"\n'
            '  get name of every application process whose background only is false\n'
            'end tell'
        )
        rc, out, err = await _osascript(script)
        if rc != 0:
            # Fallback: ps
            _, ps_out, _ = await _shell(["ps", "aux"])
            apps = list({line.split()[-1].split("/")[-1] for line in ps_out.splitlines()[1:]
                        if not line.split()[-1].startswith("-")})[:30]
            return ToolResult(tool_name=self.name, status="success",
                              message=f"{len(apps)} procesai", data={"apps": sorted(apps)})

        apps = [a.strip() for a in out.split(",") if a.strip()]
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"{len(apps)} programos veikia",
            data={"apps": sorted(apps)},
        )


class GetBatteryStatusTool(BaseTool):
    name = "get_battery_status"
    description = "Get current battery level, charging status, and time remaining."
    requires_approval = False
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        rc, out, _ = await _shell(["pmset", "-g", "batt"])
        lines = out.splitlines()
        info: dict = {"raw": out}

        for line in lines:
            if "%" in line:
                import re
                m = re.search(r"(\d+)%", line)
                if m:
                    info["percentage"] = int(m.group(1))
                if "charging" in line.lower():
                    info["status"] = "charging"
                elif "discharging" in line.lower():
                    info["status"] = "discharging"
                elif "charged" in line.lower():
                    info["status"] = "fully charged"
                time_m = re.search(r"(\d+:\d+) remaining", line)
                if time_m:
                    info["time_remaining"] = time_m.group(1)

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"🔋 {info.get('percentage', '?')}% – {info.get('status', 'unknown')}",
            data=info,
        )


class GetDiskUsageTool(BaseTool):
    name = "get_disk_usage"
    description = (
        "Get disk usage for a path or the whole system. "
        "Parameters: path (optional, default '/'), human_readable (bool, default true)."
    )
    requires_approval = False
    parameters = [
        {"name": "path",           "description": "Path to check", "required": False},
        {"name": "human_readable", "description": "Human-readable sizes", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        path: str = params.get("path", "/")
        hr: bool  = params.get("human_readable", True)

        # df for filesystem
        args = ["df", "-h" if hr else "-k", path]
        rc1, df_out, _ = await _shell(args)

        # du for folder size
        args2 = ["du", "-sh" if hr else "-sk", path]
        rc2, du_out, _ = await _shell(args2)

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"Disk usage for {path}",
            data={"df": df_out, "du": du_out.split()[0] if du_out else "?", "path": path},
        )


class SpeakTextTool(BaseTool):
    name = "speak_text"
    description = (
        "Read text aloud using macOS built-in text-to-speech (say command). "
        "Parameters: text (required), voice (optional, e.g. 'Samantha', 'Tomas' for Lithuanian), "
        "rate (words per minute, default 175)."
    )
    requires_approval = False
    parameters = [
        {"name": "text",  "description": "Text to speak", "required": True},
        {"name": "voice", "description": "macOS voice name", "required": False},
        {"name": "rate",  "description": "Speech rate (wpm)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        text: str = params.get("text", "").strip()
        if not text:
            return ToolResult(tool_name=self.name, status="error", message="text is required")

        voice: str = params.get("voice", "")
        rate: int  = int(params.get("rate", 175))

        cmd = ["say"]
        if voice:
            cmd += ["-v", voice]
        cmd += ["-r", str(rate), text]

        rc, _, err = await _shell(cmd, timeout=60)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err)

        return ToolResult(
            tool_name=self.name, status="success",
            message="✅ Tekstas perskaitytas",
            data={"text": text, "voice": voice or "default"},
        )


class SetVolumeTool(BaseTool):
    name = "set_volume"
    description = (
        "Set the macOS system output volume. "
        "Parameters: level (0–100, required)."
    )
    requires_approval = False
    parameters = [{"name": "level", "description": "Volume level 0–100", "required": True}]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        level = max(0, min(100, int(params.get("level", 50))))
        script = f"set volume output volume {level}"
        rc, _, err = await _osascript(script)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err)
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"🔊 Garsumas nustatytas: {level}%",
            data={"level": level},
        )


class EmptyTrashTool(BaseTool):
    name = "empty_trash"
    description = "Empty the macOS Trash. This permanently deletes all items in the Trash."
    requires_approval = True
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        script = (
            'tell application "Finder"\n'
            '  empty the trash\n'
            'end tell'
        )
        rc, _, err = await _osascript(script, timeout=30)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err)
        return ToolResult(
            tool_name=self.name, status="success",
            message="✅ Šiukšliadėžė ištuštinta",
        )
