"""
Execution Guard – single, universal enforcement point for all tool actions.

Every execution path (command_router, plan_executor, workflow_executor) must
call ``guarded_execute()`` instead of calling ``tool.run()`` directly.

The guard enforces, in order:
  1. Capability registry lookup
  2. Policy evaluation
  3. Intent preview creation
  4. Approval routing  (if policy denies or requires approval)
  5. Retry orchestration (based on capability retry_policy)
  6. Timed tool execution
  7. Success verification
  8. Rollback / compensation on failure (if applicable)
  9. Post-action world-state delta update
 10. Eval recording  (includes verification + retry metadata)
 11. Audit chain save

Returns a structured ``GuardResult`` with a rich ``outcome`` field so callers
can distinguish between all meaningful execution categories.

Outcome categories
──────────────────
  blocked              – policy hard-denied
  approval_required    – waiting for user approval
  executed_unverified  – tool ran, verification inconclusive
  executed_verified    – tool ran and verified success
  failed_retryable     – failed but retries remain (guard internally retried)
  failed_nonretryable  – failed and no retries possible
  rolled_back          – failed and rollback succeeded
  rollback_failed      – failed and rollback also failed

Usage::

    guard_result = await guarded_execute(
        tool_name="delete_file",
        params={"path": "~/Desktop/test.txt"},
        command="delete test file",
        db=db,
        settings_row=settings_row,
    )

    if guard_result.needs_approval:
        return approval_response(guard_result.approval_id)
    if guard_result.blocked:
        return error_response(guard_result.block_reason)
    # check outcome for verification details
    return ok_response(guard_result.tool_result)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import secrets
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Outcome constants ────────────────────────────────────────────────────────

OUTCOME_BLOCKED              = "blocked"
OUTCOME_APPROVAL_REQUIRED    = "approval_required"
OUTCOME_EXECUTED_UNVERIFIED  = "executed_unverified"
OUTCOME_EXECUTED_VERIFIED    = "executed_verified"
OUTCOME_FAILED_RETRYABLE     = "failed_retryable"
OUTCOME_FAILED_NONRETRYABLE  = "failed_nonretryable"
OUTCOME_ROLLED_BACK          = "rolled_back"
OUTCOME_ROLLBACK_FAILED      = "rollback_failed"


# ─── Failure reason constants (Phase 4) ──────────────────────────────────────

FAILURE_NETWORK_ERROR        = "network_error"
FAILURE_PERMISSION_ERROR     = "permission_error"
FAILURE_ELEMENT_NOT_FOUND    = "element_not_found"
FAILURE_TIMEOUT              = "timeout"
FAILURE_UNKNOWN_STATE        = "unknown_state"
FAILURE_VERIFICATION_MISMATCH = "verification_mismatch"
FAILURE_NONE                 = None  # no failure


# ─── Failure classifier ───────────────────────────────────────────────────────

def classify_failure(tool_result: Any, verification_verdict: Optional[str] = None) -> Optional[str]:
    """
    Classify the failure reason from a tool result.

    Returns one of the FAILURE_* constants, or None if not a failure.
    """
    if tool_result is None:
        return FAILURE_UNKNOWN_STATE
    status = getattr(tool_result, "status", None)
    message = (getattr(tool_result, "message", None) or "").lower()
    data = getattr(tool_result, "data", None) or {}

    if status == "success":
        # Tool succeeded but verification disagreed
        if verification_verdict == "failed":
            return FAILURE_VERIFICATION_MISMATCH
        return None

    # Infer from message / data content
    if any(kw in message for kw in ("timeout", "timed out", "deadline")):
        return FAILURE_TIMEOUT
    if any(kw in message for kw in ("permission", "forbidden", "access denied", "unauthorized", "403")):
        return FAILURE_PERMISSION_ERROR
    if any(kw in message for kw in ("network", "connection", "unreachable", "dns", "socket", "502", "503")):
        return FAILURE_NETWORK_ERROR
    if any(kw in message for kw in ("not found", "element not found", "no such element", "404")):
        return FAILURE_ELEMENT_NOT_FOUND
    if verification_verdict == "failed":
        return FAILURE_VERIFICATION_MISMATCH
    # Check error key in data
    if isinstance(data, dict) and "error" in data:
        err = str(data["error"]).lower()
        if "timeout" in err:
            return FAILURE_TIMEOUT
        if "permission" in err or "forbidden" in err:
            return FAILURE_PERMISSION_ERROR
        if "network" in err or "connection" in err:
            return FAILURE_NETWORK_ERROR
    return FAILURE_UNKNOWN_STATE


# ─── Checkpoint data model (Phase 4) ─────────────────────────────────────────

@dataclass
class ExecutionCheckpoint:
    """
    A snapshot captured at one point in the execution chain.

    Stored in ``GuardResult.checkpoints`` so callers and the replay service
    can reconstruct what happened step by step.
    """
    checkpoint_id: str = field(default_factory=lambda: secrets.token_hex(8))
    action: str = ""                    # tool name
    inputs: Dict[str, Any] = field(default_factory=dict)
    result_status: str = ""             # "success" | "error" | "pending"
    result_summary: str = ""
    verification_verdict: Optional[str] = None
    state_delta_summary: str = ""
    failure_reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "action": self.action,
            "inputs": self.inputs,
            "result_status": self.result_status,
            "result_summary": self.result_summary,
            "verification_verdict": self.verification_verdict,
            "state_delta_summary": self.state_delta_summary,
            "failure_reason": self.failure_reason,
            "timestamp": self.timestamp,
        }


# ─── Return type ──────────────────────────────────────────────────────────────

@dataclass
class GuardResult:
    """Structured outcome of a guarded tool execution."""

    # Core status (legacy field kept for backward compat)
    status: str  # "executed" | "approval_required" | "denied" | "error"

    # Rich outcome category (Phase 3)
    outcome: str = OUTCOME_EXECUTED_UNVERIFIED

    # Tool output (None if not executed)
    tool_result: Any = None

    # Approval info
    approval_id: Optional[int] = None

    # Policy info
    policy_verdict: str = "allow"
    policy_reason: str = ""
    risk_level: str = "low"

    # Capability metadata (dict snapshot)
    cap_meta: Optional[Dict[str, Any]] = None

    # Timing
    duration_ms: float = 0.0

    # Audit chain id (if persisted)
    audit_chain_id: Optional[str] = None

    # Verification result (Phase 3)
    verification: Optional[Dict[str, Any]] = None

    # Retry metadata (Phase 3)
    retries_attempted: int = 0

    # Rollback result (Phase 3)
    rollback: Optional[Dict[str, Any]] = None

    # Execution checkpoints (Phase 4) – one per action step / retry
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)

    # Failure reason classification (Phase 4)
    failure_reason: Optional[str] = None

    # Session context (Phase 4)
    session_id: Optional[str] = None

    # Convenience flags
    @property
    def executed(self) -> bool:
        return self.status == "executed"

    @property
    def needs_approval(self) -> bool:
        return self.status == "approval_required"

    @property
    def blocked(self) -> bool:
        return self.status == "denied"

    @property
    def block_reason(self) -> str:
        return self.policy_reason

    @property
    def verified_success(self) -> bool:
        return self.outcome == OUTCOME_EXECUTED_VERIFIED

    @property
    def was_rolled_back(self) -> bool:
        return self.outcome == OUTCOME_ROLLED_BACK



# ─── Central guard ────────────────────────────────────────────────────────────

async def guarded_execute(
    tool_name: str,
    params: Dict[str, Any],
    command: str,
    db: Any,  # AsyncSession
    *,
    settings_row: Any = None,
    execution_context: Optional[Dict[str, Any]] = None,
    caller: str = "unknown",   # "router" | "plan" | "workflow"
    session_id: Optional[str] = None,  # Phase 4: browser/operator session context
) -> GuardResult:
    """
    Universal guarded execution entrypoint.

    Parameters
    ----------
    tool_name         : Registered tool name.
    params            : Resolved parameters to pass to the tool.
    command           : Original user command (for audit / eval).
    db                : AsyncSession – required for approval + eval + audit.
    settings_row      : UserSettings ORM row (used to build policy context).
    execution_context : Optional dict stored on the approval record for resume.
                        Shape: {"plan": ..., "start_from_step": int, "executor_type": str}
    caller            : Label identifying which execution path called the guard.
    """
    from app.services.capability_registry import get_capability
    from app.services.policy_engine import evaluate as policy_evaluate, build_context_from_settings
    from app.services.session_manager import list_active_account_types, validate_session_context
    from app.services.world_state import record_tool_execution
    from app.services.eval_service import record as eval_record
    from app.services.approval_service import create_approval_request
    from app.services.intent_preview import build_intent_preview, save_intent_to_audit, _ROLLBACK
    from app.services.audit_chain import record_audit_chain
    from app.services.state_delta import capture_before, capture_after, build_delta
    from app.tools.registry import get_tool
    from app.services.audit_service import record_action
    from app.services.success_verifier import verify as verify_success
    from app.services.rollback_executor import attempt_rollback

    # ── 1. Capability lookup ─────────────────────────────────────────────────
    cap_meta_obj = get_capability(tool_name)
    cap_meta_dict: Optional[Dict[str, Any]] = (
        cap_meta_obj.__dict__ if cap_meta_obj is not None else None
    )
    risk_level: str = cap_meta_obj.risk_level if cap_meta_obj else "medium"

    # Extract retry policy
    retry_policy = cap_meta_obj.retry_policy if cap_meta_obj is not None else None
    max_retries: int = getattr(retry_policy, "max_retries", 0) if retry_policy else 0
    backoff_seconds: float = getattr(retry_policy, "backoff_seconds", 1.0) if retry_policy else 1.0

    # Destructive / critical tools must NEVER be automatically retried
    if risk_level in ("critical", "high") or max_retries > 3:
        max_retries = 0

    # ── 2. Tool lookup ───────────────────────────────────────────────────────
    tool = get_tool(tool_name)
    if tool is None:
        log.warning("[guard] Unknown tool '%s' requested by %s", tool_name, caller)
        return GuardResult(
            status="error",
            outcome=OUTCOME_FAILED_NONRETRYABLE,
            policy_verdict="error",
            policy_reason=f"Tool '{tool_name}' not found in registry.",
            risk_level=risk_level,
            cap_meta=cap_meta_dict,
            session_id=session_id,
        )

    # ── 2b. Session isolation enforcement (Phase 4) ──────────────────────────
    session_error = validate_session_context(tool_name, session_id)
    if session_error:
        log.info("[guard] Session required for '%s': %s", tool_name, session_error)
        await _safe_record_action(db, command, tool_name, "denied", f"[session] {session_error}")
        return GuardResult(
            status="denied",
            outcome=OUTCOME_BLOCKED,
            policy_verdict="deny",
            policy_reason=session_error,
            risk_level=risk_level,
            cap_meta=cap_meta_dict,
            session_id=session_id,
        )

    # ── 3. Policy evaluation ─────────────────────────────────────────────────
    policy_decision = None
    policy_verdict = "allow"
    policy_reason = ""
    try:
        active_accounts = list_active_account_types()
        policy_ctx = build_context_from_settings(settings_row, active_accounts)
        policy_decision = policy_evaluate(tool_name, params, policy_ctx)
        policy_verdict = policy_decision.verdict
        policy_reason = policy_decision.reason or ""
        risk_level = policy_decision.risk_level or risk_level
    except Exception as _pe:
        log.warning("[guard] Policy evaluation failed (non-fatal): %s", _pe)

    # ── 4. Blocked by policy ─────────────────────────────────────────────────
    if policy_decision is not None and policy_decision.denied:
        await _safe_record_action(db, command, tool_name, "denied", f"Policy blocked: {policy_reason}")
        await _safe_eval(db, command, tool_name, "denied", 0.0, risk_level, "denied",
                         retries=0, verification_verdict=None)
        return GuardResult(
            status="denied",
            outcome=OUTCOME_BLOCKED,
            policy_verdict="deny",
            policy_reason=policy_reason,
            risk_level=risk_level,
            cap_meta=cap_meta_dict,
        )

    # ── 5. Approval gate ─────────────────────────────────────────────────────
    needs_approval = tool.requires_approval or (
        policy_decision is not None and policy_decision.needs_approval
    )
    if needs_approval:
        preview = build_intent_preview(command, tool_name, params, policy_decision, cap_meta_dict)
        approval_id = await create_approval_request(
            db,
            tool_name=tool_name,
            command=command,
            params=params,
            execution_context=execution_context,
        )
        await save_intent_to_audit(db, preview, approval_id=approval_id)
        await _safe_record_action(
            db, command, tool_name, "approval_required",
            f"[{caller}] approval #{approval_id} created"
        )
        await _safe_audit_chain(
            db, command, tool_name, cap_meta_dict, policy_decision,
            "approval_required", None, None, None, approval_id
        )
        return GuardResult(
            status="approval_required",
            outcome=OUTCOME_APPROVAL_REQUIRED,
            approval_id=approval_id,
            policy_verdict=policy_verdict,
            policy_reason=policy_reason,
            risk_level=risk_level,
            cap_meta=cap_meta_dict,
        )

    # ── 6. Intent preview rollback strategy (for use on failure) ────────────
    rollback_strategy: str = _ROLLBACK.get(tool_name, "N/A")

    # chain_id will be set in step 13; pre-declare so rollback can reference it
    chain_id: Optional[str] = None

    # ── 7. Capture pre-execution state snapshot ──────────────────────────────
    state_before = capture_before()

    # ── 8. Execute with retry orchestration ─────────────────────────────────
    from types import SimpleNamespace
    _sentinel = SimpleNamespace(status="error", message="tool never ran", data=None)
    tool_result: Any = _sentinel
    retries_attempted = 0
    _total_duration_ms = 0.0

    for attempt in range(max_retries + 1):
        if attempt > 0:
            log.info("[guard] Retrying '%s' (attempt %d/%d) after %.1fs backoff",
                     tool_name, attempt + 1, max_retries + 1, backoff_seconds)
            await _safe_record_action(
                db, command, tool_name, "retry",
                f"[{caller}] retry attempt {attempt}/{max_retries}",
            )
            await asyncio.sleep(backoff_seconds)
            retries_attempted += 1

        _t0 = _time.monotonic()
        try:
            tool_result = await tool.run(params)
        except Exception as exc:
            log.warning("[guard] tool.run() raised on attempt %d: %s", attempt + 1, exc)
            # Synthesise a failed ToolResult-like object
            tool_result = SimpleNamespace(
                status="error",
                message=str(exc),
                data=None,
            )
        _total_duration_ms += (_time.monotonic() - _t0) * 1000.0

        if tool_result.status == "success":
            break   # no need to retry

        if attempt < max_retries:
            log.info("[guard] '%s' failed on attempt %d, will retry.", tool_name, attempt + 1)
        # else: exhausted retries, fall through

    duration_ms = _total_duration_ms
    exec_status = tool_result.status  # "success" | "error"

    # ── 9. World state delta ─────────────────────────────────────────────────

    delta = None
    try:
        record_tool_execution(
            tool=tool_name,
            status=exec_status,
            summary=(tool_result.message or "")[:200],
            duration_ms=duration_ms,
        )
        state_after = capture_after()
        delta = build_delta(
            before=state_before,
            after=state_after,
            triggering_action=tool_name,
            command=command,
        )
    except Exception as _wse:
        log.warning("[guard] World state update failed (non-fatal): %s", _wse)

    # ── 10. Success verification ─────────────────────────────────────────────
    verification_result = await verify_success(
        tool_name=tool_name,
        params=params,
        tool_result=tool_result,
    )
    verification_dict = verification_result.to_dict()

    # ── 10b. Failure classification (Phase 4) ─────────────────────────────────
    failure_reason_val: Optional[str] = classify_failure(
        tool_result,
        verification_verdict=verification_result.verdict if exec_status != "success" else None,
    )

    # ── 10c. Execution checkpoint (Phase 4) ───────────────────────────────────
    checkpoints: List[Dict[str, Any]] = []
    _checkpoint = ExecutionCheckpoint(
        action=tool_name,
        inputs=params,
        result_status=exec_status,
        result_summary=(getattr(tool_result, "message", None) or "")[:300],
        verification_verdict=verification_result.verdict,
        state_delta_summary=(
            ", ".join(delta.changed_fields) if delta and hasattr(delta, "changed_fields") else ""
        ),
        failure_reason=failure_reason_val if exec_status != "success" else None,
    )
    checkpoints.append(_checkpoint.to_dict())

    # ── 11. Determine outcome ─────────────────────────────────────────────────
    rollback_result = None

    if exec_status == "success" or verification_result.is_positive:
        if verification_result.verdict == "success":
            outcome = OUTCOME_EXECUTED_VERIFIED
        else:
            # likely_success or uncertain with positive tool result
            outcome = OUTCOME_EXECUTED_UNVERIFIED
        final_status = "executed"

    else:
        # Tool failed.  Decide between retryable / nonretryable / rollback.
        retries_remain = retries_attempted < max_retries
        if retries_remain:
            outcome = OUTCOME_FAILED_RETRYABLE
        else:
            # Attempt rollback
            rollback_result = await attempt_rollback(
                tool_name=tool_name,
                params=params,
                command=command,
                db=db,
                rollback_strategy=rollback_strategy,
                risk_level=risk_level,
                chain_id=chain_id,
            )
            if rollback_result.succeeded:
                outcome = OUTCOME_ROLLED_BACK
            elif rollback_result.attempted:
                outcome = OUTCOME_ROLLBACK_FAILED
            else:
                outcome = OUTCOME_FAILED_NONRETRYABLE
        final_status = "executed"  # tool ran (even if it failed)

    # ── 12. Eval + audit ─────────────────────────────────────────────────────
    eval_status = "success" if exec_status == "success" else "error"
    await _safe_record_action(db, command, tool_name, exec_status, tool_result.message or "")
    await _safe_eval(
        db, command, tool_name, eval_status, duration_ms, risk_level, policy_verdict,
        error_message=tool_result.message if exec_status != "success" else None,
        retries=retries_attempted,
        verification_verdict=verification_result.verdict,
        failure_reason=failure_reason_val,
    )

    # ── 13. Audit chain ───────────────────────────────────────────────────────
    chain_id = await _safe_audit_chain(
        db, command, tool_name, cap_meta_dict, policy_decision,
        exec_status, tool_result, delta, eval_status, None
    )

    return GuardResult(
        status=final_status,
        outcome=outcome,
        tool_result=tool_result,
        policy_verdict=policy_verdict,
        policy_reason=policy_reason,
        risk_level=risk_level,
        cap_meta=cap_meta_dict,
        duration_ms=duration_ms,
        audit_chain_id=chain_id,
        verification=verification_dict,
        retries_attempted=retries_attempted,
        rollback=rollback_result.to_dict() if rollback_result is not None else None,
        checkpoints=checkpoints,
        failure_reason=failure_reason_val,
        session_id=session_id,
    )


# ─── Safe helpers ─────────────────────────────────────────────────────────────

async def _safe_record_action(db: Any, command: str, tool_name: str, status: str, msg: str) -> None:
    try:
        from app.services.audit_service import record_action
        await record_action(db, command, tool_name, status, msg)
    except Exception as exc:
        log.warning("[guard] audit record_action failed: %s", exc)


async def _safe_eval(
    db: Any,
    command: str,
    tool_name: str,
    status: str,
    duration_ms: float,
    risk_level: str,
    policy_verdict: str,
    error_message: Optional[str] = None,
    retries: int = 0,
    verification_verdict: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> None:
    try:
        from app.services.eval_service import record as eval_record
        context: Dict[str, Any] = {}
        if verification_verdict is not None:
            context["verification_verdict"] = verification_verdict
        if failure_reason is not None:
            context["failure_reason"] = failure_reason
        await eval_record(
            db,
            command=command,
            tool_name=tool_name,
            status=status,
            duration_ms=duration_ms,
            risk_level=risk_level,
            policy_verdict=policy_verdict,
            error_message=error_message,
            retries=retries,
            context=context if context else None,
        )
    except Exception as exc:
        log.warning("[guard] eval record failed: %s", exc)


async def _safe_audit_chain(
    db: Any,
    command: str,
    tool_name: str,
    cap_meta: Optional[Dict[str, Any]],
    policy_decision: Any,
    execution_status: str,
    tool_result: Any,
    delta: Any,
    eval_status: Optional[str],
    approval_id: Optional[int],
) -> Optional[str]:
    try:
        from app.services.audit_chain import record_audit_chain
        return await record_audit_chain(
            db=db,
            command=command,
            tool_name=tool_name,
            cap_meta=cap_meta,
            policy_decision=policy_decision,
            execution_status=execution_status,
            tool_result=tool_result,
            state_delta=delta,
            eval_status=eval_status,
            approval_id=approval_id,
        )
    except Exception as exc:
        log.warning("[guard] audit chain failed: %s", exc)
        return None
