"""
conversation_tools.py – Long-term conversation archive & recall tools.

Lani can now answer:
  "ką mes kalbėjome apie X?"          → SearchConversationsTool
  "ką aš veikiau šiandien?"            → RecallTodayTool
  "savaitės apžvalga"                   → RecallWeekTool
  "parodyk paskutinius pokalbius"       → ListRecentConversationsTool

All data comes from the `episodic_memory` table which is written to
automatically on every chat turn.  No extra DB writes needed here.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


# ─── Search conversations ──────────────────────────────────────────────────────

class SearchConversationsTool(BaseTool):
    """Semantic search over all past conversation turns."""

    name = "search_conversations"
    description = (
        "Search the long-term conversation archive for turns related to a query. "
        "Use this when the user asks 'what did we talk about regarding X?', "
        "'ką kalbėjome apie X?', or similar memory-recall questions."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = params.get("query", "").strip()
        limit: int = int(params.get("limit", 10))
        days_back: int = int(params.get("days_back", 90))

        if not query:
            return ToolResult(
                tool_name=self.name,
                status="error",
                message="Parametras 'query' yra privalomas.",
            )

        try:
            from app.services.episodic_memory_service import recall
            events = await recall(
                query=query,
                limit=limit,
                days_back=days_back,
                event_type="conversation",
            )
        except Exception as exc:
            log.warning("[search_conversations] recall failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=f"Paieška nepavyko: {exc}",
            )

        if not events:
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"results": [], "count": 0},
                message=f"Nerasta jokių pokalbių susijusių su '{query}'.",
            )

        results = []
        for ev in events:
            ts = ev.created_at.strftime("%Y-%m-%d %H:%M")
            results.append({
                "timestamp": ts,
                "user": ev.user_message[:300],
                "assistant": ev.assistant_response[:500],
            })

        summary_lines = [f"📚 Rasta {len(results)} pokalbių susijusių su '{query}':"]
        for r in results:
            summary_lines.append(
                f"\n  🕐 {r['timestamp']}\n"
                f"  👤 {r['user']}\n"
                f"  🤖 {r['assistant'][:200]}…" if len(r['assistant']) > 200 else
                f"\n  🕐 {r['timestamp']}\n"
                f"  👤 {r['user']}\n"
                f"  🤖 {r['assistant']}"
            )

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={"results": results, "count": len(results), "query": query},
            message="\n".join(summary_lines),
        )


# ─── Recall today ──────────────────────────────────────────────────────────────

class RecallTodayTool(BaseTool):
    """Return a summary of today's activity (conversations + tool calls)."""

    name = "recall_today"
    description = (
        "Show a summary of everything Lani did and discussed today. "
        "Use when the user asks 'ką veikiau šiandien?', 'what did I do today?', "
        "'today's summary', 'šiandienos apžvalga'."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        session_id: str = params.get("session_id", "default")
        try:
            from app.services.episodic_memory_service import recall_today
            summary = await recall_today(session_id=session_id)
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"summary": summary},
                message=summary,
            )
        except Exception as exc:
            log.warning("[recall_today] failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=f"Nepavyko gauti šiandienos apžvalgos: {exc}",
            )


# ─── Recall week ───────────────────────────────────────────────────────────────

class RecallWeekTool(BaseTool):
    """Return a statistical summary of the past 7 days."""

    name = "recall_week"
    description = (
        "Show a weekly activity summary with counts of conversations and tool calls. "
        "Use when the user asks 'savaitės apžvalga', 'what happened this week?', "
        "'weekly summary'."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        try:
            from app.services.episodic_memory_service import recall_week_summary
            summary = await recall_week_summary()
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"summary": summary},
                message=summary,
            )
        except Exception as exc:
            log.warning("[recall_week] failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=f"Nepavyko gauti savaitės apžvalgos: {exc}",
            )


# ─── List recent conversations ────────────────────────────────────────────────

class ListRecentConversationsTool(BaseTool):
    """List the N most recent conversation turns with timestamps."""

    name = "list_recent_conversations"
    description = (
        "List the most recent conversation turns with full timestamps. "
        "Use when the user asks 'show recent chat', 'parodyk paskutinius pokalbius', "
        "'what did we last discuss?'."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        limit: int = int(params.get("limit", 10))
        days_back: int = int(params.get("days_back", 30))

        try:
            from app.services.episodic_memory_service import recall
            events = await recall(
                query="conversation",   # broad – all recent convs
                limit=limit,
                days_back=days_back,
                event_type="conversation",
            )
            # Sort chronologically for readability
            events = sorted(events, key=lambda e: e.created_at)
        except Exception as exc:
            log.warning("[list_recent_conversations] failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                status="error",
                message=f"Nepavyko gauti pokalbių: {exc}",
            )

        if not events:
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"results": [], "count": 0},
                message="Nerasta jokių pokalbių.",
            )

        results = []
        for ev in events:
            ts = ev.created_at.strftime("%Y-%m-%d %H:%M")
            results.append({
                "timestamp": ts,
                "user": ev.user_message[:300],
                "assistant": ev.assistant_response[:300],
            })

        lines = [f"📖 Paskutiniai {len(results)} pokalbiai:"]
        for r in results:
            lines.append(f"\n  [{r['timestamp']}]\n  👤 {r['user']}\n  🤖 {r['assistant']}")

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={"results": results, "count": len(results)},
            message="\n".join(lines),
        )
