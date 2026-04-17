"""
File system tools.

All operations are restricted to the directories listed in
settings.ALLOWED_DIRECTORIES.  Attempts to operate outside those paths
are rejected with an error result.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings
from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXTENSION_BUCKETS: Dict[str, str] = {
    ".pdf": "Documents",
    ".docx": "Documents",
    ".doc": "Documents",
    ".txt": "Documents",
    ".md": "Documents",
    ".xlsx": "Spreadsheets",
    ".xls": "Spreadsheets",
    ".csv": "Spreadsheets",
    ".pptx": "Presentations",
    ".ppt": "Presentations",
    ".jpg": "Images",
    ".jpeg": "Images",
    ".png": "Images",
    ".gif": "Images",
    ".svg": "Images",
    ".mp4": "Videos",
    ".mov": "Videos",
    ".avi": "Videos",
    ".mp3": "Audio",
    ".wav": "Audio",
    ".zip": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
}


def _allowed(path: str, allowed_dirs: list[str] | None = None) -> bool:
    """Return True if *path* is inside one of the allowed directories.

    *allowed_dirs* can be passed explicitly (e.g. loaded from the DB by the
    command router) so that runtime changes to Settings take effect without a
    restart.  Falls back to the env-based config when not provided.
    """
    allowed = allowed_dirs if allowed_dirs is not None else settings.ALLOWED_DIRECTORIES
    if not allowed:
        return False
    resolved = Path(path).resolve()
    for allowed_dir in allowed:
        try:
            resolved.relative_to(Path(allowed_dir).resolve())
            return True
        except ValueError:
            continue
    return False


# Runtime-configurable override – set by command_router from the DB each request.
# Using a mutable list so all tool instances share the same reference.
_runtime_allowed_dirs: list[str] = []


def set_runtime_allowed_dirs(dirs: list[str]) -> None:
    """Called by the command router to inject DB-stored allowed directories."""
    global _runtime_allowed_dirs
    _runtime_allowed_dirs = dirs


def _check_allowed(path: str) -> bool:
    """Use runtime dirs (from DB) when available, else fall back to config."""
    dirs = _runtime_allowed_dirs if _runtime_allowed_dirs else settings.ALLOWED_DIRECTORIES
    return _allowed(path, dirs)


def _deny(path: str) -> ToolResult:
    return ToolResult(
        tool_name="file_tools",
        status="error",
        message=f"Path '{path}' is outside allowed directories. "
                "Update Settings → Allowed Directories to grant access.",
    )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class CreateFolderTool(BaseTool):
    name = "create_folder"
    description = "Create a new directory at the given path."
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        path: str = params["path"]
        if not _check_allowed(path):
            return _deny(path)
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Folder created: {path}",
                data={"path": path},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class CreateFileTool(BaseTool):
    name = "create_file"
    description = "Create a new file with optional content."
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        path: str = params["path"]
        content: str = params.get("content", "")
        if not _check_allowed(path):
            return _deny(path)
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"File created: {path}",
                data={"path": path, "bytes_written": len(content.encode())},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class MoveFileTool(BaseTool):
    name = "move_file"
    description = "Move or rename a file from src to dst."
    requires_approval = True  # destructive – requires approval

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        src: str = params["src"]
        dst: str = params["dst"]
        for p in (src, dst):
            if not _check_allowed(p):
                return _deny(p)
        try:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Moved '{src}' → '{dst}'",
                data={"src": src, "dst": dst},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class SortDownloadsTool(BaseTool):
    name = "sort_downloads"
    description = (
        "Sort files in a directory into sub-folders by extension "
        "(Documents, Images, Videos, etc.)."
    )
    requires_approval = True  # moves many files – requires approval

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        base_path: str = params["base_path"]
        if not _check_allowed(base_path):
            return _deny(base_path)
        try:
            base = Path(base_path)
            moved: list[dict] = []
            for item in base.iterdir():
                if item.is_dir():
                    continue
                bucket = EXTENSION_BUCKETS.get(item.suffix.lower(), "Other")
                target_dir = base / bucket
                target_dir.mkdir(exist_ok=True)
                target = target_dir / item.name
                shutil.move(str(item), str(target))
                moved.append({"file": item.name, "bucket": bucket})
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Sorted {len(moved)} file(s) in '{base_path}'.",
                data={"moved": moved},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = (
        "Ieško failų kompiuteryje pagal vardą arba plėtinį (Spotlight / find). "
        "Naudoti kai vartotojas klausia 'kur yra failas X' arba 'rask visus PDF'. "
        "Parametrai: query (failo pavadinimas arba dalis), "
        "path (kur ieškoti, default namų aplankas), "
        "extension (pvz. .pdf – neprivaloma)."
    )
    requires_approval = False
    parameters = [
        {"name": "query", "description": "Failo pavadinimas arba jo dalis", "required": False},
        {"name": "path", "description": "Aplankas kuriame ieškoti", "required": False},
        {"name": "extension", "description": "Plėtinys pvz. .pdf", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        import subprocess
        query: str = params.get("query", "").strip()
        search_path: str = params.get("path", str(Path.home())).strip()
        extension: str = params.get("extension", "").strip()

        if not query and not extension:
            return ToolResult(tool_name=self.name, status="error", message="Nurodykite query arba extension.")

        try:
            if query:
                # macOS Spotlight – greičiausia
                cmd = ["mdfind", "-name", query]
                if search_path and search_path != str(Path.home()):
                    cmd += ["-onlyin", search_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                files = [f for f in result.stdout.strip().splitlines() if f]
            else:
                # Tik plėtinys – find
                ext = extension if extension.startswith(".") else "." + extension
                cmd = ["find", search_path, "-name", f"*{ext}", "-not", "-path", "*/.*"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                files = [f for f in result.stdout.strip().splitlines() if f]

            # Filtras pagal plėtinį jei abu nurodyti
            if extension and query:
                ext = extension if extension.startswith(".") else "." + extension
                files = [f for f in files if f.lower().endswith(ext.lower())]

            files = files[:20]

            if not files:
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"Nerasta failų pagal '{query or extension}'.",
                    data={"files": []},
                )

            text = "\n".join(f"• {f}" for f in files)
            return ToolResult(
                tool_name=self.name, status="success",
                message=f"Rasta {len(files)} failas(-ų):\n{text}",
                data={"files": files, "count": len(files)},
            )
        except Exception as exc:
            return ToolResult(tool_name=self.name, status="error", message=str(exc))
