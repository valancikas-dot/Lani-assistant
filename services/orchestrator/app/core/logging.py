"""
Structured logging configuration for the orchestrator.
"""

import logging
import sys


def setup_logging(debug: bool = False) -> None:
    """Configure root logger with a sensible format."""
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


# Module-level logger for convenience
logger = logging.getLogger("assistant")
