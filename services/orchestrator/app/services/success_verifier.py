"""
Success Verifier – determines whether a tool action truly succeeded.

The verifier is deliberately signal-agnostic: it collects every available
evidence signal and produces a structured ``VerificationResult`` without
blocking execution.

Supported signal types
──────────────────────
  TOOL_RESULT   – The ``ToolResult.status`` returned by the tool itself.
  EXPECTED_OUTPUT – Check whether expected keys/values appear in result data.
  EXIT_CODE     – For shell tools: exit code 0 = success.
  NO_ERROR_KEY  – Result data contains no "error" or "traceback" keys.
  CUSTOM        – Caller-supplied predicate (used for tests / extensions).

Verdict ladder (ordered by confidence)
──────────────────────────────────────
  success        – all signals positive, no contradictions
  likely_success – primary signal positive, secondary signals absent/neutral
  uncertain      – contradictory signals or no signal available
  failed         – primary signal negative, or hard failure criteria met

Usage::

    result = await verify(
        tool_name="create_file",
        params={"path": "/tmp/test.txt"},
        tool_result=tool_result,
        expected_output={"path": "/tmp/test.txt"},
    )

    if result.verdict == "failed":
        # trigger rollback / retry
        ...

The verifier never raises – any internal error produces ``uncertain``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Signal types ─────────────────────────────────────────────────────────────

SIGNAL_TOOL_RESULT    = "tool_result"
SIGNAL_EXPECTED_OUTPUT = "expected_output"
SIGNAL_EXIT_CODE       = "exit_code"
SIGNAL_NO_ERROR_KEY    = "no_error_key"
SIGNAL_CUSTOM          = "custom"
SIGNAL_BROWSER_PROOF  = "browser_proof"   # Phase 4 – DOM / URL / screenshot evidence


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class SignalOutcome:
    """One piece of verification evidence."""
    signal_type: str           # one of the SIGNAL_* constants
    passed: bool
    weight: float = 1.0        # relative importance (0.0–2.0)
    detail: str = ""


@dataclass
class VerificationResult:
    """
    Structured verdict from the success verifier.

    Attributes
    ----------
    verdict        : "success" | "likely_success" | "uncertain" | "failed"
    signals        : individual evidence pieces that led to the verdict
    confidence     : float 0.0–1.0 (ratio of positive weighted signal mass)
    detail         : human-readable summary of why this verdict was reached
    tool_name      : which tool was verified
    """
    verdict: str              # success | likely_success | uncertain | failed
    signals: List[SignalOutcome] = field(default_factory=list)
    confidence: float = 0.0   # 0.0 – 1.0
    detail: str = ""
    tool_name: str = ""

    @property
    def is_positive(self) -> bool:
        return self.verdict in ("success", "likely_success")

    @property
    def is_negative(self) -> bool:
        return self.verdict == "failed"

    @property
    def is_uncertain(self) -> bool:
        return self.verdict == "uncertain"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "detail": self.detail,
            "tool_name": self.tool_name,
            "signals": [
                {
                    "signal_type": s.signal_type,
                    "passed": s.passed,
                    "weight": s.weight,
                    "detail": s.detail,
                }
                for s in self.signals
            ],
        }


# ─── Tool-specific verification hints ────────────────────────────────────────
# Maps tool name → list of expected output keys whose *presence* indicates
# success.  If a key maps to a non-None value, that exact value is required.

_EXPECTED_KEYS: Dict[str, Dict[str, Any]] = {
    "create_file":          {"absolute_path": None},
    "move_file":            {"destination": None},
    "create_folder":        {"path": None},
    "web_search":           {"results": None},
    "read_document":        {"content": None},
    "summarize_document":   {"summary": None},
    "gmail_send_email":     {"message_id": None},
    "gmail_create_draft":   {"draft_id": None},
    "drive_upload_file":    {"file_id": None},
    "create_presentation":  {"path": None},
    "run_shell_command":    {"exit_code": 0},
    "run_python":           {"exit_code": 0},
    "run_javascript":       {"exit_code": 0},
    "git_commit":           {"commit_hash": None},
    "git_push":             {"pushed": True},
}

# Tools whose result.data must NOT contain these keys for a success verdict
_FORBIDDEN_KEYS: frozenset = frozenset({"error", "traceback", "exception"})

# Tools that are inherently non-verifiable (read-only / ambiguous)
_UNVERIFIABLE_TOOLS: frozenset = frozenset({
    "list_files",
    "search_files",
    "summarize_web_results",
    "compare_research_results",
    "research_and_prepare_brief",
    "fetch_url",
})


# ─── Public API ───────────────────────────────────────────────────────────────

async def verify(
    tool_name: str,
    params: Dict[str, Any],
    tool_result: Any,  # ToolResult-like object with .status, .data, .message
    *,
    expected_output: Optional[Dict[str, Any]] = None,
    custom_check: Optional[Callable[[Any], bool]] = None,
    browser_checks: Optional[Any] = None,  # Sequence[BrowserVerificationRequest] | None
) -> VerificationResult:
    """
    Determine whether *tool_result* represents a genuine success.

    Parameters
    ----------
    tool_name      : Name of the tool that was executed.
    params         : Parameters that were passed to the tool.
    tool_result    : The raw ``ToolResult`` (or duck-typed equivalent).
    expected_output: Optional dict of key/value pairs expected in result.data.
    custom_check   : Optional callable that receives tool_result and returns bool.
    browser_checks : Optional list of BrowserVerificationRequest for DOM/URL proof.
                     When supplied, browser proofs are included as SIGNAL_BROWSER_PROOF
                     signals with weight 2.5 each.

    Returns
    -------
    VerificationResult with verdict and individual signal outcomes.
    """
    try:
        return _verify_impl(
            tool_name, params, tool_result,
            expected_output=expected_output,
            custom_check=custom_check,
            browser_checks=browser_checks,
        )
    except Exception as exc:
        log.warning("[success_verifier] internal error for '%s': %s", tool_name, exc)
        return VerificationResult(
            verdict="uncertain",
            detail=f"Verifier raised an exception: {exc}",
            tool_name=tool_name,
        )


def _verify_impl(
    tool_name: str,
    params: Dict[str, Any],
    tool_result: Any,
    *,
    expected_output: Optional[Dict[str, Any]],
    custom_check: Optional[Callable[[Any], bool]],
    browser_checks: Optional[Any] = None,  # Sequence[BrowserVerificationRequest] | None
) -> VerificationResult:
    """Synchronous core of the verifier (wrapped by the async public function)."""
    signals: List[SignalOutcome] = []

    # ── Signal 1: primary tool result status ─────────────────────────────────
    raw_status = getattr(tool_result, "status", None)
    result_data: Dict[str, Any] = getattr(tool_result, "data", None) or {}
    result_msg: str = getattr(tool_result, "message", None) or ""

    tool_result_passed = raw_status == "success"
    signals.append(SignalOutcome(
        signal_type=SIGNAL_TOOL_RESULT,
        passed=tool_result_passed,
        weight=2.0,   # primary signal – carries most weight
        detail=f"tool status={raw_status!r}",
    ))

    # ── Signal 2: no error keys in result data ────────────────────────────────
    has_error_key = bool(_FORBIDDEN_KEYS.intersection(result_data.keys() if isinstance(result_data, dict) else []))
    signals.append(SignalOutcome(
        signal_type=SIGNAL_NO_ERROR_KEY,
        passed=not has_error_key,
        weight=1.5,
        detail=("no error keys in data" if not has_error_key
                else f"error keys found: {_FORBIDDEN_KEYS.intersection(result_data.keys())}"),
    ))

    # ── Signal 3: expected output key/value check ─────────────────────────────
    # Use caller-supplied expected_output first, fall back to registry hints
    target_keys = expected_output if expected_output is not None else _EXPECTED_KEYS.get(tool_name)
    if target_keys and isinstance(result_data, dict):
        all_present = True
        missing: List[str] = []
        wrong_val: List[str] = []
        for key, expected_val in target_keys.items():
            if key not in result_data:
                all_present = False
                missing.append(key)
            elif expected_val is not None and result_data[key] != expected_val:
                all_present = False
                wrong_val.append(f"{key}={result_data[key]!r} (expected {expected_val!r})")
        detail_parts = []
        if missing:
            detail_parts.append(f"missing keys: {missing}")
        if wrong_val:
            detail_parts.append(f"wrong values: {wrong_val}")
        signals.append(SignalOutcome(
            signal_type=SIGNAL_EXPECTED_OUTPUT,
            passed=all_present,
            weight=1.0,
            detail=", ".join(detail_parts) if detail_parts else "all expected keys present",
        ))
    elif target_keys and not isinstance(result_data, dict):
        # Data not inspectable – neutral signal
        signals.append(SignalOutcome(
            signal_type=SIGNAL_EXPECTED_OUTPUT,
            passed=True,
            weight=0.0,   # zero-weight: don't influence score
            detail="result.data not a dict; skipping key check",
        ))

    # ── Signal 4: exit code check (shell / script tools) ─────────────────────
    if tool_name in ("run_shell_command", "run_python", "run_javascript"):
        exit_code = result_data.get("exit_code") if isinstance(result_data, dict) else None
        if exit_code is not None:
            signals.append(SignalOutcome(
                signal_type=SIGNAL_EXIT_CODE,
                passed=(exit_code == 0),
                weight=1.5,
                detail=f"exit_code={exit_code}",
            ))

    # ── Signal 5: custom check ────────────────────────────────────────────────
    if custom_check is not None:
        try:
            custom_passed = bool(custom_check(tool_result))
        except Exception as exc:
            custom_passed = False
            log.debug("[success_verifier] custom_check raised: %s", exc)
        signals.append(SignalOutcome(
            signal_type=SIGNAL_CUSTOM,
            passed=custom_passed,
            weight=1.0,
            detail="custom check " + ("passed" if custom_passed else "failed"),
        ))

    # ── Signal 6: browser proof signals (Phase 4) ─────────────────────────────
    # Convert each BrowserProof returned by browser_verifier into a signal.
    if browser_checks is not None:
        try:
            from app.services.browser_verifier import verify_browser_action
            proofs = verify_browser_action(tool_name, params, tool_result, checks=browser_checks)
            for proof in proofs:
                signals.append(SignalOutcome(
                    signal_type=SIGNAL_BROWSER_PROOF,
                    passed=proof.passed,
                    weight=2.5 * proof.confidence_score,  # scale weight by confidence
                    detail=f"[{proof.proof_type}] {proof.detail}",
                ))
        except Exception as exc:
            log.warning("[success_verifier] browser_checks signal failed: %s", exc)

    # ── Compute verdict ───────────────────────────────────────────────────────
    return _compute_verdict(tool_name, signals)


def _compute_verdict(tool_name: str, signals: List[SignalOutcome]) -> VerificationResult:
    """
    Aggregate signal outcomes into a final verdict.

    Rules
    ─────
    1. Unverifiable tools → "likely_success" if primary signal passes, else "failed"
    2. Primary signal (TOOL_RESULT) is hard-failed → "failed" immediately
    3. Compute weighted score across all signals
       - score ≥ 0.85 → "success"
       - score ≥ 0.60 → "likely_success"
       - score ≥ 0.35 → "uncertain"
       - score <  0.35 → "failed"
    """
    # Separate primary signal from others
    primary = next((s for s in signals if s.signal_type == SIGNAL_TOOL_RESULT), None)

    # Rule 1: non-verifiable tools
    if tool_name in _UNVERIFIABLE_TOOLS:
        if primary is not None and not primary.passed:
            return VerificationResult(
                verdict="failed",
                signals=signals,
                confidence=0.0,
                detail="Tool returned error status (unverifiable category).",
                tool_name=tool_name,
            )
        return VerificationResult(
            verdict="likely_success",
            signals=signals,
            confidence=0.7,
            detail="Tool in non-verifiable category; primary status is positive.",
            tool_name=tool_name,
        )

    # Rule 2: primary hard-fail
    if primary is not None and not primary.passed:
        return VerificationResult(
            verdict="failed",
            signals=signals,
            confidence=0.0,
            detail=f"Primary tool result indicates failure: {primary.detail}",
            tool_name=tool_name,
        )

    # Rule 3: weighted score
    total_weight = sum(s.weight for s in signals)
    if total_weight == 0.0:
        return VerificationResult(
            verdict="uncertain",
            signals=signals,
            confidence=0.0,
            detail="No weighted signals available.",
            tool_name=tool_name,
        )

    positive_weight = sum(s.weight for s in signals if s.passed)
    score = positive_weight / total_weight

    if score >= 0.85:
        verdict, detail = "success", f"All signals positive (score={score:.2f})"
    elif score >= 0.60:
        verdict, detail = "likely_success", f"Most signals positive (score={score:.2f})"
    elif score >= 0.35:
        verdict, detail = "uncertain", f"Mixed signals (score={score:.2f})"
    else:
        verdict, detail = "failed", f"Most signals negative (score={score:.2f})"

    return VerificationResult(
        verdict=verdict,
        signals=signals,
        confidence=round(score, 3),
        detail=detail,
        tool_name=tool_name,
    )
