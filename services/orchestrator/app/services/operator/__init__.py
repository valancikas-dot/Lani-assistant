"""Computer Operator service package.

Importing this package registers all platform operators and exposes
the factory helpers used throughout the rest of the application.
"""

# Order matters – importing the platform modules triggers register_operator()
# for each platform, so the registry is fully populated by the time any
# caller invokes get_operator().
from app.services.operator import macos_operator, windows_operator, linux_operator  # noqa: F401

from app.services.operator.base import (
    get_operator,
    get_manifest,
    OperatorResult,
    OperatorBase,
)

__all__ = [
    "get_operator",
    "get_manifest",
    "OperatorResult",
    "OperatorBase",
]
