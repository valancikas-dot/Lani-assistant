"""
Research tools – BaseTool wrappers around research_service functions.

Each class:
  - has a unique name used in the tool registry and in plan steps
  - has requires_approval = False (read-only web access, no local writes)
  - calls the corresponding research_service function
  - returns a ToolResult with .data = the serialised schema object
    so the executor / frontend can render it as a structured research card

Tool names (used in plan steps and the registry):
  • web_search
  • summarize_web_results
  • compare_research_results
  • research_and_prepare_brief
"""

from __future__ import annotations

from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.services import research_service
from app.tools.base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for a query using DuckDuckGo. "
        "Returns a structured list of results with title, URL, snippet, "
        "and source domain."
    )
    requires_approval = False
    parameters = [
        {"name": "query", "description": "The search query to look up on the web", "required": True},
        {"name": "max_results", "description": "Maximum number of results to return (default 8)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = params.get("query", "")
        max_results: int = int(params.get("max_results", 8))

        if not query:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parameter 'query' is required.",
            )

        resp = await research_service.web_search(query, max_results=max_results)

        if resp.error and not resp.results:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=resp.error,
                data=resp.model_dump(),
            )

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=(
                f"Found {resp.total_results} result(s) for '{query}'."
            ),
            data=resp.model_dump(),
        )


class SummarizeWebResultsTool(BaseTool):
    name = "summarize_web_results"
    description = (
        "Fetch a list of URLs, extract their text content, and produce an "
        "overall summary with key points and source attribution."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = params.get("query", "")
        urls: list[str] = params.get("urls", [])
        max_sources: int = int(params.get("max_sources", 5))

        if not urls:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parameter 'urls' (list) is required.",
            )

        resp = await research_service.summarize_urls(
            query=query or "summary",
            urls=urls,
            max_sources=max_sources,
        )

        status = "success" if resp.sources_succeeded > 0 else "error"
        msg = (
            f"Summarised {resp.sources_succeeded}/{resp.sources_attempted} source(s)."
            if status == "success"
            else (resp.error or "No sources could be loaded.")
        )

        return ToolResult(
            tool_name=self.name,
            status=status,
            message=msg,
            data=resp.model_dump(),
        )


class CompareResearchResultsTool(BaseTool):
    name = "compare_research_results"
    description = (
        "Compare multiple web sources on a given topic. "
        "Returns a structured comparison table with criteria, per-item scores, "
        "and a conclusion."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        topic: str = params.get("topic", "")
        urls: list[str] = params.get("urls", [])
        max_sources: int = int(params.get("max_sources", 6))

        if not topic:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parameter 'topic' is required.",
            )
        if not urls:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parameter 'urls' (list) is required.",
            )

        resp = await research_service.compare_urls(
            topic=topic,
            urls=urls,
            max_sources=max_sources,
        )

        status = "success" if resp.compared_items else "error"
        return ToolResult(
            tool_name=self.name,
            status=status,
            message=(
                f"Compared {len(resp.compared_items)} source(s) on '{topic}'."
                if status == "success"
                else (resp.error or "Comparison failed.")
            ),
            data=resp.model_dump(),
        )


class ResearchAndPrepareBriefTool(BaseTool):
    name = "research_and_prepare_brief"
    description = (
        "All-in-one research tool: searches the web, fetches top sources, "
        "summarises findings and optionally produces a comparison. "
        "Returns a concise research brief usable by the planner or "
        "presentation tools."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = params.get("query", "")
        max_sources: int = int(params.get("max_sources", 5))
        include_comparison: bool = bool(params.get("include_comparison", False))

        if not query:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parameter 'query' is required.",
            )

        brief = await research_service.research_brief(
            query=query,
            max_sources=max_sources,
            include_comparison=include_comparison,
        )

        status = "error" if (brief.error and not brief.key_points) else "success"
        return ToolResult(
            tool_name=self.name,
            status=status,
            message=(
                f"Research brief ready for '{query}': "
                f"{len(brief.key_points)} key point(s), "
                f"{len(brief.top_sources)} source(s)."
            ),
            data=brief.model_dump(),
        )
