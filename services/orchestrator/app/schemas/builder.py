"""Pydantic schemas for Builder Mode endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ─── Shared enums ─────────────────────────────────────────────────────────────

ProjectTemplate = Literal[
    "react",
    "react-ts",
    "nextjs",
    "vite-react",
    "fastapi",
    "python-script",
    "node-express",
    "static-html",
    "mobile-expo",
    "generic",
]

CommandRisk = Literal["safe", "moderate", "destructive"]


# ─── Proposed terminal command ─────────────────────────────────────────────────

class ProposedCommand(BaseModel):
    """A single terminal command proposed by the builder."""

    command: str
    description: str
    risk: CommandRisk = "safe"
    requires_approval: bool = False
    cwd: Optional[str] = None


# ─── Generated file ────────────────────────────────────────────────────────────

class GeneratedFile(BaseModel):
    """A file path + content pair produced by the builder."""

    path: str
    """Relative path inside the project root."""

    content: str
    """Full text content to write."""

    is_new: bool = True
    """False when this is an update to an existing file."""


# ─── Project scaffold ──────────────────────────────────────────────────────────

class ScaffoldRequest(BaseModel):
    name: str = Field(..., description="Project name (becomes the root folder name)")
    template: ProjectTemplate = "generic"
    base_dir: str = Field(..., description="Absolute base directory to create the project in")
    description: Optional[str] = None
    features: List[str] = Field(default_factory=list,
                                description="Optional feature keywords, e.g. ['auth', 'api', 'db']")


class ScaffoldResponse(BaseModel):
    ok: bool
    project_path: str
    files_created: List[str]
    proposed_commands: List[ProposedCommand]
    message: str
    requires_approval: bool = False


# ─── Single code file ──────────────────────────────────────────────────────────

class CreateFileRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project root")
    relative_path: str = Field(..., description="Relative path inside project, e.g. 'src/App.tsx'")
    content: str
    overwrite: bool = False


class CreateFileResponse(BaseModel):
    ok: bool
    absolute_path: str
    message: str
    requires_approval: bool = False


# ─── README ────────────────────────────────────────────────────────────────────

class ReadmeRequest(BaseModel):
    project_path: str
    project_name: str
    description: Optional[str] = None
    template: ProjectTemplate = "generic"
    features: List[str] = Field(default_factory=list)


class ReadmeResponse(BaseModel):
    ok: bool
    absolute_path: str
    content: str
    message: str


# ─── Feature file generation ───────────────────────────────────────────────────

class FeatureFilesRequest(BaseModel):
    project_path: str
    feature_description: str
    template: ProjectTemplate = "generic"
    output_dir: str = "src"


class FeatureFilesResponse(BaseModel):
    ok: bool
    files: List[GeneratedFile]
    message: str


# ─── Project tree ─────────────────────────────────────────────────────────────

class ProjectTreeRequest(BaseModel):
    project_path: str
    max_depth: int = Field(default=4, ge=1, le=8)


class ProjectTreeNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    children: List["ProjectTreeNode"] = Field(default_factory=list)


ProjectTreeNode.model_rebuild()


class ProjectTreeResponse(BaseModel):
    ok: bool
    root: Optional[ProjectTreeNode]
    message: str


# ─── Terminal commands ────────────────────────────────────────────────────────

class ProposeCommandsRequest(BaseModel):
    project_path: str
    template: ProjectTemplate = "generic"
    goal: Optional[str] = None


class ProposeCommandsResponse(BaseModel):
    ok: bool
    commands: List[ProposedCommand]
    message: str


# ─── Full builder task (used by planner integration) ──────────────────────────

class BuilderTaskRequest(BaseModel):
    """Top-level request sent by the chat planner for a builder task."""
    goal: str
    template: ProjectTemplate = "generic"
    base_dir: Optional[str] = None
    project_name: Optional[str] = None
    features: List[str] = Field(default_factory=list)


class BuilderTaskResponse(BaseModel):
    ok: bool
    project_path: Optional[str]
    files_created: List[str]
    files_updated: List[str]
    proposed_commands: List[ProposedCommand]
    summary: str
    steps_taken: List[str]
    requires_approval: bool = False
