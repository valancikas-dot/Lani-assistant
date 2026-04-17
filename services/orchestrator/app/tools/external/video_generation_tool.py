"""
video_generation_tool.py – Runway ML Gen-4 Turbo with simulation fallback.

Wraps the core Runway ML HTTP logic with:
  • graceful simulation when RUNWAY_API_KEY / VIDEO_API_KEY is absent
  • unified {success, data, provider, simulation, error} result schema
  • explicit timeout (300 s polling max)
  • retry on transient 5xx errors (up to 2 retries)

Result schema (ToolResult.data):
  {
    "success":      bool,
    "simulation":   bool,
    "provider":     "runway_gen4" | "simulation",
    "video_path":   str | None,   # local .mp4 path
    "video_url":    str | None,   # Runway CDN URL before download
    "duration_s":   int,
    "ratio":        str,
    "prompt_used":  str,
    "error":        str | None,
  }

Env vars:
  VIDEO_API_KEY   – primary key (alias for RUNWAY_API_KEY)
  RUNWAY_API_KEY  – Runway ML key
  RUNWAY_MODEL    – model override (default: gen4_turbo)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_RUNWAY_BASE = "https://api.runwayml.com/v1"
_POLL_INTERVAL = 5
_MAX_WAIT = 300
_RETRY_LIMIT = 2

# ── Config helpers ─────────────────────────────────────────────────────────────

def _video_key() -> Optional[str]:
    from app.core.config import settings as cfg
    return (
        getattr(cfg, "VIDEO_API_KEY", "") or
        os.environ.get("VIDEO_API_KEY", "") or
        getattr(cfg, "RUNWAY_API_KEY", "") or
        os.environ.get("RUNWAY_API_KEY", "")
    ) or None


def _runway_model() -> str:
    from app.core.config import settings as cfg
    return getattr(cfg, "RUNWAY_MODEL", "gen4_turbo")


def _output_dir() -> Path:
    d = Path.home() / "Desktop" / "Lani_Video"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def _post(endpoint: str, payload: dict, api_key: str) -> dict:
    url = f"{_RUNWAY_BASE}/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Runway-Version": "2024-11-06",
        },
        method="POST",
    )
    loop = asyncio.get_event_loop()
    def _do():
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"Runway {e.code}: {body}") from e
    return await loop.run_in_executor(None, _do)


async def _get(endpoint: str, api_key: str) -> dict:
    url = f"{_RUNWAY_BASE}/{endpoint}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Runway-Version": "2024-11-06",
        },
    )
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    return await loop.run_in_executor(None, _do)


async def _poll_task(task_id: str, api_key: str) -> str:
    """Poll until task SUCCEEDED. Returns output URL."""
    waited = 0
    while waited < _MAX_WAIT:
        await asyncio.sleep(_POLL_INTERVAL)
        waited += _POLL_INTERVAL
        data = await _get(f"tasks/{task_id}", api_key)
        status = data.get("status", "")
        log.debug("[video_ext] task %s → %s", task_id, status)
        if status == "SUCCEEDED":
            outputs = data.get("output", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("Task SUCCEEDED but no output URL.")
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Runway task {status}: {data.get('failure', '')}")
    raise RuntimeError(f"Runway task timed out after {_MAX_WAIT}s.")


async def _download(url: str, out_path: Path) -> None:
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(url, timeout=120) as r:
            out_path.write_bytes(r.read())
    await loop.run_in_executor(None, _do)


# ── Real generation ────────────────────────────────────────────────────────────

async def _generate_runway(prompt: str, duration: int, ratio: str, api_key: str, out_path: Path) -> str:
    """Execute text→image→video pipeline. Returns video CDN URL."""
    model = _runway_model()
    log.info("[video_ext] text→image (%s %ds %s)", model, duration, ratio)

    # Step 1: text → seed image
    w, h = (
        (1280, 720) if ratio == "16:9" else
        (720, 1280) if ratio == "9:16" else
        (1024, 1024)
    )
    img_resp = await _post("text_to_image", {
        "model": "gen3a_turbo",
        "promptText": prompt,
        "width": w, "height": h,
    }, api_key)
    img_url = img_resp.get("url") or (img_resp.get("artifacts") or [{}])[0].get("url")
    if not img_url:
        raise RuntimeError(f"text_to_image returned no URL: {img_resp}")

    # Step 2: image → video
    vid_resp = await _post("image_to_video", {
        "model": model,
        "promptImage": img_url,
        "promptText": prompt,
        "duration": duration,
        "ratio": ratio,
    }, api_key)
    task_id = vid_resp.get("id")
    if not task_id:
        raise RuntimeError(f"No task ID: {vid_resp}")

    # Step 3: poll + download
    video_url = await _poll_task(task_id, api_key)
    await _download(video_url, out_path)
    return video_url


# ── Tool class ─────────────────────────────────────────────────────────────────

class GenerateVideoExtTool(BaseTool):
    """
    Generate a short video from a text prompt using Runway ML Gen-4 Turbo.
    Falls back to simulation if VIDEO_API_KEY / RUNWAY_API_KEY is not set.
    """
    name = "generate_video_ext"
    description = (
        "Generate a short video clip (5–10 s) from a text description via Runway ML Gen-4 Turbo. "
        "Saves .mp4 locally. Gracefully simulates when VIDEO_API_KEY is absent."
    )
    requires_approval = True   # video generation incurs cost
    parameters = [
        {"name": "prompt", "type": "str", "required": True,
         "description": "Detailed scene description for the video."},
        {"name": "duration", "type": "int", "required": False,
         "description": "Clip length in seconds: 5 or 10 (default: 5)."},
        {"name": "ratio", "type": "str", "required": False,
         "description": "Aspect ratio: '16:9' | '9:16' | '1:1' (default: 9:16)."},
        {"name": "output_filename", "type": "str", "required": False,
         "description": "Output filename, e.g. 'scene1.mp4'."},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        prompt: str = str(params.get("prompt", "")).strip()
        duration: int = int(params.get("duration", 5))
        ratio: str = str(params.get("ratio", "9:16")).strip()
        filename: str = str(params.get("output_filename", "lani_video.mp4")).strip()

        if not prompt:
            return ToolResult(
                tool_name=self.name, status="error",
                message="Parameter 'prompt' is required.",
                data={"success": False, "simulation": False, "provider": None, "error": "prompt required"},
            )

        if duration not in (5, 10):
            duration = 5

        out_path = _output_dir() / filename
        api_key = _video_key()

        if not api_key:
            log.info("[video_ext] no VIDEO_API_KEY – simulation fallback")
            return ToolResult(
                tool_name=self.name, status="success",
                message=(
                    "⚠ SIMULATION: VIDEO_API_KEY not configured.\n"
                    "Add RUNWAY_API_KEY or VIDEO_API_KEY to .env to enable real video generation."
                ),
                data={
                    "success": True,
                    "simulation": True,
                    "provider": "simulation",
                    "video_path": None,
                    "video_url": None,
                    "duration_s": duration,
                    "ratio": ratio,
                    "prompt_used": prompt[:200],
                    "error": None,
                    "setup_hint": "Add VIDEO_API_KEY=rw-... to .env (get key at runwayml.com)",
                },
            )

        # Real generation with retry
        last_error: Optional[str] = None
        for attempt in range(1, _RETRY_LIMIT + 1):
            try:
                log.info("[video_ext] attempt %d/%d – generating %ds %s video", attempt, _RETRY_LIMIT, duration, ratio)
                video_url = await _generate_runway(prompt, duration, ratio, api_key, out_path)
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"✅ Video generated: {out_path}",
                    data={
                        "success": True,
                        "simulation": False,
                        "provider": "runway_gen4",
                        "video_path": str(out_path),
                        "video_url": video_url,
                        "duration_s": duration,
                        "ratio": ratio,
                        "prompt_used": prompt[:200],
                        "error": None,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                log.warning("[video_ext] attempt %d failed: %s", attempt, exc)
                if attempt < _RETRY_LIMIT:
                    await asyncio.sleep(3)

        return ToolResult(
            tool_name=self.name, status="error",
            message=f"Video generation failed after {_RETRY_LIMIT} attempts: {last_error}",
            data={
                "success": False,
                "simulation": False,
                "provider": "runway_gen4",
                "video_path": None,
                "video_url": None,
                "duration_s": duration,
                "ratio": ratio,
                "prompt_used": prompt[:200],
                "error": last_error,
            },
        )
