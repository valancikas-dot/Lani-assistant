"""Builder routes – project scaffolding, file creation, and code generation."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.builder import (
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
    BuilderTaskRequest,
    BuilderTaskResponse,
)
from app.services.builder_service import (
    scaffold_project,
    create_file,
    create_readme,
    generate_feature_files,
    get_project_tree,
    propose_commands,
    run_builder_task,
)

router = APIRouter()


@router.post("/builder/scaffold", response_model=ScaffoldResponse)
async def api_scaffold_project(
    req: ScaffoldRequest,
    db: AsyncSession = Depends(get_db),
) -> ScaffoldResponse:
    """Create a new project from a template and return proposed setup commands."""
    return await scaffold_project(req, db)


@router.post("/builder/file", response_model=CreateFileResponse)
async def api_create_file(
    req: CreateFileRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateFileResponse:
    """Write a new source file (or request approval to overwrite an existing one)."""
    return await create_file(req, db)


@router.post("/builder/readme", response_model=ReadmeResponse)
async def api_create_readme(
    req: ReadmeRequest,
    db: AsyncSession = Depends(get_db),
) -> ReadmeResponse:
    """Generate a README.md for a project."""
    return await create_readme(req, db)


@router.post("/builder/feature", response_model=FeatureFilesResponse)
async def api_generate_feature_files(
    req: FeatureFilesRequest,
    db: AsyncSession = Depends(get_db),
) -> FeatureFilesResponse:
    """Generate boilerplate source files for a named feature."""
    return await generate_feature_files(req, db)


@router.get("/builder/tree", response_model=ProjectTreeResponse)
async def api_project_tree(
    project_path: str = Query(..., description="Absolute path to the project root"),
    max_depth: int = Query(4, ge=1, le=10, description="Maximum directory depth"),
    db: AsyncSession = Depends(get_db),
) -> ProjectTreeResponse:
    """Return a JSON file-tree for the given project directory."""
    return await get_project_tree(
        ProjectTreeRequest(project_path=project_path, max_depth=max_depth), db
    )


@router.post("/builder/commands", response_model=ProposeCommandsResponse)
async def api_propose_commands(
    req: ProposeCommandsRequest,
    db: AsyncSession = Depends(get_db),
) -> ProposeCommandsResponse:
    """Propose (never execute) CLI commands appropriate for the project template."""
    return await propose_commands(req, db)


@router.post("/builder/task", response_model=BuilderTaskResponse)
async def api_run_builder_task(
    req: BuilderTaskRequest,
    db: AsyncSession = Depends(get_db),
) -> BuilderTaskResponse:
    """
    High-level endpoint: scaffold a project, generate feature files, and
    return a full proposed command list in a single orchestrated call.
    """
    return await run_builder_task(req, db)
