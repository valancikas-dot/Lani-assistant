"""
Intent Preview – builds a structured preview of what Lani is *about to do*
before executing a risky action.

Usage::

    preview = build_intent_preview(
        command="delete all temp files",
        tool_name="delete_file",
        params={"path": "/tmp"},
        policy_decision=decision,
        cap_meta=cap_meta,
    )
    await save_intent_to_audit(db, preview, approval_id=42)

The resulting ``IntentPreview`` is serialisable to JSON and surfaced via the
approval queue / audit trail so users can see exactly what was planned.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IntentPreview:
    """Full intent snapshot captured before a risky action executes."""

    # Human intent
    user_intent: str
    selected_tool: str

    # Target resource (inferred from params)
    target: str

    # Identity context
    account: Optional[str]

    # Risk assessment
    risk_level: str                # low | medium | high | critical
    requires_approval: bool

    # What will happen
    expected_side_effects: List[str] = field(default_factory=list)

    # Audit helpers
    success_check: str = ""        # "File deleted" / "Email sent" etc.
    rollback_strategy: str = ""    # "Restore from trash" / "N/A" etc.

    # Policy snapshot (serialised PolicyDecision fields)
    policy_decision: Optional[Dict[str, Any]] = None

    # Timestamp
    created_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

# Side-effect catalogue: maps tool names → human-readable side-effect list
_SIDE_EFFECTS: Dict[str, List[str]] = {
    "delete_file": [
        "Permanently removes file from disk.",
        "Cannot be undone without a backup.",
    ],
    "move_file": ["Moves file to a new location; original path no longer valid."],
    "create_file": ["Creates a new file; overwrites if path already exists."],
    "create_folder": ["Creates directory tree."],
    "sort_downloads": ["Moves files within the Downloads folder into sub-folders."],
    "send_email": [
        "Delivers an email to external recipient(s).",
        "Cannot be recalled once sent.",
    ],
    "calendar_create_event": ["Adds a calendar entry visible to all invitees."],
    "calendar_delete_event": ["Removes the event for all invitees."],
    "drive_upload_file": ["Uploads file to Google Drive; uses quota."],
    "drive_delete_file": ["Deletes a Drive file (moved to Trash by default)."],
    "create_presentation": ["Creates a local PPTX/ODTP file on disk."],
    "create_project_scaffold": ["Writes multiple new files to disk."],
    "run_shell_command": [
        "Executes an arbitrary shell command.",
        "May modify filesystem, network, or processes.",
    ],
}

_SUCCESS_CHECKS: Dict[str, str] = {
    "delete_file": "File no longer present at the given path.",
    "move_file": "File present at destination path.",
    "create_file": "File present and readable at the given path.",
    "send_email": "Email appears in Sent folder.",
    "calendar_create_event": "Event visible in calendar for the target date.",
    "drive_upload_file": "File listed in Drive with matching name/size.",
    "run_shell_command": "Command exits with code 0.",
}

_ROLLBACK: Dict[str, str] = {
    "delete_file": "Restore from system Trash or most-recent backup.",
    "move_file": "Move file back to original path.",
    "create_file": "Delete the newly created file.",
    "send_email": "N/A – email cannot be unsent.",
    "calendar_create_event": "Delete the calendar event.",
    "drive_upload_file": "Delete the uploaded file from Drive.",
    "run_shell_command": "Depends on what the command did – manual recovery required.",
}


def build_intent_preview(
    command: str,
    tool_name: str,
    params: Dict[str, Any],
    policy_decision: Any,           # PolicyDecision or None
    cap_meta: Optional[Dict[str, Any]] = None,
    account: Optional[str] = None,
) -> IntentPreview:
    """
    Construct an ``IntentPreview`` from the pieces available at dispatch time.

    Args:
        command:         The raw user command string.
        tool_name:       The resolved tool name.
        params:          Resolved tool parameters.
        policy_decision: The ``PolicyDecision`` returned by the policy engine,
                         or ``None`` if policy was not evaluated.
        cap_meta:        The ``CapabilityMeta`` dict from the registry, or
                         ``None`` if the tool is not in the registry.
        account:         The active account identifier, if any.
    """
    # Infer target from common param keys
    target = (
        params.get("path")
        or params.get("url")
        or params.get("to")
        or params.get("email")
        or params.get("query")
        or params.get("name")
        or "(unknown)"
    )
    if isinstance(target, list):
        target = ", ".join(str(t) for t in target[:3])

    # Risk level from capability meta or policy
    risk_level = "low"
    if cap_meta:
        risk_level = cap_meta.get("risk_level", "low")
    if policy_decision is not None:
        pd_risk = getattr(policy_decision, "risk_level", None)
        if pd_risk:
            risk_level = pd_risk

    requires_approval = False
    if policy_decision is not None:
        requires_approval = bool(
            getattr(policy_decision, "needs_approval", False)
            or getattr(policy_decision, "denied", False)
        )

    # Serialise policy decision
    pd_dict: Optional[Dict[str, Any]] = None
    if policy_decision is not None:
        try:
            pd_dict = {
                "verdict": getattr(policy_decision, "verdict", None),
                "action": getattr(policy_decision, "action", None),
                "reason": getattr(policy_decision, "reason", None),
                "risk_level": getattr(policy_decision, "risk_level", None),
            }
        except Exception:
            pd_dict = None

    return IntentPreview(
        user_intent=command,
        selected_tool=tool_name,
        target=str(target),
        account=account,
        risk_level=risk_level,
        requires_approval=requires_approval,
        expected_side_effects=_SIDE_EFFECTS.get(tool_name, []),
        success_check=_SUCCESS_CHECKS.get(tool_name, ""),
        rollback_strategy=_ROLLBACK.get(tool_name, "N/A"),
        policy_decision=pd_dict,
    )


# ---------------------------------------------------------------------------
# Audit persistence
# ---------------------------------------------------------------------------

async def save_intent_to_audit(
    db: Any,       # AsyncSession
    preview: IntentPreview,
    *,
    approval_id: Optional[int] = None,
) -> None:
    """
    Persist the intent preview to the audit log so it appears in the
    approval queue and the Logs page.
    """
    try:
        from app.services.audit_service import record_action

        extra = f" (approval #{approval_id})" if approval_id else ""
        summary = (
            f"[INTENT] tool={preview.selected_tool} "
            f"target={preview.target!r} "
            f"risk={preview.risk_level} "
            f"approval_required={preview.requires_approval}"
            f"{extra}"
        )
        await record_action(
            db,
            preview.user_intent,
            preview.selected_tool,
            "intent_preview",
            summary,
        )
    except Exception as exc:
        log.warning("save_intent_to_audit failed (non-fatal): %s", exc)
