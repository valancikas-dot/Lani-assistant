"""
Browser Verifier – proof-based verification for browser and UI actions.

This module produces ``BrowserProof`` objects that describe *what was observed*
in the browser/DOM after an action, compared to *what was expected*.  The proofs
are designed to be:

  1. Structured  – machine-parseable (proof_type / expected / observed / confidence)
  2. Composable  – multiple proofs can be combined by the caller
  3. Safe        – the verifier never drives a real browser; it inspects data
                   returned by browser/operator tool results
  4. Extensible  – screenshot comparison is an abstraction hook (no PIL dep)

Supported proof types
─────────────────────
  dom_element_exists      – An element matching a selector is present in the DOM
  dom_element_absent      – An element is confirmed absent
  dom_text_match          – Element inner text / page text contains expected string
  url_change              – Current URL matches expected pattern
  navigation_success      – Page title / URL indicates successful navigation
  form_submission_success – Form-specific signals (redirect, success banner)
  screenshot_hash_match   – Optional pixel-hash comparison (abstraction hook)
  generic_state_match     – Generic key→value state comparison

Public API
──────────
  verify_browser_action(tool_name, params, tool_result, *, checks) → List[BrowserProof]
  proof_to_signal(proof) → SignalOutcome   (for integration into success_verifier)

The result list is passed back up to success_verifier as additional signals
via the SIGNAL_BROWSER_PROOF signal type.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

log = logging.getLogger(__name__)


# ─── Proof types ──────────────────────────────────────────────────────────────

PROOF_DOM_ELEMENT_EXISTS      = "dom_element_exists"
PROOF_DOM_ELEMENT_ABSENT      = "dom_element_absent"
PROOF_DOM_TEXT_MATCH          = "dom_text_match"
PROOF_URL_CHANGE              = "url_change"
PROOF_NAVIGATION_SUCCESS      = "navigation_success"
PROOF_FORM_SUBMISSION_SUCCESS = "form_submission_success"
PROOF_SCREENSHOT_HASH_MATCH   = "screenshot_hash_match"
PROOF_GENERIC_STATE_MATCH     = "generic_state_match"


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class BrowserProof:
    """
    Structured proof of a browser/UI state assertion.

    Attributes
    ----------
    proof_type       : One of the PROOF_* constants above.
    expected         : What we expected to observe.
    observed         : What the tool result / DOM snapshot actually showed.
    passed           : Whether the assertion was satisfied.
    confidence_score : 0.0–1.0.  High = high certainty.  Low = partial / inferred.
    detail           : Human-readable explanation.
    selector         : CSS selector or locator string, if applicable.
    """
    proof_type: str
    expected: Any
    observed: Any
    passed: bool
    confidence_score: float = 1.0  # 0.0 – 1.0
    detail: str = ""
    selector: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proof_type": self.proof_type,
            "expected": self.expected,
            "observed": self.observed,
            "passed": self.passed,
            "confidence_score": round(self.confidence_score, 3),
            "detail": self.detail,
            "selector": self.selector,
        }


@dataclass
class BrowserVerificationRequest:
    """
    A single check request supplied by the caller.

    Examples::

        BrowserVerificationRequest(
            proof_type=PROOF_DOM_TEXT_MATCH,
            selector="#flash-message",
            expected_value="Successfully saved",
        )

        BrowserVerificationRequest(
            proof_type=PROOF_URL_CHANGE,
            expected_value="https://example.com/dashboard",
        )
    """
    proof_type: str
    expected_value: Any = None   # The assertion target
    selector: str = ""           # CSS / XPath selector (optional)
    screenshot_before: Optional[bytes] = None
    screenshot_after: Optional[bytes] = None


# ─── Tool result keys ─────────────────────────────────────────────────────────
# These are the keys we look for inside tool_result.data to find DOM/URL info.

_DOM_SNAPSHOT_KEY  = "dom_snapshot"   # str – HTML fragment or text content
_CURRENT_URL_KEY   = "current_url"    # str
_PAGE_TITLE_KEY    = "page_title"     # str
_ELEMENTS_KEY      = "elements"       # list of {selector, text, exists}
_SUCCESS_BANNER_KEY = "success_banner" # bool or str
_FORM_REDIRECT_KEY = "redirect_url"   # str – post-form-submit redirect


# ─── Public API ───────────────────────────────────────────────────────────────

def verify_browser_action(
    tool_name: str,
    params: Dict[str, Any],
    tool_result: Any,  # ToolResult-like object
    *,
    checks: Optional[Sequence[BrowserVerificationRequest]] = None,
) -> List[BrowserProof]:
    """
    Inspect ``tool_result`` and produce a list of ``BrowserProof`` objects.

    Parameters
    ----------
    tool_name   : Tool that was executed (e.g. ``browser_click``, ``browser_fill``).
    params      : Parameters passed to the tool.
    tool_result : The raw ToolResult (duck-typed: .status, .data, .message).
    checks      : Optional explicit list of assertions to verify.
                  If None, automatic checks are derived from tool_name and params.

    Returns
    -------
    List of BrowserProof, one per assertion evaluated.  Empty list if tool_result
    is None or data is not inspectable.
    """
    try:
        return _verify_impl(tool_name, params, tool_result, checks=checks or [])
    except Exception as exc:
        log.warning("[browser_verifier] internal error for '%s': %s", tool_name, exc)
        return [BrowserProof(
            proof_type=PROOF_GENERIC_STATE_MATCH,
            expected="verifier success",
            observed=f"exception: {exc}",
            passed=False,
            confidence_score=0.0,
            detail=f"BrowserVerifier raised an internal exception: {exc}",
        )]


def proof_to_signal(proof: BrowserProof) -> Any:
    """
    Convert a BrowserProof into a SignalOutcome for use in success_verifier.

    Returns a ``SignalOutcome`` instance.  The import is deferred to avoid
    circular imports between browser_verifier and success_verifier.
    """
    from app.services.success_verifier import SignalOutcome, SIGNAL_BROWSER_PROOF  # type: ignore[attr-defined]
    return SignalOutcome(
        signal_type=SIGNAL_BROWSER_PROOF,
        passed=proof.passed,
        weight=2.5,   # Browser proofs carry high weight (direct DOM evidence)
        detail=f"[{proof.proof_type}] {proof.detail or proof.observed!r}",
    )


# ─── Internal implementation ──────────────────────────────────────────────────

def _verify_impl(
    tool_name: str,
    params: Dict[str, Any],
    tool_result: Any,
    *,
    checks: Sequence[BrowserVerificationRequest],
) -> List[BrowserProof]:
    """Synchronous core – inspects tool result data and runs assertions."""
    proofs: List[BrowserProof] = []

    # Extract result data safely
    data: Dict[str, Any] = {}
    if tool_result is not None:
        raw_data = getattr(tool_result, "data", None)
        if isinstance(raw_data, dict):
            data = raw_data

    current_url: Optional[str]  = data.get(_CURRENT_URL_KEY)
    page_title: Optional[str]   = data.get(_PAGE_TITLE_KEY)
    dom_snapshot: Optional[str] = data.get(_DOM_SNAPSHOT_KEY)
    elements: List[Dict[str, Any]] = data.get(_ELEMENTS_KEY) or []

    # ── Explicit caller checks ────────────────────────────────────────────────
    for check in checks:
        proof = _run_check(check, data, current_url, page_title, dom_snapshot, elements)
        proofs.append(proof)

    # ── Auto-derived checks based on tool name ────────────────────────────────
    if not checks:
        auto_proofs = _auto_checks(tool_name, params, data,
                                   current_url, page_title, dom_snapshot, elements)
        proofs.extend(auto_proofs)

    return proofs


def _run_check(
    check: BrowserVerificationRequest,
    data: Dict[str, Any],
    current_url: Optional[str],
    page_title: Optional[str],
    dom_snapshot: Optional[str],
    elements: List[Dict[str, Any]],
) -> BrowserProof:
    """Execute a single BrowserVerificationRequest and return a BrowserProof."""

    pt = check.proof_type

    # ── DOM element exists ────────────────────────────────────────────────────
    if pt == PROOF_DOM_ELEMENT_EXISTS:
        found_element = _find_element(check.selector, elements, dom_snapshot)
        passed = found_element is not None
        return BrowserProof(
            proof_type=pt,
            expected=f"element '{check.selector}' present",
            observed="found" if passed else "not found",
            passed=passed,
            confidence_score=0.9 if elements else 0.5,
            detail=(f"Element '{check.selector}' {'found' if passed else 'not found'} in DOM."),
            selector=check.selector,
        )

    # ── DOM element absent ────────────────────────────────────────────────────
    if pt == PROOF_DOM_ELEMENT_ABSENT:
        found_element = _find_element(check.selector, elements, dom_snapshot)
        passed = found_element is None
        return BrowserProof(
            proof_type=pt,
            expected=f"element '{check.selector}' absent",
            observed="absent" if passed else "still present",
            passed=passed,
            confidence_score=0.9 if elements else 0.5,
            detail=f"Element '{check.selector}' {'absent (expected)' if passed else 'still present (unexpected)'}.",
            selector=check.selector,
        )

    # ── DOM text match ────────────────────────────────────────────────────────
    if pt == PROOF_DOM_TEXT_MATCH:
        expected_text = str(check.expected_value or "")
        text_source = _get_text_from_element(check.selector, elements, dom_snapshot)
        passed = expected_text.lower() in (text_source or "").lower()
        return BrowserProof(
            proof_type=pt,
            expected=expected_text,
            observed=text_source[:200] if text_source else "(no text)",
            passed=passed,
            confidence_score=0.95 if text_source else 0.3,
            detail=(
                f"Expected text '{expected_text}' {'found' if passed else 'NOT found'} "
                f"in element '{check.selector}'."
            ),
            selector=check.selector,
        )

    # ── URL change ────────────────────────────────────────────────────────────
    if pt == PROOF_URL_CHANGE:
        expected_url = str(check.expected_value or "")
        observed_url = current_url or "(unknown)"
        # Support both exact match and pattern match
        passed = _url_matches(expected_url, observed_url)
        return BrowserProof(
            proof_type=pt,
            expected=expected_url,
            observed=observed_url,
            passed=passed,
            confidence_score=1.0 if current_url else 0.2,
            detail=f"URL {'matches' if passed else 'does NOT match'} expected '{expected_url}'.",
        )

    # ── Navigation success ────────────────────────────────────────────────────
    if pt == PROOF_NAVIGATION_SUCCESS:
        expected_title = str(check.expected_value or "")
        observed_title = page_title or "(no title)"
        passed = expected_title.lower() in observed_title.lower() if expected_title else bool(page_title)
        confidence = 0.8 if page_title else 0.3
        return BrowserProof(
            proof_type=pt,
            expected=expected_title or "(any page loaded)",
            observed=observed_title,
            passed=passed,
            confidence_score=confidence,
            detail=f"Page title '{observed_title}' {'matches' if passed else 'does NOT match'} '{expected_title}'.",
        )

    # ── Form submission success ───────────────────────────────────────────────
    if pt == PROOF_FORM_SUBMISSION_SUCCESS:
        banner = data.get(_SUCCESS_BANNER_KEY)
        redirect = data.get(_FORM_REDIRECT_KEY)
        # A form submission is considered successful if:
        # - There's a success_banner truthy value, OR
        # - A redirect URL is present (post-submit redirect pattern)
        has_banner = bool(banner)
        has_redirect = bool(redirect)
        passed = has_banner or has_redirect
        confidence = 0.9 if has_banner else (0.7 if has_redirect else 0.2)
        details = []
        if has_banner:
            details.append(f"success_banner={banner!r}")
        if has_redirect:
            details.append(f"redirect_url={redirect!r}")
        return BrowserProof(
            proof_type=pt,
            expected="form success indicator",
            observed=", ".join(details) or "(no success indicators)",
            passed=passed,
            confidence_score=confidence,
            detail=f"Form submission {'success' if passed else 'could not be verified'}.",
        )

    # ── Screenshot hash match ─────────────────────────────────────────────────
    if pt == PROOF_SCREENSHOT_HASH_MATCH:
        # Abstraction hook – compares hash of before/after screenshots.
        # Real implementation would use an image comparison library.
        before_hash = _screenshot_hash(check.screenshot_before)
        after_hash  = _screenshot_hash(check.screenshot_after)
        if before_hash is None or after_hash is None:
            return BrowserProof(
                proof_type=pt,
                expected="screenshot comparison",
                observed="screenshots unavailable",
                passed=False,
                confidence_score=0.0,
                detail="Screenshot comparison skipped: one or both screenshots missing.",
            )
        changed = before_hash != after_hash
        # For this type, "passed" means the page *changed* (action had visible effect)
        return BrowserProof(
            proof_type=pt,
            expected="page state changed",
            observed="changed" if changed else "unchanged",
            passed=changed,
            confidence_score=0.85,
            detail=f"Screenshot hash {'changed' if changed else 'unchanged'} after action.",
        )

    # ── Generic state match ───────────────────────────────────────────────────
    if pt == PROOF_GENERIC_STATE_MATCH:
        expected_val = check.expected_value
        if isinstance(expected_val, dict):
            # Check all key/value pairs in tool result data
            mismatches: List[str] = []
            for k, v in expected_val.items():
                actual = data.get(k)
                if actual != v:
                    mismatches.append(f"{k}: expected {v!r}, got {actual!r}")
            passed = len(mismatches) == 0
            return BrowserProof(
                proof_type=pt,
                expected=expected_val,
                observed={k: data.get(k) for k in expected_val},
                passed=passed,
                confidence_score=0.9 if data else 0.3,
                detail=", ".join(mismatches) if mismatches else "All expected state keys match.",
            )
        # Scalar check
        observed_scalar = data.get(str(expected_val), data)
        passed = expected_val == observed_scalar
        return BrowserProof(
            proof_type=pt,
            expected=expected_val,
            observed=observed_scalar,
            passed=passed,
            confidence_score=0.5,
            detail=f"Generic match: {'passed' if passed else 'failed'}.",
        )

    # ── Unknown proof type ────────────────────────────────────────────────────
    return BrowserProof(
        proof_type=pt,
        expected=check.expected_value,
        observed="unknown proof type",
        passed=False,
        confidence_score=0.0,
        detail=f"Proof type '{pt}' is not implemented.",
    )


def _auto_checks(
    tool_name: str,
    params: Dict[str, Any],
    data: Dict[str, Any],
    current_url: Optional[str],
    page_title: Optional[str],
    dom_snapshot: Optional[str],
    elements: List[Dict[str, Any]],
) -> List[BrowserProof]:
    """
    Derive automatic checks from tool name and params when no explicit
    BrowserVerificationRequest list is supplied.
    """
    proofs: List[BrowserProof] = []

    # Navigation tools: verify URL and page title
    if tool_name in ("browser_navigate", "browser_goto", "navigate_to"):
        target_url = params.get("url") or params.get("target")
        if target_url and current_url:
            passed = _url_matches(str(target_url), current_url)
            proofs.append(BrowserProof(
                proof_type=PROOF_URL_CHANGE,
                expected=target_url,
                observed=current_url,
                passed=passed,
                confidence_score=1.0,
                detail=f"Navigation to '{target_url}': URL {'matches' if passed else 'mismatch'}.",
            ))
        if page_title:
            proofs.append(BrowserProof(
                proof_type=PROOF_NAVIGATION_SUCCESS,
                expected="(any page loaded)",
                observed=page_title,
                passed=True,
                confidence_score=0.8,
                detail=f"Page loaded with title: '{page_title}'.",
            ))

    # Click tools: verify element present/absent after click
    elif tool_name in ("browser_click", "click_element"):
        selector = params.get("selector") or params.get("element")
        if selector:
            found = _find_element(str(selector), elements, dom_snapshot)
            proofs.append(BrowserProof(
                proof_type=PROOF_DOM_ELEMENT_EXISTS,
                expected=f"element '{selector}'",
                observed="found" if found else "not found",
                passed=found is not None,
                confidence_score=0.7,
                detail=f"After click: element '{selector}' {'found' if found else 'not found'}.",
                selector=str(selector),
            ))

    # Form fill tools: check for success banner or redirect
    elif tool_name in ("browser_fill_form", "fill_form", "browser_submit_form", "submit_form"):
        banner = data.get(_SUCCESS_BANNER_KEY)
        redirect = data.get(_FORM_REDIRECT_KEY)
        passed = bool(banner) or bool(redirect)
        proofs.append(BrowserProof(
            proof_type=PROOF_FORM_SUBMISSION_SUCCESS,
            expected="success indicator",
            observed=str(banner or redirect or "(none)"),
            passed=passed,
            confidence_score=0.85 if passed else 0.4,
            detail="Form action " + ("succeeded" if passed else "success not confirmed") + ".",
        ))

    # Generic browser tools: check that current_url is present (page loaded)
    elif tool_name.startswith("browser_") or tool_name.startswith("operator_"):
        if current_url:
            proofs.append(BrowserProof(
                proof_type=PROOF_NAVIGATION_SUCCESS,
                expected="page URL available",
                observed=current_url,
                passed=True,
                confidence_score=0.6,
                detail=f"Browser action completed; URL={current_url}.",
            ))

    return proofs


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _find_element(
    selector: str,
    elements: List[Dict[str, Any]],
    dom_snapshot: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Try to find ``selector`` in the elements list or DOM snapshot text.
    Returns the element dict if found, None otherwise.
    """
    if not selector:
        return None

    # Check structured elements list first (most reliable)
    for el in elements:
        el_selector = el.get("selector") or el.get("id") or el.get("class") or ""
        if selector.lower() in el_selector.lower():
            # If element has an explicit 'exists' flag, honour it
            if el.get("exists") is False:
                return None
            return el

    # Fall back to text search in DOM snapshot
    if dom_snapshot:
        # Simple substring / attribute check
        if selector.startswith("#"):
            attr = selector[1:]
            if f'id="{attr}"' in dom_snapshot or f"id='{attr}'" in dom_snapshot:
                return {"selector": selector, "source": "dom_snapshot"}
        elif selector.startswith("."):
            cls = selector[1:]
            if f'class="{cls}"' in dom_snapshot or cls in dom_snapshot:
                return {"selector": selector, "source": "dom_snapshot"}
        else:
            if selector in dom_snapshot:
                return {"selector": selector, "source": "dom_snapshot"}

    return None


def _get_text_from_element(
    selector: str,
    elements: List[Dict[str, Any]],
    dom_snapshot: Optional[str],
) -> Optional[str]:
    """Extract the inner text associated with a selector."""
    if not selector:
        return dom_snapshot  # use full snapshot as fallback

    for el in elements:
        el_selector = el.get("selector") or el.get("id") or ""
        if selector.lower() in el_selector.lower():
            return el.get("text") or el.get("inner_text") or el.get("value")

    # Fall back to raw DOM snapshot
    if dom_snapshot:
        return dom_snapshot  # caller will substring-search the full snapshot
    return None


def _url_matches(expected: str, observed: str) -> bool:
    """
    Compare URLs with tolerance for trailing slashes and optional regex.

    If ``expected`` starts with ``re:`` it is treated as a regular expression.
    """
    if not expected or not observed:
        return False
    expected = expected.strip()
    observed = observed.strip()

    if expected.startswith("re:"):
        pattern = expected[3:]
        return bool(re.match(pattern, observed))

    # Exact match (normalise trailing slash)
    return expected.rstrip("/") == observed.rstrip("/")


def _screenshot_hash(data: Optional[bytes]) -> Optional[str]:
    """
    Compute a simple content hash for screenshot comparison.
    Returns None if data is absent.  Uses hashlib to avoid PIL dependency.
    """
    if not data:
        return None
    import hashlib
    return hashlib.sha256(data).hexdigest()
