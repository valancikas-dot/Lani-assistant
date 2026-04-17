"""Gmail connector.

Uses the Gmail REST API v1 via ``google-api-python-client``.

Required OAuth scopes
─────────────────────
  Read-only  : https://www.googleapis.com/auth/gmail.readonly
  Send mail  : https://mail.google.com/  (send = full-scope; narrower send-only
               requires a G-Suite Marketplace app – not suitable here)

Sensitive actions
─────────────────
  gmail_create_draft  – requires_approval = True
  gmail_send_email    – requires_approval = True
"""

from __future__ import annotations

import base64
import email as email_lib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.connector_account import ConnectorAccount
from app.models.connector_token import ConnectorToken
from app.schemas.connectors import (
    CapabilityInfo,
    ConnectorManifest,
    GmailDraftResult,
    GmailListResult,
    GmailMessageSummary,
    OAuthCallbackResponse,
)
from app.services.connectors.base import ConnectorBase, TokenStore, CONNECTOR_REGISTRY

_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
_GMAIL_SEND = "https://mail.google.com/"
_USERINFO_EMAIL = "https://www.googleapis.com/auth/userinfo.email"
_USERINFO_PROFILE = "https://www.googleapis.com/auth/userinfo.profile"
_SCOPES = [_USERINFO_EMAIL, _USERINFO_PROFILE, _GMAIL_READONLY, _GMAIL_SEND]

_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_USERINFO_URI = "https://www.googleapis.com/oauth2/v1/userinfo"


def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _is_google_libs_available() -> bool:
    try:
        import googleapiclient  # noqa: F401
        import google.auth       # noqa: F401
        return True
    except ImportError:
        return False


def _extract_header(headers: List[Dict], name: str) -> str:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


class GmailConnector(ConnectorBase):
    provider = "gmail"
    display_name = "Gmail"
    icon = "✉️"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            provider="gmail",
            display_name=self.display_name,
            icon=self.icon,
            auth_scopes=_SCOPES,
            capabilities=[
                CapabilityInfo(
                    name="gmail_list_recent",
                    description="List the most recent Gmail messages",
                    requires_approval=False,
                    required_scopes=[_GMAIL_READONLY],
                    read_only=True,
                ),
                CapabilityInfo(
                    name="gmail_get_message",
                    description="Get full content of a specific Gmail message by ID",
                    requires_approval=False,
                    required_scopes=[_GMAIL_READONLY],
                    read_only=True,
                ),
                CapabilityInfo(
                    name="gmail_create_draft",
                    description="Create a Gmail draft (requires approval)",
                    requires_approval=True,
                    required_scopes=[_GMAIL_SEND],
                    read_only=False,
                ),
                CapabilityInfo(
                    name="gmail_send_email",
                    description="Send an email from the connected Gmail account (requires approval)",
                    requires_approval=True,
                    required_scopes=[_GMAIL_SEND],
                    read_only=False,
                ),
            ],
        )

    # ─── OAuth ───────────────────────────────────────────────────────────

    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        from urllib.parse import urlencode
        params = {
            "client_id": _client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH_URI}?{urlencode(params)}"

    async def exchange_code(
        self,
        db: AsyncSession,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> OAuthCallbackResponse:
        if not _is_google_libs_available():
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="gmail",
                account_email="", scopes_granted=[],
                message="google-api-python-client not installed. "
                        "Run: pip install google-api-python-client google-auth-oauthlib",
            )
        if not _client_id():
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="gmail",
                account_email="", scopes_granted=[],
                message="GOOGLE_CLIENT_ID not configured in .env",
            )

        try:
            from google_auth_oauthlib.flow import Flow
            import requests as req_lib

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": _client_id(),
                        "client_secret": _client_secret(),
                        "auth_uri": _AUTH_URI,
                        "token_uri": _TOKEN_URI,
                        "redirect_uris": [redirect_uri],
                    }
                },
                scopes=_SCOPES,
                redirect_uri=redirect_uri,
            )
            flow.fetch_token(code=code)
            creds = flow.credentials

            headers = {"Authorization": f"Bearer {creds.token}"}
            ui = req_lib.get(_USERINFO_URI, headers=headers, timeout=10).json()
            email = ui.get("email", "")
            name = ui.get("name", "")

            creds_dict = {
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or _SCOPES),
            }

            existing = await db.execute(
                select(ConnectorAccount).where(
                    ConnectorAccount.provider == "gmail",
                    ConnectorAccount.account_email == email,
                )
            )
            account = existing.scalar_one_or_none()
            if account is None:
                account = ConnectorAccount(
                    provider="gmail",
                    account_email=email,
                    display_name=name,
                    scopes_granted=",".join(creds_dict["scopes"]),
                )
                db.add(account)
                await db.flush()
            else:
                account.is_active = True
                account.scopes_granted = ",".join(creds_dict["scopes"])
                account.display_name = name

            await TokenStore.save(db, account.id, creds_dict)

            return OAuthCallbackResponse(
                ok=True,
                account_id=account.id,
                provider="gmail",
                account_email=email,
                scopes_granted=creds_dict["scopes"],
                message=f"Gmail connected for {email}",
            )
        except Exception as exc:
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="gmail",
                account_email="", scopes_granted=[],
                message=f"OAuth exchange failed: {exc}",
            )

    # ─── Actions ─────────────────────────────────────────────────────────

    async def execute_action(
        self,
        db: AsyncSession,
        account_id: int,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        creds_dict = await self._load_creds(db, account_id)
        await self._touch_account(db, account_id)

        if not _is_google_libs_available():
            return {"error": "google-api-python-client not installed"}

        try:
            service = self._build_service(creds_dict)
            if action == "gmail_list_recent":
                return await self._list_recent(service, params)
            elif action == "gmail_get_message":
                return await self._get_message(service, params)
            elif action == "gmail_create_draft":
                return await self._create_draft(service, params)
            elif action == "gmail_send_email":
                return await self._send_email(service, params)
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as exc:
            await self._record_error(db, account_id, str(exc))
            return {"error": str(exc)}

    def _build_service(self, creds_dict: Dict[str, Any]):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=creds_dict["access_token"],
            refresh_token=creds_dict.get("refresh_token"),
            token_uri=creds_dict.get("token_uri", _TOKEN_URI),
            client_id=creds_dict.get("client_id", _client_id()),
            client_secret=creds_dict.get("client_secret", _client_secret()),
            scopes=creds_dict.get("scopes", _SCOPES),
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    async def _list_recent(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        max_results = min(int(params.get("max_results", 10)), 50)
        label_ids = params.get("label_ids", ["INBOX"])

        response = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            labelIds=label_ids,
        ).execute()

        messages: List[Dict[str, Any]] = []
        for msg_stub in response.get("messages", []):
            full = service.users().messages().get(
                userId="me",
                id=msg_stub["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = full.get("payload", {}).get("headers", [])
            messages.append(
                GmailMessageSummary(
                    id=full["id"],
                    thread_id=full["threadId"],
                    subject=_extract_header(headers, "Subject") or "(no subject)",
                    **{"from": _extract_header(headers, "From")},
                    date=_extract_header(headers, "Date"),
                    snippet=full.get("snippet", ""),
                ).model_dump(by_alias=True)
            )

        return GmailListResult(
            messages=messages,
            result_size_estimate=response.get("resultSizeEstimate", len(messages)),
        ).model_dump()

    async def _get_message(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        message_id = params.get("message_id", "")
        if not message_id:
            return {"error": "message_id is required"}

        full = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

        headers = full.get("payload", {}).get("headers", [])
        body = self._extract_body(full.get("payload", {}))

        return {
            "id": full["id"],
            "thread_id": full["threadId"],
            "subject": _extract_header(headers, "Subject"),
            "from": _extract_header(headers, "From"),
            "to": _extract_header(headers, "To"),
            "date": _extract_header(headers, "Date"),
            "snippet": full.get("snippet", ""),
            "body": body,
        }

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Recursively extract plain-text body from MIME payload."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")
        if "text/plain" in mime_type and body_data:
            return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            result = self._extract_body(part)
            if result:
                return result
        return ""

    async def _create_draft(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        to = params.get("to", "")
        subject = params.get("subject", "(no subject)")
        body = params.get("body", "")
        if not to:
            return {"error": "'to' field is required"}

        msg = MIMEMultipart("alternative")
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        return GmailDraftResult(
            draft_id=draft["id"],
            message_id=draft["message"]["id"],
        ).model_dump()

    async def _send_email(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        to = params.get("to", "")
        subject = params.get("subject", "(no subject)")
        body = params.get("body", "")
        if not to:
            return {"error": "'to' field is required"}

        msg = MIMEMultipart("alternative")
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        return {
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds", []),
        }


CONNECTOR_REGISTRY["gmail"] = GmailConnector()
