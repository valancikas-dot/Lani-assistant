# Voice Integration Guide

This document explains the voice layer architecture and provides step-by-step
instructions for connecting a real STT/TTS provider.

---

## Architecture Overview

```
Browser
  │
  │  push-to-talk (MediaRecorder API)
  ▼
MicrophoneButton.tsx  ──▶  voiceStore.startListening()
                                │
                                │  stopListening() → audio Blob
                                ▼
                       POST /api/v1/voice/transcribe
                                │
                         voice_service.py
                         VoiceProvider.transcribe()
                                │
                         ┌──────┴──────────────┐
                         │  PlaceholderProvider │  ← default (no key needed)
                         │  OpenAIProvider      │  ← add VOICE_PROVIDER=openai
                         │  YourProvider        │  ← implement VoiceProvider ABC
                         └─────────────────────┘
                                │
                         TranscribeResponse
                                │
                    voiceStore  → transcript → ChatInput (auto-fill)
                                │
                       user reviews & sends command

Assistant reply
  │
  │  voice_enabled=true → AudioPlayer.tsx
  ▼
POST /api/v1/voice/synthesize
  │
VoiceProvider.synthesize()  →  audio_base64
  │
AudioPlayer → HTMLAudioElement.play()
```

---

## Current Status

| Feature | Status |
|---|---|
| STT endpoint (`/voice/transcribe`) | ✅ wired, placeholder response |
| TTS endpoint (`/voice/synthesize`) | ✅ wired, placeholder response |
| Provider info (`/voice/providers`) | ✅ live |
| Push-to-talk UI | ✅ `MicrophoneButton` component |
| TTS playback UI | ✅ `AudioPlayer` component |
| Settings UI | ✅ voice_enabled, language, voice selector |
| Real STT | 🔲 needs provider (see below) |
| Real TTS | 🔲 needs provider (see below) |

---

## Enabling a Real Provider

### Option A — OpenAI (Whisper STT + TTS)

**Prerequisites:** OpenAI API key with access to `whisper-1` and `tts-1`.

1. Add to `services/orchestrator/.env`:
   ```
   VOICE_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   ```

2. Install the SDK inside the venv:
   ```bash
   cd services/orchestrator
   source .venv/bin/activate
   pip install openai
   ```

3. Create `services/orchestrator/app/services/providers/openai_voice.py`:
   ```python
   import io, base64
   from app.schemas.voice import TranscribeResponse, SynthesizeResponse
   from app.services.voice_service import VoiceProvider
   from app.core.config import settings

   class OpenAIVoiceProvider(VoiceProvider):
       name = "openai"

       async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
           import openai
           client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
           result = await client.audio.transcriptions.create(
               model="whisper-1",
               file=("audio.webm", io.BytesIO(audio), "audio/webm"),
               language=language[:2],   # Whisper wants 2-char ISO code
           )
           return TranscribeResponse(
               transcript=result.text,
               provider=self.name,
               status="success",
           )

       async def synthesize(
           self, text: str, voice: str, language: str
       ) -> SynthesizeResponse:
           import openai
           client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
           resp = await client.audio.speech.create(
               model="tts-1", voice=voice or "alloy", input=text
           )
           audio_bytes = resp.read()
           return SynthesizeResponse(
               audio_base64=base64.b64encode(audio_bytes).decode(),
               mime_type="audio/mpeg",
               provider=self.name,
               status="success",
           )
   ```

4. Register it in `voice_service.py`:
   ```python
   # At the bottom of _PROVIDERS dict initialisation:
   from app.services.providers.openai_voice import OpenAIVoiceProvider
   _PROVIDERS["openai"] = OpenAIVoiceProvider()
   ```

5. Restart the server — the provider endpoint will show `configured: true`.

---

### Option B — Azure Cognitive Services

```
VOICE_PROVIDER=azure
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=eastus
```

Implement `AzureVoiceProvider` using the `azure-cognitiveservices-speech` SDK.
Refer to the same pattern as the OpenAI provider above.

---

### Option C — Local Whisper (offline, no API key)

```
VOICE_PROVIDER=whisper-local
WHISPER_MODEL=base.en   # tiny, base, small, medium, large
```

Install `openai-whisper` (requires ffmpeg):
```bash
pip install openai-whisper
```

In the provider's `transcribe` method:
```python
import whisper, io, tempfile, os
model = whisper.load_model(settings.WHISPER_MODEL)

async def transcribe(self, audio: bytes, language: str) -> TranscribeResponse:
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio)
        tmp = f.name
    try:
        result = model.transcribe(tmp, language=language[:2])
        return TranscribeResponse(
            transcript=result["text"].strip(),
            provider=self.name, status="success"
        )
    finally:
        os.unlink(tmp)
```

Note: Whisper runs synchronously — wrap in `asyncio.to_thread()` or a
`ProcessPoolExecutor` to avoid blocking the event loop.

---

## Frontend Notes

### Browser permissions

The first call to `startListening()` will trigger the browser's microphone
permission dialog.  In Tauri this maps to the OS-level mic permission.
Users must grant it for the push-to-talk to function.

Add to `src-tauri/tauri.conf.json` under `tauri.allowlist.shell` if needed:
```json
"microphone": true
```

### Audio format

`MediaRecorder` defaults to `audio/webm;codecs=opus` in Chrome/Chromium-based
Tauri. Whisper and most providers accept WebM, MP3, WAV, OGG, and M4A.

If a provider requires a specific format, install `ffmpeg` on the system and
transcode server-side before forwarding to the provider.

### Push-to-hold vs toggle

`MicrophoneButton` defaults to push-to-hold (mousedown/mouseup).
For a tap-to-toggle mode, call `startListening()` on first tap and
`stopListening()` on second tap — the store's `voiceState` tracks this.

---

## Settings Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `voice_enabled` | `bool` | `false` | Master switch for mic button + TTS playback in UI |
| `selected_language` | `string` | `"en"` | BCP-47 tag forwarded to STT and TTS |
| `selected_voice` | `string` | `"default"` | Provider-specific voice ID for TTS |

Update via PATCH `/api/v1/settings` or through the Settings page.

---

## API Reference

### `POST /api/v1/voice/transcribe`

**Content-Type:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `audio` | file | Raw audio (WebM, WAV, MP3…) |
| `language` | string (form) | BCP-47 tag, default `"en"` |

**Response:** `TranscribeResponse`
```json
{
  "transcript": "create folder /tmp/test",
  "confidence": 0.97,
  "provider": "openai",
  "status": "success",
  "message": null
}
```

### `POST /api/v1/voice/synthesize`

**Content-Type:** `application/json`

```json
{ "text": "Done! Folder created.", "voice": "nova", "language": "en" }
```

**Response:** `SynthesizeResponse`
```json
{
  "audio_base64": "//NAxAA...",
  "mime_type": "audio/mpeg",
  "provider": "openai",
  "status": "success"
}
```

### `GET /api/v1/voice/providers`

Returns array of registered provider metadata.

---

## Known Limitations (placeholder)

- STT returns `transcript: ""` with `status: provider_not_configured`.
- TTS returns `audio_base64: null` with same status.
- The UI shows the error toast in the chat input bar — dismiss with ×.
- No streaming/chunked STT yet; entire clip is uploaded at once.
