"""
Memory tools – let Lani save and search facts in long-term memory.

Tools:
  save_memory    – stores a key-value fact in a given category
  search_memory  – searches memory for entries matching a query string
  list_memory    – lists all memory entries (optionally filtered by category)
"""

from __future__ import annotations

from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.schemas.memory import MemoryCategory
from app.tools.base import BaseTool


_ALLOWED_MEMORY_CATEGORIES: set[MemoryCategory] = {
    "user_preferences",
    "workflow_preferences",
    "task_history",
    "suggestions",
    "scheduled_tasks",
}


class SaveMemoryTool(BaseTool):
    name = "save_memory"
    description = (
        "Save a fact or preference to Lani's long-term memory. "
        "Use this to remember user preferences, important facts, or task notes."
    )
    requires_approval = False
    parameters = [
        {"name": "key", "description": "Short identifier for this memory, e.g. 'user.favorite_color' or 'meeting.monday'", "required": True},
        {"name": "value", "description": "The value or content to remember, e.g. 'blue' or 'standup at 9am'", "required": True},
        {"name": "category", "description": "Category: 'user_preferences', 'task_history', 'workflow_preferences', or 'facts'. Defaults to 'facts'", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        key = str(params.get("key", "")).strip()
        value_raw = params.get("value", "")
        raw_category = str(params.get("category", "user_preferences")).strip() or "user_preferences"
        category: MemoryCategory = (
            raw_category if raw_category in _ALLOWED_MEMORY_CATEGORIES else "user_preferences"
        )

        if not key:
            return ToolResult(tool_name=self.name, status="error", message="'key' is required.")
        if not value_raw:
            return ToolResult(tool_name=self.name, status="error", message="'value' is required.")

        # Normalize value to dict
        if isinstance(value_raw, dict):
            value = value_raw
        else:
            value = {"data": str(value_raw)}

        try:
            from app.core.database import AsyncSessionLocal
            from app.services.memory_service import write_memory
            from app.schemas.memory import MemoryEntryCreate

            async with AsyncSessionLocal() as db:
                entry = await write_memory(
                    db,
                    MemoryEntryCreate(
                        category=category,
                        key=key,
                        value=value,
                        source="user_explicit",
                        confidence=1.0,
                    ),
                )
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Remembered: '{key}' = '{value_raw}' (category: {category}).",
                data={"id": entry.id, "key": key, "category": category},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "Search Lani's long-term memory for facts, preferences or notes. "
        "Returns matching entries."
    )
    requires_approval = False
    parameters = [
        {"name": "query", "description": "Text to search for in memory keys and values", "required": True},
        {"name": "category", "description": "Optional category filter: 'user_preferences', 'facts', 'task_history', etc.", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query = str(params.get("query", "")).strip().lower()
        category = str(params.get("category", "")).strip() or None

        if not query:
            return ToolResult(tool_name=self.name, status="error", message="'query' is required.")

        try:
            from app.core.database import AsyncSessionLocal
            from app.services.memory_service import get_all

            async with AsyncSessionLocal() as db:
                entries = await get_all(db, category=category)

            # Filter by query string in key or value
            matches = []
            for e in entries:
                key_match = query in e.key.lower()
                value_str = str(e.value).lower()
                value_match = query in value_str
                if key_match or value_match:
                    val = e.value.get("data", e.value) if isinstance(e.value, dict) else e.value
                    matches.append({"key": e.key, "value": val, "category": e.category})

            if not matches:
                return ToolResult(
                    tool_name=self.name,
                    status="success",
                    message=f"No memories found for '{query}'.",
                    data={"results": [], "count": 0},
                )

            summary = "; ".join(f"{m['key']}: {m['value']}" for m in matches[:5])
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Found {len(matches)} memory entry(ies): {summary}",
                data={"results": matches, "count": len(matches)},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class ListMemoryTool(BaseTool):
    name = "list_memory"
    description = "List all entries in Lani's long-term memory, optionally filtered by category."
    requires_approval = False
    parameters = [
        {"name": "category", "description": "Optional category filter", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        category = str(params.get("category", "")).strip() or None

        try:
            from app.core.database import AsyncSessionLocal
            from app.services.memory_service import get_all

            async with AsyncSessionLocal() as db:
                entries = await get_all(db, category=category)

            items = []
            for e in entries:
                val = e.value.get("data", e.value) if isinstance(e.value, dict) else e.value
                items.append({"key": e.key, "value": val, "category": e.category})

            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"{len(items)} memory entry(ies)." if items else "Memory is empty.",
                data={"results": items, "count": len(items)},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))
