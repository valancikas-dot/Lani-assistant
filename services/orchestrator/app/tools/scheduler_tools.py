"""
scheduler_tools.py – Tool wrappers for Lani's proactive task scheduler.

Exposes the scheduler_service API as standard BaseTool subclasses so that
the command router, task planner, and agent_loop can all schedule, list,
and delete timed tasks through the normal tool interface.

Tools:
  ScheduleTaskTool      – schedule a command once or on a cron
  ListScheduledTasksTool – list all active scheduled tasks
  DeleteScheduledTaskTool – cancel and remove a task by ID
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


class ScheduleTaskTool(BaseTool):
    """Schedule a command to run at a specific time or on a recurring cron schedule.

    Params (one of run_at or cron_expr is required):
        command   – the natural-language command to execute on schedule
                    (e.g. "check email", "send daily report")
        run_at    – ISO-8601 datetime string for a one-time run
                    (e.g. "2025-06-15T09:00:00")
        cron_expr – 5-field cron expression for recurring tasks
                    (e.g. "0 8 * * *" = every day at 08:00)
        task_id   – optional custom ID (auto-generated if omitted)

    Alternatively, you may pass `natural_language` and the scheduler will
    parse the time from the command string (e.g. "every morning check email").
    """

    name = "schedule_task"
    description = (
        "Schedule a command to execute at a specific time or on a recurring schedule. "
        "Supports one-time ('run_at') and recurring ('cron_expr') triggers. "
        "Also accepts free-form 'natural_language' for automatic time extraction."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        command: str = params.get("command", "").strip()
        run_at_str: str = params.get("run_at", "").strip()
        cron_expr: str = params.get("cron_expr", "").strip()
        natural: str = params.get("natural_language", "").strip()
        task_id: str | None = params.get("task_id") or None

        # Try auto-parsing natural language if no explicit trigger
        if natural and not run_at_str and not cron_expr:
            command = natural
            try:
                from app.services.scheduler_service import parse_schedule_from_command
                parsed = await parse_schedule_from_command(natural)
                if parsed["detected"]:
                    command = parsed["clean_command"] or natural
                    run_at_str = parsed["run_at"].isoformat() if parsed.get("run_at") else ""
                    cron_expr = parsed.get("cron_expr") or ""
                else:
                    return ToolResult(
                        tool_name=self.name,
                        status="error",
                        message=(
                            f"Nepavyko aptikti laiko iš teksto: '{natural}'. "
                            "Nurodykite 'run_at' arba 'cron_expr'."
                        ),
                    )
            except Exception as exc:
                log.warning("[schedule_task] parse failed: %s", exc)
                return ToolResult(tool_name=self.name, status="error", message=str(exc))

        if not command:
            return ToolResult(tool_name=self.name, status="error",
                              message="Parametras 'command' arba 'natural_language' yra privalomas.")

        if not run_at_str and not cron_expr:
            return ToolResult(tool_name=self.name, status="error",
                              message="Nurodykite 'run_at' (data/laikas) arba 'cron_expr'.")

        try:
            from app.services.scheduler_service import schedule_task

            run_at = None
            if run_at_str:
                from datetime import datetime
                run_at = datetime.fromisoformat(run_at_str)

            record = await schedule_task(
                command=command,
                run_at=run_at,
                cron_expr=cron_expr or None,
                task_id=task_id,
            )

            trigger_desc = (
                f"vienkartinis {run_at_str}" if run_at else f"kartojamas ({cron_expr})"
            )
            return ToolResult(
                tool_name=self.name,
                status="success",
                data=record,
                message=(
                    f"✅ Užduotis suplanuota! ID: {record['id']}\n"
                    f"📋 Komanda: '{command}'\n"
                    f"⏰ Paleidimas: {trigger_desc}"
                ),
            )
        except Exception as exc:
            log.warning("[schedule_task] failed: %s", exc)
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class ListScheduledTasksTool(BaseTool):
    """Return all currently active scheduled tasks."""

    name = "list_scheduled_tasks"
    description = (
        "List all scheduled tasks that are currently active. "
        "Use when the user asks 'what tasks are scheduled?', "
        "'kokios užduotys suplanuotos?', 'show my reminders'."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        try:
            from app.core.database import AsyncSessionLocal
            from app.services.scheduler_service import list_tasks
            async with AsyncSessionLocal() as db:
                tasks = await list_tasks(db)
        except Exception as exc:
            log.warning("[list_scheduled_tasks] failed: %s", exc)
            return ToolResult(tool_name=self.name, status="error", message=str(exc))

        if not tasks:
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"tasks": [], "count": 0},
                message="Nėra aktyvių suplanuotų užduočių.",
            )

        lines = [f"📅 Aktyvios suplanuotos užduotys ({len(tasks)}):"]
        for t in tasks:
            trigger = t.get("trigger", {})
            if trigger.get("type") == "date":
                when = trigger.get("run_at", "?")
                trigger_str = f"vienkartinis: {when}"
            else:
                trigger_str = f"cron: {trigger.get('cron_expr', '?')}"
            lines.append(f"  🆔 {t.get('id', '?')} | {trigger_str} | '{t.get('command', '')}'")

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={"tasks": tasks, "count": len(tasks)},
            message="\n".join(lines),
        )


class DeleteScheduledTaskTool(BaseTool):
    """Cancel and permanently remove a scheduled task by its ID."""

    name = "delete_scheduled_task"
    description = (
        "Cancel and delete a scheduled task by its ID. "
        "Use when the user says 'cancel reminder', 'ištrink užduotį', "
        "'stop the daily check'. Use list_scheduled_tasks first to get the ID."
    )
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        task_id: str = params.get("task_id", "").strip()
        if not task_id:
            return ToolResult(tool_name=self.name, status="error",
                              message="Parametras 'task_id' yra privalomas.")

        try:
            from app.core.database import AsyncSessionLocal
            from app.services.scheduler_service import delete_task
            async with AsyncSessionLocal() as db:
                removed = await delete_task(task_id, db)
        except Exception as exc:
            log.warning("[delete_scheduled_task] failed: %s", exc)
            return ToolResult(tool_name=self.name, status="error", message=str(exc))

        if removed:
            return ToolResult(
                tool_name=self.name,
                status="success",
                data={"task_id": task_id, "removed": True},
                message=f"✅ Užduotis '{task_id}' sėkmingai ištrinta.",
            )
        return ToolResult(
            tool_name=self.name,
            status="error",
            data={"task_id": task_id, "removed": False},
            message=f"Užduotis '{task_id}' nerasta arba jau ištrinta.",
        )
