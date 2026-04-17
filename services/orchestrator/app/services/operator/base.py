"""Abstract base class and result type for the Computer Operator."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.schemas.operator import (
    OperatorActionName,
    OperatorCapability,
    OperatorManifest,
    Platform,
)


# ─── Low-level result returned by every operator method ───────────────────────

class OperatorResult:
    """Thin, non-Pydantic container so operator code stays free of HTTP concerns."""

    def __init__(
        self,
        ok: bool,
        message: str,
        data: Optional[Any] = None,
        requires_approval: bool = False,
        approval_id: Optional[int] = None,
    ) -> None:
        self.ok = ok
        self.message = message
        self.data = data
        self.requires_approval = requires_approval
        self.approval_id = approval_id


# ─── Abstract base ────────────────────────────────────────────────────────────

class OperatorBase(ABC):
    """Platform operator contract — subclass one per platform."""

    #: Canonical platform identifier matching sys.platform
    sys_platform: str = "unknown"
    #: Human-friendly display name
    platform_display: Platform = "unknown"

    @abstractmethod
    def get_capabilities(self) -> List[OperatorCapability]:
        """Return the full capability manifest for this platform."""
        ...

    @abstractmethod
    async def execute(
        self, action: OperatorActionName, params: Dict[str, Any]
    ) -> OperatorResult:
        """Execute an operator action.  Must never raise — use ok=False instead."""
        ...

    def build_manifest(self) -> OperatorManifest:
        return OperatorManifest(
            platform=self.platform_display,
            platform_available=True,
            capabilities=self.get_capabilities(),
        )


# ─── Registry + factory ───────────────────────────────────────────────────────

# Populated by each platform module at import time.
_OPERATOR_REGISTRY: Dict[str, OperatorBase] = {}


def register_operator(operator: OperatorBase) -> None:
    """Register a platform operator instance."""
    _OPERATOR_REGISTRY[operator.sys_platform] = operator


def get_operator() -> OperatorBase:
    """Return the operator for the current platform, falling back to the stub."""
    candidate = _OPERATOR_REGISTRY.get(sys.platform)
    if candidate is not None:
        return candidate
    # Return any stub that has been registered (they all behave the same).
    for op in _OPERATOR_REGISTRY.values():
        return op
    raise RuntimeError("No operator implementation has been registered.")


def get_manifest() -> OperatorManifest:
    op = get_operator()
    return op.build_manifest()
