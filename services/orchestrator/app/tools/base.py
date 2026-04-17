"""
Abstract base class that every tool must implement.
Tools are the atomic units of capability in the assistant.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from app.schemas.commands import ToolResult


class BaseTool(ABC):
    """
    All tools derive from this class.

    Attributes
    ----------
    name : str
        Unique identifier used in the tool registry.
    description : str
        Human-readable description of what the tool does.
    requires_approval : bool
        If True, the tool execution must be confirmed by the user before running.
    """

    name: str = ""
    description: str = ""
    requires_approval: bool = False
    parameters: list = []

    @abstractmethod
    async def run(self, params: Dict[str, Any]) -> ToolResult:
        """
        Execute the tool.

        Parameters
        ----------
        params:
            Tool-specific parameters validated by the caller.

        Returns
        -------
        ToolResult
            Structured outcome of the execution.
        """
        ...
