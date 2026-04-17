"""
image_generation_tool.py – OpenAI Images / Stability AI with simulation fallback.

Provider priority:
  1. OpenAI gpt-image-1 / DALL-E 3 (IMAGE_API_KEY or OPENAI_API_KEY)
  2. Simulation (returns structured prompt plan)

Result schema (ToolResult.data):
  {
    "success":      bool,
    "simulation":   bool,
    "provider":     "openai_images" | "simulation",
    "image_paths":  List[str],   # local saved paths
    "image_urls":   List[str],   # CDN URLs if available
    "prompt_used":  str,
    "model":        str,
    "count":        int,
    "error":        str | None,
  }

Env vars:
  IMAGE_API_KEY   – primary (if separate from OPENAI_API_KEY)
  OPENAI_API_KEY  – fallback
  IMAGE_MODEL     – override model (default: gpt-image-1)
  IMAGE_OUTPUT_DIR – where to save images
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_OAI_BASE = "https://api.openai.com/v1"

# ── Config helpers ─────────────────────────────────────────────────────────────

def _image_key() -> Optional[str]:
    from app.core.config import settings as cfg
    return (
        getattr(cfg, "IMAGE_API_KEY", "") or
        os.environ.get("IMAGE_API_KEY", "") or
        getattr(cfg, "OPENAI_API_KEY", "") or
        os.environ.get("OPENAI_API_KEY", "")
    ) or None


def _image_model() -> str:
    from app.core.config import settings as cfg
    return getattr(cfg, "IMAGE_MODEL", "gpt-image-1")


def _output_dir() -> Path:
    from app.core.config import settings as cfg
    d = Path(getattr(cfg, "IMAGE_OUTPUT_DIR", str(Path.home() / "Desktop" / "Lani_Images"))).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── OpenAI Images API ──────────────────────────────────────────────────────────

async def _openai_generate(prompt: str, model: str, size: str, count: int, api_key: str) -> List[Dict]:
    """Call OpenAI images/generations. Returns list of {url?, b64_json?}."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt[:4000],
        "n": count,
        "size": size,
        "response_format": "b64_json",
    }).encode()

    req = urllib.request.Request(
        f"{_OAI_BASE}/images/generations",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    loop = asyncio.get_event_loop()
    def _do():
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"OpenAI Images {e.code}: {body}") from e

    resp = await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=150)
    return resp.get("data", [])


def _save_b64(b64: str, out_path: Path) -> str:
    out_path.write_bytes(base64.b64decode(b64))
    return str(out_path)


# ── Tool class ─────────────────────────────────────────────────────────────────

class GenerateImageExtTool(BaseTool):
    """
    Generate images from a text prompt via OpenAI (gpt-image-1 / DALL-E 3).
    Falls back to simulation when IMAGE_API_KEY / OPENAI_API_KEY is absent.
    """
    name = "generate_image_ext"
    description = (
        "Generate high-quality images from a text description using OpenAI's best image model. "
        "Saves images locally. Gracefully simulates when IMAGE_API_KEY is absent."
    )
    requires_approval = False
    parameters = [
        {"name": "prompt", "type": "str", "required": True,
         "description": "Detailed image description."},
        {"name": "count", "type": "int", "required": False,
         "description": "Number of images to generate (1–4, default 1)."},
        {"name": "size", "type": "str", "required": False,
         "description": "Image size: '1024x1024' | '1792x1024' | '1024x1792' (default: 1024x1024)."},
        {"name": "filename_prefix", "type": "str", "required": False,
         "description": "Filename prefix (e.g. 'campaign_hero'). Saves as prefix_0.png, etc."},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        prompt: str = str(params.get("prompt", "")).strip()
        count: int = min(max(int(params.get("count", 1)), 1), 4)
        size: str = str(params.get("size", "1024x1024")).strip()
        prefix: str = str(params.get("filename_prefix", "lani_image")).strip()

        if not prompt:
            return ToolResult(
                tool_name=self.name, status="error",
                message="Parameter 'prompt' is required.",
                data={"success": False, "simulation": False, "provider": None, "error": "prompt required"},
            )

        api_key = _image_key()

        if not api_key:
            log.info("[image_ext] no IMAGE_API_KEY – simulation fallback")
            return ToolResult(
                tool_name=self.name, status="success",
                message=(
                    "⚠ SIMULATION: IMAGE_API_KEY not configured.\n"
                    "Add OPENAI_API_KEY or IMAGE_API_KEY to .env to enable real image generation."
                ),
                data={
                    "success": True,
                    "simulation": True,
                    "provider": "simulation",
                    "image_paths": [],
                    "image_urls": [],
                    "prompt_used": prompt[:200],
                    "model": _image_model(),
                    "count": count,
                    "error": None,
                    "setup_hint": "Add IMAGE_API_KEY=sk-... or OPENAI_API_KEY=sk-... to .env",
                },
            )

        model = _image_model()
        out_dir = _output_dir()

        try:
            log.info("[image_ext] generating %d image(s) with %s", count, model)
            items = await _openai_generate(prompt, model, size, count, api_key)

            paths: List[str] = []
            for i, item in enumerate(items):
                b64 = item.get("b64_json", "")
                if b64:
                    fname = f"{prefix}_{i}.png"
                    p = _save_b64(b64, out_dir / fname)
                    paths.append(p)

            return ToolResult(
                tool_name=self.name, status="success",
                message=f"✅ {len(paths)} image(s) generated: {', '.join(paths)}",
                data={
                    "success": True,
                    "simulation": False,
                    "provider": "openai_images",
                    "image_paths": paths,
                    "image_urls": [],
                    "prompt_used": prompt[:200],
                    "model": model,
                    "count": len(paths),
                    "error": None,
                },
            )

        except Exception as exc:
            log.exception("[image_ext] generation failed")
            return ToolResult(
                tool_name=self.name, status="error",
                message=f"Image generation failed: {exc}",
                data={
                    "success": False,
                    "simulation": False,
                    "provider": "openai_images",
                    "image_paths": [],
                    "image_urls": [],
                    "prompt_used": prompt[:200],
                    "model": model,
                    "count": 0,
                    "error": str(exc),
                },
            )
