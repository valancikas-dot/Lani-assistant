"""
music_generation_tool.py – Suno AI music generation with simulation fallback.

Wraps the Suno AI API with:
  • graceful simulation when MUSIC_API_KEY / SUNO_API_KEY is absent
  • unified {success, data, provider, simulation, error} result schema
  • poll timeout: 300 s
  • retry on transient failures: up to 2 attempts

Result schema (ToolResult.data):
  {
    "success":      bool,
    "simulation":   bool,
    "provider":     "suno_ai" | "simulation",
    "track_paths":  List[str],   # local .mp3 paths
    "track_urls":   List[str],   # Suno CDN audio URLs
    "style":        str,
    "title":        str,
    "duration_s":   float | None,
    "error":        str | None,
  }

Env vars:
  MUSIC_API_KEY   – primary (alias for SUNO_API_KEY)
  SUNO_API_KEY    – Suno AI key
  SUNO_BASE_URL   – override base URL (for self-hosted suno-api proxy)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_DEFAULT_SUNO_BASE = "https://studio-api.suno.ai/api"
_POLL_INTERVAL = 5
_MAX_WAIT = 300
_RETRY_LIMIT = 2

# ── Config helpers ─────────────────────────────────────────────────────────────

def _music_key() -> Optional[str]:
    from app.core.config import settings as cfg
    return (
        getattr(cfg, "MUSIC_API_KEY", "") or
        os.environ.get("MUSIC_API_KEY", "") or
        getattr(cfg, "SUNO_API_KEY", "") or
        os.environ.get("SUNO_API_KEY", "")
    ) or None


def _suno_base() -> str:
    return os.environ.get("SUNO_BASE_URL", _DEFAULT_SUNO_BASE).rstrip("/")


def _output_dir() -> Path:
    d = Path.home() / "Desktop" / "Lani_Music"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def _post(endpoint: str, payload: dict, api_key: str) -> Any:
    url = f"{_suno_base()}/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    loop = asyncio.get_event_loop()
    def _do():
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"Suno {e.code}: {body}") from e
    return await loop.run_in_executor(None, _do)


async def _get(endpoint: str, api_key: str) -> Any:
    url = f"{_suno_base()}/{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    return await loop.run_in_executor(None, _do)


async def _poll_clips(clip_ids: List[str], api_key: str) -> List[dict]:
    """Poll until all clips are complete."""
    ids_str = ",".join(clip_ids)
    waited = 0
    while waited < _MAX_WAIT:
        await asyncio.sleep(_POLL_INTERVAL)
        waited += _POLL_INTERVAL
        data = await _get(f"feed/?ids={ids_str}", api_key)
        clips = data if isinstance(data, list) else data.get("clips", [])
        statuses = [c.get("status", "") for c in clips]
        log.debug("[music_ext] poll statuses: %s", statuses)
        if all(s == "complete" for s in statuses):
            return clips
        if any(s == "error" for s in statuses):
            errors = [c.get("error") for c in clips if c.get("status") == "error"]
            raise RuntimeError(f"Suno generation error: {errors}")
    raise RuntimeError(f"Suno task timed out after {_MAX_WAIT}s.")


async def _download(url: str, out_path: Path) -> None:
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(url, timeout=120) as r:
            out_path.write_bytes(r.read())
    await loop.run_in_executor(None, _do)


# ── Real generation ────────────────────────────────────────────────────────────

async def _generate_suno(
    prompt: str, lyrics: str, style: str, title: str,
    instrumental: bool, api_key: str
) -> tuple[List[str], List[str]]:
    """Generate song. Returns (local_paths, audio_urls)."""
    out_dir = _output_dir()

    if lyrics:
        payload = {
            "prompt": lyrics,
            "tags": style or "",
            "title": title,
            "make_instrumental": instrumental,
            "wait_audio": False,
        }
        endpoint = "generate/custom-mode/"
    else:
        full_prompt = f"{style}. {prompt}" if style else prompt
        payload = {"prompt": full_prompt, "make_instrumental": instrumental, "wait_audio": False}
        endpoint = "generate/"

    resp = await _post(endpoint, payload, api_key)
    clips_raw = resp if isinstance(resp, list) else resp.get("clips", [])
    if not clips_raw:
        raise RuntimeError(f"No clips in response: {resp}")

    clip_ids = [c["id"] for c in clips_raw if c.get("id")]
    if not clip_ids:
        raise RuntimeError("No clip IDs returned.")

    clips = await _poll_clips(clip_ids, api_key)

    paths: List[str] = []
    urls: List[str] = []
    for clip in clips:
        audio_url = clip.get("audio_url", "")
        if not audio_url:
            continue
        urls.append(audio_url)
        clip_title = clip.get("title", title)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in clip_title)
        out_path = out_dir / f"{safe[:50]}.mp3"
        await _download(audio_url, out_path)
        paths.append(str(out_path))

    return paths, urls


# ── Tool class ─────────────────────────────────────────────────────────────────

class GenerateSongExtTool(BaseTool):
    """
    Generate a complete AI song using Suno AI.
    Falls back to simulation if MUSIC_API_KEY / SUNO_API_KEY is not set.
    """
    name = "generate_song_ext"
    description = (
        "Generate a full AI song (vocals + instruments) from a text description using Suno AI. "
        "Saves .mp3 locally. Gracefully simulates when MUSIC_API_KEY is absent."
    )
    requires_approval = True
    parameters = [
        {"name": "prompt", "type": "str", "required": True,
         "description": "Song description: style, mood, topic."},
        {"name": "lyrics", "type": "str", "required": False,
         "description": "Optional custom lyrics text."},
        {"name": "style", "type": "str", "required": False,
         "description": "Style/genre tags, e.g. 'pop, electronic, melancholic'."},
        {"name": "title", "type": "str", "required": False,
         "description": "Song title."},
        {"name": "instrumental", "type": "bool", "required": False,
         "description": "Generate instrumental only (no vocals). Default: false."},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        prompt: str = str(params.get("prompt", "")).strip()
        lyrics: str = str(params.get("lyrics", "")).strip()
        style: str = str(params.get("style", "")).strip()
        title: str = str(params.get("title", "Lani Song")).strip()
        instrumental: bool = bool(params.get("instrumental", False))

        if not prompt:
            return ToolResult(
                tool_name=self.name, status="error",
                message="Parameter 'prompt' is required.",
                data={"success": False, "simulation": False, "provider": None, "error": "prompt required"},
            )

        api_key = _music_key()

        if not api_key:
            log.info("[music_ext] no MUSIC_API_KEY – simulation fallback")
            return ToolResult(
                tool_name=self.name, status="success",
                message=(
                    "⚠ SIMULATION: MUSIC_API_KEY not configured.\n"
                    "Add SUNO_API_KEY or MUSIC_API_KEY to .env to enable real music generation."
                ),
                data={
                    "success": True,
                    "simulation": True,
                    "provider": "simulation",
                    "track_paths": [],
                    "track_urls": [],
                    "style": style,
                    "title": title,
                    "duration_s": None,
                    "lyrics_preview": lyrics[:200] if lyrics else None,
                    "error": None,
                    "setup_hint": "Add MUSIC_API_KEY=your_suno_key to .env (https://suno.com)",
                },
            )

        last_error: Optional[str] = None
        for attempt in range(1, _RETRY_LIMIT + 1):
            try:
                log.info("[music_ext] attempt %d/%d – generating '%s'", attempt, _RETRY_LIMIT, title)
                paths, urls = await _generate_suno(prompt, lyrics, style, title, instrumental, api_key)
                if not paths:
                    raise RuntimeError("Generation succeeded but no audio URLs available.")
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"✅ {len(paths)} track(s) generated: {', '.join(paths)}",
                    data={
                        "success": True,
                        "simulation": False,
                        "provider": "suno_ai",
                        "track_paths": paths,
                        "track_urls": urls,
                        "style": style,
                        "title": title,
                        "duration_s": None,
                        "error": None,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                log.warning("[music_ext] attempt %d failed: %s", attempt, exc)
                if attempt < _RETRY_LIMIT:
                    await asyncio.sleep(5)

        return ToolResult(
            tool_name=self.name, status="error",
            message=f"Music generation failed after {_RETRY_LIMIT} attempts: {last_error}",
            data={
                "success": False,
                "simulation": False,
                "provider": "suno_ai",
                "track_paths": [],
                "track_urls": [],
                "style": style,
                "title": title,
                "duration_s": None,
                "error": last_error,
            },
        )
