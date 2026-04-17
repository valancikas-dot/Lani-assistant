"""Centralised security primitives for Lani.

This module is the single source of truth for:
  - Password / PIN hashing and verification (Argon2id)
  - Approval policy levels for every tool and operator action
  - Security status snapshot used by the status API and UI

Design goals
────────────
1. No raw secrets ever stored or logged.
2. Argon2id with conservative parameters (time=3, memory=64 MB, parallelism=2).
3. Backward-compatibility: if an existing stored hash starts with ``sha256:``
   (the old scheme) it is re-verified with the old method and flagged for
   upgrade on next successful login.
4. The approval policy is a simple dict that maps tool_name → ApprovalLevel.
   New tools default to ``write_requires_approval`` (safe default).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from enum import Enum
from typing import Dict

log = logging.getLogger(__name__)


# ─── Approval policy ─────────────────────────────────────────────────────────

class ApprovalLevel(str, Enum):
    """Risk levels that map to whether approval is needed before execution."""

    read_safe = "read_safe"
    """Safe read-only operations; no approval required."""

    write_requires_approval = "write_requires_approval"
    """Mutations that can be undone; approval gated."""

    destructive_requires_approval = "destructive_requires_approval"
    """Irreversible data changes; always approval gated."""

    security_sensitive_requires_approval = "security_sensitive_requires_approval"
    """Operations that touch credentials, auth state, or system security."""


# Tool-name → ApprovalLevel policy table.
# Every tool that requires_approval=True must appear here.
# Tools not in this table default to ``write_requires_approval``.
APPROVAL_POLICY: Dict[str, ApprovalLevel] = {
    # ── File tools ────────────────────────────────────────────────────────
    "create_folder":            ApprovalLevel.write_requires_approval,
    "create_file":              ApprovalLevel.write_requires_approval,
    "move_file":                ApprovalLevel.write_requires_approval,
    "sort_downloads":           ApprovalLevel.write_requires_approval,

    # ── Document tools ────────────────────────────────────────────────────
    "read_document":            ApprovalLevel.read_safe,
    "summarize_document":       ApprovalLevel.read_safe,
    "create_presentation":      ApprovalLevel.write_requires_approval,

    # ── Research tools ────────────────────────────────────────────────────
    "web_search":               ApprovalLevel.read_safe,
    "summarize_web_results":    ApprovalLevel.read_safe,
    "compare_research_results": ApprovalLevel.read_safe,
    "research_and_prepare_brief": ApprovalLevel.read_safe,

    # ── Builder tools ─────────────────────────────────────────────────────
    "create_project_scaffold":  ApprovalLevel.write_requires_approval,
    "create_code_file":         ApprovalLevel.write_requires_approval,
    "update_code_file":         ApprovalLevel.write_requires_approval,
    "create_readme":            ApprovalLevel.write_requires_approval,
    "generate_feature_files":   ApprovalLevel.write_requires_approval,
    "list_project_tree":        ApprovalLevel.read_safe,
    "propose_terminal_commands": ApprovalLevel.write_requires_approval,

    # ── Connector tools (read) ────────────────────────────────────────────
    "drive_list_files":         ApprovalLevel.read_safe,
    "drive_search_files":       ApprovalLevel.read_safe,
    "drive_get_file":           ApprovalLevel.read_safe,
    "gmail_list_recent":        ApprovalLevel.read_safe,
    "gmail_get_message":        ApprovalLevel.read_safe,
    "calendar_list_events":     ApprovalLevel.read_safe,

    # ── Connector tools (write) ───────────────────────────────────────────
    "gmail_create_draft":       ApprovalLevel.write_requires_approval,
    "gmail_send_email":         ApprovalLevel.destructive_requires_approval,
    "calendar_create_event":    ApprovalLevel.write_requires_approval,
    "calendar_delete_event":    ApprovalLevel.destructive_requires_approval,

    # ── Operator actions ──────────────────────────────────────────────────
    "operator.list_open_windows":   ApprovalLevel.read_safe,
    "operator.open_app":            ApprovalLevel.write_requires_approval,
    "operator.focus_window":        ApprovalLevel.write_requires_approval,
    "operator.minimize_window":     ApprovalLevel.write_requires_approval,
    "operator.close_window":        ApprovalLevel.destructive_requires_approval,
    "operator.open_path":           ApprovalLevel.write_requires_approval,
    "operator.reveal_file":         ApprovalLevel.read_safe,
    "operator.copy_to_clipboard":   ApprovalLevel.write_requires_approval,
    "operator.paste_clipboard":     ApprovalLevel.write_requires_approval,
    "operator.type_text":           ApprovalLevel.security_sensitive_requires_approval,
    "operator.press_shortcut":      ApprovalLevel.write_requires_approval,
    "operator.take_screenshot":     ApprovalLevel.read_safe,

    # ── Security / auth ───────────────────────────────────────────────────
    "security.unlock.pin":          ApprovalLevel.security_sensitive_requires_approval,
    "security.unlock.passphrase":   ApprovalLevel.security_sensitive_requires_approval,
    "security.set_pin":             ApprovalLevel.security_sensitive_requires_approval,
}


def get_approval_level(tool_name: str) -> ApprovalLevel:
    """Return the ApprovalLevel for *tool_name*, defaulting to write_requires_approval."""
    return APPROVAL_POLICY.get(tool_name, ApprovalLevel.write_requires_approval)


def requires_approval(tool_name: str) -> bool:
    """Return True when the tool should be blocked until a human approves it."""
    return get_approval_level(tool_name) != ApprovalLevel.read_safe


# ─── Argon2id hashing ─────────────────────────────────────────────────────────

_ARGON2_PREFIX = "argon2:"
_SHA256_PREFIX = "sha256:"      # legacy – stored in old deployments
_OLD_SALT = "lani_local_salt_v1"  # used by old _hash_pin()


def _argon2_hasher():
    """Return a configured PasswordHasher (lazy import so tests without
    argon2-cffi installed still pass when the hasher is not called)."""
    from argon2 import PasswordHasher  # type: ignore[import]
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)


def hash_secret(value: str) -> str:
    """Hash *value* with Argon2id and return a prefixed opaque string.

    The prefix ``argon2:`` allows future scheme detection.
    Never store the raw input.
    """
    ph = _argon2_hasher()
    return _ARGON2_PREFIX + ph.hash(value)


def verify_secret(stored_hash: str, provided_value: str) -> tuple[bool, bool]:
    """Verify *provided_value* against *stored_hash*.

    Returns ``(ok: bool, needs_rehash: bool)``.
    When ``needs_rehash`` is True the caller should hash the value again with
    the current scheme and persist the new hash (silent upgrade).

    Supports:
    - ``argon2:<hash>``  – current scheme
    - ``sha256:<hex>``   – legacy scheme (auto-migration path)
    """
    if not stored_hash:
        return False, False

    if stored_hash.startswith(_ARGON2_PREFIX):
        raw = stored_hash[len(_ARGON2_PREFIX):]
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError  # type: ignore
            ph = _argon2_hasher()
            try:
                ph.verify(raw, provided_value)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False, False
            needs_rehash = ph.check_needs_rehash(raw)
            return True, needs_rehash
        except ImportError:
            log.error("argon2-cffi not installed; cannot verify Argon2 hash")
            return False, False

    if stored_hash.startswith(_SHA256_PREFIX):
        # Legacy path: sha256(salt + value) comparison
        legacy_hash = hashlib.sha256((_OLD_SALT + provided_value).encode()).hexdigest()
        ok = hmac.compare_digest(legacy_hash, stored_hash[len(_SHA256_PREFIX):])
        return ok, ok  # if match, needs rehash to Argon2
    
    # Unrecognised scheme – treat as failure
    log.warning("Unrecognised stored_hash scheme: %s…", stored_hash[:10])
    return False, False


def legacy_sha256_hash(value: str) -> str:
    """Return a ``sha256:`` prefixed legacy hash (for migration detection only)."""
    return _SHA256_PREFIX + hashlib.sha256((_OLD_SALT + value).encode()).hexdigest()
