"""
Rollback Executor – compensating action runner for failed tool executions.

When a tool fails and a rollback strategy exists (from IntentPreview or the
static _ROLLBACK catalogue), this module attempts to execute the compensation
action safely.

Design decisions
────────────────
1. Rollback actions are a *subset* of tool actions – they go through
   ``_guarded_rollback_run()`` which calls ``tool.run()`` directly but logs
   everything to audit.  We deliberately do NOT recurse into full
   ``guarded_execute()`` to avoid policy loops / double approval gates.

2. Only tools with a registered ``rollback_tool`` can be automatically rolled
   back.  Tools with free-text rollback strategies (e.g. "manual recovery")
   are logged but not executed.

3. Rollback execution is always logged in audit, eval, and the audit chain
   regardless of outcome.

4. Rollback of destructive / critical tools is skipped automatically (nothing
   to roll back that wouldn't cause further damage).

Public API
──────────
  attempt_rollback(tool_name, params, command, db, *, rollback_strategy)
      → RollbackResult
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class RollbackResult:
    """Outcome of a rollback / compensation attempt."""
    attempted: bool          # Was a rollback actually run (vs skipped)?
    status: str              # "rolled_back" | "rollback_failed" | "skipped" | "not_applicable" | "blocked_policy"
    rollback_tool: str = ""  # Tool used for rollback, if any
    detail: str = ""         # Human-readable explanation
    duration_ms: float = 0.0
    # Phase 4: chain context for auditability
    chain_id: Optional[str] = None       # Original execution chain_id
    original_action: str = ""            # Tool that was rolled back
    rollback_action: str = ""            # Tool used for rollback (mirrors rollback_tool)
    rollback_result_summary: str = ""    # Brief outcome phrase

    @property
    def succeeded(self) -> bool:
        return self.status == "rolled_back"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted": self.attempted,
            "status": self.status,
            "rollback_tool": self.rollback_tool,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 1),
            "chain_id": self.chain_id,
            "original_action": self.original_action,
            "rollback_action": self.rollback_action,
            "rollback_result_summary": self.rollback_result_summary,
        }


# ─── Rollback catalogue ───────────────────────────────────────────────────────
# Maps original tool name → (rollback_tool_name, param_transform_fn)
# param_transform_fn receives the original params and returns rollback params.

def _identity(params: Dict[str, Any]) -> Dict[str, Any]:
    return params


def _reverse_move(params: Dict[str, Any]) -> Dict[str, Any]:
    """Swap source and destination for move_file rollback."""
    return {
        "source": params.get("destination", ""),
        "destination": params.get("source", ""),
    }


# (rollback_tool, param_transform, description_template)
_ROLLBACK_CATALOGUE: Dict[str, tuple] = {
    "create_file": (
        "delete_file",
        lambda p: {"path": p.get("path", "")},
        "Delete the newly created file at {path}",
    ),
    "create_folder": (
        "delete_file",   # delete_file handles empty dirs on most systems
        lambda p: {"path": p.get("path", "")},
        "Delete the created folder at {path}",
    ),
    "move_file": (
        "move_file",
        _reverse_move,
        "Move file back from {destination} to {source}",
    ),
    "gmail_create_draft": (
        None,  # No automated rollback; API call needed to delete draft
        None,
        "Manually delete draft in Gmail (draft_id from result data)",
    ),
    "calendar_create_event": (
        None,
        None,
        "Manually delete calendar event.",
    ),
    "drive_upload_file": (
        None,
        None,
        "Manually delete uploaded file from Google Drive.",
    ),
}

# Tools that should NEVER be rolled back (destructive / irreversible categories)
_NO_ROLLBACK_RISK_LEVELS = frozenset({"critical"})

# Tools that explicitly have no rollback
_NO_ROLLBACK_TOOLS = frozenset({
    "gmail_send_email",
    "run_shell_command",
    "run_python",
    "run_javascript",
    "install_package",
    "empty_trash",
    "git_push",
    "git_commit",
    "github_create_pr",
    "web_search",
    "read_document",
    "summarize_document",
    "list_files",
    "search_files",
})


# ─── Public API ───────────────────────────────────────────────────────────────

async def attempt_rollback(
    tool_name: str,
    params: Dict[str, Any],
    command: str,
    db: Any,
    *,
    rollback_strategy: str = "",
    risk_level: str = "low",
    chain_id: Optional[str] = None,
) -> RollbackResult:
    """
    Attempt a compensating action for a failed tool execution.

    Parameters
    ----------
    tool_name          : Original (failed) tool name.
    params             : Parameters that were passed to the original tool.
    command            : Original user command string.
    db                 : AsyncSession for audit logging.
    rollback_strategy  : Human-readable rollback hint from IntentPreview.
    risk_level         : Risk level of the original tool.
    chain_id           : Audit chain ID of the original execution (Phase 4).

    Returns
    -------
    RollbackResult describing what happened.
    """
    _chain_ctx = chain_id

    # ── Gate 1: Skip critical-risk originals entirely ────────────────────────
    if risk_level in _NO_ROLLBACK_RISK_LEVELS:
        return RollbackResult(
            attempted=False,
            status="not_applicable",
            detail=f"No rollback for critical-risk tool '{tool_name}'.",
            chain_id=_chain_ctx,
            original_action=tool_name,
        )

    # ── Gate 2: Explicit no-rollback list ────────────────────────────────────
    if tool_name in _NO_ROLLBACK_TOOLS:
        detail = (
            rollback_strategy
            if rollback_strategy and rollback_strategy.lower() not in ("n/a", "")
            else f"No automatic rollback available for '{tool_name}'."
        )
        return RollbackResult(
            attempted=False,
            status="not_applicable",
            detail=detail,
            chain_id=_chain_ctx,
            original_action=tool_name,
        )

    # ── Gate 3: Check rollback catalogue ────────────────────────────────────
    catalogue_entry = _ROLLBACK_CATALOGUE.get(tool_name)
    if catalogue_entry is None:
        return RollbackResult(
            attempted=False,
            status="not_applicable",
            detail=f"No rollback catalogue entry for '{tool_name}'. "
                   + (f"Manual: {rollback_strategy}" if rollback_strategy else ""),
            chain_id=_chain_ctx,
            original_action=tool_name,
        )

    rollback_tool_name, param_transform, desc_template = catalogue_entry

    if rollback_tool_name is None or param_transform is None:
        # Manual-only rollback (annotated but not automated)
        await _log_rollback_skip(db, command, tool_name, desc_template, rollback_strategy)
        return RollbackResult(
            attempted=False,
            status="not_applicable",
            detail=f"Manual rollback required. {desc_template}",
            chain_id=_chain_ctx,
            original_action=tool_name,
        )

    # ── Gate 4: Minimal policy check for dangerous rollback tools ────────────
    # Allows safe reversals (create→delete) but blocks rollbacks that are
    # themselves high-risk and could cause further damage.
    policy_block = _rollback_policy_check(tool_name, rollback_tool_name)
    if policy_block:
        log.warning(
            "[rollback_executor] rollback blocked by policy: %s → %s: %s",
            tool_name, rollback_tool_name, policy_block,
        )
        await _safe_log(
            db, command, rollback_tool_name, "blocked",
            f"[ROLLBACK-BLOCKED] {policy_block}",
        )
        return RollbackResult(
            attempted=False,
            status="blocked_policy",
            rollback_tool=rollback_tool_name,
            detail=policy_block,
            chain_id=_chain_ctx,
            original_action=tool_name,
            rollback_action=rollback_tool_name,
        )

    # ── Execute rollback ─────────────────────────────────────────────────────
    rollback_params = param_transform(params)
    return await _execute_rollback(
        rollback_tool_name, rollback_params,
        original_tool=tool_name,
        command=command,
        db=db,
        desc_template=desc_template,
        chain_id=_chain_ctx,
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────

# Safe rollback pairs: original_tool → rollback_tool pairs that are permitted.
# Any pair NOT in this set (and whose rollback_tool is in the dangerous list)
# will be blocked.
_SAFE_ROLLBACK_PAIRS: frozenset = frozenset({
    ("create_file",   "delete_file"),
    ("create_folder", "delete_file"),
    ("move_file",     "move_file"),
})

# Rollback tools considered inherently dangerous (could cause further damage)
_DANGEROUS_ROLLBACK_TOOLS: frozenset = frozenset({
    "run_shell_command",
    "run_python",
    "run_javascript",
    "empty_trash",
    "git_push",
    "git_commit",
    "github_create_pr",
})


def _rollback_policy_check(original_tool: str, rollback_tool: str) -> Optional[str]:
    """
    Minimal policy check for rollback safety.

    Returns an error string if the rollback should be blocked, or None if allowed.

    Rules:
    1. If the rollback tool is dangerous and the pair is not in the safe list → block.
    2. Otherwise → allow.
    """
    if rollback_tool in _DANGEROUS_ROLLBACK_TOOLS:
        if (original_tool, rollback_tool) not in _SAFE_ROLLBACK_PAIRS:
            return (
                f"Rollback of '{original_tool}' via '{rollback_tool}' is blocked: "
                f"'{rollback_tool}' is a dangerous tool and this pair is not pre-approved."
            )
    return None


async def _execute_rollback(
    rollback_tool_name: str,
    rollback_params: Dict[str, Any],
    *,
    original_tool: str,
    command: str,
    db: Any,
    desc_template: str,
    chain_id: Optional[str] = None,
) -> RollbackResult:
    """Run the rollback tool directly (no policy loop) and log the outcome."""
    from app.tools.registry import get_tool

    rollback_tool = get_tool(rollback_tool_name)
    if rollback_tool is None:
        await _safe_log(db, command, rollback_tool_name, "error",
                        f"Rollback tool '{rollback_tool_name}' not found in registry.")
        return RollbackResult(
            attempted=True,
            status="rollback_failed",
            rollback_tool=rollback_tool_name,
            detail=f"Rollback tool '{rollback_tool_name}' not found.",
            chain_id=chain_id,
            original_action=original_tool,
            rollback_action=rollback_tool_name,
        )

    _t0 = _time.monotonic()
    try:
        rb_result = await rollback_tool.run(rollback_params)
        duration_ms = (_time.monotonic() - _t0) * 1000.0
        success = rb_result.status == "success"
        status = "rolled_back" if success else "rollback_failed"
        result_phrase = "ok" if success else "failed"
        detail = (
            f"Rollback of '{original_tool}' via '{rollback_tool_name}': "
            + (rb_result.message or result_phrase)
        )
        # Richer audit entry includes original_action + rollback_action
        audit_msg = (
            f"[ROLLBACK] original_action={original_tool} "
            f"rollback_action={rollback_tool_name} "
            f"chain_id={chain_id or 'n/a'} "
            f"result={result_phrase}"
        )
        await _safe_log(db, command, rollback_tool_name, rb_result.status, audit_msg)
        await _safe_eval_rollback(
            db, command, rollback_tool_name, status, duration_ms, original_tool,
            chain_id=chain_id,
        )
        log.info("[rollback_executor] %s for '%s': %s", status, original_tool, detail)
        return RollbackResult(
            attempted=True,
            status=status,
            rollback_tool=rollback_tool_name,
            detail=detail,
            duration_ms=duration_ms,
            chain_id=chain_id,
            original_action=original_tool,
            rollback_action=rollback_tool_name,
            rollback_result_summary=result_phrase,
        )
    except Exception as exc:
        duration_ms = (_time.monotonic() - _t0) * 1000.0
        log.warning("[rollback_executor] rollback tool raised: %s", exc)
        await _safe_log(db, command, rollback_tool_name, "error",
                        f"[ROLLBACK] exception: {exc}")
        return RollbackResult(
            attempted=True,
            status="rollback_failed",
            rollback_tool=rollback_tool_name,
            detail=f"Rollback raised exception: {exc}",
            duration_ms=duration_ms,
            chain_id=chain_id,
            original_action=original_tool,
            rollback_action=rollback_tool_name,
            rollback_result_summary="exception",
        )


async def _log_rollback_skip(
    db: Any, command: str, tool_name: str,
    desc_template: str, rollback_strategy: str,
) -> None:
    detail = f"[ROLLBACK-MANUAL] '{tool_name}': {desc_template}"
    if rollback_strategy:
        detail += f" | strategy hint: {rollback_strategy}"
    await _safe_log(db, command, tool_name, "rollback_manual", detail)


async def _safe_log(db: Any, command: str, tool_name: str, status: str, msg: str) -> None:
    try:
        from app.services.audit_service import record_action
        await record_action(db, command, tool_name, status, msg)
    except Exception as exc:
        log.warning("[rollback_executor] audit log failed: %s", exc)


async def _safe_eval_rollback(
    db: Any,
    command: str,
    rollback_tool: str,
    status: str,
    duration_ms: float,
    original_tool: str,
    *,
    chain_id: Optional[str] = None,
) -> None:
    try:
        from app.services.eval_service import record as eval_record
        await eval_record(
            db,
            command=command,
            tool_name=rollback_tool,
            status=status,
            duration_ms=duration_ms,
            context={
                "is_rollback": True,
                "original_tool": original_tool,
                "chain_id": chain_id,
            },
        )
    except Exception as exc:
        log.warning("[rollback_executor] eval log failed: %s", exc)
