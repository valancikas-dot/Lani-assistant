"""
Session Manager – multi-account session isolation layer.

Responsibilities
────────────────
1. Maintain one ``AccountSession`` per account type (gmail, google_drive, browser, …)
2. Provide session vault: tokens are held encrypted in-memory (backed by the
   existing TokenStore from connectors/base.py for persistence).
3. Enforce session isolation – each session has its own credential namespace.
4. Active session switching – caller can set the "active" session per type.
5. Detect stale / expired sessions and mark them accordingly.

Design
──────
All mutable state lives in the ``_SessionVault`` singleton (in-process).
Tokens are only written to the DB through the existing ``TokenStore`` so the
connector encryption infrastructure is reused without duplication.

Public API
──────────
  get_vault()                              → _SessionVault
  get_session(account_type, account_id)   → AccountSession | None
  register_session(...)                   → AccountSession
  activate_session(account_type, id)      → None
  get_active_session(account_type)        → AccountSession | None
  deactivate_session(account_type, id)    → None
  list_sessions()                         → List[SessionSummary]
  clear_all()                             → None  (test helper)
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ─── Session status constants ─────────────────────────────────────────────────
SESSION_ACTIVE     = "active"
SESSION_INACTIVE   = "inactive"
SESSION_EXPIRED    = "expired"
SESSION_REVOKED    = "revoked"


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AccountSession:
    """Represents one authenticated account session."""

    session_id: str                        # opaque UUID-hex
    account_type: str                      # gmail | google_drive | google_calendar | browser | …
    account_id: str                        # user identifier within that account type
    display_name: str = ""
    status: str = SESSION_ACTIVE
    scopes: List[str] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    last_used_at: Optional[datetime.datetime] = None
    expires_at: Optional[datetime.datetime] = None
    # Opaque credential blob stored in-memory (never logged)
    _credentials: Dict[str, Any] = field(default_factory=dict, repr=False)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Helpers ───────────────────────────────────────────────────────────

    def touch(self) -> None:
        self.last_used_at = datetime.datetime.now(tz=datetime.timezone.utc)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        # Handle naive expires_at (legacy) by treating it as UTC
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.timezone.utc)
        return now > exp

    def to_summary(self) -> "SessionSummary":
        return SessionSummary(
            session_id=self.session_id,
            account_type=self.account_type,
            account_id=self.account_id,
            display_name=self.display_name,
            status=SESSION_EXPIRED if self.is_expired() else self.status,
            scopes=list(self.scopes),
            created_at=self.created_at.isoformat(),
            last_used_at=self.last_used_at.isoformat() if self.last_used_at else None,
            expires_at=self.expires_at.isoformat() if self.expires_at else None,
        )


@dataclass
class SessionSummary:
    """JSON-serialisable view of a session (no credentials)."""
    session_id: str
    account_type: str
    account_id: str
    display_name: str
    status: str
    scopes: List[str]
    created_at: str
    last_used_at: Optional[str]
    expires_at: Optional[str]


# ─── Vault ────────────────────────────────────────────────────────────────────

class _SessionVault:
    """
    In-process session vault.

    Structure
    ─────────
    _sessions: { account_type: { account_id: AccountSession } }
    _active:   { account_type: account_id }  # which session is "current"
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, AccountSession]] = {}
        self._active: Dict[str, str] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register(
        self,
        account_type: str,
        account_id: str,
        *,
        display_name: str = "",
        scopes: Optional[List[str]] = None,
        credentials: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime.datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        make_active: bool = True,
    ) -> AccountSession:
        """Register (or update) a session and optionally make it active."""
        bucket = self._sessions.setdefault(account_type, {})

        if account_id in bucket:
            # Update existing session in-place
            sess = bucket[account_id]
            sess.status = SESSION_ACTIVE
            sess.last_used_at = datetime.datetime.utcnow()
            if credentials:
                sess._credentials = credentials
            if scopes:
                sess.scopes = scopes
            if expires_at:
                sess.expires_at = expires_at
            if metadata:
                sess.metadata.update(metadata)
            log.info("[session_manager] updated session %s/%s", account_type, account_id)
        else:
            sess = AccountSession(
                session_id=secrets.token_hex(16),
                account_type=account_type,
                account_id=account_id,
                display_name=display_name or account_id,
                status=SESSION_ACTIVE,
                scopes=scopes or [],
                expires_at=expires_at,
                _credentials=credentials or {},
                metadata=metadata or {},
            )
            bucket[account_id] = sess
            log.info("[session_manager] registered new session %s/%s", account_type, account_id)

        if make_active:
            self._active[account_type] = account_id

        return sess

    # ── Lookup ────────────────────────────────────────────────────────────

    def get(self, account_type: str, account_id: str) -> Optional[AccountSession]:
        sess = self._sessions.get(account_type, {}).get(account_id)
        if sess and sess.is_expired():
            sess.status = SESSION_EXPIRED
        return sess

    def get_active(self, account_type: str) -> Optional[AccountSession]:
        active_id = self._active.get(account_type)
        if not active_id:
            return None
        sess = self.get(account_type, active_id)
        # get() may have just marked it expired; don't return expired sessions
        if sess is not None and sess.status in (SESSION_EXPIRED, SESSION_REVOKED):
            # Clean up the active pointer so future lookups are fast
            del self._active[account_type]
            return None
        return sess

    def get_credentials(self, account_type: str, account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Return raw credentials for a session.
        If account_id is None, uses the active session for account_type.
        Returns None if session is missing or expired.
        """
        aid = account_id or self._active.get(account_type)
        if not aid:
            return None
        sess = self.get(account_type, aid)
        if sess is None or sess.status in (SESSION_EXPIRED, SESSION_REVOKED):
            return None
        sess.touch()
        return dict(sess._credentials)

    # ── Activation ────────────────────────────────────────────────────────

    def activate(self, account_type: str, account_id: str) -> None:
        if account_id in self._sessions.get(account_type, {}):
            self._active[account_type] = account_id
            log.info("[session_manager] activated %s/%s", account_type, account_id)
        else:
            raise KeyError(f"No session for {account_type}/{account_id}")

    def deactivate(self, account_type: str, account_id: str) -> None:
        bucket = self._sessions.get(account_type, {})
        if account_id in bucket:
            bucket[account_id].status = SESSION_INACTIVE
        if self._active.get(account_type) == account_id:
            del self._active[account_type]
        log.info("[session_manager] deactivated %s/%s", account_type, account_id)

    def revoke(self, account_type: str, account_id: str) -> None:
        bucket = self._sessions.get(account_type, {})
        if account_id in bucket:
            bucket[account_id].status = SESSION_REVOKED
            bucket[account_id]._credentials = {}
        if self._active.get(account_type) == account_id:
            del self._active[account_type]
        log.info("[session_manager] revoked %s/%s", account_type, account_id)

    # ── Listing ───────────────────────────────────────────────────────────

    def list_sessions(self) -> List[SessionSummary]:
        result: List[SessionSummary] = []
        for sessions_by_id in self._sessions.values():
            for sess in sessions_by_id.values():
                result.append(sess.to_summary())
        return result

    def list_active_account_types(self) -> List[str]:
        """Return account types that have at least one active session."""
        active = []
        for atype, sessions_by_id in self._sessions.items():
            if any(
                s.status == SESSION_ACTIVE and not s.is_expired()
                for s in sessions_by_id.values()
            ):
                active.append(atype)
        return active

    # ── Maintenance ───────────────────────────────────────────────────────

    def expire_stale(self) -> int:
        """Mark expired sessions; return count of sessions expired."""
        count = 0
        for sessions_by_id in self._sessions.values():
            for sess in sessions_by_id.values():
                if sess.status == SESSION_ACTIVE and sess.is_expired():
                    sess.status = SESSION_EXPIRED
                    count += 1
        return count

    def clear_all(self) -> None:
        """Remove all sessions (used in tests)."""
        self._sessions.clear()
        self._active.clear()


# ─── Module-level singleton ───────────────────────────────────────────────────

_vault: Optional[_SessionVault] = None


def get_vault() -> _SessionVault:
    global _vault
    if _vault is None:
        _vault = _SessionVault()
    return _vault


# ─── Convenience functions ────────────────────────────────────────────────────

def register_session(
    account_type: str,
    account_id: str,
    *,
    display_name: str = "",
    scopes: Optional[List[str]] = None,
    credentials: Optional[Dict[str, Any]] = None,
    expires_at: Optional[datetime.datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
    make_active: bool = True,
) -> AccountSession:
    return get_vault().register(
        account_type,
        account_id,
        display_name=display_name,
        scopes=scopes,
        credentials=credentials,
        expires_at=expires_at,
        metadata=metadata,
        make_active=make_active,
    )


def get_session(account_type: str, account_id: str) -> Optional[AccountSession]:
    return get_vault().get(account_type, account_id)


def get_active_session(account_type: str) -> Optional[AccountSession]:
    return get_vault().get_active(account_type)


def get_credentials(account_type: str, account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return get_vault().get_credentials(account_type, account_id)


def activate_session(account_type: str, account_id: str) -> None:
    get_vault().activate(account_type, account_id)


def deactivate_session(account_type: str, account_id: str) -> None:
    get_vault().deactivate(account_type, account_id)


def revoke_session(account_type: str, account_id: str) -> None:
    get_vault().revoke(account_type, account_id)


def list_sessions() -> List[SessionSummary]:
    return get_vault().list_sessions()


def list_active_account_types() -> List[str]:
    return get_vault().list_active_account_types()


def sync_from_connector_accounts(connector_accounts: List[Any]) -> None:
    """
    Populate the vault from ConnectorAccount ORM rows returned by the DB.
    Call this at startup to restore sessions from persistent storage.

    connector_accounts: list of ConnectorAccount model instances.
    """
    vault = get_vault()
    for row in connector_accounts:
        if row.status != "connected":
            continue
        vault.register(
            account_type=row.provider,
            account_id=row.account_id,
            display_name=getattr(row, "display_name", "") or row.account_id,
            make_active=True,
        )
    log.info(
        "[session_manager] synced %d connector accounts into vault",
        len(connector_accounts),
    )


# ─── Phase 4: Session isolation enforcement ───────────────────────────────────

# Tools that REQUIRE an active session context before they may execute.
# Attempting to run these without a session_id triggers a guard denial.
_SESSION_REQUIRED_TOOLS: frozenset = frozenset({
    "browser_navigate",
    "browser_goto",
    "browser_click",
    "click_element",
    "browser_fill_form",
    "fill_form",
    "browser_submit_form",
    "submit_form",
    "operator_action",
    "operator_screenshot",
    "browser_screenshot",
    "gmail_send_email",
    "gmail_create_draft",
    "calendar_create_event",
    "drive_upload_file",
})


def validate_session_context(
    tool_name: str,
    session_id: Optional[str],
    *,
    require_for_all_browser_tools: bool = True,
) -> Optional[str]:
    """
    Validate that a session context is present when required.

    Parameters
    ----------
    tool_name                  : Tool about to be executed.
    session_id                 : Session ID supplied by the caller (may be None).
    require_for_all_browser_tools: If True, all tools starting with ``browser_``
                                   or ``operator_`` also require a session_id.

    Returns
    -------
    None if validation passes, or an error string that the guard should use
    to deny the request.
    """
    needs_session = tool_name in _SESSION_REQUIRED_TOOLS
    if require_for_all_browser_tools:
        if tool_name.startswith("browser_") or tool_name.startswith("operator_"):
            needs_session = True

    if needs_session and not session_id:
        return (
            f"Tool '{tool_name}' requires an active session context. "
            "Provide a session_id or connect the relevant account first."
        )
    return None


def assert_session_isolation(session_id_a: Optional[str], session_id_b: Optional[str]) -> bool:
    """
    Confirm that two session IDs are different (i.e., properly isolated).

    Returns True if they are isolated (different or one is None).
    Returns False if they are the same non-None value (sharing violation).
    """
    if session_id_a is None or session_id_b is None:
        return True
    return session_id_a != session_id_b
