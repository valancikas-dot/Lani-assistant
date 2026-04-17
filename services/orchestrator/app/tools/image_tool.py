"""
image_tool.py – AI image generation and editing.

Providers (auto-selected by availability):
  1. gpt-image-1   – OpenAI's newest image model (2025+), native editing, inpainting
  2. dall-e-3      – DALL-E 3 for high-quality creative images
  3. dall-e-2      – DALL-E 2 for fast/cheap generation and variations

Tools:
  generate_image     – text-to-image (best available model)
  edit_image         – inpaint / edit existing image with a prompt
  create_variation   – create visual variations of an existing image
  upscale_image      – upscale image 2× or 4× (Real-ESRGAN via replicate or local)

Config (.env):
  OPENAI_API_KEY=...
  IMAGE_OUTPUT_DIR=~/Desktop/Lani_Images   (default)
  IMAGE_MODEL=gpt-image-1                  (override model)
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
from typing import Any, Dict, Optional, Literal, cast

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "Lani_Images"
_VARIATION_SIZES: tuple[Literal["256x256", "512x512", "1024x1024"], ...] = (
    "256x256",
    "512x512",
    "1024x1024",
)


def _output_dir() -> Path:
    from app.core.config import settings as cfg
    d = Path(getattr(cfg, "IMAGE_OUTPUT_DIR", str(_DEFAULT_OUTPUT_DIR))).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _openai_key() -> str:
    from app.core.config import settings as cfg
    key = getattr(cfg, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY nenustatytas .env faile.")
    return key


def _preferred_model() -> str:
    from app.core.config import settings as cfg
    return getattr(cfg, "IMAGE_MODEL", "gpt-image-1")


def _save_b64(b64: str, filename: str) -> str:
    """Save base64 image to output dir and return absolute path."""
    out = _output_dir() / filename
    out.write_bytes(base64.b64decode(b64))
    return str(out)


# ─────────────────────────────────────────────────────────────────────────────
# Generate Image
# ─────────────────────────────────────────────────────────────────────────────

class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = (
        "Generate a high-quality image from a text prompt using OpenAI's best image model. "
        "Returns the saved file path and a preview URL. "
        "Parameters: prompt (required), size ('1024x1024'|'1792x1024'|'1024x1792', default '1024x1024'), "
        "quality ('standard'|'hd', default 'hd'), style ('vivid'|'natural', default 'vivid'), "
        "n (1-4, default 1, dall-e-2 only for >1), filename (optional, auto-generated if omitted)."
    )
    requires_approval = False
    parameters = [
        {"name": "prompt",   "description": "Detailed text description of the image to generate", "required": True},
        {"name": "size",     "description": "Image size: '1024x1024', '1792x1024', or '1024x1792'", "required": False},
        {"name": "quality",  "description": "Quality: 'standard' or 'hd'", "required": False},
        {"name": "style",    "description": "Style: 'vivid' or 'natural'", "required": False},
        {"name": "n",        "description": "Number of images (1–4)", "required": False},
        {"name": "filename", "description": "Output filename without extension", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        prompt: str = params.get("prompt", "").strip()
        if not prompt:
            return ToolResult(tool_name=self.name, status="error", message="prompt is required")

        size: str    = params.get("size", "1024x1024")
        quality: str = params.get("quality", "hd")
        style: str   = params.get("style", "vivid")
        n: int       = min(int(params.get("n", 1)), 4)
        model: str   = _preferred_model()

        try:
            key = _openai_key()
        except RuntimeError as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))

        import openai
        client = openai.AsyncOpenAI(api_key=key)

        try:
            # gpt-image-1 supports response_format="b64_json" natively
            # dall-e-3 also supports it; dall-e-2 supports n>1 but lower quality
            kwargs: dict = dict(
                model=model,
                prompt=prompt,
                n=n,
                size=size,
                response_format="b64_json",
            )
            # quality + style only for dall-e-3 and gpt-image-1
            if model in ("dall-e-3", "gpt-image-1"):
                kwargs["quality"] = quality
            if model == "dall-e-3":
                kwargs["style"] = style

            response = await client.images.generate(**kwargs)

            saved_paths: list[str] = []
            base_name = params.get("filename") or _slug(prompt)[:40]
            for i, img_data in enumerate(response.data):
                b64 = img_data.b64_json or ""
                if not b64 and img_data.url:
                    # Fallback: download URL
                    b64 = await _download_b64(img_data.url)
                suffix = f"_{i+1}" if n > 1 else ""
                path = _save_b64(b64, f"{base_name}{suffix}.png")
                saved_paths.append(path)

            revised = getattr(response.data[0], "revised_prompt", None) if response.data else None
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"✅ {len(saved_paths)} paveiksl{'as' if len(saved_paths)==1 else 'ai'} sukurti",
                data={
                    "paths": saved_paths,
                    "path": saved_paths[0] if saved_paths else None,
                    "model": model,
                    "revised_prompt": revised,
                    "prompt": prompt,
                },
            )
        except openai.BadRequestError as e:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"OpenAI atsisakė generuoti: {e.message}")
        except Exception as e:
            log.exception("[generate_image] error")
            return ToolResult(tool_name=self.name, status="error", message=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Edit Image (inpainting)
# ─────────────────────────────────────────────────────────────────────────────

class EditImageTool(BaseTool):
    name = "edit_image"
    description = (
        "Edit an existing image using a text prompt (inpainting / outpainting). "
        "Optionally provide a mask PNG where white areas will be edited. "
        "Parameters: image_path (required), prompt (required), "
        "mask_path (optional), size ('1024x1024' default), filename (optional)."
    )
    requires_approval = False
    parameters = [
        {"name": "image_path", "description": "Absolute path to the source PNG/JPEG", "required": True},
        {"name": "prompt",     "description": "What to change or add to the image",   "required": True},
        {"name": "mask_path",  "description": "Absolute path to mask PNG (white = edit area)", "required": False},
        {"name": "size",       "description": "Output size: '1024x1024'", "required": False},
        {"name": "filename",   "description": "Output filename without extension", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        image_path: str = params.get("image_path", "").strip()
        prompt: str     = params.get("prompt", "").strip()
        if not image_path or not prompt:
            return ToolResult(tool_name=self.name, status="error",
                              message="image_path and prompt are required")

        src = Path(image_path).expanduser()
        if not src.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Failas nerastas: {image_path}")

        try:
            key = _openai_key()
        except RuntimeError as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))

        import openai
        client = openai.AsyncOpenAI(api_key=key)

        try:
            size: str = params.get("size", "1024x1024")
            mask_path = params.get("mask_path")

            kwargs: dict = dict(
                model="dall-e-2",   # edit endpoint uses dall-e-2
                image=open(str(src), "rb"),
                prompt=prompt,
                n=1,
                size=size,
                response_format="b64_json",
            )
            if mask_path:
                mask_src = Path(mask_path).expanduser()
                if mask_src.exists():
                    kwargs["mask"] = open(str(mask_src), "rb")

            response = await client.images.edit(**kwargs)
            b64 = response.data[0].b64_json or ""
            base_name = params.get("filename") or f"edited_{src.stem}"
            path = _save_b64(b64, f"{base_name}.png")

            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"✅ Paveikslėlis redaguotas: {path}",
                data={"path": path, "prompt": prompt},
            )
        except Exception as e:
            log.exception("[edit_image] error")
            return ToolResult(tool_name=self.name, status="error", message=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Create Variation
# ─────────────────────────────────────────────────────────────────────────────

class CreateImageVariationTool(BaseTool):
    name = "create_image_variation"
    description = (
        "Create n visual variations of an existing image (DALL-E 2). "
        "Parameters: image_path (required), n (1–4, default 2), "
        "size ('1024x1024' default), filename_prefix (optional)."
    )
    requires_approval = False
    parameters = [
        {"name": "image_path",       "description": "Absolute path to the source PNG", "required": True},
        {"name": "n",                "description": "Number of variations (1–4)", "required": False},
        {"name": "size",             "description": "Output size", "required": False},
        {"name": "filename_prefix",  "description": "Prefix for output filenames", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        image_path: str = params.get("image_path", "").strip()
        if not image_path:
            return ToolResult(tool_name=self.name, status="error",
                              message="image_path is required")

        src = Path(image_path).expanduser()
        if not src.exists():
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Failas nerastas: {image_path}")

        try:
            key = _openai_key()
        except RuntimeError as e:
            return ToolResult(tool_name=self.name, status="error", message=str(e))

        import openai
        client = openai.AsyncOpenAI(api_key=key)

        n: int     = min(int(params.get("n", 2)), 4)
        requested_size = str(params.get("size", "1024x1024"))
        size: Literal["256x256", "512x512", "1024x1024"] = (
            cast(Literal["256x256", "512x512", "1024x1024"], requested_size)
            if requested_size in _VARIATION_SIZES
            else "1024x1024"
        )
        prefix: str = params.get("filename_prefix", f"variation_{src.stem}")

        try:
            response = await client.images.create_variation(
                image=open(str(src), "rb"),
                n=n,
                size=size,
                response_format="b64_json",
            )
            paths: list[str] = []
            response_items = response.data or []
            for i, img in enumerate(response_items):
                b64 = img.b64_json or ""
                path = _save_b64(b64, f"{prefix}_{i+1}.png")
                paths.append(path)

            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"✅ {n} variacijų sukurta",
                data={"paths": paths},
            )
        except Exception as e:
            log.exception("[create_image_variation] error")
            return ToolResult(tool_name=self.name, status="error", message=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    """Convert prompt to safe filename slug."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


async def _download_b64(url: str) -> str:
    """Download image URL and return base64 string."""
    loop = asyncio.get_event_loop()
    def _fetch():
        with urllib.request.urlopen(url, timeout=30) as r:
            return base64.b64encode(r.read()).decode()
    return await loop.run_in_executor(None, _fetch)
