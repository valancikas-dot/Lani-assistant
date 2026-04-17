"""Builder tools – atomic file-system operations for Builder Mode.

All tools enforce:
  1. Path containment – every write must be inside an allowed project directory.
  2. Non-destructive defaults – overwriting existing files requires
     ``overwrite=True`` (and sets ``requires_approval=True`` on the tool).
  3. Audit-friendly results – every ToolResult carries a clear message.

Templates
─────────
Templates are pure Python dicts mapping relative paths to starter content.
They are intentionally minimal – real content generation is layered on top
by builder_service.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool


# ─── Path safety ──────────────────────────────────────────────────────────────

def _resolve_safe(base: str, relative: str) -> Path | None:
    """Return resolved absolute path only if it stays inside *base*.

    Returns None if the resolved path escapes the base (path traversal guard).
    """
    base_path = Path(base).expanduser().resolve()
    target = (base_path / relative).resolve()
    try:
        target.relative_to(base_path)
        return target
    except ValueError:
        return None


def _check_allowed(path: Path, allowed_dirs: List[str]) -> bool:
    """Return True only if *path* is inside one of the allowed directories."""
    if not allowed_dirs:
        return False
    for d in allowed_dirs:
        try:
            path.relative_to(Path(d).expanduser().resolve())
            return True
        except ValueError:
            continue
    return False


# ─── Template definitions ─────────────────────────────────────────────────────

def _react_ts_files(name: str) -> Dict[str, str]:
    return {
        "package.json": f'''{{\n  "name": "{name.lower().replace(" ", "-")}",\n  "private": true,\n  "version": "0.1.0",\n  "scripts": {{\n    "dev": "vite",\n    "build": "tsc && vite build",\n    "preview": "vite preview"\n  }},\n  "dependencies": {{\n    "react": "^18.3.1",\n    "react-dom": "^18.3.1"\n  }},\n  "devDependencies": {{\n    "@types/react": "^18.3.3",\n    "@types/react-dom": "^18.3.0",\n    "@vitejs/plugin-react": "^4.3.0",\n    "typescript": "^5.4.5",\n    "vite": "^5.2.11"\n  }}\n}}\n''',
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2020",\n    "lib": ["ES2020", "DOM"],\n    "module": "ESNext",\n    "moduleResolution": "bundler",\n    "jsx": "react-jsx",\n    "strict": true,\n    "outDir": "dist"\n  },\n  "include": ["src"]\n}\n',
        "vite.config.ts": 'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\nexport default defineConfig({ plugins: [react()] });\n',
        "index.html": f'<!DOCTYPE html>\n<html lang="en">\n  <head><meta charset="UTF-8" /><title>{name}</title></head>\n  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>\n</html>\n',
        "src/main.tsx": 'import React from "react";\nimport ReactDOM from "react-dom/client";\nimport App from "./App";\nReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);\n',
        "src/App.tsx": f'import React from "react";\nexport default function App() {{\n  return <div><h1>{name}</h1><p>Edit src/App.tsx to get started.</p></div>;\n}}\n',
        "src/App.css": "body { font-family: sans-serif; margin: 2rem; }\n",
    }


def _nextjs_files(name: str) -> Dict[str, str]:
    slug = name.lower().replace(" ", "-")
    return {
        "package.json": f'{{\n  "name": "{slug}",\n  "version": "0.1.0",\n  "scripts": {{\n    "dev": "next dev",\n    "build": "next build",\n    "start": "next start"\n  }},\n  "dependencies": {{\n    "next": "^14.0.0",\n    "react": "^18.3.1",\n    "react-dom": "^18.3.1"\n  }},\n  "devDependencies": {{\n    "@types/node": "^20.0.0",\n    "@types/react": "^18.3.3",\n    "typescript": "^5.4.5"\n  }}\n}}\n',
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2017",\n    "lib": ["dom", "dom.iterable", "esnext"],\n    "allowJs": true,\n    "skipLibCheck": true,\n    "strict": true,\n    "module": "esnext",\n    "moduleResolution": "bundler",\n    "jsx": "preserve",\n    "incremental": true,\n    "plugins": [{ "name": "next" }]\n  },\n  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],\n  "exclude": ["node_modules"]\n}\n',
        "app/layout.tsx": f'export const metadata = {{ title: "{name}" }};\nexport default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{\n  return <html lang="en"><body>{{children}}</body></html>;\n}}\n',
        "app/page.tsx": f'export default function Home() {{\n  return <main><h1>Welcome to {name}</h1></main>;\n}}\n',
        "app/globals.css": "body { font-family: sans-serif; margin: 0; }\n",
    }


def _fastapi_files(name: str) -> Dict[str, str]:
    slug = name.lower().replace(" ", "_").replace("-", "_")
    return {
        "pyproject.toml": f'[project]\nname = "{slug}"\nversion = "0.1.0"\ndependencies = ["fastapi>=0.100", "uvicorn[standard]>=0.20"]\n\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.backends.legacy:build"\n',
        "app/__init__.py": "",
        "app/main.py": f'from fastapi import FastAPI\n\napp = FastAPI(title="{name}")\n\n@app.get("/")\nasync def root():\n    return {{"message": "Hello from {name}"}}\n',
        "app/routers/__init__.py": "",
        "app/models/__init__.py": "",
        "app/schemas/__init__.py": "",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n",
    }


def _node_express_files(name: str) -> Dict[str, str]:
    slug = name.lower().replace(" ", "-")
    return {
        "package.json": f'{{\n  "name": "{slug}",\n  "version": "1.0.0",\n  "main": "src/index.js",\n  "scripts": {{ "start": "node src/index.js", "dev": "nodemon src/index.js" }},\n  "dependencies": {{ "express": "^4.18.2" }},\n  "devDependencies": {{ "nodemon": "^3.0.0" }}\n}}\n',
        "src/index.js": f'const express = require("express");\nconst app = express();\nconst PORT = process.env.PORT || 3000;\napp.use(express.json());\napp.get("/", (req, res) => res.json({{ message: "Hello from {name}" }}));\napp.listen(PORT, () => console.log(`Server running on port ${{PORT}}`));\n',
        ".gitignore": "node_modules/\n.env\n",
    }


def _static_html_files(name: str) -> Dict[str, str]:
    return {
        "index.html": f'<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n  <title>{name}</title>\n  <link rel="stylesheet" href="styles.css">\n</head>\n<body>\n  <h1>{name}</h1>\n  <p>Welcome! Edit index.html to get started.</p>\n  <script src="main.js"></script>\n</body>\n</html>\n',
        "styles.css": "*, *::before, *::after { box-sizing: border-box; }\nbody { font-family: system-ui, sans-serif; margin: 0; padding: 2rem; }\n",
        "main.js": "// Your JavaScript here\nconsole.log('Hello from main.js');\n",
    }


def _python_script_files(name: str) -> Dict[str, str]:
    slug = name.lower().replace(" ", "_").replace("-", "_")
    return {
        f"{slug}.py": f'"""Entry point for {name}."""\n\n\ndef main() -> None:\n    print("Hello from {name}")\n\n\nif __name__ == "__main__":\n    main()\n',
        "requirements.txt": "# Add your dependencies here\n",
        ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n",
    }


def _generic_files(name: str) -> Dict[str, str]:
    return {
        "README.md": f"# {name}\n\n> Generated by Lani Builder Mode.\n\n## Getting Started\n\nAdd your project description here.\n",
        ".gitignore": ".env\n*.log\n",
    }


TEMPLATE_FILES: Dict[str, Any] = {
    "react":        lambda n: _react_ts_files(n),
    "react-ts":     lambda n: _react_ts_files(n),
    "vite-react":   lambda n: _react_ts_files(n),
    "nextjs":       lambda n: _nextjs_files(n),
    "fastapi":      lambda n: _fastapi_files(n),
    "node-express": lambda n: _node_express_files(n),
    "static-html":  lambda n: _static_html_files(n),
    "python-script": lambda n: _python_script_files(n),
    "mobile-expo":  lambda n: {
        "package.json": f'{{\n  "name": "{n.lower().replace(" ", "-")}",\n  "version": "1.0.0",\n  "main": "node_modules/expo/AppEntry.js",\n  "scripts": {{ "start": "expo start" }},\n  "dependencies": {{\n    "expo": "~51.0.0",\n    "react": "18.2.0",\n    "react-native": "0.74.0"\n  }}\n}}\n',
        "App.tsx": f'import {{ Text, View }} from "react-native";\nexport default function App() {{\n  return <View style={{{{ flex: 1, alignItems: "center", justifyContent: "center" }}}}><Text>{n}</Text></View>;\n}}\n',
    },
    "generic":      lambda n: _generic_files(n),
}

PROPOSED_COMMANDS: Dict[str, List[Dict[str, str]]] = {
    "react":        [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npm run dev", "desc": "Start dev server", "risk": "safe"}],
    "react-ts":     [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npm run dev", "desc": "Start Vite dev server", "risk": "safe"}],
    "vite-react":   [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npm run dev", "desc": "Start Vite dev server", "risk": "safe"}],
    "nextjs":       [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npm run dev", "desc": "Start Next.js dev server", "risk": "safe"}],
    "fastapi":      [{"cmd": "python -m venv .venv", "desc": "Create virtual environment", "risk": "safe"}, {"cmd": "source .venv/bin/activate && pip install -e .", "desc": "Install project", "risk": "safe"}, {"cmd": "uvicorn app.main:app --reload", "desc": "Start FastAPI dev server", "risk": "safe"}],
    "node-express": [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npm run dev", "desc": "Start dev server with nodemon", "risk": "safe"}],
    "static-html":  [{"cmd": "open index.html", "desc": "Open in browser", "risk": "safe"}],
    "python-script": [{"cmd": "python -m venv .venv && source .venv/bin/activate", "desc": "Create and activate virtual environment", "risk": "safe"}],
    "mobile-expo":  [{"cmd": "npm install", "desc": "Install dependencies", "risk": "safe"}, {"cmd": "npx expo start", "desc": "Start Expo dev server", "risk": "safe"}],
    "generic":      [],
}


# ─── Base builder tool ────────────────────────────────────────────────────────

class _BuilderBase(BaseTool):
    """Common helpers shared by all builder tools."""

    def _ok(self, tool: str, data: Any, msg: str) -> ToolResult:
        return ToolResult(tool_name=tool, status="success", data=data, message=msg)

    def _err(self, tool: str, msg: str) -> ToolResult:
        return ToolResult(tool_name=tool, status="error", message=msg)

    def _approval(self, tool: str, data: Any, msg: str) -> ToolResult:
        return ToolResult(tool_name=tool, status="approval_required", data=data, message=msg)


# ─── create_project_scaffold ──────────────────────────────────────────────────

class CreateProjectScaffoldTool(_BuilderBase):
    name = "create_project_scaffold"
    description = "Create a new project folder structure from a template (react, nextjs, fastapi, etc.)"
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        name: str = params.get("name", "my-project")
        template: str = params.get("template", "generic")
        base_dir: str = params.get("base_dir", "")
        allowed: List[str] = params.get("_allowed_dirs", [])

        if not base_dir:
            return self._err(self.name, "base_dir is required")

        project_root = Path(base_dir).expanduser().resolve() / name
        if not _check_allowed(project_root, allowed):
            return self._err(self.name,
                f"Path '{project_root}' is outside allowed directories. "
                "Add it to allowed directories in Settings.")

        file_factory = TEMPLATE_FILES.get(template, TEMPLATE_FILES["generic"])
        files: Dict[str, str] = file_factory(name)

        created: List[str] = []
        try:
            project_root.mkdir(parents=True, exist_ok=True)
            for rel_path, content in files.items():
                target = (project_root / rel_path).resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                created.append(rel_path)
        except OSError as exc:
            return self._err(self.name, f"File system error: {exc}")

        cmds = PROPOSED_COMMANDS.get(template, [])
        return self._ok(self.name, {
            "project_path": str(project_root),
            "files_created": created,
            "proposed_commands": cmds,
        }, f"Scaffolded '{name}' ({template}) with {len(created)} files.")


# ─── create_code_file ─────────────────────────────────────────────────────────

class CreateCodeFileTool(_BuilderBase):
    name = "create_code_file"
    description = "Create a new source code file inside a project directory"
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_path: str = params.get("project_path", "")
        relative_path: str = params.get("relative_path", "")
        content: str = params.get("content", "")
        overwrite: bool = bool(params.get("overwrite", False))
        allowed: List[str] = params.get("_allowed_dirs", [])

        if not project_path or not relative_path:
            return self._err(self.name, "project_path and relative_path are required")

        target = _resolve_safe(project_path, relative_path)
        if target is None:
            return self._err(self.name, "Path traversal detected – relative_path must stay inside project_path")

        if not _check_allowed(target, allowed):
            return self._err(self.name, f"'{target}' is outside allowed directories")

        if target.exists() and not overwrite:
            return self._approval(self.name, {"path": str(target)},
                f"File '{relative_path}' already exists. Set overwrite=True to replace it.")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return self._err(self.name, f"Could not write file: {exc}")

        verb = "Updated" if target.exists() else "Created"
        return self._ok(self.name, {"absolute_path": str(target)},
            f"{verb} {relative_path}")


# ─── update_code_file ─────────────────────────────────────────────────────────

class UpdateCodeFileTool(_BuilderBase):
    name = "update_code_file"
    description = "Overwrite an existing code file with new content (always requires approval)"
    requires_approval = True

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        params_with_overwrite = dict(params)
        params_with_overwrite["overwrite"] = True
        tool = CreateCodeFileTool()
        return await tool.run(params_with_overwrite)


# ─── create_readme ────────────────────────────────────────────────────────────

class CreateReadmeTool(_BuilderBase):
    name = "create_readme"
    description = "Generate a README.md for a project"
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_path: str = params.get("project_path", "")
        project_name: str = params.get("project_name", "Project")
        description: str = params.get("description", "")
        template: str = params.get("template", "generic")
        features: List[str] = params.get("features", [])
        allowed: List[str] = params.get("_allowed_dirs", [])

        if not project_path:
            return self._err(self.name, "project_path is required")

        root = Path(project_path).expanduser().resolve()
        if not _check_allowed(root, allowed):
            return self._err(self.name, f"'{root}' is outside allowed directories")

        # Build README content
        feature_lines = "\n".join(f"- {f}" for f in features) if features else "- Core functionality"
        tech_hint = {
            "react": "React + TypeScript + Vite",
            "react-ts": "React + TypeScript + Vite",
            "vite-react": "React + TypeScript + Vite",
            "nextjs": "Next.js 14 + TypeScript",
            "fastapi": "Python + FastAPI + uvicorn",
            "node-express": "Node.js + Express",
            "static-html": "HTML + CSS + JavaScript",
            "python-script": "Python",
            "mobile-expo": "React Native + Expo",
        }.get(template, "")

        content = f"""# {project_name}

{description or "A project generated by Lani Builder Mode."}
{f"{chr(10)}**Tech stack:** {tech_hint}" if tech_hint else ""}

## Features

{feature_lines}

## Getting Started

```bash
# Clone / enter the project
cd {project_name.lower().replace(" ", "-")}

# Install dependencies (if applicable)
npm install  # or: pip install -e .
```

## Development

```bash
npm run dev  # or: uvicorn app.main:app --reload
```

## License

MIT
"""
        readme_path = root / "README.md"
        try:
            readme_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return self._err(self.name, f"Could not write README: {exc}")

        return self._ok(self.name, {
            "absolute_path": str(readme_path),
            "content": content,
        }, f"README.md created for '{project_name}'.")


# ─── generate_feature_files ──────────────────────────────────────────────────

class GenerateFeatureFilesTool(_BuilderBase):
    name = "generate_feature_files"
    description = "Generate boilerplate code files for a described feature (component, page, API route, etc.)"
    requires_approval = False

    _REACT_COMPONENT_TEMPLATE = """\
import React from "react";

interface {PascalName}Props {{
  // TODO: define props
}}

const {PascalName}: React.FC<{PascalName}Props> = (props) => {{
  return (
    <div className="{kebab_name}">
      <h2>{Display Name}</h2>
      {{/* TODO: implement */}}
    </div>
  );
}};

export default {PascalName};
"""

    _FASTAPI_ROUTER_TEMPLATE = """\
\"\"\"Router for {display_name} endpoints.\"\"\"

from fastapi import APIRouter, Depends

router = APIRouter(prefix="/{url_slug}", tags=["{display_name}"])


@router.get("/")
async def list_{snake}():
    return []


@router.post("/")
async def create_{snake}(payload: dict):
    return payload
"""

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_path: str = params.get("project_path", "")
        feature: str = params.get("feature_description", "")
        template: str = params.get("template", "generic")
        output_dir: str = params.get("output_dir", "src")
        allowed: List[str] = params.get("_allowed_dirs", [])

        if not project_path or not feature:
            return self._err(self.name, "project_path and feature_description are required")

        root = Path(project_path).expanduser().resolve()
        if not _check_allowed(root, allowed):
            return self._err(self.name, f"'{root}' is outside allowed directories")

        # Derive naming variants
        words = feature.strip().replace("-", " ").replace("_", " ").split()
        pascal = "".join(w.capitalize() for w in words)
        snake = "_".join(w.lower() for w in words)
        kebab = "-".join(w.lower() for w in words)
        display = " ".join(w.capitalize() for w in words)
        url_slug = kebab

        files: List[Dict[str, str]] = []

        if template in ("react", "react-ts", "vite-react"):
            content = (
                self._REACT_COMPONENT_TEMPLATE
                .replace("{PascalName}", pascal)
                .replace("{kebab_name}", kebab)
                .replace("{Display Name}", display)
            )
            files.append({"path": f"{output_dir}/components/{pascal}.tsx", "content": content})
            files.append({"path": f"{output_dir}/components/{pascal}.css",
                          "content": f".{kebab} {{\n  /* styles for {display} */\n}}\n"})

        elif template == "nextjs":
            files.append({"path": f"app/{kebab}/page.tsx",
                          "content": f'export default function {pascal}Page() {{\n  return <main><h1>{display}</h1></main>;\n}}\n'})

        elif template == "fastapi":
            router_content = (
                self._FASTAPI_ROUTER_TEMPLATE
                .replace("{display_name}", display)
                .replace("{url_slug}", url_slug)
                .replace("{snake}", snake)
            )
            files.append({"path": f"app/routers/{snake}.py", "content": router_content})
            files.append({"path": f"app/schemas/{snake}.py",
                          "content": f'from pydantic import BaseModel\n\n\nclass {pascal}(BaseModel):\n    # TODO: define fields\n    pass\n'})

        elif template == "node-express":
            files.append({"path": f"src/routes/{snake}.js",
                          "content": f'const express = require("express");\nconst router = express.Router();\nrouter.get("/", (req, res) => res.json([]));\nmodule.exports = router;\n'})

        else:
            files.append({"path": f"{output_dir}/{snake}.txt",
                          "content": f"# {display}\n\nTODO: implement {feature}\n"})

        written: List[str] = []
        try:
            for f in files:
                target = _resolve_safe(project_path, f["path"])
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f["content"], encoding="utf-8")
                written.append(f["path"])
        except OSError as exc:
            return self._err(self.name, f"Could not write feature files: {exc}")

        return self._ok(self.name, {
            "files": [{"path": p, "content": c} for p, c in
                      ((f["path"], f["content"]) for f in files)],
        }, f"Generated {len(written)} file(s) for feature '{feature}'.")


# ─── list_project_tree ────────────────────────────────────────────────────────

_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".expo", ".pytest_cache", "*.egg-info",
}


class ListProjectTreeTool(_BuilderBase):
    name = "list_project_tree"
    description = "Return the directory tree of a project (read-only)"
    requires_approval = False

    def _build_tree(self, path: Path, max_depth: int, current_depth: int = 0) -> Dict[str, Any]:
        node: Dict[str, Any] = {
            "name": path.name,
            "path": str(path),
            "is_dir": path.is_dir(),
            "children": [],
        }
        if path.is_dir() and current_depth < max_depth:
            try:
                for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
                    if child.name in _IGNORE_DIRS or child.name.startswith("."):
                        continue
                    node["children"].append(
                        self._build_tree(child, max_depth, current_depth + 1)
                    )
            except PermissionError:
                pass
        return node

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_path: str = params.get("project_path", "")
        max_depth: int = int(params.get("max_depth", 4))
        allowed: List[str] = params.get("_allowed_dirs", [])

        if not project_path:
            return self._err(self.name, "project_path is required")

        root = Path(project_path).expanduser().resolve()
        if not _check_allowed(root, allowed):
            return self._err(self.name, f"'{root}' is outside allowed directories")
        if not root.exists():
            return self._err(self.name, f"Path '{root}' does not exist")

        tree = self._build_tree(root, max_depth)
        return self._ok(self.name, {"root": tree}, f"Project tree for '{root.name}'.")


# ─── propose_terminal_commands ────────────────────────────────────────────────

class ProposeTerminalCommandsTool(_BuilderBase):
    name = "propose_terminal_commands"
    description = "Propose relevant terminal commands for a project (does not execute them)"
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        project_path: str = params.get("project_path", "")
        template: str = params.get("template", "generic")
        goal: str = params.get("goal", "")

        cmds = PROPOSED_COMMANDS.get(template, [])

        # Add goal-specific hints
        if goal:
            goal_lower = goal.lower()
            if "test" in goal_lower:
                cmds = cmds + [{"cmd": "npm test", "desc": "Run tests", "risk": "safe"}]
            if "deploy" in goal_lower or "build" in goal_lower:
                cmds = cmds + [{"cmd": "npm run build", "desc": "Production build", "risk": "safe"}]
            if "docker" in goal_lower:
                cmds = cmds + [
                    {"cmd": "docker build -t app .", "desc": "Build Docker image", "risk": "moderate"},
                    {"cmd": "docker run -p 3000:3000 app", "desc": "Run Docker container", "risk": "moderate"},
                ]

        return self._ok(self.name, {"commands": cmds, "project_path": project_path},
            f"Proposed {len(cmds)} commands for '{template}' project.")
