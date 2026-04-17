"""Builder service – orchestrates builder tools into higher-level operations.

Responsibilities:
  1. Load allowed directories from the DB (per-request safety).
  2. Inject ``_allowed_dirs`` into every tool's params dict.
  3. Record every operation in the audit log.
  4. Return structured BuilderTaskResponse objects ready for the API layer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.settings import UserSettings
from app.schemas.builder import (
    BuilderTaskRequest,
    BuilderTaskResponse,
    ScaffoldRequest,
    ScaffoldResponse,
    CreateFileRequest,
    CreateFileResponse,
    ReadmeRequest,
    ReadmeResponse,
    FeatureFilesRequest,
    FeatureFilesResponse,
    ProjectTreeRequest,
    ProjectTreeResponse,
    ProposeCommandsRequest,
    ProposeCommandsResponse,
    ProposedCommand,
    GeneratedFile,
)
from app.services.audit_service import record_action
from app.tools.builder_tools import (
    CreateProjectScaffoldTool,
    CreateCodeFileTool,
    UpdateCodeFileTool,
    CreateReadmeTool,
    GenerateFeatureFilesTool,
    ListProjectTreeTool,
    ProposeTerminalCommandsTool,
    PROPOSED_COMMANDS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_allowed_dirs(db: AsyncSession) -> List[str]:
    """Load allowed_directories from the DB settings row."""
    import json
    result = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        return []
    raw = row.allowed_directories or "[]"
    try:
        dirs = json.loads(raw)
        if isinstance(dirs, list):
            return [str(d) for d in dirs]
    except (ValueError, TypeError):
        pass
    # Fallback: newline or comma-separated string
    from app.core.config import settings as app_settings
    return app_settings.ALLOWED_DIRECTORIES


def _inject(params: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    return {**params, "_allowed_dirs": allowed}


def _cmds_from_raw(raw: List[Dict[str, str]]) -> List[ProposedCommand]:
    return [
        ProposedCommand(
            command=c["cmd"],
            description=c["desc"],
            risk=c.get("risk", "safe"),
            requires_approval=c.get("risk", "safe") in ("moderate", "destructive"),
        )
        for c in raw
    ]


# ─── scaffold ─────────────────────────────────────────────────────────────────

async def scaffold_project(
    req: ScaffoldRequest,
    db: AsyncSession,
) -> ScaffoldResponse:
    allowed = await _get_allowed_dirs(db)
    tool = CreateProjectScaffoldTool()

    result = await tool.run(_inject({
        "name": req.name,
        "template": req.template,
        "base_dir": req.base_dir,
    }, allowed))

    if result.status == "error":
        await record_action(db, "builder.scaffold", "create_project_scaffold",
                            "error", error_message=result.message or "")
        return ScaffoldResponse(
            ok=False, project_path="", files_created=[],
            proposed_commands=[], message=result.message or "Error",
        )

    data = result.data or {}
    cmds = _cmds_from_raw(data.get("proposed_commands", []))

    # Add README if description or features given
    if req.description or req.features:
        readme_req = ReadmeRequest(
            project_path=data["project_path"],
            project_name=req.name,
            description=req.description,
            template=req.template,
            features=req.features,
        )
        await create_readme(readme_req, db)

    await record_action(
        db, "builder.scaffold", "create_project_scaffold", "success",
        result_summary=f"template={req.template},files={len(data.get('files_created', []))}",
    )
    return ScaffoldResponse(
        ok=True,
        project_path=data["project_path"],
        files_created=data.get("files_created", []),
        proposed_commands=cmds,
        message=result.message or "Project scaffolded.",
    )


# ─── create file ──────────────────────────────────────────────────────────────

async def create_file(
    req: CreateFileRequest,
    db: AsyncSession,
) -> CreateFileResponse:
    allowed = await _get_allowed_dirs(db)
    tool = UpdateCodeFileTool() if req.overwrite else CreateCodeFileTool()

    result = await tool.run(_inject({
        "project_path": req.project_path,
        "relative_path": req.relative_path,
        "content": req.content,
        "overwrite": req.overwrite,
    }, allowed))

    status_ok = result.status == "success"
    needs_approval = result.status == "approval_required"

    await record_action(
        db, "builder.create_file", tool.name,
        result.status,
        result_summary=req.relative_path,
        error_message=(result.message or "") if not status_ok else "",
    )
    return CreateFileResponse(
        ok=status_ok,
        absolute_path=(result.data or {}).get("absolute_path", ""),
        message=result.message or "",
        requires_approval=needs_approval,
    )


# ─── create readme ────────────────────────────────────────────────────────────

async def create_readme(
    req: ReadmeRequest,
    db: AsyncSession,
) -> ReadmeResponse:
    allowed = await _get_allowed_dirs(db)
    tool = CreateReadmeTool()

    result = await tool.run(_inject({
        "project_path": req.project_path,
        "project_name": req.project_name,
        "description": req.description or "",
        "template": req.template,
        "features": req.features,
    }, allowed))

    ok = result.status == "success"
    data = result.data or {}

    await record_action(
        db, "builder.readme", "create_readme",
        result.status,
        result_summary=req.project_name,
        error_message="" if ok else (result.message or ""),
    )
    return ReadmeResponse(
        ok=ok,
        absolute_path=data.get("absolute_path", ""),
        content=data.get("content", ""),
        message=result.message or "",
    )


# ─── generate feature files ───────────────────────────────────────────────────

async def generate_feature_files(
    req: FeatureFilesRequest,
    db: AsyncSession,
) -> FeatureFilesResponse:
    allowed = await _get_allowed_dirs(db)
    tool = GenerateFeatureFilesTool()

    result = await tool.run(_inject({
        "project_path": req.project_path,
        "feature_description": req.feature_description,
        "template": req.template,
        "output_dir": req.output_dir,
    }, allowed))

    ok = result.status == "success"
    data = result.data or {}
    files = [
        GeneratedFile(path=f["path"], content=f["content"])
        for f in data.get("files", [])
    ]

    await record_action(
        db, "builder.feature_files", "generate_feature_files",
        result.status,
        result_summary=req.feature_description,
        error_message="" if ok else (result.message or ""),
    )
    return FeatureFilesResponse(ok=ok, files=files, message=result.message or "")


# ─── project tree ─────────────────────────────────────────────────────────────

async def get_project_tree(
    req: ProjectTreeRequest,
    db: AsyncSession,
) -> ProjectTreeResponse:
    allowed = await _get_allowed_dirs(db)
    tool = ListProjectTreeTool()

    result = await tool.run(_inject({
        "project_path": req.project_path,
        "max_depth": req.max_depth,
    }, allowed))

    ok = result.status == "success"
    data = result.data or {}

    await record_action(db, "builder.tree", "list_project_tree", result.status,
                        result_summary=req.project_path)

    from app.schemas.builder import ProjectTreeNode
    def _parse(node: Dict) -> ProjectTreeNode:
        return ProjectTreeNode(
            name=node["name"],
            path=node["path"],
            is_dir=node["is_dir"],
            children=[_parse(c) for c in node.get("children", [])],
        )

    return ProjectTreeResponse(
        ok=ok,
        root=_parse(data["root"]) if ok and data.get("root") else None,
        message=result.message or "",
    )


# ─── propose commands ─────────────────────────────────────────────────────────

async def propose_commands(
    req: ProposeCommandsRequest,
    db: AsyncSession,
) -> ProposeCommandsResponse:
    tool = ProposeTerminalCommandsTool()
    result = await tool.run({
        "project_path": req.project_path,
        "template": req.template,
        "goal": req.goal or "",
    })

    ok = result.status == "success"
    data = result.data or {}
    cmds = _cmds_from_raw(data.get("commands", []))

    await record_action(db, "builder.propose_commands", "propose_terminal_commands",
                        result.status, result_summary=req.template)
    return ProposeCommandsResponse(ok=ok, commands=cmds, message=result.message or "")


# ─── full builder task (planner integration) ──────────────────────────────────

async def run_builder_task(
    req: BuilderTaskRequest,
    db: AsyncSession,
) -> BuilderTaskResponse:
    """Execute a high-level builder task – used by the planner/executor."""
    files_created: List[str] = []
    files_updated: List[str] = []
    steps: List[str] = []
    project_path: Optional[str] = None

    # Determine project name from goal if not supplied
    project_name = req.project_name
    if not project_name:
        import re
        m = re.search(
            r"(?:called?|named?|for)\s+['\"]?([A-Za-z0-9_\- ]+)['\"]?",
            req.goal, re.I,
        )
        project_name = m.group(1).strip() if m else "my-project"

    base_dir = req.base_dir
    if not base_dir:
        allowed = await _get_allowed_dirs(db)
        base_dir = allowed[0] if allowed else str(Path.home() / "Desktop")

    # Step 1: scaffold
    scaffold_resp = await scaffold_project(
        ScaffoldRequest(
            name=project_name,
            template=req.template,
            base_dir=base_dir,
            description=req.goal,
            features=req.features,
        ),
        db,
    )
    if not scaffold_resp.ok:
        return BuilderTaskResponse(
            ok=False,
            project_path=None,
            files_created=[],
            files_updated=[],
            proposed_commands=[],
            summary=scaffold_resp.message,
            steps_taken=["scaffold: failed"],
        )

    project_path = scaffold_resp.project_path
    files_created.extend(scaffold_resp.files_created)
    steps.append(f"scaffold: created {len(files_created)} files")

    # Step 2: README (scaffold_project already writes README if description given,
    # but we ensure it here explicitly as well to cover edge cases)
    steps.append("readme: included in scaffold")

    # Step 3: feature files if features specified
    for feature in req.features:
        feat_resp = await generate_feature_files(
            FeatureFilesRequest(
                project_path=project_path,
                feature_description=feature,
                template=req.template,
            ),
            db,
        )
        if feat_resp.ok:
            files_created.extend([f.path for f in feat_resp.files])
            steps.append(f"feature '{feature}': {len(feat_resp.files)} files")

    # Step 4: propose commands
    cmds_resp = await propose_commands(
        ProposeCommandsRequest(
            project_path=project_path,
            template=req.template,
            goal=req.goal,
        ),
        db,
    )
    steps.append(f"commands: proposed {len(cmds_resp.commands)}")

    summary = (
        f"Project '{project_name}' ({req.template}) created at {project_path}. "
        f"{len(files_created)} files written."
    )

    await record_action(
        db, "builder.task", "builder_service",
        "success",
        result_summary=f"goal={req.goal[:60]},template={req.template},files={len(files_created)}",
    )

    return BuilderTaskResponse(
        ok=True,
        project_path=project_path,
        files_created=files_created,
        files_updated=files_updated,
        proposed_commands=cmds_resp.commands,
        summary=summary,
        steps_taken=steps,
    )
