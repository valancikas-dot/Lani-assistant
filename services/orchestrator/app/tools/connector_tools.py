"""Connector tool wrappers.

These thin BaseTool subclasses allow the command router and task planner to
invoke connector actions through the same interface as all other tools.

They do NOT execute the connector action directly – they delegate to the
connector's ``execute_action`` method via an async DB session obtained from
``AsyncSessionLocal``.

Approval is handled at the router level (``/connectors/{id}/action``), but
``requires_approval`` is also set here so the planner can reflect that in
execution plans.
"""

from __future__ import annotations

from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool


class _ConnectorTool(BaseTool):
    """Internal base for all connector-backed tools."""

    #: The ``ConnectorProvider`` string – must match CONNECTOR_REGISTRY key.
    _provider: str = ""

    #: The action name passed to ``execute_action``.
    _action: str = ""

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        """Execute via connector.  Requires ``account_id`` in params."""
        from app.core.database import AsyncSessionLocal
        from app.services.connectors.base import get_connector

        account_id = params.get("account_id")
        if not account_id:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="account_id is required in params",
            )

        connector = get_connector(self._provider)
        if connector is None:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=f"Provider '{self._provider}' is not registered",
            )

        async with AsyncSessionLocal() as db:
            try:
                data = await connector.execute_action(
                    db=db,
                    account_id=int(account_id),
                    action=self._action,
                    params=params,
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                return ToolResult(
                    tool_name=self.name,
                    status="error",
                    message=str(exc),
                )

        has_error = isinstance(data, dict) and "error" in data
        return ToolResult(
            tool_name=self.name,
            status="error" if has_error else "success",
            data=data if not has_error else None,
            message=data.get("error", "") if has_error else None,
        )


# ─── Google Drive tools ───────────────────────────────────────────────────────

class DriveListFilesTool(_ConnectorTool):
    name = "drive_list_files"
    description = "List files in the connected Google Drive account"
    requires_approval = False
    _provider = "google_drive"
    _action = "drive_list_files"


class DriveSearchFilesTool(_ConnectorTool):
    name = "drive_search_files"
    description = "Search for files in Google Drive by name"
    requires_approval = False
    _provider = "google_drive"
    _action = "drive_search_files"


class DriveGetFileTool(_ConnectorTool):
    name = "drive_get_file"
    description = "Get metadata for a specific Google Drive file by ID"
    requires_approval = False
    _provider = "google_drive"
    _action = "drive_get_file"


# ─── Gmail tools ─────────────────────────────────────────────────────────────

class GmailListRecentTool(_ConnectorTool):
    name = "gmail_list_recent"
    description = "List recent messages in the connected Gmail inbox"
    requires_approval = False
    _provider = "gmail"
    _action = "gmail_list_recent"


class GmailGetMessageTool(_ConnectorTool):
    name = "gmail_get_message"
    description = "Get the full content of a Gmail message by ID"
    requires_approval = False
    _provider = "gmail"
    _action = "gmail_get_message"


class GmailCreateDraftTool(_ConnectorTool):
    name = "gmail_create_draft"
    description = "Create a Gmail draft (requires approval)"
    requires_approval = True
    _provider = "gmail"
    _action = "gmail_create_draft"


class GmailSendEmailTool(_ConnectorTool):
    name = "gmail_send_email"
    description = "Send an email from the connected Gmail account (requires approval)"
    requires_approval = True
    _provider = "gmail"
    _action = "gmail_send_email"


# ─── Google Calendar tools ────────────────────────────────────────────────────

class CalendarListEventsTool(_ConnectorTool):
    name = "calendar_list_events"
    description = "List upcoming events in the connected Google Calendar"
    requires_approval = False
    _provider = "google_calendar"
    _action = "calendar_list_events"


class CalendarCreateEventTool(_ConnectorTool):
    name = "calendar_create_event"
    description = "Create a new Google Calendar event (requires approval)"
    requires_approval = True
    _provider = "google_calendar"
    _action = "calendar_create_event"


class CalendarDeleteEventTool(_ConnectorTool):
    name = "calendar_delete_event"
    description = "Delete a Google Calendar event (requires approval)"
    requires_approval = True
    _provider = "google_calendar"
    _action = "calendar_delete_event"
