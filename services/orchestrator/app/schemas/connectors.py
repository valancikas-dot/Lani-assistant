"""Pydantic schemas for the Account Connectors feature."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ─── Provider / capability literals ──────────────────────────────────────────

ConnectorProvider = Literal[
    "google_drive",
    "gmail",
    "google_calendar",
]

ConnectorActionName = Literal[
    "drive_list_files",
    "drive_search_files",
    "drive_get_file",
    "gmail_list_recent",
    "gmail_get_message",
    "gmail_create_draft",
    "gmail_send_email",
    "calendar_list_events",
    "calendar_create_event",
    "calendar_delete_event",
]

# ─── OAuth flow schemas ───────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    """Start an OAuth connection for a provider."""
    provider: ConnectorProvider
    # In a real Tauri app the frontend opens a browser window with this URL.
    # We return it so the UI can present it as a button / deep-link.
    redirect_uri: str = "http://localhost:8000/api/v1/connectors/oauth/callback"


class ConnectResponse(BaseModel):
    """Returned immediately when the user initiates OAuth."""
    ok: bool
    provider: ConnectorProvider
    auth_url: str
    state: str                      # CSRF token; must be echoed back in callback
    message: str


class OAuthCallbackRequest(BaseModel):
    """Body that the frontend POSTs after the OAuth redirect."""
    provider: ConnectorProvider
    code: str
    state: str
    redirect_uri: str = "http://localhost:8000/api/v1/connectors/oauth/callback"


class OAuthCallbackResponse(BaseModel):
    ok: bool
    account_id: int
    provider: ConnectorProvider
    account_email: str
    scopes_granted: List[str]
    message: str


# ─── Account info ─────────────────────────────────────────────────────────────

class ConnectorAccountOut(BaseModel):
    id: int
    provider: ConnectorProvider
    account_email: str
    display_name: str
    scopes_granted: List[str]
    is_active: bool
    connected_at: datetime.datetime
    last_used_at: Optional[datetime.datetime]
    last_error: str

    model_config = {"from_attributes": True}


class DisconnectRequest(BaseModel):
    account_id: int


class DisconnectResponse(BaseModel):
    ok: bool
    message: str


# ─── Capability manifest ──────────────────────────────────────────────────────

class CapabilityInfo(BaseModel):
    """One action a connector can perform."""
    name: ConnectorActionName
    description: str
    requires_approval: bool
    required_scopes: List[str]
    read_only: bool


class ConnectorManifest(BaseModel):
    """Full capability list for a provider."""
    provider: ConnectorProvider
    display_name: str
    icon: str
    capabilities: List[CapabilityInfo]
    auth_scopes: List[str]


# ─── Action request / response ────────────────────────────────────────────────

class ConnectorActionRequest(BaseModel):
    account_id: int
    action: ConnectorActionName
    params: Dict[str, Any] = Field(default_factory=dict)


class ConnectorActionResponse(BaseModel):
    ok: bool
    action: ConnectorActionName
    data: Any = None
    message: str
    requires_approval: bool = False
    approval_id: Optional[int] = None


# ─── Drive-specific result types ──────────────────────────────────────────────

class DriveFile(BaseModel):
    id: str
    name: str
    mime_type: str
    size: Optional[int]
    modified_at: Optional[str]
    web_view_link: Optional[str]


class DriveListResult(BaseModel):
    files: List[DriveFile]
    next_page_token: Optional[str]


# ─── Gmail-specific result types ─────────────────────────────────────────────

class GmailMessageSummary(BaseModel):
    id: str
    thread_id: str
    subject: str
    from_: str = Field(alias="from")
    date: str
    snippet: str

    model_config = {"populate_by_name": True}


class GmailListResult(BaseModel):
    messages: List[GmailMessageSummary]
    result_size_estimate: int


class GmailDraftResult(BaseModel):
    draft_id: str
    message_id: str


# ─── Calendar-specific result types ──────────────────────────────────────────

class CalendarEvent(BaseModel):
    id: str
    summary: str
    description: Optional[str]
    start: str      # ISO 8601
    end: str
    location: Optional[str]
    html_link: Optional[str]


class CalendarListResult(BaseModel):
    events: List[CalendarEvent]


class CalendarCreateResult(BaseModel):
    event_id: str
    html_link: Optional[str]
    summary: str
    start: str
    end: str
