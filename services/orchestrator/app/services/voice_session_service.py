"""Voice session service – manages the unlock/lock lifecycle.

A voice session is an in-memory token that is created when the user
successfully activates Lani (via wake word + optional speaker verification).
It expires after ``voice_session_timeout_seconds`` of wall-clock time.

All mutable state is kept in-process (no DB row) because session lifetimes are
short (<1 h) and we want zero-latency access. Audit events ARE written to SQLite.

Server-side relock flow
-----------------------
1.  ``unlock_session()`` stores ``unlocked_at``, ``expires_at``, and
    ``last_activity_at``.
2.  Every request that needs a live session calls ``ensure_active_session()``.
    This helper calls ``expire_if_needed()`` first, and if the session has
    expired it:
      a. calls ``relock()`` (sets ``unlocked=False``, voice_state=timeout)
      b. writes audit log: ``voice.session.expired``
      c. if ``require_reverification=True`` also writes
         ``voice.session.reverification_required``
      d. raises ``SessionExpiredError`` so the route can return a structured
         blocked response immediately.
3.  Successful commands call ``touch()`` to keep ``last_activity_at`` fresh
    (used for future idle-timeout extension).
4.  ``GET /wake/status`` always calls ``expire_if_needed()`` so the client
    always gets the authoritative lock state.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import record_action
from app.schemas.wake import VoiceState, SessionInfo


# ─── Custom exception ─────────────────────────────────────────────────────────

class SessionExpiredError(Exception):
    """Raised by ensure_active_session() when the session has expired."""

    def __init__(self, require_reverification: bool = False) -> None:
        self.require_reverification = require_reverification
        super().__init__("Voice session has expired.")


# ─── In-process session state ─────────────────────────────────────────────────

class _VoiceSession:
    """Singleton-ish mutable session container.

    All timestamps are stored as **naive UTC** datetimes so comparison with
    ``datetime.datetime.utcnow()`` is consistent across Python versions.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.session_id: Optional[str] = None
        self.unlocked: bool = False
        self.unlocked_at: Optional[datetime.datetime] = None
        self.expires_at: Optional[datetime.datetime] = None
        self.last_activity_at: Optional[datetime.datetime] = None
        self.voice_state: VoiceState = VoiceState.idle
        self.require_reverification: bool = False
        # ── Conversational context (cleared on lock/expiry) ───────────────
        self._turns: List[Dict[str, str]] = []
        """Ring buffer of recent turns: [{"role": "user"|"assistant", "text": str}]"""
        self._last_tts_text: Optional[str] = None
        """Last spoken TTS text – used for 'replay last' feature."""

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> datetime.datetime:
        """Return naive UTC now (consistent with stored timestamps)."""
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def is_expired(self) -> bool:
        """Return True if the session is unlocked but the expiry time has passed."""
        if not self.unlocked or self.expires_at is None:
            return False
        return self._now() >= self.expires_at

    def is_active(self) -> bool:
        """Return True if session is unlocked AND not expired."""
        return self.unlocked and not self.is_expired()

    def seconds_remaining(self) -> Optional[int]:
        if not self.unlocked or self.expires_at is None:
            return None
        delta = (self.expires_at - self._now()).total_seconds()
        return max(0, int(delta))

    def touch(self) -> None:
        """Update last_activity_at to now (call after each successful command)."""
        if self.unlocked:
            self.last_activity_at = self._now()

    def to_session_info(self) -> SessionInfo:
        return SessionInfo(
            unlocked=self.is_active(),
            unlocked_at=self.unlocked_at.isoformat() if self.unlocked_at else None,
            expires_at=self.expires_at.isoformat() if self.expires_at else None,
            seconds_remaining=self.seconds_remaining(),
            session_id=self.session_id,
            last_activity_at=(
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
        )

    # ── Conversational context helpers ────────────────────────────────────────

    MAX_TURNS = 6  # keep last 3 user+assistant pairs

    def add_turn(self, role: str, text: str) -> None:
        """Append a turn to the context ring buffer."""
        self._turns.append({"role": role, "text": text[:400]})
        if len(self._turns) > self.MAX_TURNS:
            self._turns = self._turns[-self.MAX_TURNS:]

    def get_context_turns(self) -> List[Dict[str, str]]:
        """Return a copy of recent turns."""
        return list(self._turns)

    def get_context_summary(self) -> str:
        """Return a single-string context summary for the planner prompt."""
        if not self._turns:
            return ""
        lines = []
        for turn in self._turns[-4:]:  # last 2 pairs
            prefix = "User" if turn["role"] == "user" else "Assistant"
            lines.append(f"{prefix}: {turn['text']}")
        return "\n".join(lines)

    def clear_context(self) -> None:
        self._turns = []
        self._last_tts_text = None

    def set_last_tts(self, text: str) -> None:
        self._last_tts_text = text

    def get_last_tts(self) -> Optional[str]:
        return self._last_tts_text


# Module-level singleton – one session per process.
_session = _VoiceSession()


# ─── Public API ───────────────────────────────────────────────────────────────

def reset_session() -> None:
    """Reset the in-process session to its initial state.

    Intended for use in tests to prevent state bleeding between test cases.
    """
    _session.reset()


def get_session() -> _VoiceSession:
    """Return the current session object (may be expired – check is_active())."""
    return _session


def get_voice_state() -> VoiceState:
    """Return current voice state, auto-setting timeout if expired."""
    if _session.is_expired():
        _session.unlocked = False
        _session.voice_state = VoiceState.timeout
    return _session.voice_state


def set_voice_state(state: VoiceState) -> None:
    _session.voice_state = state


def touch_session() -> None:
    """Bump last_activity_at without hitting the DB (zero-cost after commands)."""
    _session.touch()


# ─── Context API ──────────────────────────────────────────────────────────────

def add_context_turn(role: str, text: str) -> None:
    """Record a user or assistant turn in the conversational context."""
    _session.add_turn(role, text)


def get_context_summary() -> str:
    """Return a multi-line context summary for the planner (last 2 pairs)."""
    return _session.get_context_summary()


def get_context_turns() -> List[Dict[str, str]]:
    """Return the raw turn list."""
    return _session.get_context_turns()


def clear_context() -> None:
    """Manually clear the conversational context."""
    _session.clear_context()


def set_last_tts(text: str) -> None:
    """Store the last spoken TTS text so the user can replay it."""
    _session.set_last_tts(text)


def get_last_tts() -> Optional[str]:
    """Return the last spoken TTS text (None if none yet)."""
    return _session.get_last_tts()


# ─── Session lifecycle ────────────────────────────────────────────────────────

async def unlock_session(
    db: AsyncSession,
    timeout_seconds: int = 120,
    require_reverification: bool = False,
) -> SessionInfo:
    """Mark session as unlocked and start the expiry clock.

    Parameters
    ----------
    timeout_seconds:
        How many seconds until the session expires.
    require_reverification:
        Whether re-verification is required after expiry (stored so
        ``ensure_active_session`` can report it back to callers).
    """
    now = _session._now()
    _session.session_id = uuid.uuid4().hex
    _session.unlocked = True
    _session.unlocked_at = now
    _session.last_activity_at = now
    # timeout_seconds == 0 means "never expire"
    if timeout_seconds and timeout_seconds > 0:
        _session.expires_at = now + datetime.timedelta(seconds=timeout_seconds)
    else:
        _session.expires_at = None
    _session.require_reverification = require_reverification
    _session.voice_state = VoiceState.unlocked

    await record_action(
        db,
        "voice.session.unlocked",
        "wake_word",
        "success",
        result_summary=(
            f"session_id={_session.session_id} "
            f"timeout={timeout_seconds}s "
            f"reverify={require_reverification}"
        ),
    )
    return _session.to_session_info()


def relock() -> None:
    """Synchronously lock the session (no DB write – callers log separately)."""
    _session.unlocked = False
    _session.session_id = None
    _session.expires_at = None
    _session.last_activity_at = None
    _session.voice_state = VoiceState.timeout
    _session.clear_context()


async def lock_session(db: AsyncSession, reason: str = "manual") -> SessionInfo:
    """Explicitly lock the current session and write an audit log."""
    was_unlocked = _session.unlocked
    old_id = _session.session_id
    relock()
    _session.voice_state = VoiceState.idle  # manual lock → idle, not timeout

    if was_unlocked:
        await record_action(
            db,
            "voice.session.locked",
            "wake_word",
            "success",
            result_summary=f"session_id={old_id} reason={reason}",
        )
    return _session.to_session_info()


async def expire_if_needed(db: AsyncSession) -> bool:
    """If the session has expired, relock it, write audit logs, return True.

    This is the canonical expiry-check called at the top of every protected
    route.  It is idempotent: if the session is already locked it returns False
    immediately.
    """
    if not _session.is_expired():
        return False

    old_id = _session.session_id
    require_reverif = _session.require_reverification
    relock()

    await record_action(
        db,
        "voice.session.expired",
        "wake_word",
        "info",
        result_summary=f"session_id={old_id}",
    )
    if require_reverif:
        await record_action(
            db,
            "voice.session.reverification_required",
            "wake_word",
            "info",
            result_summary=f"session_id={old_id}",
        )
    return True


async def ensure_active_session(db: AsyncSession) -> None:
    """Assert that the voice session is currently active.

    Calls ``expire_if_needed`` first so the session state is up-to-date,
    then raises ``SessionExpiredError`` ONLY if the session was previously
    unlocked but has since expired (auto-relock).

    A session that was never unlocked does NOT raise here — routes should
    check ``session_info.unlocked`` separately and return ``session_locked``.
    """
    just_expired = await expire_if_needed(db)
    if just_expired:
        raise SessionExpiredError(
            require_reverification=_session.require_reverification
        )


# ─── Backwards-compat alias used by existing routes ──────────────────────────

async def maybe_expire(db: AsyncSession) -> bool:
    """Legacy alias for expire_if_needed(); kept for backward compatibility."""
    return await expire_if_needed(db)
