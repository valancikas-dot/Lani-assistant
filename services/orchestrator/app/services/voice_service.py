"""
Voice service – STT (transcription) and TTS (synthesis) abstraction layer.

Architecture
------------
This module defines the *interface* that all voice providers must satisfy, plus
a built-in ``PlaceholderProvider`` that returns descriptive stub responses when
no real provider is configured.

Adding a real provider
~~~~~~~~~~~~~~~~~~~~~~
1. Create a new class that inherits from ``VoiceProvider``.
2. Implement ``transcribe`` and ``synthesize``.
3. Register it in ``_get_provider()`` by checking for the required env vars /
   API keys in ``app.core.config.settings``.

Example skeleton for an OpenAI-compatible provider::

    class OpenAIVoiceProvider(VoiceProvider):
        name = "openai"

        async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            result = await client.audio.transcriptions.create(
                model="whisper-1",
                file=("audio.webm", io.BytesIO(audio), "audio/webm"),
                language=language,
            )
            return TranscribeResponse(
                transcript=result.text,
                provider=self.name,
                status="success",
            )

        async def synthesize(self, text: str, voice: str, language: str) -> SynthesizeResponse:
            import base64, openai
            client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.audio.speech.create(
                model="tts-1", voice=voice or "alloy", input=text
            )
            audio_bytes = response.read()
            return SynthesizeResponse(
                audio_base64=base64.b64encode(audio_bytes).decode(),
                mime_type="audio/mpeg",
                provider=self.name,
                status="success",
            )
"""

from __future__ import annotations

import abc
import urllib.request
import urllib.error


def _detect_audio_format(audio: bytes) -> tuple[str, str]:
    """Detect real audio format from magic bytes and return (filename, mime_type).

    MediaRecorder gali siųsti WebM, OGG, arba MP4 nepriklausomai nuo MIME header.
    OpenAI Whisper API atmeta failą jei pavadinimas neatitinka turinio.
    """
    if audio[:4] == b"RIFF":
        return "audio.wav", "audio/wav"
    if audio[:4] == b"fLaC":
        return "audio.flac", "audio/flac"
    if audio[:4] == b"\x1aE\xdf\xa3":
        return "audio.webm", "audio/webm"
    if audio[:4] == b"OggS":
        return "audio.ogg", "audio/ogg"
    if audio[4:8] in (b"ftyp", b"moov", b"mdat"):
        return "audio.mp4", "audio/mp4"
    if audio[:3] == b"ID3" or (len(audio) > 1 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0):
        return "audio.mp3", "audio/mpeg"
    # Numatytasis: webm (dažniausias iš MediaRecorder)
    return "audio.webm", "audio/webm"


# Minimalus WebM EBML Document header + Segment header.
# Tauri WKWebView MediaRecorder siunčia Cluster chunks be šio header,
# todėl pridedame jį rankiniu būdu kad OpenAI Whisper priimtų failą.
#
# Šis header yra minimalus validus WebM konteineris:
#   EBML (1a 45 df a3) + size + DocType "webm" + DocTypeVersion 4
#   Segment (18 53 80 67) + unknown size (ff ff ff ff ff ff ff)
_WEBM_EBML_HEADER = bytes([
    # EBML header element
    0x1a, 0x45, 0xdf, 0xa3,  # EBML ID
    0xa3,                     # size = 35 bytes
    0x42, 0x86, 0x81, 0x04,  # EBMLVersion = 4
    0x42, 0xf7, 0x81, 0x01,  # EBMLReadVersion = 1
    0x42, 0xf2, 0x81, 0x04,  # EBMLMaxIDLength = 4
    0x42, 0xf3, 0x81, 0x08,  # EBMLMaxSizeLength = 8
    0x42, 0x82, 0x84,        # DocType, size 4
    0x77, 0x65, 0x62, 0x6d,  # "webm"
    0x42, 0x87, 0x81, 0x04,  # DocTypeVersion = 4
    0x42, 0x85, 0x81, 0x02,  # DocTypeReadVersion = 2
    # Segment element (unknown size)
    0x18, 0x53, 0x80, 0x67,  # Segment ID
    0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,  # size = unknown
])


def _fix_webm_audio(audio: bytes) -> bytes:
    """Prideda EBML header jei audio prasideda Cluster chunks be header.

    Tauri MediaRecorder chunks prasideda 1f 43 b6 75 (Cluster ID) be EBML header.
    OpenAI Whisper atmeta tokį failą. Šis metodas prideda minimalų header.
    """
    # Jei jau yra EBML header – nieko nekeičiame
    if audio[:4] == b"\x1a\x45\xdf\xa3":
        return audio
    # Jei prasideda Cluster ID (1f 43 b6 75) – pridedame header
    if audio[:3] == b"\x1f\x43\xb6":
        return _WEBM_EBML_HEADER + audio
    return audio
from urllib.error import HTTPError as _UrllibHTTPError

from app.schemas.voice import SynthesizeResponse, TranscribeResponse

# ---------------------------------------------------------------------------
# Abstract provider interface
# ---------------------------------------------------------------------------

class VoiceProvider(abc.ABC):
    """Base class every voice provider must implement."""

    name: str = "unknown"

    @abc.abstractmethod
    async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
        """Convert raw audio bytes → text transcript."""
        ...

    @abc.abstractmethod
    async def synthesize(
        self, text: str, voice: str, language: str
    ) -> SynthesizeResponse:
        """Convert text → audio bytes (base-64 encoded)."""
        ...


# ---------------------------------------------------------------------------
# Built-in placeholder provider (no external deps, always available)
# ---------------------------------------------------------------------------

_SETUP_MSG = (
    "No voice provider is configured. "
    "To enable real STT/TTS: set VOICE_PROVIDER=openai (or another provider) "
    "and the corresponding API key in your .env file, then restart the server. "
    "See docs/voice-integration.md for details."
)


class PlaceholderProvider(VoiceProvider):
    """
    Returns descriptive stub responses so the UI can exercise the full
    request/response flow without a real provider.
    """

    name = "placeholder"

    async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
        return TranscribeResponse(
            transcript="",
            confidence=None,
            provider=self.name,
            status="provider_not_configured",
            message=_SETUP_MSG,
            provider_status="not_configured",
        )

    async def synthesize(
        self, text: str, voice: str, language: str
    ) -> SynthesizeResponse:
        return SynthesizeResponse(
            audio_base64=None,
            provider=self.name,
            status="provider_not_configured",
            message=_SETUP_MSG,
            provider_status="not_configured",
        )


# ---------------------------------------------------------------------------
# OpenAI provider (Whisper STT + TTS-1)
# ---------------------------------------------------------------------------

class OpenAIVoiceProvider(VoiceProvider):
    """Real OpenAI Whisper (STT) + TTS-1 (synthesis) provider."""

    name = "openai"

    async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
        import io
        import openai
        from app.core.config import settings as cfg
        client = openai.AsyncOpenAI(api_key=cfg.OPENAI_API_KEY)
        # Normalise language tag: "lt-LT" → "lt"
        lang = language.split("-")[0].lower() if language else "lt"

        # Whisper prompt dramatically improves accuracy for Lithuanian and
        # command-style speech. It primes the model on expected vocabulary.
        whisper_prompts = {
            "lt": (
                "Lani, atidaryk, sukurk, perkelk, ištrink, rūšiuok, ieškok, "
                "parodyk, paleisk, sustabdyk, terminalas, dokumentai, atsisiuntimai, "
                "failas, aplankas, programa, internetas, nustatymai, spotify, safari, "
                "chrome, slack, vscode, finder, užrašai, kalendorius"
            ),
            "en": (
                "Lani, open, create, move, delete, sort, search, show, run, stop, "
                "terminal, documents, downloads, file, folder, app, browser, settings, "
                "spotify, safari, chrome, slack, vscode, finder, notes, calendar"
            ),
        }
        prompt = whisper_prompts.get(lang, whisper_prompts["en"])

        # Detect actual audio format from magic bytes and use matching filename+mime.
        # MediaRecorder may produce WebM, OGG, or MP4 regardless of reported MIME.
        # Also fix WebM chunks missing EBML header (Tauri WKWebView MediaRecorder).
        fixed_audio = _fix_webm_audio(audio)
        filename, mime = _detect_audio_format(fixed_audio)

        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, io.BytesIO(fixed_audio), mime),
            language=lang,
            prompt=prompt,
        )
        return TranscribeResponse(
            transcript=result.text,
            confidence=None,
            provider=self.name,
            status="success",
            message=None,
            provider_status="ok",
        )

    async def synthesize(self, text: str, voice: str, language: str) -> SynthesizeResponse:
        import base64
        import openai
        from app.core.config import settings as cfg
        client = openai.AsyncOpenAI(api_key=cfg.OPENAI_API_KEY)
        lang = language.split("-")[0].lower() if language else "en"
        # Supported voices: alloy, echo, fable, onyx, nova, shimmer
        if voice and voice not in ("default", ""):
            tts_voice = voice
        else:
            # OpenAI voices are still English-biased. For Lithuanian, shimmer tends
            # to sound a bit softer/clearer than nova, while ElevenLabs remains the
            # preferred path when configured.
            tts_voice = "shimmer" if lang == "lt" else "nova"

        # Try ElevenLabs first if configured (better quality, natural voice cloning)
        elevenlabs_key = getattr(cfg, "ELEVENLABS_API_KEY", "") or ""
        if elevenlabs_key:
            try:
                return await _synthesize_elevenlabs(
                    text=text, voice=voice, cfg=cfg, api_key=elevenlabs_key
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "[voice] ElevenLabs TTS failed, falling back to OpenAI: %s", exc
                )

        # tts-1 = greičiausias modelis, ~2x greitesnis nei tts-1-hd
        response = await client.audio.speech.create(
            model="tts-1",
            voice=tts_voice,
            input=text,
        )
        audio_bytes = response.read()
        return SynthesizeResponse(
            audio_base64=base64.b64encode(audio_bytes).decode(),
            mime_type="audio/mpeg",
            provider=self.name,
            status="success",
            message=None,
            provider_status="ok",
        )


# ---------------------------------------------------------------------------
# ElevenLabs TTS helper (premium natural voice)
# ---------------------------------------------------------------------------

async def _synthesize_elevenlabs(
    text: str,
    voice: str,
    cfg: object,
    api_key: str,
) -> SynthesizeResponse:
    """
    Call ElevenLabs TTS API for high-quality, natural-sounding speech.
    Supports voice cloning via ELEVENLABS_VOICE_ID in .env.
    Falls back to a default voice if no voice ID is configured.
    """
    import asyncio
    import base64
    import json

    voice_id = getattr(cfg, "ELEVENLABS_VOICE_ID", "") or "21m00Tcm4TlvDq8ikWAM"  # Rachel (default)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",   # Best model – supports Lithuanian
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
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
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except _UrllibHTTPError as e:
            raise RuntimeError(f"ElevenLabs {e.code}: {e.read().decode()}") from e

    audio_bytes = await loop.run_in_executor(None, _do)

    return SynthesizeResponse(
        audio_base64=base64.b64encode(audio_bytes).decode(),
        mime_type="audio/mpeg",
        provider="elevenlabs",
        status="success",
        message=None,
        provider_status="ok",
    )


# ---------------------------------------------------------------------------
# Provider registry & selector
# ---------------------------------------------------------------------------

# Future providers can be registered here:
_PROVIDERS: dict[str, VoiceProvider] = {
    "placeholder": PlaceholderProvider(),
    "openai": OpenAIVoiceProvider(),
}


def _get_provider() -> VoiceProvider:
    """
    Return the active voice provider.

    Selection priority:
      1. Explicit VOICE_PROVIDER env var (if set to a known provider name).
      2. Auto-detect: if OPENAI_API_KEY is set and VOICE_PROVIDER is absent /
         'placeholder', silently upgrade to OpenAI Whisper + TTS-1.
      3. PlaceholderProvider as last resort.

    This means the user only needs to set OPENAI_API_KEY in .env to get
    real voice – no extra VOICE_PROVIDER variable required.
    """
    from app.core.config import settings  # local import to avoid circular deps

    requested: str = getattr(settings, "VOICE_PROVIDER", "placeholder").lower()

    # Auto-upgrade: if no explicit real provider is chosen but OpenAI key exists
    if requested in ("", "placeholder") and getattr(settings, "OPENAI_API_KEY", ""):
        return _PROVIDERS["openai"]

    return _PROVIDERS.get(requested, PlaceholderProvider())


# ---------------------------------------------------------------------------
# Public service functions (called from the API route)
# ---------------------------------------------------------------------------

async def transcribe_audio(audio: bytes, language: str = "en") -> TranscribeResponse:
    """
    Transcribe raw audio bytes to text.

    Parameters
    ----------
    audio:
        Raw audio data (WebM, WAV, MP3, …) captured from the browser microphone.
    language:
        BCP-47 language tag (default ``"en"``).
    """
    provider = _get_provider()
    return await provider.transcribe(audio, language)


async def synthesize_speech(
    text: str,
    voice: str = "default",
    language: str = "en",
) -> SynthesizeResponse:
    """
    Synthesize *text* into audio.

    Parameters
    ----------
    text:
        The text to speak (max ~5 000 characters for most providers).
    voice:
        Provider-specific voice identifier (e.g. ``"alloy"``, ``"nova"``).
        Defaults to ``"default"`` which the provider may interpret freely.
    language:
        BCP-47 language tag.
    """
    provider = _get_provider()
    return await provider.synthesize(text, voice, language)


async def list_providers() -> list[dict]:
    """Return metadata about all registered providers."""
    active_provider = _get_provider()
    return [
        {
            "name": name,
            "active": name == active_provider.name,
            "configured": name != "placeholder",
        }
        for name in _PROVIDERS
    ]
