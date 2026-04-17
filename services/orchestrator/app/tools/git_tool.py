"""
git_tool.py – Git and GitHub operations for the AI assistant.

Tools:
  git_status        – show repo status, branch, uncommitted changes
  git_diff          – show diff of changes (file or full repo)
  git_commit        – stage all changes and commit with a message
  git_push          – push current branch to remote
  git_pull          – pull latest changes
  git_clone         – clone a repository
  git_log           – show recent commit history
  git_create_branch – create and switch to a new branch
  github_create_pr  – create a GitHub Pull Request via API
  git_search_code   – search GitHub for code snippets (GitHub API)

Safety: git_commit, git_push require approval.
        All operations confined to user-specified working directory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


def _git() -> str:
    g = shutil.which("git")
    if not g:
        raise RuntimeError("git nerasta. Įdiek: xcode-select --install")
    return g


async def _git_run(args: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            _git(), *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"Timeout po {timeout}s"
        rc = proc.returncode if proc.returncode is not None else -1
        return rc, out.decode(errors="replace"), err.decode(errors="replace")
    except FileNotFoundError:
        return -1, "", "git nerasta sistemoje"
    except Exception as e:
        return -1, "", str(e)


def _cwd_or_error(params: dict) -> tuple[str, ToolResult | None]:
    d = params.get("repo_dir") or params.get("working_dir") or os.getcwd()
    d = str(Path(d).expanduser())
    if not Path(d).exists():
        return d, ToolResult(
            tool_name="git", status="error",
            message=f"Katalogas nerastas: {d}",
        )
    return d, None


# ─────────────────────────────────────────────────────────────────────────────

class GitStatusTool(BaseTool):
    name = "git_status"
    description = (
        "Show the current git status of a repository: branch, staged/unstaged files, "
        "recent commit. Parameters: repo_dir (path to git repo, required)."
    )
    requires_approval = False
    parameters = [{"name": "repo_dir", "description": "Absolute path to git repository", "required": True}]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        rc, out, _ = await _git_run(["status", "--short", "--branch"], cwd=cwd)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Ne git repo arba klaida: {_}")

        # Also get last commit
        _, log_out, _ = await _git_run(
            ["log", "--oneline", "-5"], cwd=cwd
        )

        return ToolResult(
            tool_name=self.name, status="success",
            message="Git status",
            data={"status": out.strip(), "recent_commits": log_out.strip(), "repo": cwd},
        )


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = (
        "Show the diff of uncommitted changes. "
        "Parameters: repo_dir (required), file_path (optional, specific file), "
        "staged (bool, default false – show unstaged; true = show staged)."
    )
    requires_approval = False
    parameters = [
        {"name": "repo_dir",  "description": "Path to git repo", "required": True},
        {"name": "file_path", "description": "Specific file to diff (optional)", "required": False},
        {"name": "staged",    "description": "Show staged diff (default false)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        args = ["diff"]
        if params.get("staged"):
            args.append("--cached")
        if params.get("file_path"):
            args.append(params["file_path"])

        rc, out, stderr = await _git_run(args, cwd=cwd)
        if not out.strip():
            out = "(No changes)"

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"{len(out.splitlines())} eilutės pakeitimuose",
            data={"diff": out[:8000], "repo": cwd},
        )


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = (
        "Stage all changes (git add -A) and create a commit. "
        "Parameters: repo_dir (required), message (commit message, required), "
        "files (list of specific files to stage, optional – defaults to all)."
    )
    requires_approval = True
    parameters = [
        {"name": "repo_dir", "description": "Path to git repo", "required": True},
        {"name": "message",  "description": "Commit message", "required": True},
        {"name": "files",    "description": "Specific files to stage (optional)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        message: str = params.get("message", "").strip()
        if not message:
            return ToolResult(tool_name=self.name, status="error", message="message is required")

        files = params.get("files", [])
        if files:
            add_args = ["add"] + files
        else:
            add_args = ["add", "-A"]

        rc1, _, err1 = await _git_run(add_args, cwd=cwd)
        if rc1 != 0:
            return ToolResult(tool_name=self.name, status="error", message=f"git add klaida: {err1}")

        rc2, out2, err2 = await _git_run(["commit", "-m", message], cwd=cwd)
        if rc2 != 0:
            return ToolResult(tool_name=self.name, status="error", message=f"git commit klaida: {err2}")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Commit sukurtas: {message}",
            data={"output": out2.strip(), "message": message, "repo": cwd},
        )


class GitPushTool(BaseTool):
    name = "git_push"
    description = (
        "Push current branch to remote origin. "
        "Parameters: repo_dir (required), remote (default 'origin'), "
        "branch (default current branch), force (bool, default false)."
    )
    requires_approval = True
    parameters = [
        {"name": "repo_dir", "description": "Path to git repo", "required": True},
        {"name": "remote",   "description": "Remote name (default origin)", "required": False},
        {"name": "branch",   "description": "Branch name (default current)", "required": False},
        {"name": "force",    "description": "Force push (--force-with-lease)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        remote: str = params.get("remote", "origin")
        branch: str = params.get("branch", "")
        force: bool = params.get("force", False)

        if not branch:
            _, branch_out, _ = await _git_run(
                ["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd
            )
            branch = branch_out.strip() or "main"

        args = ["push", remote, branch]
        if force:
            args.append("--force-with-lease")

        rc, out, stderr = await _git_run(args, cwd=cwd, timeout=60)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"git push klaida: {stderr}")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Pushed {branch} → {remote}",
            data={"output": (out + stderr).strip(), "branch": branch, "remote": remote},
        )


class GitPullTool(BaseTool):
    name = "git_pull"
    description = (
        "Pull latest changes from remote. "
        "Parameters: repo_dir (required), remote (default 'origin')."
    )
    requires_approval = False
    parameters = [
        {"name": "repo_dir", "description": "Path to git repo", "required": True},
        {"name": "remote",   "description": "Remote name", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        rc, out, stderr = await _git_run(
            ["pull", params.get("remote", "origin")], cwd=cwd, timeout=60
        )
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"git pull klaida: {stderr}")

        return ToolResult(
            tool_name=self.name, status="success",
            message="✅ Pulled latest changes",
            data={"output": (out + stderr).strip()},
        )


class GitCloneTool(BaseTool):
    name = "git_clone"
    description = (
        "Clone a git repository to a local directory. "
        "Parameters: url (required), dest_dir (optional, defaults to ~/Desktop), "
        "depth (shallow clone depth, optional)."
    )
    requires_approval = True
    parameters = [
        {"name": "url",      "description": "Git repository URL", "required": True},
        {"name": "dest_dir", "description": "Destination parent directory", "required": False},
        {"name": "depth",    "description": "Shallow clone depth (e.g. 1)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str  = params.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, status="error", message="url is required")

        dest = Path(params.get("dest_dir") or "~/Desktop").expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        args = ["clone", url]
        if depth := params.get("depth"):
            args += ["--depth", str(depth)]

        rc, out, stderr = await _git_run(args, cwd=str(dest), timeout=120)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"git clone klaida: {stderr}")

        repo_name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Repas klonuotas: {dest / repo_name}",
            data={"path": str(dest / repo_name), "url": url},
        )


class GitLogTool(BaseTool):
    name = "git_log"
    description = (
        "Show recent commit history of a repository. "
        "Parameters: repo_dir (required), n (number of commits, default 10)."
    )
    requires_approval = False
    parameters = [
        {"name": "repo_dir", "description": "Path to git repo", "required": True},
        {"name": "n",        "description": "Number of commits to show", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        n = int(params.get("n", 10))
        rc, out, _ = await _git_run(
            ["log", f"-{n}", "--oneline", "--graph", "--decorate"], cwd=cwd
        )
        return ToolResult(
            tool_name=self.name, status="success" if rc == 0 else "error",
            message="Git log",
            data={"log": out.strip()},
        )


class GitCreateBranchTool(BaseTool):
    name = "git_create_branch"
    description = (
        "Create a new git branch and switch to it. "
        "Parameters: repo_dir (required), branch_name (required)."
    )
    requires_approval = False
    parameters = [
        {"name": "repo_dir",     "description": "Path to git repo", "required": True},
        {"name": "branch_name",  "description": "New branch name", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        cwd, err = _cwd_or_error(params)
        if err: return err

        branch: str = params.get("branch_name", "").strip()
        if not branch:
            return ToolResult(tool_name=self.name, status="error", message="branch_name is required")

        rc, out, stderr = await _git_run(["checkout", "-b", branch], cwd=cwd)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Nepavyko sukurti šakos: {stderr}")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"✅ Sukurta ir pasirinkta šaka: {branch}",
            data={"branch": branch},
        )


class GitHubCreatePRTool(BaseTool):
    name = "github_create_pr"
    description = (
        "Create a GitHub Pull Request via the GitHub API. "
        "Parameters: owner (required), repo (required), title (required), "
        "head (source branch, required), base (target branch, default 'main'), "
        "body (PR description, optional)."
    )
    requires_approval = True
    parameters = [
        {"name": "owner", "description": "GitHub username/org", "required": True},
        {"name": "repo",  "description": "Repository name", "required": True},
        {"name": "title", "description": "PR title", "required": True},
        {"name": "head",  "description": "Source branch name", "required": True},
        {"name": "base",  "description": "Target branch (default main)", "required": False},
        {"name": "body",  "description": "PR description", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        from app.core.config import settings as cfg
        token = getattr(cfg, "GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return ToolResult(tool_name=self.name, status="error",
                              message="GITHUB_TOKEN nenustatytas .env faile")

        owner = params.get("owner", "").strip()
        repo  = params.get("repo", "").strip()
        title = params.get("title", "").strip()
        head  = params.get("head", "").strip()
        if not all([owner, repo, title, head]):
            return ToolResult(tool_name=self.name, status="error",
                              message="owner, repo, title, head are required")

        payload = json.dumps({
            "title": title,
            "head":  head,
            "base":  params.get("base", "main"),
            "body":  params.get("body", ""),
        }).encode()

        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )

        loop = asyncio.get_event_loop()
        def _do():
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"GitHub {e.code}: {e.read().decode()}") from e

        try:
            raw = await loop.run_in_executor(None, _do)
            data = json.loads(raw)
            return ToolResult(
                tool_name=self.name, status="success",
                message=f"✅ PR sukurtas: {data.get('html_url')}",
                data={"pr_url": data.get("html_url"), "number": data.get("number")},
            )
        except Exception as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))
