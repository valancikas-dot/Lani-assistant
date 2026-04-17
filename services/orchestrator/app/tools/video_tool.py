"""
video_tool.py – Generate short video clips / Reels from text prompts.

Uses Runway ML Gen-4 Turbo API (best-in-class video generation, 2026-03).
Also supports image-to-video for animating existing images.

Requirements:
  pip install runwayml   (or HTTP calls – no SDK dependency used here)

Config (.env):
  RUNWAY_API_KEY=your_key
  RUNWAY_MODEL=gen4_turbo   (default)

Endpoints used:
  POST https://api.runwayml.com/v1/image_to_video    – image+prompt → video
  POST https://api.runwayml.com/v1/text_to_image     – text → image (for pure text→video)
  GET  https://api.runwayml.com/v1/tasks/{id}        – poll for result
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_RUNWAY_BASE = "https://api.runwayml.com/v1"
_POLL_INTERVAL = 5   # seconds between status polls
_MAX_WAIT = 300      # 5 minutes max


def _runway_key() -> str:
    from app.core.config import settings as cfg
    key = getattr(cfg, "RUNWAY_API_KEY", "") or os.environ.get("RUNWAY_API_KEY", "")
    if not key:
        raise RuntimeError(
            "RUNWAY_API_KEY nenustatytas. Gauk raktą iš https://runwayml.com ir "
            "pridėk į .env: RUNWAY_API_KEY=rw-..."
        )
    return key


def _runway_model() -> str:
    from app.core.config import settings as cfg
    return getattr(cfg, "RUNWAY_MODEL", "gen4_turbo")


async def _http_post(endpoint: str, payload: dict, api_key: str) -> dict:
    """Async HTTP POST to Runway API."""
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
            body = e.read().decode()
            raise RuntimeError(f"Runway API {e.code}: {body}") from e
    return await loop.run_in_executor(None, _do)


async def _http_get(endpoint: str, api_key: str) -> dict:
    """Async HTTP GET to Runway API."""
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
    """Poll until task completes. Returns output URL."""
    waited = 0
    while waited < _MAX_WAIT:
        await asyncio.sleep(_POLL_INTERVAL)
        waited += _POLL_INTERVAL
        data = await _http_get(f"tasks/{task_id}", api_key)
        status = data.get("status", "")
        log.debug("[video] task %s status=%s", task_id, status)
        if status == "SUCCEEDED":
            outputs = data.get("output", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("Task succeeded but no output URL found.")
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Runway task {status}: {data.get('failure', '')}")
    raise RuntimeError(f"Runway task timed out after {_MAX_WAIT}s.")


async def _download_video(url: str, out_path: Path) -> None:
    """Download video from URL to local path."""
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(url, timeout=60) as r:
            out_path.write_bytes(r.read())
    await loop.run_in_executor(None, _do)


# ──────────────────────────────────────────────────────────────────────────────
# Tool: Text → Video (via intermediate image)
# ──────────────────────────────────────────────────────────────────────────────

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    description = (
        "Create a short video clip (≤10 sec) from a text description. "
        "Uses Runway Gen-4 Turbo – best AI video model available (2026). "
        "Saves to ~/Desktop by default. "
        "Requires RUNWAY_API_KEY in .env."
    )
    parameters = [
        {
            "name": "prompt",
            "type": "str",
            "required": True,
            "description": "Describe the video scene in detail (English gives best results).",
        },
        {
            "name": "duration",
            "type": "int",
            "required": False,
            "description": "Duration in seconds: 5 or 10 (default: 5).",
        },
        {
            "name": "output_path",
            "type": "str",
            "required": False,
            "description": "Where to save the .mp4 file. Defaults to ~/Desktop/lani_video.mp4",
        },
        {
            "name": "ratio",
            "type": "str",
            "required": False,
            "description": "Aspect ratio: '16:9' (landscape), '9:16' (reels/portrait), '1:1' (square). Default: 9:16",
        },
    ]

    async def run(self, **kwargs) -> ToolResult:
        prompt: str = kwargs.get("prompt", "").strip()
        duration: int = int(kwargs.get("duration", 5))
        ratio: str = kwargs.get("ratio", "9:16")
        out_str: str = kwargs.get("output_path", "").strip()

        if not prompt:
            return ToolResult(ok=False, message="'prompt' parametras būtinas.")

        if duration not in (5, 10):
            duration = 5

        out_path = Path(out_str) if out_str else Path.home() / "Desktop" / "lani_video.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            api_key = _runway_key()
        except RuntimeError as e:
            return ToolResult(ok=False, message=str(e))

        try:
            model = _runway_model()
            log.info("[video] generating %ds %s video: %r", duration, ratio, prompt[:80])

            # Step 1: text → image (first frame)
            img_resp = await _http_post("text_to_image", {
                "model": "gen3a_turbo",
                "promptText": prompt,
                "width": 1280 if ratio == "16:9" else (720 if ratio == "9:16" else 1024),
                "height": 720 if ratio == "16:9" else (1280 if ratio == "9:16" else 1024),
            }, api_key)

            img_url = img_resp.get("url") or (img_resp.get("artifacts") or [{}])[0].get("url")
            if not img_url:
                raise RuntimeError(f"text_to_image returned no URL: {img_resp}")

            # Step 2: image → video
            vid_resp = await _http_post("image_to_video", {
                "model": model,
                "promptImage": img_url,
                "promptText": prompt,
                "duration": duration,
                "ratio": ratio,
            }, api_key)

            task_id = vid_resp.get("id")
            if not task_id:
                raise RuntimeError(f"No task ID in response: {vid_resp}")

            # Step 3: poll until done
            video_url = await _poll_task(task_id, api_key)

            # Step 4: download
            await _download_video(video_url, out_path)

            # Token tracking (approximate cost)
            try:
                from app.services.token_tracker import record_usage
                record_usage("runway/gen4_turbo", duration * 1000, 0, "video")
            except Exception:
                pass

            return ToolResult(
                ok=True,
                message=f"✅ Video sukurtas: {out_path}\n"
                        f"Trukmė: {duration}s | Formatas: {ratio} | Modelis: {model}",
            )

        except Exception as exc:
            log.exception("[video] generation failed")
            return ToolResult(ok=False, message=f"Video kūrimas nepavyko: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# Tool: Image → Video (animate an existing image)
# ──────────────────────────────────────────────────────────────────────────────

class AnimateImageTool(BaseTool):
    name = "animate_image"
    description = (
        "Animate a still image into a short video using Runway Gen-4 Turbo. "
        "Provide a local image path or URL and a motion description. "
        "Requires RUNWAY_API_KEY in .env."
    )
    parameters = [
        {
            "name": "image",
            "type": "str",
            "required": True,
            "description": "Local path or public URL of the image to animate.",
        },
        {
            "name": "prompt",
            "type": "str",
            "required": True,
            "description": "Describe the motion / animation (e.g. 'camera slowly zooms in, leaves rustling').",
        },
        {
            "name": "duration",
            "type": "int",
            "required": False,
            "description": "Duration: 5 or 10 seconds (default: 5).",
        },
        {
            "name": "output_path",
            "type": "str",
            "required": False,
            "description": "Where to save the .mp4. Defaults to ~/Desktop/lani_animated.mp4",
        },
    ]

    async def run(self, **kwargs) -> ToolResult:
        import base64
        import mimetypes

        image: str = kwargs.get("image", "").strip()
        prompt: str = kwargs.get("prompt", "").strip()
        duration: int = int(kwargs.get("duration", 5))
        out_str: str = kwargs.get("output_path", "").strip()

        if not image:
            return ToolResult(ok=False, message="'image' parametras būtinas.")
        if not prompt:
            return ToolResult(ok=False, message="'prompt' parametras būtinas.")

        if duration not in (5, 10):
            duration = 5

        out_path = Path(out_str) if out_str else Path.home() / "Desktop" / "lani_animated.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            api_key = _runway_key()
        except RuntimeError as e:
            return ToolResult(ok=False, message=str(e))

        # Resolve image to URL or data URI
        if image.startswith(("http://", "https://")):
            image_input = image
        else:
            p = Path(image)
            if not p.exists():
                return ToolResult(ok=False, message=f"Paveikslėlis nerastas: {image}")
            mime, _ = mimetypes.guess_type(str(p))
            mime = mime or "image/jpeg"
            b64 = base64.b64encode(p.read_bytes()).decode()
            image_input = f"data:{mime};base64,{b64}"

        try:
            model = _runway_model()
            vid_resp = await _http_post("image_to_video", {
                "model": model,
                "promptImage": image_input,
                "promptText": prompt,
                "duration": duration,
            }, api_key)

            task_id = vid_resp.get("id")
            if not task_id:
                raise RuntimeError(f"No task ID: {vid_resp}")

            video_url = await _poll_task(task_id, api_key)
            await _download_video(video_url, out_path)

            return ToolResult(
                ok=True,
                message=f"✅ Animuotas video sukurtas: {out_path}\nTrukmė: {duration}s",
            )

        except Exception as exc:
            log.exception("[animate] failed")
            return ToolResult(ok=False, message=f"Animacijos kūrimas nepavyko: {exc}")
