"""
voice_generation_tool.py – Text-to-speech with real audio output.

Provider priority:
  1. OpenAI TTS  (tts-1-hd, voice=nova – geriausiai taria lietuviškai, OPENAI_API_KEY)
  2. ElevenLabs  (multilingual, TTS_API_KEY / ELEVENLABS_API_KEY)
  3. Simulation  (returns structured plan – no audio file)

Result schema (always present in ToolResult.data):
  {
    "success":    bool,
    "simulation": bool,
    "provider":   "openai_tts" | "elevenlabs" | "simulation",
    "audio_path": str | None,   # absolute local path to saved .mp3
    "audio_url":  str | None,   # public URL if available
    "duration_s": float | None, # approximate spoken duration
    "voice_id":   str,
    "text_length": int,
    "error":      str | None,
  }

Env vars:
  OPENAI_API_KEY       – OpenAI key (primary – nova voice)
  TTS_API_KEY          – ElevenLabs API key (fallback)
  ELEVENLABS_API_KEY   – ElevenLabs API key (fallback alias)
  ELEVENLABS_VOICE_ID  – Voice ID (default: EXAVITQu4vr4xnSDxMaL = "Sarah", multilingual)
  TTS_OUTPUT_DIR       – Where to save audio files (default: ~/Desktop/Lani_Audio)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_SSL_CTX = ssl._create_unverified_context()

# ElevenLabs "Sarah" – high-quality multilingual female voice
_DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
_EL_BASE = "https://api.elevenlabs.io/v1"
_OAI_BASE = "https://api.openai.com/v1"

# ── Config helpers ────────────────────────────────────────────────────────────

def _tts_key() -> Optional[str]:
    """Return ElevenLabs key from TTS_API_KEY or ELEVENLABS_API_KEY."""
    from app.core.config import settings as cfg
    return (
        getattr(cfg, "TTS_API_KEY", "") or
        os.environ.get("TTS_API_KEY", "") or
        getattr(cfg, "ELEVENLABS_API_KEY", "") or
        os.environ.get("ELEVENLABS_API_KEY", "")
    ) or None


def _openai_key() -> Optional[str]:
    from app.core.config import settings as cfg
    return (getattr(cfg, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")) or None


def _voice_id() -> str:
    from app.core.config import settings as cfg
    return getattr(cfg, "ELEVENLABS_VOICE_ID", "") or os.environ.get("ELEVENLABS_VOICE_ID", "") or _DEFAULT_VOICE_ID


def _output_dir() -> Path:
    from app.core.config import settings as cfg
    d = Path(getattr(cfg, "TTS_OUTPUT_DIR", str(Path.home() / "Desktop" / "Lani_Audio"))).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Words-per-minute estimate for duration ────────────────────────────────────

def _estimate_duration(text: str) -> float:
    words = len(text.split())
    return round(words / 150, 1)   # ~150 wpm spoken pace


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

async def _elevenlabs_tts(text: str, voice_id: str, api_key: str, out_path: Path) -> None:
    """Call ElevenLabs TTS and save audio to out_path."""
    url = f"{_EL_BASE}/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.50,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    loop = asyncio.get_event_loop()
    def _do():
        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
                out_path.write_bytes(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"ElevenLabs {e.code}: {body}") from e

    await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=90)


# ── OpenAI TTS ────────────────────────────────────────────────────────────────

async def _openai_tts(text: str, api_key: str, out_path: Path) -> None:
    """Call OpenAI TTS (tts-1-hd) and save audio to out_path."""
    # Truncate to 4096 chars (OpenAI limit)
    payload = json.dumps({
        "model": "tts-1-hd",
        "input": text[:4096],
        "voice": "nova",
        "response_format": "mp3",
    }).encode()

    req = urllib.request.Request(
        f"{_OAI_BASE}/audio/speech",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    loop = asyncio.get_event_loop()
    def _do():
        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
                out_path.write_bytes(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"OpenAI TTS {e.code}: {body}") from e

    await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=90)


# ── Tool class ────────────────────────────────────────────────────────────────

class GenerateVoiceTool(BaseTool):
    """
    Convert text to spoken audio.

    Tries ElevenLabs first (best multilingual quality), then OpenAI TTS.
    Falls back to simulation when no TTS key is configured.
    """
    name = "generate_voice"
    description = (
        "Convert text to natural-sounding speech. "
        "Supports Lithuanian and 30+ languages via ElevenLabs or OpenAI TTS. "
        "Returns an .mp3 file path. Requires TTS_API_KEY (ElevenLabs) or OPENAI_API_KEY."
    )
    requires_approval = False
    parameters = [
        {
            "name": "text",
            "type": "str",
            "required": True,
            "description": "The text to convert to speech.",
        },
        {
            "name": "voice_id",
            "type": "str",
            "required": False,
            "description": (
                "ElevenLabs voice ID. Leave empty to use ELEVENLABS_VOICE_ID from config "
                "(default: Sarah – multilingual)."
            ),
        },
        {
            "name": "output_filename",
            "type": "str",
            "required": False,
            "description": "Output filename (e.g. 'voiceover.mp3'). Saved in TTS_OUTPUT_DIR.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        text: str = str(params.get("text", "")).strip()
        voice_id: str = str(params.get("voice_id", "") or _voice_id()).strip()
        filename: str = str(params.get("output_filename", "lani_voiceover.mp3")).strip()

        if not text:
            return ToolResult(
                tool_name=self.name, status="error",
                message="Parameter 'text' is required.",
                data={"success": False, "simulation": False, "provider": None, "error": "text required"},
            )

        out_path = _output_dir() / filename
        duration_est = _estimate_duration(text)

        # ── Try OpenAI TTS (pirmas – geriau taria lietuviškai) ───────────
        oai_key = _openai_key()
        if oai_key:
            try:
                log.info("[voice] OpenAI TTS nova: %d chars", len(text))
                await _openai_tts(text, oai_key, out_path)
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"✅ Audio generated (OpenAI TTS nova): {out_path} (~{duration_est}s)",
                    data={
                        "success": True,
                        "simulation": False,
                        "provider": "openai_tts",
                        "audio_path": str(out_path),
                        "audio_url": None,
                        "duration_s": duration_est,
                        "voice_id": "nova",
                        "text_length": len(text),
                        "error": None,
                    },
                )
            except Exception as exc:
                log.warning("[voice] OpenAI TTS failed, trying ElevenLabs: %s", exc)

        # ── Try ElevenLabs (atsarginis) ───────────────────────────────────
        el_key = _tts_key()
        if el_key:
            try:
                log.info("[voice] ElevenLabs TTS: %d chars, voice=%s", len(text), voice_id)
                await _elevenlabs_tts(text, voice_id, el_key, out_path)
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"✅ Audio generated: {out_path} (~{duration_est}s)",
                    data={
                        "success": True,
                        "simulation": False,
                        "provider": "elevenlabs",
                        "audio_path": str(out_path),
                        "audio_url": None,
                        "duration_s": duration_est,
                        "voice_id": voice_id,
                        "text_length": len(text),
                        "error": None,
                    },
                )
            except Exception as exc:
                log.warning("[voice] ElevenLabs failed: %s", exc)

        # ── Simulation fallback ────────────────────────────────────────────
        sim_error = "All TTS providers failed or no API keys configured (OPENAI_API_KEY or TTS_API_KEY)."
        log.info("[voice] simulation fallback – no TTS key available")
        return ToolResult(
            tool_name=self.name, status="success",
            message=(
                f"⚠ SIMULATION: TTS not configured. Voice plan generated.\n"
                f"Text length: {len(text)} chars | Estimated duration: ~{duration_est}s\n"
                f"Configure TTS_API_KEY (ElevenLabs) or OPENAI_API_KEY to enable real audio."
            ),
            data={
                "success": True,
                "simulation": True,
                "provider": "simulation",
                "audio_path": None,
                "audio_url": None,
                "duration_s": duration_est,
                "voice_id": voice_id,
                "text_length": len(text),
                "text_preview": text[:300],
                "error": sim_error,
                "setup_hint": "Add TTS_API_KEY=your_elevenlabs_key to .env",
            },
        )
