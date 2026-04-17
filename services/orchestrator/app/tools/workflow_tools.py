"""
workflow_tools.py – Leidžia vartotojui kurti ir valdyti savo custom workflow.

Tools:
  save_custom_workflow    – išsaugo naują workflow į atmintį
  list_custom_workflows   – išvardo visus išsaugotus workflow
  delete_custom_workflow  – ištrina workflow iš atminties

Custom workflow formatas atmintyje (category='custom_workflows'):
  key   = slugified workflow pavadinimas
  value = {
    "name": "Mano workflow",
    "description": "Ką daryti",
    "trigger_phrases": ["kada aktyvuoti", ...],
    "steps": [
      {"tool": "web_search", "description": "...", "args": {...}},
      ...
    ]
  }
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")[:80]


class SaveCustomWorkflowTool(BaseTool):
    name = "save_custom_workflow"
    description = (
        "Save a custom workflow that Lani will recognise and execute automatically "
        "when the user says one of the trigger phrases. "
        "The workflow defines an ordered list of tool steps to run. "
        "Parameters: name (required), description (required), "
        "trigger_phrases (required, list of strings), "
        "steps (required, list of {tool, description, args})."
    )
    requires_approval = False
    parameters = [
        {"name": "name",            "description": "Short workflow name, e.g. 'Morning briefing'", "required": True},
        {"name": "description",     "description": "What this workflow does", "required": True},
        {"name": "trigger_phrases", "description": "List of phrases that activate this workflow", "required": True},
        {"name": "steps",           "description": "List of step objects: [{tool, description, args}]", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        name = str(params.get("name", "")).strip()
        description = str(params.get("description", "")).strip()
        trigger_phrases = params.get("trigger_phrases", [])
        steps = params.get("steps", [])

        if not name:
            return ToolResult(tool_name=self.name, status="error", message="'name' is required.")
        if not steps:
            return ToolResult(tool_name=self.name, status="error", message="'steps' list is required.")
        if not trigger_phrases:
            return ToolResult(tool_name=self.name, status="error", message="'trigger_phrases' list is required.")

        # Normalise steps – ensure each has tool + description + args
        normalised_steps = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or not s.get("tool"):
                return ToolResult(
                    tool_name=self.name, status="error",
                    message=f"Step {i} is missing 'tool' key."
                )
            normalised_steps.append({
                "index": i,
                "tool": s["tool"],
                "description": s.get("description", f"Run {s['tool']}"),
                "args": s.get("args", {}),
            })

        key = _slugify(name)
        value = {
            "name": name,
            "description": description,
            "trigger_phrases": [str(p).lower().strip() for p in trigger_phrases],
            "steps": normalised_steps,
        }

        # Persist to DB via memory_service
        try:
            from app.core.database import AsyncSessionLocal
            from app.services import memory_service
            from app.schemas.memory import MemoryEntryCreate

            async with AsyncSessionLocal() as db:
                await memory_service.write_memory(
                    db,
                    MemoryEntryCreate(
                        category="custom_workflows",
                        key=key,
                        value=value,
                        source="user_explicit",
                        confidence=1.0,
                        pinned=True,
                    ),
                )
                await db.commit()
        except Exception as exc:
            log.error("[save_custom_workflow] DB error: %s", exc)
            return ToolResult(
                tool_name=self.name, status="error",
                message=f"Could not save workflow to database: {exc}"
            )

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"Workflow '{name}' saved. Trigger with: {', '.join(repr(p) for p in trigger_phrases[:3])}",
            data={"key": key, "name": name, "step_count": len(normalised_steps)},
        )


class ListCustomWorkflowsTool(BaseTool):
    name = "list_custom_workflows"
    description = (
        "List all custom workflows saved by the user. "
        "Returns workflow names, descriptions, and trigger phrases. "
        "No parameters required."
    )
    requires_approval = False
    parameters = []

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        try:
            from app.core.database import AsyncSessionLocal
            from app.services import memory_service

            async with AsyncSessionLocal() as db:
                entries = await memory_service.get_all(
                    db, category="custom_workflows", status="active"
                )

            if not entries:
                return ToolResult(
                    tool_name=self.name, status="success",
                    message="No custom workflows saved yet.",
                    data={"workflows": []},
                )

            lines = []
            wf_list = []
            for e in entries:
                v = e.value
                n = v.get("name", e.key)
                d = v.get("description", "")
                triggers = v.get("trigger_phrases", [])
                steps = v.get("steps", [])
                lines.append(
                    f"• **{n}** ({len(steps)} steps)\n"
                    f"  {d}\n"
                    f"  Trigger: {', '.join(repr(t) for t in triggers[:3])}"
                )
                wf_list.append({"name": n, "description": d, "triggers": triggers, "step_count": len(steps)})

            return ToolResult(
                tool_name=self.name,
                status="success",
                message="\n\n".join(lines),
                data={"workflows": wf_list},
            )
        except Exception as exc:
            log.error("[list_custom_workflows] error: %s", exc)
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class DeleteCustomWorkflowTool(BaseTool):
    name = "delete_custom_workflow"
    description = (
        "Delete a custom workflow by name. "
        "Parameter: name (required) – the exact workflow name to delete."
    )
    requires_approval = False
    parameters = [
        {"name": "name", "description": "Exact workflow name to delete", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        name = str(params.get("name", "")).strip()
        if not name:
            return ToolResult(tool_name=self.name, status="error", message="'name' is required.")

        key = _slugify(name)
        try:
            from app.core.database import AsyncSessionLocal
            from app.services import memory_service
            from sqlalchemy import select, and_
            from app.models.memory_entry import MemoryEntry

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(MemoryEntry).where(
                        and_(
                            MemoryEntry.category == "custom_workflows",
                            MemoryEntry.key == key,
                        )
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return ToolResult(
                        tool_name=self.name, status="error",
                        message=f"Workflow '{name}' not found."
                    )
                await db.delete(row)
                await db.commit()

            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Workflow '{name}' deleted.",
                data={"deleted_key": key},
            )
        except Exception as exc:
            log.error("[delete_custom_workflow] error: %s", exc)
            return ToolResult(tool_name=self.name, status="error", message=str(exc))
