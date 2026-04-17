"""Pydantic schemas for tool parameter contracts."""

from typing import Any, Dict, Optional
from pydantic import BaseModel


class CreateFolderParams(BaseModel):
    path: str


class CreateFileParams(BaseModel):
    path: str
    content: str = ""


class MoveFileParams(BaseModel):
    src: str
    dst: str


class SortDownloadsParams(BaseModel):
    base_path: str


class ReadDocumentParams(BaseModel):
    path: str


class SummarizeDocumentParams(BaseModel):
    path: str


class CreatePresentationParams(BaseModel):
    title: str
    outline: list[str]
    output_path: str


class ToolCallSchema(BaseModel):
    """Generic wrapper used internally when dispatching tools."""
    tool_name: str
    params: Dict[str, Any]
    requires_approval: bool = False
