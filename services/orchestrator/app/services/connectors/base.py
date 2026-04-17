"""Base connector infrastructure.

Responsibilities
────────────────
1. ``TokenStore``      – encrypt/decrypt OAuth credentials in the DB.
2. ``ConnectorBase``   – abstract class every connector must subclass.
3. ``CONNECTOR_REGISTRY`` – mapping provider → ConnectorBase instance.
4. ``get_connector``   – safe lookup helper.
5. ``list_manifests``  – returns all available CapabilityInfo manifests.

Encryption
──────────
Tokens are encrypted at rest with **Fernet** (symmetric, authenticated
encryption from the ``cryptography`` library).  The key is derived from
``CONNECTOR_ENCRYPTION_KEY`` in the .env file.  If the env var is absent
a *deterministic development key* is used automatically and a warning is
logged – this is intentionally non-secret and safe only for local dev.

Rotating the key: set the new value, then call
``TokenStore.re_encrypt_all(db, old_key)`` once at startup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import datetime

from app.models.connector_account import ConnectorAccount
from app.models.connector_token import ConnectorToken
from app.schemas.connectors import (
    ConnectorManifest,
    ConnectorProvider,
    ConnectResponse,
    OAuthCallbackResponse,
)

log = logging.getLogger(__name__)

# ─── Encryption helpers ───────────────────────────────────────────────────────

def _get_fernet():
    """Return a Fernet instance appropriate for the current environment.

    - production:  CONNECTOR_ENCRYPTION_KEY must be set; raises if absent.
    - dev/test:    Falls back to a deterministic hostname-derived key with a
                   prominent warning.  This key is NOT secret and must never be
                   used in production.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise RuntimeError(
            "The 'cryptography' package is required for connector token storage. "
            "Install it with: pip install cryptography"
        )

    from app.core.config import settings  # local import to avoid circular

    raw_key = settings.CONNECTOR_ENCRYPTION_KEY or os.environ.get("CONNECTOR_ENCRYPTION_KEY", "")

    if raw_key:
        try:
            key_bytes = base64.urlsafe_b64decode(raw_key + "==")
            if len(key_bytes) == 32:
                key = base64.urlsafe_b64encode(key_bytes)
            else:
                key = raw_key.encode()
        except Exception:
            key = raw_key.encode()
        return Fernet(key)

    # No key configured.
    if settings.is_production:
        raise RuntimeError(
            "[FATAL] CONNECTOR_ENCRYPTION_KEY is not set and APP_ENV=production. "
            "Refusing to use a dev key in production. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    # Dev/test: use a deterministic hostname-based key and warn loudly.
    seed = f"lani-dev-connector-key-{os.uname().nodename}"
    key = base64.urlsafe_b64encode(
        hashlib.sha256(seed.encode()).digest()
    )
    log.warning(
        "CONNECTOR_ENCRYPTION_KEY not set – using a deterministic DEV key derived "
        "from the machine hostname. THIS IS NOT SECURE. "
        "Set CONNECTOR_ENCRYPTION_KEY in services/orchestrator/.env before connecting real accounts."
    )
    return Fernet(key)


def encrypt_credentials(creds: Dict[str, Any]) -> str:
    """Return a base64 Fernet-encrypted JSON string of *creds*."""
    f = _get_fernet()
    return f.encrypt(json.dumps(creds).encode()).decode()


def decrypt_credentials(encrypted: str) -> Dict[str, Any]:
    """Decrypt and parse an encrypted credential blob. Raises on tamper/bad key."""
    f = _get_fernet()
    return json.loads(f.decrypt(encrypted.encode()))


# ─── Token store ─────────────────────────────────────────────────────────────

class TokenStore:
    """CRUD helpers for ConnectorToken rows."""

    @staticmethod
    async def save(
        db: AsyncSession,
        account_id: int,
        creds: Dict[str, Any],
        expires_at: Optional[datetime.datetime] = None,
    ) -> ConnectorToken:
        # Delete any existing token for this account first (upsert)
        await db.execute(
            delete(ConnectorToken).where(ConnectorToken.account_id == account_id)
        )
        token = ConnectorToken(
            account_id=account_id,
            encrypted_credentials=encrypt_credentials(creds),
            expires_at=expires_at,
        )
        db.add(token)
        await db.flush()
        return token

    @staticmethod
    async def load(
        db: AsyncSession, account_id: int
    ) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(ConnectorToken).where(ConnectorToken.account_id == account_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        try:
            return decrypt_credentials(row.encrypted_credentials)
        except Exception as exc:
            log.error(
                "Failed to decrypt token for account %d (possible key rotation or tamper): %s",
                account_id,
                exc,
            )
            # Import here to avoid circular dependency
            from app.services.audit_service import record_action  # type: ignore
            await record_action(
                db,
                command="connector.token_decrypt_failure",
                tool_name="connector.token_store",
                status="error",
                result_summary=f"account_id={account_id}",
                error_message=f"Decryption failed: {type(exc).__name__}",
            )
            return None

    @staticmethod
    async def delete(db: AsyncSession, account_id: int) -> None:
        await db.execute(
            delete(ConnectorToken).where(ConnectorToken.account_id == account_id)
        )


# ─── Abstract connector ───────────────────────────────────────────────────────

class ConnectorBase(ABC):
    """All connectors must subclass this."""

    #: e.g. "google_drive"
    provider: ConnectorProvider

    #: Human-readable name shown in the UI
    display_name: str

    #: Emoji / SVG identifier for the UI
    icon: str

    #: Full capability manifest
    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        ...

    # ── OAuth flow (Google-style PKCE-less web flow) ──────────────────────

    @abstractmethod
    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        """Return the provider's OAuth consent-screen URL."""
        ...

    @abstractmethod
    async def exchange_code(
        self,
        db: AsyncSession,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> OAuthCallbackResponse:
        """Exchange an auth code for tokens; persist account + token rows."""
        ...

    # ── Disconnect ────────────────────────────────────────────────────────

    async def disconnect(self, db: AsyncSession, account_id: int) -> None:
        """Delete tokens and mark account inactive."""
        await TokenStore.delete(db, account_id)
        result = await db.execute(
            select(ConnectorAccount).where(ConnectorAccount.id == account_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.is_active = False
        await db.flush()

    # ── Actions ───────────────────────────────────────────────────────────

    @abstractmethod
    async def execute_action(
        self,
        db: AsyncSession,
        account_id: int,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a named action and return raw result dict."""
        ...

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _load_creds(
        self, db: AsyncSession, account_id: int
    ) -> Dict[str, Any]:
        creds = await TokenStore.load(db, account_id)
        if not creds:
            raise ValueError(
                f"No credentials found for account {account_id}. "
                "Re-connect the account."
            )
        return creds

    async def _touch_account(
        self, db: AsyncSession, account_id: int
    ) -> None:
        result = await db.execute(
            select(ConnectorAccount).where(ConnectorAccount.id == account_id)
        )
        row = result.scalar_one_or_none()
        if row:
                row.last_used_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

    async def _record_error(
        self, db: AsyncSession, account_id: int, error: str
    ) -> None:
        result = await db.execute(
            select(ConnectorAccount).where(ConnectorAccount.id == account_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.last_error = error[:500]
        await db.flush()

    # ── OAuth state CSRF token ─────────────────────────────────────────────

    @staticmethod
    def new_state() -> str:
        return secrets.token_urlsafe(24)


# ─── Registry ─────────────────────────────────────────────────────────────────

CONNECTOR_REGISTRY: Dict[str, ConnectorBase] = {}


def _register_connectors() -> None:
    """Import connectors to populate CONNECTOR_REGISTRY."""
    from app.services.connectors.google_drive import GoogleDriveConnector
    from app.services.connectors.gmail import GmailConnector
    from app.services.connectors.calendar import GoogleCalendarConnector

    for connector in [
        GoogleDriveConnector(),
        GmailConnector(),
        GoogleCalendarConnector(),
    ]:
        CONNECTOR_REGISTRY[connector.provider] = connector


def get_connector(provider: str) -> Optional[ConnectorBase]:
    if not CONNECTOR_REGISTRY:
        _register_connectors()
    return CONNECTOR_REGISTRY.get(provider)


def list_manifests() -> List[ConnectorManifest]:
    if not CONNECTOR_REGISTRY:
        _register_connectors()
    return [c.manifest for c in CONNECTOR_REGISTRY.values()]
