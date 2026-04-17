"""Connectors route – manage OAuth-connected accounts and run connector actions.

Endpoints
─────────
  GET  /connectors                              list all connected accounts
  GET  /connectors/capabilities                 list all provider manifests
  GET  /connectors/oauth/init                   build OAuth consent URL
  POST /connectors/oauth/callback               exchange auth code → save account
  DELETE /connectors/{account_id}               disconnect account + purge tokens
  POST /connectors/{account_id}/action          run a connector action

Approval gate
─────────────
Actions with ``requires_approval=True`` (gmail_send_email, gmail_create_draft,
calendar_create_event, calendar_update_event, calendar_delete_event) are
routed through the existing approval service instead of being executed directly.
The response will contain ``requires_approval=True`` and ``approval_id=<id>``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.connector_account import ConnectorAccount
from app.schemas.connectors import (
    ConnectorAccountOut,
    ConnectorActionRequest,
    ConnectorActionResponse,
    ConnectorManifest,
    ConnectResponse,
    DisconnectResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
)
from app.services.connectors.base import (
    ConnectorBase,
    get_connector,
    list_manifests,
)
from app.services.audit_service import record_action

router = APIRouter()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _account_out(account: ConnectorAccount) -> ConnectorAccountOut:
    return ConnectorAccountOut(
        id=account.id,
        provider=account.provider,  # type: ignore[arg-type]
        account_email=account.account_email,
        display_name=account.display_name,
        scopes_granted=[s for s in account.scopes_granted.split(",") if s],
        is_active=account.is_active,
        connected_at=account.connected_at,
        last_used_at=account.last_used_at,
        last_error=account.last_error,
    )


def _get_connector_or_404(provider: str) -> ConnectorBase:
    connector = get_connector(provider)
    if connector is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' is not supported. "
                   f"Supported providers: google_drive, gmail, google_calendar",
        )
    return connector


# ─── Account list ─────────────────────────────────────────────────────────────

@router.get("/connectors", response_model=List[ConnectorAccountOut])
async def list_connectors(
    db: AsyncSession = Depends(get_db),
) -> List[ConnectorAccountOut]:
    """Return all connected accounts (active and inactive)."""
    result = await db.execute(
        select(ConnectorAccount).order_by(ConnectorAccount.id)
    )
    accounts = result.scalars().all()
    return [_account_out(a) for a in accounts]


# ─── Provider capabilities ────────────────────────────────────────────────────

@router.get("/connectors/capabilities", response_model=List[ConnectorManifest])
async def get_capabilities() -> List[ConnectorManifest]:
    """Return the capability manifest for every registered provider."""
    return list_manifests()


# ─── OAuth initiation ─────────────────────────────────────────────────────────

@router.get("/connectors/oauth/init", response_model=ConnectResponse)
async def oauth_init(
    provider: str = Query(..., description="Provider key, e.g. 'google_drive'"),
    redirect_uri: str = Query(
        default="http://127.0.0.1:8000/api/v1/connectors/oauth/callback",
        description="Must match the redirect URI registered with the OAuth provider",
    ),
) -> ConnectResponse:
    """Build and return the OAuth consent-screen URL for the given provider.

    The frontend should open this URL in a browser (or system webview) and
    capture the ``code`` + ``state`` params from the redirect to pass to
    ``/connectors/oauth/callback``.
    """
    connector = _get_connector_or_404(provider)
    state = ConnectorBase.new_state()
    auth_url = connector.build_auth_url(state=state, redirect_uri=redirect_uri)
    return ConnectResponse(
        ok=True,
        provider=provider,  # type: ignore[arg-type]
        auth_url=auth_url,
        state=state,
        message=f"Visit auth_url to connect your {connector.display_name} account.",
    )


# ─── OAuth callback ───────────────────────────────────────────────────────────

@router.post("/connectors/oauth/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(
    body: OAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
) -> OAuthCallbackResponse:
    """Exchange an OAuth authorisation code for tokens and persist the account.

    The frontend calls this after extracting ``code`` and ``state`` from the
    OAuth redirect URL.  A CSRF check on ``state`` should be added here once
    session storage is available; for now the state is a random nonce.
    """
    connector = _get_connector_or_404(body.provider)
    response = await connector.exchange_code(
        db=db,
        code=body.code,
        state=body.state,
        redirect_uri=body.redirect_uri,
    )
    if response.ok:
        await record_action(
            db=db,
            command=f"connect_account:{body.provider}",
            tool_name="connector_oauth",
            status="success",
            result_summary=f"Connected {body.provider} account {response.account_email}",
        )
    return response


# ─── Disconnect ───────────────────────────────────────────────────────────────

@router.delete("/connectors/{account_id}", response_model=DisconnectResponse)
async def disconnect(
    account_id: int,
    db: AsyncSession = Depends(get_db),
) -> DisconnectResponse:
    """Disconnect an account – deletes all encrypted tokens and marks it inactive."""
    result = await db.execute(
        select(ConnectorAccount).where(ConnectorAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account #{account_id} not found.")

    connector = _get_connector_or_404(account.provider)
    await connector.disconnect(db=db, account_id=account_id)

    await record_action(
        db=db,
        command=f"disconnect_account:{account.provider}",
        tool_name="connector_oauth",
        status="success",
        result_summary=(
            f"Disconnected {account.provider} account {account.account_email}"
        ),
    )
    return DisconnectResponse(ok=True, message=f"Account #{account_id} disconnected.")


# ─── Run action ───────────────────────────────────────────────────────────────

@router.post(
    "/connectors/{account_id}/action",
    response_model=ConnectorActionResponse,
)
async def run_action(
    account_id: int,
    body: ConnectorActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ConnectorActionResponse:
    """Execute a named connector action.

    * Read-only actions run immediately and return their result.
    * Actions that require approval are submitted to the approval queue and
      the response includes ``requires_approval=True`` and ``approval_id``.
    """
    result = await db.execute(
        select(ConnectorAccount).where(
            ConnectorAccount.id == account_id,
            ConnectorAccount.is_active == True,  # noqa: E712
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=404,
            detail=f"Active connected account #{account_id} not found.",
        )

    connector = _get_connector_or_404(account.provider)

    # Check if this action requires approval
    manifest = connector.manifest
    capability = next(
        (c for c in manifest.capabilities if c.name == body.action), None
    )
    if capability is None:
        raise HTTPException(
            status_code=400,
            detail=f"Action '{body.action}' is not supported by provider '{account.provider}'.",
        )

    if capability.requires_approval:
        # Queue an approval request instead of running directly
        from app.services.approval_service import create_approval_request

        approval_id = await create_approval_request(
            db=db,
            command=body.action,
            tool_name=f"connector:{account.provider}",
            params=body.params,
        )
        await record_action(
            db=db,
            command=body.action,
            tool_name=f"connector:{account.provider}",
            status="pending_approval",
            result_summary=f"Queued approval #{approval_id} for {body.action}",
        )
        return ConnectorActionResponse(
            ok=True,
            action=body.action,
            data=None,
            message=(
                f"Action '{body.action}' requires approval. "
                f"Approval #{approval_id} has been queued."
            ),
            requires_approval=True,
            approval_id=approval_id,
        )

    # Execute read-only / pre-approved action directly
    try:
        data = await connector.execute_action(
            db=db,
            account_id=account_id,
            action=body.action,
            params=body.params,
        )
    except Exception as exc:
        await record_action(
            db=db,
            command=body.action,
            tool_name=f"connector:{account.provider}",
            status="error",
            result_summary="",
            error_message=str(exc)[:500],
        )
        raise HTTPException(status_code=500, detail=str(exc))

    has_error = isinstance(data, dict) and "error" in data
    await record_action(
        db=db,
        command=body.action,
        tool_name=f"connector:{account.provider}",
        status="error" if has_error else "success",
        result_summary="" if has_error else f"Ran {body.action} on {account.provider}",
        error_message=data.get("error", "") if has_error else "",
    )

    return ConnectorActionResponse(
        ok=not has_error,
        action=body.action,
        data=data,
        message=data.get("error", "OK") if has_error else "OK",
        requires_approval=False,
        approval_id=None,
    )
