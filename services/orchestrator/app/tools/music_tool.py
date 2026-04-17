"""
music_tool.py – Generate music and songs from text using Suno AI.

Suno AI (suno.com) is the best AI music generation platform (2026-03):
  • Generates full songs with vocals + instruments from a text prompt
  • Supports custom lyrics input
  • Supports genre/style tags

Config (.env):
  SUNO_API_KEY=your_key

Note: Suno's official API is available through their enterprise tier.
This tool uses the Suno API v2 endpoint. For personal use, a community
API wrapper (https://github.com/gcui-art/suno-api) can be self-hosted.
Set SUNO_BASE_URL in .env to override (default: https://studio-api.suno.ai).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.services.llm_text_service import complete_text
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_SUNO_BASE = "https://studio-api.suno.ai/api"
_POLL_INTERVAL = 5
_MAX_WAIT = 300  # 5 min


def _suno_key() -> str:
    from app.core.config import settings as cfg
    key = getattr(cfg, "SUNO_API_KEY", "") or os.environ.get("SUNO_API_KEY", "")
    if not key:
        raise RuntimeError(
            "SUNO_API_KEY nenustatytas. Gauk raktą iš https://suno.com "
            "ir pridėk į .env: SUNO_API_KEY=..."
        )
    return key


def _suno_base() -> str:
    return os.environ.get("SUNO_BASE_URL", _SUNO_BASE).rstrip("/")


async def _post(endpoint: str, payload: dict, api_key: str) -> dict:
    url = f"{_suno_base()}/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
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
            raise RuntimeError(f"Suno API {e.code}: {body}") from e
    return await loop.run_in_executor(None, _do)


async def _get(endpoint: str, api_key: str) -> dict:
    url = f"{_suno_base()}/{endpoint}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    return await loop.run_in_executor(None, _do)


async def _download(url: str, out_path: Path) -> None:
    loop = asyncio.get_event_loop()
    def _do():
        with urllib.request.urlopen(url, timeout=120) as r:
            out_path.write_bytes(r.read())
    await loop.run_in_executor(None, _do)


async def _poll_song(clip_ids: list[str], api_key: str) -> list[dict]:
    """Poll until all clips are complete. Returns list of clip data."""
    ids_str = ",".join(clip_ids)
    waited = 0
    while waited < _MAX_WAIT:
        await asyncio.sleep(_POLL_INTERVAL)
        waited += _POLL_INTERVAL
        data = await _get(f"feed/?ids={ids_str}", api_key)
        clips = data if isinstance(data, list) else data.get("clips", [])
        statuses = [c.get("status", "") for c in clips]
        log.debug("[music] poll statuses: %s", statuses)
        if all(s == "complete" for s in statuses):
            return clips
        if any(s == "error" for s in statuses):
            errors = [c.get("error", "") for c in clips if c.get("status") == "error"]
            raise RuntimeError(f"Suno generation error: {errors}")
    raise RuntimeError(f"Suno task timed out after {_MAX_WAIT}s.")


# ──────────────────────────────────────────────────────────────────────────────
# Tool: Generate Song
# ──────────────────────────────────────────────────────────────────────────────

class GenerateSongTool(BaseTool):
    name = "generate_song"
    description = (
        "Generate a complete AI song (vocals + instruments + lyrics) from a text description. "
        "Uses Suno AI – best music generation model (2026). "
        "Saves .mp3 to ~/Desktop by default. "
        "Requires SUNO_API_KEY in .env."
    )
    parameters = [
        {
            "name": "prompt",
            "type": "str",
            "required": True,
            "description": (
                "Describe the song: style, mood, topic. "
                "Example: 'upbeat Lithuanian folk pop song about summer in Vilnius, female vocals'"
            ),
        },
        {
            "name": "lyrics",
            "type": "str",
            "required": False,
            "description": "Optional custom lyrics. If provided, Suno will use them.",
        },
        {
            "name": "style",
            "type": "str",
            "required": False,
            "description": "Genre/style tags, e.g. 'pop, electronic, sad, piano'. Optional.",
        },
        {
            "name": "title",
            "type": "str",
            "required": False,
            "description": "Song title. Optional.",
        },
        {
            "name": "output_dir",
            "type": "str",
            "required": False,
            "description": "Directory to save .mp3 files. Defaults to ~/Desktop.",
        },
        {
            "name": "instrumental",
            "type": "bool",
            "required": False,
            "description": "If true, generate instrumental only (no vocals). Default: false.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        prompt = str(params.get("prompt", "")).strip()
        lyrics = str(params.get("lyrics", "")).strip()
        style = str(params.get("style", "")).strip()
        title = str(params.get("title", "Lani Song")).strip()
        out_dir_str = str(params.get("output_dir", "")).strip()
        instrumental = bool(params.get("instrumental", False))

        if not prompt:
            return ToolResult(tool_name=self.name, status="error", message="'prompt' parametras būtinas.")

        out_dir = Path(out_dir_str) if out_dir_str else Path.home() / "Desktop"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            api_key = _suno_key()
        except RuntimeError as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))

        try:
            log.info("[music] generating song: %r (instrumental=%s)", prompt[:80], instrumental)

            payload: dict = {
                "make_instrumental": instrumental,
                "wait_audio": False,
            }

            if lyrics:
                # Custom mode: user-provided lyrics
                payload.update({
                    "prompt": lyrics,
                    "tags": style or "",
                    "title": title,
                })
                endpoint = "generate/custom-mode/"
            else:
                # Descriptive mode: Suno writes the lyrics
                full_prompt = prompt
                if style:
                    full_prompt = f"{style}. {prompt}"
                payload["prompt"] = full_prompt
                endpoint = "generate/"

            resp = await _post(endpoint, payload, api_key)
            clips_raw = resp if isinstance(resp, list) else resp.get("clips", [])
            if not clips_raw:
                raise RuntimeError(f"No clips in response: {resp}")

            clip_ids = [c["id"] for c in clips_raw if c.get("id")]
            if not clip_ids:
                raise RuntimeError("No clip IDs returned.")

            log.info("[music] polling %d clip(s): %s", len(clip_ids), clip_ids)
            clips = await _poll_song(clip_ids, api_key)

            saved = []
            for clip in clips:
                audio_url = clip.get("audio_url", "")
                if not audio_url:
                    continue
                clip_title = clip.get("title", title)
                safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in clip_title)
                out_path = out_dir / f"{safe_name[:50]}.mp3"
                await _download(audio_url, out_path)
                saved.append(str(out_path))

            if not saved:
                raise RuntimeError("Generation succeeded but no audio URLs available.")

            # Token tracking (approximate)
            try:
                from app.services.token_tracker import record_usage
                record_usage("suno/v2", len(clip_ids) * 1000, 0, "music")
            except Exception:
                pass

            files_str = "\n".join(f"  • {f}" for f in saved)
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"✅ {len(saved)} daina(-os) sukurta(-os):\n{files_str}",
                data={"files": saved},
            )

        except Exception as exc:
            log.exception("[music] generation failed")
            return ToolResult(tool_name=self.name, status="error", message=f"Dainos kūrimas nepavyko: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# Tool: Write Lyrics (GPT-4.5 + optional song generation)
# ──────────────────────────────────────────────────────────────────────────────

class WriteLyricsTool(BaseTool):
    name = "write_lyrics"
    description = (
        "Write song lyrics for any theme, style, or language using AI. "
        "Optionally also generate the actual song audio (if SUNO_API_KEY is set). "
        "No API key required just for lyrics writing."
    )
    parameters = [
        {
            "name": "topic",
            "type": "str",
            "required": True,
            "description": "What the song should be about.",
        },
        {
            "name": "style",
            "type": "str",
            "required": False,
            "description": "Musical style/genre, e.g. 'hip-hop', 'ballad', 'punk rock'.",
        },
        {
            "name": "language",
            "type": "str",
            "required": False,
            "description": "Language for lyrics: 'lt' (Lithuanian), 'en', 'de', etc. Default: same as UI language.",
        },
        {
            "name": "also_generate_audio",
            "type": "bool",
            "required": False,
            "description": "If true and SUNO_API_KEY is set, also generate the song audio. Default: false.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        topic = str(params.get("topic", "")).strip()
        style = str(params.get("style", "pop")).strip()
        language = str(params.get("language", "lt")).strip()
        also_audio = bool(params.get("also_generate_audio", False))

        if not topic:
            return ToolResult(tool_name=self.name, status="error", message="'topic' parametras būtinas.")

        from app.core.config import settings as cfg
        api_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
        anthropic_key = getattr(cfg, "ANTHROPIC_API_KEY", "") or ""

        lang_map = {
            "lt": "Lithuanian", "en": "English", "de": "German",
            "fr": "French", "es": "Spanish", "ru": "Russian",
        }
        lang_name = lang_map.get(language, language)

        prompt = (
            f"Write complete song lyrics in {lang_name}.\n"
            f"Topic: {topic}\n"
            f"Style/genre: {style}\n\n"
            "Include: verse 1, chorus, verse 2, chorus, bridge, final chorus.\n"
            "Make the lyrics emotional, memorable, and fit the style perfectly.\n"
            "Format with clear section labels like [Verse 1], [Chorus], etc."
        )

        lyrics = ""
        try:
            if not anthropic_key and not api_key:
                return ToolResult(tool_name=self.name, status="error", message="Nenustatytas AI API raktas.")

            lyrics = await complete_text(
                openai_api_key=api_key,
                anthropic_api_key=anthropic_key,
                openai_model=getattr(cfg, "LLM_MODEL", "gpt-4.5-preview"),
                anthropic_model=getattr(cfg, "ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219"),
                openai_messages=[{"role": "user", "content": prompt}],
                anthropic_messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                provider_preference="anthropic_first" if anthropic_key else "openai_first",
                tracking_operation="music_lyrics",
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=f"Tekstų kūrimas nepavyko: {exc}")

        result_msg = f"🎵 **{topic}** ({style}, {lang_name})\n\n{lyrics}"

        # Optionally generate audio too
        if also_audio:
            try:
                audio_tool = GenerateSongTool()
                audio_result = await audio_tool.run(
                    {
                        "prompt": f"{style} song about {topic}",
                        "lyrics": lyrics,
                        "style": style,
                        "title": topic[:50],
                    }
                )
                if audio_result.status == "success":
                    result_msg += f"\n\n{audio_result.message}"
                else:
                    result_msg += f"\n\n⚠️ Audio nepavyko: {audio_result.message}"
            except Exception as exc:
                result_msg += f"\n\n⚠️ Audio klaida: {exc}"

        return ToolResult(tool_name=self.name, status="success", message=result_msg, data={"lyrics": lyrics})
