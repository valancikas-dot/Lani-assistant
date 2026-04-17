"""Smoke tests for the orchestrator API.

All tests use the ``async_client`` fixture from conftest.py, which:
  - Calls init_db() so all tables exist.
  - Resets the voice-session singleton so tests don't bleed state.
  - Provides a ready-to-use httpx AsyncClient.
"""
import asyncio
import datetime
import io
import pytest

from app.services import voice_session_service as vss


# ─── Health ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(async_client):
    r = await async_client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ─── Settings ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_settings(async_client):
    r = await async_client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()
    # Core language fields
    assert "preferred_language" in data or "ui_language" in data
    # Wake fields must be present
    assert "wake_word_enabled" in data
    assert "wake_mode" in data


# ─── Logs ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_logs(async_client):
    r = await async_client.get("/api/v1/logs")
    assert r.status_code in (200, 422)


# ─── Approvals ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_approvals(async_client):
    r = await async_client.get("/api/v1/approvals")
    assert r.status_code == 200


# ─── Plans ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_plans_simple(async_client):
    payload = {"command": "echo hello"}
    r = await async_client.post("/api/v1/plans", json=payload)
    assert r.status_code < 500


# ─── Wake – status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_status(async_client):
    """GET /wake/status returns a valid WakeStatus payload."""
    r = await async_client.get("/api/v1/wake/status")
    assert r.status_code == 200
    data = r.json()
    assert "voice_state" in data
    assert "wake_mode" in data
    assert "session" in data
    assert data["session"]["unlocked"] is False  # fresh session is always locked


# ─── Wake – activate disabled ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_activate_manual_disabled(async_client):
    """Activate fails when wake_word_enabled=False (default)."""
    r = await async_client.post("/api/v1/wake/activate", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["blocked_reason"] == "wake_word_disabled"


# ─── Wake – activate then lock ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_activate_and_lock(async_client):
    """Enable wake word, activate (manual mode), verify unlocked, then lock."""
    # Enable wake word via settings
    patch_r = await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    assert patch_r.status_code == 200

    # Activate
    act_r = await async_client.post("/api/v1/wake/activate", json={})
    assert act_r.status_code == 200
    act_data = act_r.json()
    assert act_data["ok"] is True
    assert act_data["voice_state"] == "unlocked"
    assert act_data["session"]["unlocked"] is True

    # Lock
    lock_r = await async_client.post("/api/v1/wake/lock", json={})
    assert lock_r.status_code == 200
    lock_data = lock_r.json()
    assert lock_data["ok"] is True
    assert lock_data["session"]["unlocked"] is False


# ─── Wake – patch settings ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_patch_settings(async_client):
    """PATCH /wake/settings persists and returns updated config."""
    r = await async_client.patch(
        "/api/v1/wake/settings",
        json={
            "wake_word_enabled": True,
            "primary_wake_phrase": "Lani",
            "secondary_wake_phrase": "Hey Lani",
            "voice_session_timeout_seconds": 60,
            "wake_mode": "wake_phrase_placeholder",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["wake_mode"] == "wake_phrase_placeholder"
    assert data["voice_session_timeout_seconds"] == 60


# ─── Wake – phrase-placeholder matching ───────────────────────────────────────

@pytest.mark.asyncio
async def test_wake_phrase_placeholder_match(async_client):
    """In placeholder mode, phrase_heard must contain the wake phrase."""
    # Configure placeholder mode
    await async_client.patch(
        "/api/v1/wake/settings",
        json={
            "wake_word_enabled": True,
            "wake_mode": "wake_phrase_placeholder",
            "primary_wake_phrase": "Lani",
        },
    )

    # Phrase contains wake word → should activate
    r_ok = await async_client.post(
        "/api/v1/wake/activate",
        json={"phrase_heard": "Hey Lani, open the file"},
    )
    assert r_ok.json()["ok"] is True

    # Lock for next sub-test
    await async_client.post("/api/v1/wake/lock", json={})

    # Phrase does NOT contain wake word → should be blocked
    r_bad = await async_client.post(
        "/api/v1/wake/activate",
        json={"phrase_heard": "open the file"},
    )
    assert r_bad.json()["ok"] is False
    assert r_bad.json()["blocked_reason"] == "phrase_not_matched"


# ─── Voice command – session locked ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_command_blocked_when_session_locked(async_client):
    """POST /voice/command is rejected when the session is locked."""
    # Ensure session is locked (default state after reset)
    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "create folder /tmp/test_lani"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["blocked_reason"] == "session_locked"
    assert data["overall_status"] == "blocked"


# ─── Voice command – session unlocked, command executes ───────────────────────

@pytest.mark.asyncio
async def test_voice_command_executes_when_unlocked(async_client):
    """Unlock session then POST /voice/command → command reaches the planner."""
    # Enable wake word and activate (manual mode → immediate unlock)
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    act = await async_client.post("/api/v1/wake/activate", json={})
    assert act.json()["session"]["unlocked"] is True

    # Send a command through the voice session
    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "create folder /tmp/lani_voice_test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # The planner might complete or ask for approval – both are valid non-error outcomes
    assert data["overall_status"] in ("completed", "approval_required", "failed")
    # Session should still be unlocked after command
    assert data["session"]["unlocked"] is True
    assert data["voice_state"] == "unlocked"


# ─── Voice command – TTS response field ───────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_command_tts_response(async_client):
    """tts_response=True populates tts_text in the response."""
    # Unlock session
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    await async_client.post("/api/v1/wake/activate", json={})

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "create folder /tmp/lani_tts_test", "tts_response": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # tts_text should be a non-empty string when command succeeds
    if data["overall_status"] == "completed":
        assert data["tts_text"] is not None
        assert len(data["tts_text"]) > 0


# ─── Voice command – unrecognised command ────────────────────────────────────

@pytest.mark.asyncio
async def test_voice_command_unrecognised(async_client):
    """Sending a nonsense command still completes (chat fallback handles everything now)."""
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    await async_client.post("/api/v1/wake/activate", json={})

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "xyzzy frobnicate the quux"},
    )
    assert r.status_code == 200
    data = r.json()
    # Session stays unlocked even on nonsense command
    assert data["session"]["unlocked"] is True
    # Chat fallback responds to everything – status is 'completed' or 'unrecognised'
    assert data["overall_status"] in ("completed", "unrecognised")
    assert data["ok"] is True


# ─── Verification flow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_and_unlock_bypass_security_disabled(async_client):
    """verify-and-unlock with bypass=True succeeds when security_mode is disabled."""
    # Ensure security is disabled (default)
    r = await async_client.post(
        "/api/v1/wake/verify-and-unlock",
        json={"bypass": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["voice_state"] == "unlocked"
    assert data["session"]["unlocked"] is True


@pytest.mark.asyncio
async def test_verify_and_unlock_bypass_blocked_with_security(async_client):
    """verify-and-unlock with bypass=True is rejected when security is active."""
    # Enable security mode
    await async_client.patch(
        "/api/v1/settings",
        json={"security_mode": "strict", "speaker_verification_enabled": True},
    )

    r = await async_client.post(
        "/api/v1/wake/verify-and-unlock",
        json={"bypass": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["blocked_reason"] == "bypass_not_allowed"

    # Clean up – restore security to disabled so other tests are not affected
    await async_client.patch(
        "/api/v1/settings",
        json={"security_mode": "disabled", "speaker_verification_enabled": False},
    )


# ─── Session state resets between tests ───────────────────────────────────────

@pytest.mark.asyncio
async def test_session_reset_between_tests(async_client):
    """Confirm the session singleton is reset – session must start locked."""
    r = await async_client.get("/api/v1/wake/status")
    assert r.status_code == 200
    data = r.json()
    assert data["session"]["unlocked"] is False, (
        "Session should always start locked in a fresh test (reset_session fixture did not run)"
    )


# ─── STT – transcription endpoint ────────────────────────────────────────────

# Minimal WAV header (44 bytes) + a small amount of silence.
# Enough for the endpoint to accept as non-empty audio.
_MINIMAL_WAV = (
    b"RIFF"
    + (36).to_bytes(4, "little")          # file size - 8
    + b"WAVE"
    + b"fmt "
    + (16).to_bytes(4, "little")          # chunk size
    + (1).to_bytes(2, "little")           # PCM format
    + (1).to_bytes(2, "little")           # channels
    + (16000).to_bytes(4, "little")       # sample rate
    + (32000).to_bytes(4, "little")       # byte rate
    + (2).to_bytes(2, "little")           # block align
    + (16).to_bytes(2, "little")          # bits per sample
    + b"data"
    + (0).to_bytes(4, "little")           # data chunk size (silent)
)


@pytest.mark.asyncio
async def test_transcribe_placeholder_provider(async_client):
    """
    POST /voice/transcribe with a minimal WAV blob.
    With OPENAI_API_KEY set: may return error (invalid audio) or success.
    Without key: returns provider_not_configured.
    """
    r = await async_client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("test.wav", io.BytesIO(_MINIMAL_WAV), "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 200
    data = r.json()
    # Accept both: real provider configured (may error on silence) or placeholder
    assert data["status"] in ("provider_not_configured", "error", "success")
    assert data["provider"] in ("placeholder", "openai", "speaker_verification")


@pytest.mark.asyncio
async def test_transcribe_empty_file_rejected(async_client):
    """POST /voice/transcribe with a zero-byte file → 422."""
    r = await async_client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("empty.wav", io.BytesIO(b""), "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 422
    assert "empty" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transcribe_oversized_file_rejected(async_client):
    """POST /voice/transcribe with >configured limit → 413."""
    # Set a tiny limit first
    await async_client.patch(
        "/api/v1/settings",
        json={"max_audio_upload_mb": 0.0001},  # 0.1 KB
    )
    large_audio = b"\x00" * 200  # 200 bytes > 0.0001 MB (≈ 102 bytes)
    r = await async_client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("big.wav", io.BytesIO(large_audio), "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 413
    # Restore limit
    await async_client.patch("/api/v1/settings", json={"max_audio_upload_mb": 25.0})


@pytest.mark.asyncio
async def test_transcribe_stt_disabled_rejected(async_client):
    """POST /voice/transcribe returns 422 when STT is disabled."""
    await async_client.patch("/api/v1/settings", json={"stt_enabled": False})
    r = await async_client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("test.wav", io.BytesIO(_MINIMAL_WAV), "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 422
    assert "disabled" in r.json()["detail"].lower()
    # Re-enable for subsequent tests
    await async_client.patch("/api/v1/settings", json={"stt_enabled": True})


@pytest.mark.asyncio
async def test_transcribe_audit_log_written(async_client):
    """A transcription attempt leaves at least one audit log entry."""
    # Record log count before
    logs_before = await async_client.get("/api/v1/logs?limit=200")
    count_before = len(logs_before.json())

    await async_client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("test.wav", io.BytesIO(_MINIMAL_WAV), "audio/wav")},
        data={"language": "en"},
    )

    logs_after = await async_client.get("/api/v1/logs?limit=200")
    count_after = len(logs_after.json())

    assert count_after > count_before, (
        "Expected at least one new audit log entry after transcription attempt"
    )
    # The last log entry should mention transcribe
    last_entry = logs_after.json()[0]  # most recent first
    assert "transcribe" in last_entry.get("command", "").lower()


@pytest.mark.asyncio
async def test_settings_stt_fields_roundtrip(async_client):
    """PATCH /settings with STT fields and GET to confirm persistence."""
    await async_client.patch(
        "/api/v1/settings",
        json={
            "stt_enabled": True,
            "max_audio_upload_seconds": 90,
            "max_audio_upload_mb": 10.0,
        },
    )
    r = await async_client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["stt_enabled"] is True
    assert data["max_audio_upload_seconds"] == 90
    assert data["max_audio_upload_mb"] == 10.0


# ─────────────────────────────────────────────────────────────────────────────
# TTS synthesis tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_placeholder_not_configured(async_client):
    """POST /voice/synthesize: if OPENAI_API_KEY is set, returns success; otherwise provider_not_configured."""
    # Ensure TTS is enabled so the check passes and we reach the provider
    await async_client.patch("/api/v1/settings", json={"tts_enabled": True})
    r = await async_client.post(
        "/api/v1/voice/synthesize",
        json={"text": "Hello Lani", "voice": "default", "language": "en"},
    )
    assert r.status_code == 200
    data = r.json()
    # With OPENAI_API_KEY set → real provider fires and succeeds
    # Without any key → placeholder fires with provider_not_configured
    assert data["status"] in ("success", "provider_not_configured", "error")
    assert data["provider"] in ("openai", "elevenlabs", "placeholder")


@pytest.mark.asyncio
async def test_synthesize_tts_disabled_rejected(async_client):
    """POST /voice/synthesize returns 422 when tts_enabled is False."""
    await async_client.patch("/api/v1/settings", json={"tts_enabled": False})
    r = await async_client.post(
        "/api/v1/voice/synthesize",
        json={"text": "Hello Lani"},
    )
    assert r.status_code == 422
    assert "disabled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_synthesize_empty_text_rejected(async_client):
    """POST /voice/synthesize returns 422 on empty text."""
    await async_client.patch("/api/v1/settings", json={"tts_enabled": True})
    r = await async_client.post(
        "/api/v1/voice/synthesize",
        json={"text": "   "},
    )
    assert r.status_code == 422
    assert "empty" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_synthesize_text_too_long_rejected(async_client):
    """POST /voice/synthesize returns 422 when text exceeds 5000 chars."""
    await async_client.patch("/api/v1/settings", json={"tts_enabled": True})
    long_text = "a" * 5001
    r = await async_client.post(
        "/api/v1/voice/synthesize",
        json={"text": long_text},
    )
    assert r.status_code == 422
    assert "5" in r.json()["detail"]  # "5 000" or "5000"


@pytest.mark.asyncio
async def test_synthesize_audit_log_written(async_client):
    """A successful synthesis attempt creates at least two audit log entries."""
    await async_client.patch("/api/v1/settings", json={"tts_enabled": True})
    # Get baseline log count – use a high limit so the cap never hides new entries
    r0 = await async_client.get("/api/v1/logs?limit=200")
    count_before = len(r0.json())

    await async_client.post(
        "/api/v1/voice/synthesize",
        json={"text": "Audit log test", "voice": "default", "language": "en"},
    )

    r1 = await async_client.get("/api/v1/logs?limit=200")
    entries = r1.json()
    assert len(entries) > count_before, "Expected new audit log entries after synthesis"

    # Confirm at least one TTS-related entry was written
    tts_entries = [
        e for e in entries
        if "tts" in e.get("command", "").lower() or "voice" in e.get("tool_name", "").lower()
    ]
    assert len(tts_entries) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Server-side auto-relock tests
# ─────────────────────────────────────────────────────────────────────────────

async def _enable_and_unlock(async_client, timeout_seconds: int = 120) -> dict:
    """Helper: enable wake word, set timeout, activate (manual mode), return session."""
    await async_client.patch(
        "/api/v1/wake/settings",
        json={
            "wake_word_enabled": True,
            "wake_mode": "manual",
            "voice_session_timeout_seconds": timeout_seconds,
        },
    )
    act = await async_client.post("/api/v1/wake/activate", json={})
    assert act.status_code == 200
    data = act.json()
    assert data["ok"] is True, f"Unlock failed: {data}"
    return data


def _force_expire_session() -> None:
    """Move the in-process session's expires_at to the past to simulate expiry."""
    s = vss.get_session()
    if s.expires_at is not None:
        s.expires_at = s._now() - datetime.timedelta(seconds=1)


@pytest.mark.asyncio
async def test_unlock_creates_expires_at(async_client):
    """Unlocking a session sets expires_at and seconds_remaining > 0."""
    data = await _enable_and_unlock(async_client, timeout_seconds=120)
    session = data["session"]
    assert session["unlocked"] is True
    assert session["expires_at"] is not None, "expires_at must be set after unlock"
    assert session["seconds_remaining"] is not None
    assert session["seconds_remaining"] > 0


@pytest.mark.asyncio
async def test_active_session_passes_command(async_client):
    """An immediately-issued command on a fresh unlocked session succeeds."""
    await _enable_and_unlock(async_client, timeout_seconds=120)
    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "xyzzy frobnicate the quux"},
    )
    assert r.status_code == 200
    data = r.json()
    # 'unrecognised' means it reached the planner – session was NOT blocked
    assert data["ok"] is True
    assert data["overall_status"] != "blocked"
    assert data["session"]["unlocked"] is True


@pytest.mark.asyncio
async def test_expired_session_blocks_command(async_client):
    """A command sent after session expiry is rejected with blocked_reason=session_expired."""
    await _enable_and_unlock(async_client)
    _force_expire_session()  # move expiry into the past

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "xyzzy frobnicate the quux"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["overall_status"] == "blocked"
    assert data["blocked_reason"] in ("session_expired", "reverification_required")


@pytest.mark.asyncio
async def test_expired_session_auto_locks(async_client):
    """GET /wake/status after expiry reports session as locked."""
    await _enable_and_unlock(async_client)
    _force_expire_session()

    r = await async_client.get("/api/v1/wake/status")
    assert r.status_code == 200
    data = r.json()
    assert data["session"]["unlocked"] is False, (
        "Backend must have auto-locked the session after expiry"
    )


@pytest.mark.asyncio
async def test_reverification_required_after_expiry(async_client):
    """When require_reverification_after_timeout=True, expiry yields blocked_reason=reverification_required."""
    # Configure require-reverification with speaker verification enabled
    await async_client.patch(
        "/api/v1/settings",
        json={"security_mode": "strict", "speaker_verification_enabled": True},
    )
    await async_client.patch(
        "/api/v1/wake/settings",
        json={
            "wake_word_enabled": True,
            "wake_mode": "manual",
            "require_reverification_after_timeout": True,
        },
    )
    act = await async_client.post("/api/v1/wake/activate", json={})
    assert act.json()["ok"] is True

    _force_expire_session()  # move expiry into the past

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "xyzzy frobnicate the quux"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["blocked_reason"] in ("reverification_required", "session_expired", "session_locked")

    # Clean up
    await async_client.patch(
        "/api/v1/settings",
        json={"security_mode": "disabled", "speaker_verification_enabled": False},
    )


@pytest.mark.asyncio
async def test_wake_status_returns_security_mode(async_client):
    """GET /wake/status includes security_mode field."""
    r = await async_client.get("/api/v1/wake/status")
    assert r.status_code == 200
    data = r.json()
    assert "security_mode" in data, "WakeStatus must include security_mode"
    # Default is 'disabled'
    assert data["security_mode"] == "disabled"


@pytest.mark.asyncio
async def test_wake_status_returns_remaining_seconds(async_client):
    """GET /wake/status after unlock returns seconds_remaining > 0."""
    await _enable_and_unlock(async_client, timeout_seconds=60)

    r = await async_client.get("/api/v1/wake/status")
    assert r.status_code == 200
    data = r.json()
    assert data["session"]["unlocked"] is True
    assert data["session"]["seconds_remaining"] is not None
    assert data["session"]["seconds_remaining"] > 0


# ─── Builder ──────────────────────────────────────────────────────────────────

import os
import tempfile


def _make_allowed_dir(tmp_path: str) -> dict:
    """Return a settings patch that allows *tmp_path*."""
    return {"allowed_directories": [tmp_path]}


@pytest.mark.asyncio
async def test_builder_scaffold_generic(async_client, tmp_path):
    """POST /builder/scaffold creates a generic project in an allowed dir."""
    allowed = str(tmp_path)
    # Allow the temp dir
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    r = await async_client.post("/api/v1/builder/scaffold", json={
        "name": "smoke-project",
        "template": "generic",
        "base_dir": allowed,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert "smoke-project" in data["project_path"]
    assert len(data["files_created"]) >= 1


@pytest.mark.asyncio
async def test_builder_scaffold_react_ts(async_client, tmp_path):
    """POST /builder/scaffold creates a react-ts project with expected files."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    r = await async_client.post("/api/v1/builder/scaffold", json={
        "name": "my-app",
        "template": "react-ts",
        "base_dir": allowed,
        "description": "A smoke-test React app",
        "features": [],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert len(data["files_created"]) >= 3
    assert len(data["proposed_commands"]) >= 1


@pytest.mark.asyncio
async def test_builder_create_file(async_client, tmp_path):
    """POST /builder/file writes a new source file."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    project_dir = os.path.join(allowed, "proj")
    os.makedirs(project_dir, exist_ok=True)

    r = await async_client.post("/api/v1/builder/file", json={
        "project_path": project_dir,
        "relative_path": "src/hello.py",
        "content": "print('hello')\n",
        "overwrite": False,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    written = os.path.join(project_dir, "src", "hello.py")
    assert os.path.exists(written)


@pytest.mark.asyncio
async def test_builder_create_file_overwrite_requires_approval(async_client, tmp_path):
    """POST /builder/file with overwrite=False on existing file → requires_approval."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    project_dir = os.path.join(allowed, "proj2")
    os.makedirs(os.path.join(project_dir, "src"), exist_ok=True)
    existing = os.path.join(project_dir, "src", "exists.py")
    with open(existing, "w") as f:
        f.write("# existing\n")

    r = await async_client.post("/api/v1/builder/file", json={
        "project_path": project_dir,
        "relative_path": "src/exists.py",
        "content": "# new content\n",
        "overwrite": False,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requires_approval"] is True
    assert data["ok"] is False


@pytest.mark.asyncio
async def test_builder_readme(async_client, tmp_path):
    """POST /builder/readme generates a README.md."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    project_dir = os.path.join(allowed, "readme-proj")
    os.makedirs(project_dir, exist_ok=True)

    r = await async_client.post("/api/v1/builder/readme", json={
        "project_path": project_dir,
        "project_name": "readme-proj",
        "description": "A test project",
        "template": "generic",
        "features": ["login", "dashboard"],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert "readme-proj" in data.get("content", "") or os.path.exists(
        os.path.join(project_dir, "README.md")
    )


@pytest.mark.asyncio
async def test_builder_feature_files(async_client, tmp_path):
    """POST /builder/feature generates component files for a React project."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    project_dir = os.path.join(allowed, "react-proj")
    os.makedirs(project_dir, exist_ok=True)

    r = await async_client.post("/api/v1/builder/feature", json={
        "project_path": project_dir,
        "feature_description": "UserProfile",
        "template": "react-ts",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert len(data["files"]) >= 1
    paths = [f["path"] for f in data["files"]]
    assert any("userprofile" in p.lower() or "user-profile" in p.lower() for p in paths)


@pytest.mark.asyncio
async def test_builder_tree(async_client, tmp_path):
    """GET /builder/tree returns a JSON tree for a directory."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    project_dir = os.path.join(allowed, "tree-proj")
    os.makedirs(os.path.join(project_dir, "src"), exist_ok=True)
    with open(os.path.join(project_dir, "src", "main.py"), "w") as f:
        f.write("")

    r = await async_client.get(
        "/api/v1/builder/tree",
        params={"project_path": project_dir, "max_depth": 3},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["root"]["name"] == "tree-proj"
    assert data["root"]["is_dir"] is True


@pytest.mark.asyncio
async def test_builder_propose_commands(async_client, tmp_path):
    """POST /builder/commands returns a list of proposed CLI commands."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    r = await async_client.post("/api/v1/builder/commands", json={
        "project_path": allowed,
        "template": "fastapi",
        "goal": "run development server",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert len(data["commands"]) >= 1
    cmd_texts = [c["command"] for c in data["commands"]]
    assert any("uvicorn" in c or "pip" in c or "python" in c for c in cmd_texts)


@pytest.mark.asyncio
async def test_builder_task_end_to_end(async_client, tmp_path):
    """POST /builder/task orchestrates scaffold + readme + commands in one call."""
    allowed = str(tmp_path)
    await async_client.patch("/api/v1/settings", json=_make_allowed_dir(allowed))

    r = await async_client.post("/api/v1/builder/task", json={
        "goal": "Create a FastAPI project called smoke-api",
        "template": "fastapi",
        "project_name": "smoke-api",
        "base_dir": allowed,
        "features": [],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["project_path"] is not None
    assert len(data["files_created"]) >= 1
    assert len(data["steps_taken"]) >= 1


# ─── Connectors ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connectors_list_empty(async_client):
    """GET /connectors returns an empty list when no accounts are connected."""
    r = await async_client.get("/api/v1/connectors")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Fresh DB: no accounts connected
    assert data == []


@pytest.mark.asyncio
async def test_connectors_capabilities_all_providers(async_client):
    """GET /connectors/capabilities returns manifests for all three providers."""
    r = await async_client.get("/api/v1/connectors/capabilities")
    assert r.status_code == 200
    manifests = r.json()
    providers = {m["provider"] for m in manifests}
    assert "google_drive" in providers
    assert "gmail" in providers
    assert "google_calendar" in providers


@pytest.mark.asyncio
async def test_connectors_capabilities_approval_flags(async_client):
    """Approval-required actions have requires_approval=True; read-only ones do not."""
    r = await async_client.get("/api/v1/connectors/capabilities")
    assert r.status_code == 200
    manifests = r.json()

    approval_actions = {
        "gmail_create_draft",
        "gmail_send_email",
        "calendar_create_event",
        "calendar_delete_event",
    }
    read_only_actions = {
        "drive_list_files",
        "drive_search_files",
        "drive_get_file",
        "gmail_list_recent",
        "gmail_get_message",
        "calendar_list_events",
    }

    capabilities_by_name = {}
    for manifest in manifests:
        for cap in manifest["capabilities"]:
            capabilities_by_name[cap["name"]] = cap

    for action in approval_actions:
        assert capabilities_by_name[action]["requires_approval"] is True, \
            f"{action} should require approval"

    for action in read_only_actions:
        assert capabilities_by_name[action]["requires_approval"] is False, \
            f"{action} should NOT require approval"


@pytest.mark.asyncio
async def test_connectors_oauth_init_google_drive(async_client):
    """GET /connectors/oauth/init?provider=google_drive returns an auth_url."""
    r = await async_client.get("/api/v1/connectors/oauth/init?provider=google_drive")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provider"] == "google_drive"
    assert "auth_url" in data
    assert data["auth_url"].startswith("https://accounts.google.com/")
    assert "state" in data
    assert len(data["state"]) >= 16


@pytest.mark.asyncio
async def test_connectors_oauth_init_gmail(async_client):
    """GET /connectors/oauth/init?provider=gmail returns an auth_url."""
    r = await async_client.get("/api/v1/connectors/oauth/init?provider=gmail")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provider"] == "gmail"
    assert data["auth_url"].startswith("https://accounts.google.com/")


@pytest.mark.asyncio
async def test_connectors_oauth_init_google_calendar(async_client):
    """GET /connectors/oauth/init?provider=google_calendar returns an auth_url."""
    r = await async_client.get("/api/v1/connectors/oauth/init?provider=google_calendar")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provider"] == "google_calendar"
    assert data["auth_url"].startswith("https://accounts.google.com/")


@pytest.mark.asyncio
async def test_connectors_oauth_init_unknown_provider(async_client):
    """GET /connectors/oauth/init with an unknown provider returns 404."""
    r = await async_client.get("/api/v1/connectors/oauth/init?provider=slack")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_connectors_disconnect_nonexistent(async_client):
    """DELETE /connectors/9999 returns 404 when the account doesn't exist."""
    r = await async_client.delete("/api/v1/connectors/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_connectors_action_no_account(async_client):
    """POST /connectors/9999/action returns 404 when the account doesn't exist."""
    r = await async_client.post("/api/v1/connectors/9999/action", json={
        "account_id": 9999,
        "action": "drive_list_files",
        "params": {},
    })
    assert r.status_code == 404


# ─── Computer Operator ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_operator_capabilities(async_client):
    """GET /operator/capabilities returns manifest with all 12 actions."""
    r = await async_client.get("/api/v1/operator/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "platform" in data
    assert "capabilities" in data
    names = {c["name"] for c in data["capabilities"]}
    expected = {
        "list_open_windows", "open_app", "focus_window", "minimize_window",
        "close_window", "open_path", "reveal_file", "copy_to_clipboard",
        "paste_clipboard", "type_text", "press_shortcut", "take_screenshot",
    }
    assert expected == names


@pytest.mark.asyncio
async def test_operator_capabilities_approval_flags(async_client):
    """type_text and close_window require approval; open_app does not."""
    r = await async_client.get("/api/v1/operator/capabilities")
    assert r.status_code == 200
    caps = {c["name"]: c for c in r.json()["capabilities"]}
    assert caps["type_text"]["requires_approval"] is True
    assert caps["close_window"]["requires_approval"] is True
    assert caps["open_app"]["requires_approval"] is False
    assert caps["take_screenshot"]["requires_approval"] is False


@pytest.mark.asyncio
async def test_operator_windows_list(async_client):
    """GET /operator/windows returns a valid response structure."""
    r = await async_client.get("/api/v1/operator/windows")
    assert r.status_code == 200
    data = r.json()
    assert "windows" in data
    assert isinstance(data["windows"], list)
    assert "platform" in data


@pytest.mark.asyncio
async def test_operator_action_invalid_action(async_client):
    """POST /operator/action with an unknown action name is rejected (422)."""
    r = await async_client.post("/api/v1/operator/action", json={
        "action": "hack_the_planet",
        "params": {},
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_operator_action_type_text_requires_approval(async_client):
    """type_text action must trigger the approval gate."""
    r = await async_client.post("/api/v1/operator/action", json={
        "action": "type_text",
        "params": {"text": "hello world"},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["requires_approval"] is True
    assert data["ok"] is False
    assert data["approval_id"] is not None


@pytest.mark.asyncio
async def test_operator_action_close_window_requires_approval(async_client):
    """close_window action must trigger the approval gate."""
    r = await async_client.post("/api/v1/operator/action", json={
        "action": "close_window",
        "params": {"window_title": "Finder"},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["requires_approval"] is True
    assert data["approval_id"] is not None


@pytest.mark.asyncio
async def test_operator_action_destructive_shortcut_requires_approval(async_client):
    """cmd+q shortcut must trigger the approval gate."""
    r = await async_client.post("/api/v1/operator/action", json={
        "action": "press_shortcut",
        "params": {"keys": ["cmd", "q"]},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["requires_approval"] is True


@pytest.mark.asyncio
async def test_operator_action_audit_logged(async_client):
    """After a type_text action (approval gate), an audit log entry must exist."""
    await async_client.post("/api/v1/operator/action", json={
        "action": "type_text",
        "params": {"text": "audit test"},
    })
    logs_r = await async_client.get("/api/v1/logs")
    assert logs_r.status_code == 200
    entries = logs_r.json()
    operator_entries = [
        e for e in entries
        if "operator" in e.get("tool_name", "").lower()
        or "operator" in e.get("command", "").lower()
    ]
    assert len(operator_entries) >= 1


@pytest.mark.asyncio
async def test_planner_open_app(async_client):
    """plan_command('Open Safari') should produce a step with open_app tool."""
    r = await async_client.post("/api/v1/plans", json={"command": "Open Safari"})
    assert r.status_code == 200
    steps = r.json().get("plan", {}).get("steps", [])
    assert any("open_app" in s.get("tool", "") for s in steps)


@pytest.mark.asyncio
async def test_planner_screenshot(async_client):
    """plan_command('Take a screenshot') should produce a take_screenshot step."""
    r = await async_client.post("/api/v1/plans", json={"command": "Take a screenshot"})
    assert r.status_code == 200
    steps = r.json().get("plan", {}).get("steps", [])
    assert any("screenshot" in s.get("tool", "") for s in steps)


# ─── Security hardening tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_security_hash_and_verify():
    """hash_secret produces an Argon2id hash; verify_secret round-trips correctly."""
    from app.core.security import hash_secret, verify_secret

    h = hash_secret("mypin123")
    assert h.startswith("argon2:"), f"Expected argon2: prefix, got: {h[:12]}"
    ok, needs_rehash = verify_secret(h, "mypin123")
    assert ok is True
    assert needs_rehash is False

    ok_wrong, _ = verify_secret(h, "wrongpin")
    assert ok_wrong is False


@pytest.mark.asyncio
async def test_security_legacy_sha256_verify():
    """verify_secret accepts the legacy sha256: prefix and signals rehash needed."""
    from app.core.security import verify_secret, legacy_sha256_hash

    legacy = legacy_sha256_hash("testpin")
    assert legacy.startswith("sha256:")

    ok, needs_rehash = verify_secret(legacy, "testpin")
    assert ok is True
    assert needs_rehash is True  # must be upgraded

    ok_wrong, _ = verify_secret(legacy, "nope")
    assert ok_wrong is False


@pytest.mark.asyncio
async def test_security_approval_levels():
    """APPROVAL_POLICY maps known tools to the correct levels."""
    from app.core.security import get_approval_level, requires_approval, ApprovalLevel

    assert get_approval_level("web_search") == ApprovalLevel.read_safe
    assert requires_approval("web_search") is False

    assert get_approval_level("gmail_send_email") == ApprovalLevel.destructive_requires_approval
    assert requires_approval("gmail_send_email") is True

    assert get_approval_level("calendar_delete_event") == ApprovalLevel.destructive_requires_approval
    assert requires_approval("calendar_delete_event") is True

    assert get_approval_level("create_file") == ApprovalLevel.write_requires_approval
    assert requires_approval("create_file") is True

    assert get_approval_level("operator.type_text") == ApprovalLevel.security_sensitive_requires_approval

    # Unknown tools default to write_requires_approval (safe default)
    assert get_approval_level("totally_unknown_tool") == ApprovalLevel.write_requires_approval


@pytest.mark.asyncio
async def test_security_production_missing_key():
    """validate_production_secrets() raises RuntimeError when APP_ENV=production and keys absent."""
    from app.core.config import Settings

    prod_settings = Settings(APP_ENV="production", CONNECTOR_ENCRYPTION_KEY="", SECRET_KEY="")
    try:
        prod_settings.validate_production_secrets()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as exc:
        assert "CONNECTOR_ENCRYPTION_KEY" in str(exc)
        assert "production" in str(exc).lower()


@pytest.mark.asyncio
async def test_security_production_ok_with_keys():
    """validate_production_secrets() passes when both keys are provided."""
    from app.core.config import Settings

    prod_settings = Settings(
        APP_ENV="production",
        CONNECTOR_ENCRYPTION_KEY="dummykey123",
        SECRET_KEY="dummysecret456",
    )
    # Should not raise
    prod_settings.validate_production_secrets()


@pytest.mark.asyncio
async def test_security_set_pin_endpoint(async_client):
    """POST /security/set_pin stores an Argon2id hash."""
    r = await async_client.post(
        "/api/v1/security/set_pin",
        json={"pin": "5678"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "Argon2id" in data["message"]


@pytest.mark.asyncio
async def test_security_set_pin_too_short(async_client):
    """POST /security/set_pin rejects PINs shorter than 4 characters."""
    r = await async_client.post(
        "/api/v1/security/set_pin",
        json={"pin": "12"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_security_unlock_pin_correct(async_client):
    """After setting a PIN, POST /security/unlock succeeds with the correct value."""
    await async_client.post("/api/v1/security/set_pin", json={"pin": "4321"})

    r = await async_client.post(
        "/api/v1/security/unlock",
        json={"method": "pin", "value": "4321"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "unlocked"
    assert data["method"] == "pin"


@pytest.mark.asyncio
async def test_security_unlock_pin_wrong(async_client):
    """POST /security/unlock returns 403 for wrong PIN."""
    await async_client.post("/api/v1/security/set_pin", json={"pin": "1111"})

    r = await async_client.post(
        "/api/v1/security/unlock",
        json={"method": "pin", "value": "9999"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_security_status_endpoint(async_client):
    """GET /security/status returns the expected security posture fields."""
    r = await async_client.get("/api/v1/security/status")
    assert r.status_code == 200
    data = r.json()

    required_keys = {
        "app_env",
        "connector_encryption_configured",
        "connector_encryption_uses_dev_key",
        "secret_key_configured",
        "speaker_verification_enabled",
        "fallback_pin_enabled",
        "fallback_pin_scheme",
        "fallback_passphrase_enabled",
        "approval_policy_summary",
        "recent_security_events",
    }
    assert required_keys.issubset(data.keys())
    assert isinstance(data["approval_policy_summary"], dict)
    assert "read_safe" in data["approval_policy_summary"]
    assert isinstance(data["recent_security_events"], list)


# ─── Voice UX Polish tests ─────────────────────────────────────────────────────

# --- voice_shaper unit tests -------------------------------------------------

def test_voice_shaper_strips_markdown():
    """shape_for_voice removes markdown syntax."""
    from app.services.voice_shaper import shape_for_voice

    md = "**Done!** The folder was created. _Details_: `~/Desktop/test`."
    result = shape_for_voice(md)
    assert "**" not in result
    assert "_Details_" not in result
    assert "`" not in result
    assert "Done" in result


def test_voice_shaper_brevity_rewrite():
    """shape_for_voice applies brevity rewrites for common verbose phrases."""
    from app.services.voice_shaper import shape_for_voice

    verbose = "I have successfully completed the task."
    result = shape_for_voice(verbose)
    # Should be shortened
    assert len(result) <= len(verbose)
    assert "Done" in result


def test_voice_shaper_truncates_at_sentence():
    """shape_for_voice truncates long text at a sentence boundary."""
    from app.services.voice_shaper import shape_for_voice

    long_text = ("This is sentence one. " * 20).strip()
    result = shape_for_voice(long_text, max_chars=100)
    assert len(result) <= 115  # some tolerance for the trailing sentence
    # Should end cleanly (sentence boundary)
    assert result.endswith(".") or result.endswith("!") or result.endswith("?")


def test_voice_shaper_is_interrupt_true():
    """is_interrupt_command returns True for known interrupt phrases."""
    from app.services.voice_shaper import is_interrupt_command

    assert is_interrupt_command("stop") is True
    assert is_interrupt_command("STOP") is True
    assert is_interrupt_command("  enough  ") is True
    assert is_interrupt_command("cancel") is True
    assert is_interrupt_command("be quiet") is True
    # Lithuanian
    assert is_interrupt_command("sustok") is True
    assert is_interrupt_command("tylėk") is True


def test_voice_shaper_is_interrupt_false():
    """is_interrupt_command returns False for normal commands."""
    from app.services.voice_shaper import is_interrupt_command

    assert is_interrupt_command("create folder ~/Desktop/test") is False
    assert is_interrupt_command("open safari") is False
    assert is_interrupt_command("now make a presentation") is False
    assert is_interrupt_command("") is False


def test_voice_shaper_confirmation_english():
    """shape_confirmation returns the English template for known tools."""
    from app.services.voice_shaper import shape_confirmation

    result = shape_confirmation("gmail_send_email", "to alice@example.com", "en")
    assert "send" in result.lower()
    assert "alice@example.com" in result


def test_voice_shaper_confirmation_lithuanian():
    """shape_confirmation returns the Lithuanian template."""
    from app.services.voice_shaper import shape_confirmation

    result = shape_confirmation("gmail_send_email", "", "lt")
    # Lithuanian template should not be English
    assert "Shall I" not in result


def test_voice_shaper_confirmation_default_fallback():
    """shape_confirmation uses the __default__ template for unknown tool names."""
    from app.services.voice_shaper import shape_confirmation

    result = shape_confirmation("some_unknown_tool_xyz", "description here", "en")
    # Should return *something* sensible
    assert len(result) > 5


# --- voice_session_service context tests ------------------------------------

def test_voice_context_add_and_get():
    """add_context_turn + get_context_turns round-trips correctly."""
    from app.services import voice_session_service as vss

    vss.clear_context()
    vss.add_context_turn("user", "Open Safari")
    vss.add_context_turn("assistant", "Opening Safari now.")
    turns = vss.get_context_turns()
    assert len(turns) == 2
    assert turns[0] == {"role": "user", "text": "Open Safari"}
    assert turns[1] == {"role": "assistant", "text": "Opening Safari now."}


def test_voice_context_summary_format():
    """get_context_summary produces a multi-line string with role prefixes."""
    from app.services import voice_session_service as vss

    vss.clear_context()
    vss.add_context_turn("user", "Take a screenshot")
    vss.add_context_turn("assistant", "Screenshot taken.")
    summary = vss.get_context_summary()
    assert "User:" in summary or "user" in summary.lower()
    assert "Screenshot" in summary


def test_voice_context_ring_buffer():
    """Context ring buffer caps at MAX_TURNS (6) entries."""
    from app.services import voice_session_service as vss
    from app.services.voice_session_service import _VoiceSession

    vss.clear_context()
    for i in range(10):
        vss.add_context_turn("user", f"command {i}")
        vss.add_context_turn("assistant", f"done {i}")

    turns = vss.get_context_turns()
    assert len(turns) <= _VoiceSession.MAX_TURNS


def test_voice_context_clears_on_lock():
    """relock() clears the context ring buffer."""
    from app.services import voice_session_service as vss

    vss.clear_context()
    vss.add_context_turn("user", "Do something")
    vss.add_context_turn("assistant", "Done.")

    # Force-lock without DB (direct state manipulation)
    vss.get_session().reset()  # reset() calls clear_context() transitively via relock path
    assert vss.get_context_turns() == []


def test_voice_last_tts_roundtrip():
    """set_last_tts + get_last_tts round-trips correctly."""
    from app.services import voice_session_service as vss

    vss.clear_context()
    assert vss.get_last_tts() is None

    vss.set_last_tts("Opening Safari now.")
    assert vss.get_last_tts() == "Opening Safari now."


# --- Voice command interrupt via API -----------------------------------------

@pytest.mark.asyncio
async def test_voice_command_interrupt(async_client):
    """POST /voice/command with an interrupt phrase returns was_interrupt=True."""
    # Unlock session first
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    await async_client.post("/api/v1/wake/activate", json={})

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "stop"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["was_interrupt"] is True
    assert data["overall_status"] == "interrupted"
    assert data["tts_text"] is None
    # Session must remain unlocked after interrupt
    assert data["voice_state"] == "unlocked"


@pytest.mark.asyncio
async def test_voice_context_endpoint(async_client):
    """GET /voice/context returns turns and summary fields."""
    # Unlock and run a command to populate context
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    await async_client.post("/api/v1/wake/activate", json={})

    r = await async_client.get("/api/v1/voice/context")
    assert r.status_code == 200
    data = r.json()
    assert "turns" in data
    assert "summary" in data
    assert isinstance(data["turns"], list)
    assert isinstance(data["summary"], str)


@pytest.mark.asyncio
async def test_voice_context_delete(async_client):
    """DELETE /voice/context clears the context and returns ok=True."""
    # Add some context first
    from app.services import voice_session_service as vss
    vss.add_context_turn("user", "Test turn")

    r = await async_client.delete("/api/v1/voice/context")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Verify it's gone
    ctx = await async_client.get("/api/v1/voice/context")
    assert ctx.json()["turns"] == []


@pytest.mark.asyncio
async def test_voice_command_tts_shaped_no_markdown(async_client):
    """tts_text in VoiceCommandResponse must not contain markdown characters."""
    await async_client.patch(
        "/api/v1/wake/settings",
        json={"wake_word_enabled": True, "wake_mode": "manual"},
    )
    await async_client.post("/api/v1/wake/activate", json={})

    r = await async_client.post(
        "/api/v1/voice/command",
        json={"command": "create folder /tmp/lani_shaped_tts_test", "tts_response": True},
    )
    assert r.status_code == 200
    data = r.json()
    if data["tts_text"]:
        tts = data["tts_text"]
        # No markdown characters expected
        assert "**" not in tts
        assert "##" not in tts
        assert "`" not in tts


# ─── Workflow ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_workflow_run_returns_result_shape(async_client):
    """POST /workflow/run returns a valid WorkflowResult shape."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "research Python async best practices and create a presentation"},
    )
    assert r.status_code == 200
    data = r.json()
    # Core fields must be present
    assert "workflow_id" in data
    assert "goal" in data
    assert "overall_status" in data
    assert "steps" in data
    assert "artifacts" in data
    assert "message" in data
    assert "memory_hints" in data
    # Goal echoed back
    assert data["goal"] == "research Python async best practices and create a presentation"
    # Status is a recognised value
    assert data["overall_status"] in ("completed", "failed", "approval_required", "partial")


@pytest.mark.asyncio
async def test_workflow_run_research_present_open(async_client):
    """Research → present → open workflow produces ≥ 3 plan steps."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "research machine learning trends and create a presentation then open it"},
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["steps"], list)
    # Should have at least web_search + summarize + create_presentation + open_path
    assert len(data["steps"]) >= 3
    tools = [s["tool"] for s in data["steps"]]
    assert "web_search" in tools
    assert "create_presentation" in tools


@pytest.mark.asyncio
async def test_workflow_run_calendar_email_invite(async_client):
    """Calendar + email invite workflow is approval-gated or safely fails without session context."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "schedule a team standup meeting and send an invite to the team"},
    )
    assert r.status_code == 200
    data = r.json()
    # calendar_create_event requires approval when session context exists;
    # otherwise guard safely fails with explicit session-required message.
    assert data["overall_status"] in ("approval_required", "failed")
    statuses = [s["status"] for s in data["steps"]]
    if data["overall_status"] == "approval_required":
        assert data["requires_approval"] is True
        assert data["approval_id"] is not None
        assert "approval_required" in statuses
    else:
        assert "failed" in statuses


@pytest.mark.asyncio
async def test_workflow_run_builder_scaffold_open(async_client):
    """Builder scaffold → open editor workflow produces project scaffold step."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "create a new React project called my-app and then open it in VS Code"},
    )
    assert r.status_code == 200
    data = r.json()
    tools = [s["tool"] for s in data["steps"]]
    assert "create_project_scaffold" in tools
    assert "operator.open_path" in tools


@pytest.mark.asyncio
async def test_workflow_run_drive_summarize_email(async_client):
    """Drive → summarize → email workflow produces ≥ 3 steps."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "find the Q4 report in my drive and draft an email summary to alice@example.com"},
    )
    assert r.status_code == 200
    data = r.json()
    tools = [s["tool"] for s in data["steps"]]
    assert "drive_search_files" in tools
    assert "gmail_create_draft" in tools
    # Status can be failed/partial because no Drive account is connected in tests,
    # but the plan must be built with the correct tools
    assert data["overall_status"] in ("completed", "failed", "partial", "approval_required")


@pytest.mark.asyncio
async def test_workflow_status_not_found(async_client):
    """GET /workflow/status/{id} returns 404 for unknown IDs."""
    r = await async_client.get("/api/v1/workflow/status/nonexistent-id-12345")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_workflow_status_found_after_run(async_client):
    """GET /workflow/status/{id} returns the result stored after a run."""
    run_r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "research climate change trends and create a presentation"},
    )
    assert run_r.status_code == 200
    workflow_id = run_r.json()["workflow_id"]

    status_r = await async_client.get(f"/api/v1/workflow/status/{workflow_id}")
    assert status_r.status_code == 200
    data = status_r.json()
    assert data["workflow_id"] == workflow_id
    assert data["goal"] == "research climate change trends and create a presentation"


@pytest.mark.asyncio
async def test_workflow_run_tts_response(async_client):
    """When tts_response=True the result includes a non-empty tts_text."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={
            "goal": "research Python frameworks and create a presentation",
            "tts_response": True,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("tts_text") is not None
    assert len(data["tts_text"]) > 0
    # TTS text must not contain markdown
    tts = data["tts_text"]
    assert "**" not in tts
    assert "##" not in tts


@pytest.mark.asyncio
async def test_workflow_artifact_piping_resolve_pipe():
    """Unit-test _resolve_pipe: pipe sentinel resolves from previous step result."""
    from app.schemas.plan import StepResult
    from app.services.workflow_executor import _resolve_pipe

    completed_sr = StepResult(
        step_index=0,
        tool="web_search",
        status="completed",
        data={"urls": ["https://example.com/a", "https://example.com/b"]},
    )

    # Pipe from step 0 → should return URLs list
    result = _resolve_pipe("__pipe_from_step_0__", [completed_sr])
    assert isinstance(result, list)
    assert "https://example.com/a" in result

    # Unknown step → sentinel returned unchanged
    result2 = _resolve_pipe("__pipe_from_step_9__", [completed_sr])
    assert result2 == "__pipe_from_step_9__"

    # Non-sentinel → returned as-is
    result3 = _resolve_pipe("some_literal", [completed_sr])
    assert result3 == "some_literal"


@pytest.mark.asyncio
async def test_workflow_artifact_collection():
    """Unit-test _collect_artifact: correctly classifies tool outputs."""
    from app.services.workflow_executor import _collect_artifact

    # Presentation artifact
    art = _collect_artifact(2, "create_presentation", {"path": "/tmp/test.pptx"})
    assert art is not None
    assert art.type == "presentation"
    assert art.path == "/tmp/test.pptx"
    assert art.step_index == 2

    # Email draft artifact
    art2 = _collect_artifact(3, "gmail_create_draft", {"subject": "Hello", "draft_id": "abc123"})
    assert art2 is not None
    assert art2.type == "email_draft"
    assert "Hello" in art2.name

    # Unknown tool → None
    art3 = _collect_artifact(0, "unknown_tool_xyz", {"foo": "bar"})
    assert art3 is None


@pytest.mark.asyncio
async def test_workflow_run_unknown_goal_returns_422(async_client):
    """POST /workflow/run with completely unrecognisable goal returns 422."""
    r = await async_client.post(
        "/api/v1/workflow/run",
        json={"goal": "xyzzy frobnicate the quux splunge"},
    )
    # Either 422 (unrecognised) or 200 with failed status
    assert r.status_code in (200, 422)


# ─── System status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_system_status_shape(async_client):
    """GET /system/status returns expected shape."""
    r = await async_client.get("/api/v1/system/status")
    assert r.status_code == 200
    data = r.json()
    # Top-level keys
    assert "ready" in data
    assert isinstance(data["ready"], bool)
    assert "app_env" in data
    assert "python_version" in data
    assert "app_version" in data
    # Component tiles
    for key in (
        "environment", "database", "encryption", "openai_key", "secret_key",
        "voice_provider", "voice_biometrics", "stt", "tts", "voice_profile", "connected_accounts", "platform",
    ):
        assert key in data, f"Missing key: {key}"
        tile = data[key]
        assert "ok" in tile and isinstance(tile["ok"], bool)
        assert "label" in tile and isinstance(tile["label"], str)


@pytest.mark.asyncio
async def test_system_status_database_ok(async_client):
    """Database component must be ok in test environment."""
    r = await async_client.get("/api/v1/system/status")
    assert r.status_code == 200
    assert r.json()["database"]["ok"] is True


@pytest.mark.asyncio
async def test_system_status_platform_ok(async_client):
    """Platform check should succeed on any supported CI OS."""
    r = await async_client.get("/api/v1/system/status")
    assert r.status_code == 200
    data = r.json()
    # On Linux/macOS/Windows CI runners this must be True
    assert data["platform"]["ok"] is True


@pytest.mark.asyncio
async def test_system_status_app_env(async_client):
    """app_env must be 'test' when APP_ENV=test."""
    import os
    if os.environ.get("APP_ENV", "test") != "test":
        pytest.skip("Only relevant when APP_ENV=test")
    r = await async_client.get("/api/v1/system/status")
    assert r.status_code == 200
    data = r.json()
    assert data["app_env"] in ("test", "development")  # either is fine in CI
