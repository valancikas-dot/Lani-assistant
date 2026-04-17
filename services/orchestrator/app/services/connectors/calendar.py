"""Google Calendar connector.

Uses the Google Calendar REST API v3 via ``google-api-python-client``.

Required OAuth scopes
─────────────────────
  Read-only  : https://www.googleapis.com/auth/calendar.readonly
  Read+write : https://www.googleapis.com/auth/calendar.events

Sensitive actions (require approval)
─────────────────────────────────────
  calendar_create_event  – creates a new calendar event
  calendar_update_event  – modifies an existing event
  calendar_delete_event  – permanently deletes an event
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.connector_account import ConnectorAccount
from app.models.connector_token import ConnectorToken
from app.schemas.connectors import (
    CalendarCreateResult,
    CalendarEvent,
    CalendarListResult,
    CapabilityInfo,
    ConnectorManifest,
    OAuthCallbackResponse,
)
from app.services.connectors.base import ConnectorBase, TokenStore, CONNECTOR_REGISTRY

_CAL_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
_CAL_EVENTS = "https://www.googleapis.com/auth/calendar.events"
_USERINFO_EMAIL = "https://www.googleapis.com/auth/userinfo.email"
_USERINFO_PROFILE = "https://www.googleapis.com/auth/userinfo.profile"
_SCOPES = [_USERINFO_EMAIL, _USERINFO_PROFILE, _CAL_READONLY, _CAL_EVENTS]

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


class GoogleCalendarConnector(ConnectorBase):
    provider = "google_calendar"
    display_name = "Google Calendar"
    icon = "📅"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            provider="google_calendar",
            display_name=self.display_name,
            icon=self.icon,
            auth_scopes=_SCOPES,
            capabilities=[
                CapabilityInfo(
                    name="calendar_list_events",
                    description="List upcoming calendar events",
                    requires_approval=False,
                    required_scopes=[_CAL_READONLY],
                    read_only=True,
                ),
                CapabilityInfo(
                    name="calendar_create_event",
                    description="Create a new calendar event (requires approval)",
                    requires_approval=True,
                    required_scopes=[_CAL_EVENTS],
                    read_only=False,
                ),
                CapabilityInfo(
                    name="calendar_delete_event",
                    description="Delete a calendar event (requires approval)",
                    requires_approval=True,
                    required_scopes=[_CAL_EVENTS],
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
                ok=False, account_id=0, provider="google_calendar",
                account_email="", scopes_granted=[],
                message="google-api-python-client not installed. "
                        "Run: pip install google-api-python-client google-auth-oauthlib",
            )
        if not _client_id():
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="google_calendar",
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
                    ConnectorAccount.provider == "google_calendar",
                    ConnectorAccount.account_email == email,
                )
            )
            account = existing.scalar_one_or_none()
            if account is None:
                account = ConnectorAccount(
                    provider="google_calendar",
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
                provider="google_calendar",
                account_email=email,
                scopes_granted=creds_dict["scopes"],
                message=f"Google Calendar connected for {email}",
            )
        except Exception as exc:
            return OAuthCallbackResponse(
                ok=False, account_id=0, provider="google_calendar",
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
            if action == "calendar_list_events":
                return await self._list_events(service, params)
            elif action == "calendar_create_event":
                return await self._create_event(service, params)
            elif action == "calendar_delete_event":
                return await self._delete_event(service, params)
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
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    async def _list_events(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        import datetime as dt
        max_results = min(int(params.get("max_results", 10)), 50)
        calendar_id = params.get("calendar_id", "primary")
        time_min = params.get(
            "time_min",
            dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        )

        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = [
            CalendarEvent(
                id=e["id"],
                summary=e.get("summary", "(no title)"),
                description=e.get("description"),
                start=e["start"].get("dateTime", e["start"].get("date", "")),
                end=e["end"].get("dateTime", e["end"].get("date", "")),
                location=e.get("location"),
                html_link=e.get("htmlLink"),
            ).model_dump()
            for e in result.get("items", [])
        ]
        return CalendarListResult(events=events).model_dump()

    async def _create_event(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        summary = params.get("summary", "")
        start = params.get("start", "")
        end = params.get("end", "")
        if not summary or not start or not end:
            return {"error": "'summary', 'start', and 'end' fields are required"}

        calendar_id = params.get("calendar_id", "primary")
        body: Dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": params.get("timezone", "UTC")},
            "end": {"dateTime": end, "timeZone": params.get("timezone", "UTC")},
        }
        if params.get("description"):
            body["description"] = params["description"]
        if params.get("location"):
            body["location"] = params["location"]
        if params.get("attendees"):
            body["attendees"] = [
                {"email": a} for a in params["attendees"]
            ]

        created = service.events().insert(
            calendarId=calendar_id, body=body
        ).execute()

        return CalendarCreateResult(
            event_id=created["id"],
            html_link=created.get("htmlLink"),
            summary=created.get("summary", summary),
            start=created["start"].get("dateTime", start),
            end=created["end"].get("dateTime", end),
        ).model_dump()

    async def _delete_event(self, service, params: Dict[str, Any]) -> Dict[str, Any]:
        event_id = params.get("event_id", "")
        if not event_id:
            return {"error": "event_id is required"}
        calendar_id = params.get("calendar_id", "primary")
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"deleted": True, "event_id": event_id}


CONNECTOR_REGISTRY["google_calendar"] = GoogleCalendarConnector()
