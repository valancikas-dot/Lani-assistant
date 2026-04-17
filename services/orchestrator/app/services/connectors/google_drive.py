"""Google Drive connector.

Uses the Google Drive REST API v3 via ``google-api-python-client``.
Falls back gracefully when the library is not installed (returns clear errors).

Required OAuth scopes
─────────────────────
  Read-only : https://www.googleapis.com/auth/drive.readonly
  Full       : https://www.googleapis.com/auth/drive        (not requested by default)

Environment variables (set in services/orchestrator/.env)
─────────────────────────────────────────────────────────
  GOOGLE_CLIENT_ID      your OAuth 2.0 client ID
  GOOGLE_CLIENT_SECRET  your OAuth 2.0 client secret
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.connector_account import ConnectorAccount
from app.models.connector_token import ConnectorToken
from app.schemas.connectors import (
    CapabilityInfo,
    ConnectorManifest,
    DriveFile,
    DriveListResult,
    OAuthCallbackResponse,
)
from app.services.connectors.base import ConnectorBase, TokenStore

_DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
_USERINFO_EMAIL = "https://www.googleapis.com/auth/userinfo.email"
_USERINFO_PROFILE = "https://www.googleapis.com/auth/userinfo.profile"
_SCOPES = [_USERINFO_EMAIL, _USERINFO_PROFILE, _DRIVE_READONLY]

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
        import google.auth  # noqa: F401
        return True
    except ImportError:
        return False


class GoogleDriveConnector(ConnectorBase):
    provider = "google_drive"
    display_name = "Google Drive"
    icon = "📁"

    # ─── Manifest ────────────────────────────────────────────────────────

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            provider="google_drive",
            display_name=self.display_name,
            icon=self.icon,
            auth_scopes=_SCOPES,
            capabilities=[
                CapabilityInfo(
                    name="drive_list_files",
                    description="List files in Google Drive (most recent first)",
                    requires_approval=False,
                    required_scopes=[_DRIVE_READONLY],
                    read_only=True,
                ),
                CapabilityInfo(
                    name="drive_search_files",
                    description="Search for files in Google Drive by name or content",
                    requires_approval=False,
                    required_scopes=[_DRIVE_READONLY],
                    read_only=True,
                ),
                CapabilityInfo(
                    name="drive_get_file",
                    description="Get metadata for a specific Drive file by ID",
                    requires_approval=False,
                    required_scopes=[_DRIVE_READONLY],
                    read_only=True,
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
                ok=False, account_id=0, provider="google_drive",
                account_email="", scopes_granted=[],
                message="google-api-python-client not installed. "
                        "Run: pip install google-api-python-client google-auth-oauthlib",
            )
        if not _client_id():
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="google_drive",
                account_email="", scopes_granted=[],
                message="GOOGLE_CLIENT_ID not configured in .env",
            )

        try:
            from google_auth_oauthlib.flow import Flow

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

            # Fetch email via userinfo
            import requests
            headers = {"Authorization": f"Bearer {creds.token}"}
            ui = requests.get(_USERINFO_URI, headers=headers, timeout=10).json()
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

            # Upsert ConnectorAccount
            existing = await db.execute(
                select(ConnectorAccount).where(
                    ConnectorAccount.provider == "google_drive",
                    ConnectorAccount.account_email == email,
                )
            )
            account = existing.scalar_one_or_none()
            if account is None:
                account = ConnectorAccount(
                    provider="google_drive",
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
                provider="google_drive",
                account_email=email,
                scopes_granted=creds_dict["scopes"],
                message=f"Google Drive connected for {email}",
            )
        except Exception as exc:
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="google_drive",
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
            if action == "drive_list_files":
                return await self._list_files(service, params)
            elif action == "drive_search_files":
                return await self._search_files(service, params)
            elif action == "drive_get_file":
                return await self._get_file(service, params)
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
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    async def _list_files(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        page_size = min(int(params.get("page_size", 20)), 100)
        page_token = params.get("page_token")
        kwargs: Dict[str, Any] = {
            "pageSize": page_size,
            "fields": "nextPageToken, files(id,name,mimeType,size,modifiedTime,webViewLink)",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.files().list(**kwargs).execute()
        files = [
            DriveFile(
                id=f["id"],
                name=f["name"],
                mime_type=f["mimeType"],
                size=int(f["size"]) if "size" in f else None,
                modified_at=f.get("modifiedTime"),
                web_view_link=f.get("webViewLink"),
            ).model_dump()
            for f in result.get("files", [])
        ]
        return DriveListResult(
            files=files, next_page_token=result.get("nextPageToken")
        ).model_dump()

    async def _search_files(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        page_size = min(int(params.get("page_size", 20)), 100)
        q = f"name contains '{query}'" if query else ""
        result = service.files().list(
            q=q,
            pageSize=page_size,
            fields="files(id,name,mimeType,size,modifiedTime,webViewLink)",
        ).execute()
        files = [
            DriveFile(
                id=f["id"],
                name=f["name"],
                mime_type=f["mimeType"],
                size=int(f["size"]) if "size" in f else None,
                modified_at=f.get("modifiedTime"),
                web_view_link=f.get("webViewLink"),
            ).model_dump()
            for f in result.get("files", [])
        ]
        return DriveListResult(files=files, next_page_token=None).model_dump()

    async def _get_file(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        file_id = params.get("file_id", "")
        if not file_id:
            return {"error": "file_id is required"}
        f = service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size,modifiedTime,webViewLink",
        ).execute()
        return DriveFile(
            id=f["id"], name=f["name"], mime_type=f["mimeType"],
            size=int(f["size"]) if "size" in f else None,
            modified_at=f.get("modifiedTime"),
            web_view_link=f.get("webViewLink"),
        ).model_dump()
