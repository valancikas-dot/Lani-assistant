"""
vision_tool.py – Analyse images with GPT-4o Vision.

Supports:
  • describe_image   – general description of what is in the image
  • extract_text     – OCR-style text extraction
  • analyse_image    – answer a specific question about the image
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

from app.schemas.commands import ToolResult
from app.services.llm_multimodal_service import complete_multimodal_text
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

# Supported local file extensions
_SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _encode_image(source: str) -> tuple[str, str]:
    """
    Return (data_url, media_type) for *source*.

    *source* can be:
      • A local filesystem path  (/Users/…/photo.png)
      • A public https:// URL    (passed through as-is to the API)
    """
    if source.startswith("http://") or source.startswith("https://"):
        # API accepts URL directly – no base64 needed
        return source, "url"

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {source}")
    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXT:
        raise ValueError(f"Unsupported image type '{ext}'. Use: {_SUPPORTED_EXT}")

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}", "base64"


async def _call_vision(
    image_source: str,
    prompt: str,
    max_tokens: int = 1024,
) -> str:
    """Call GPT-4o with the given image + text prompt."""
    from app.core.config import settings as cfg

    api_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = "gpt-4o"

    data_or_url, kind = _encode_image(image_source)

    if kind == "url":
        image_content = {"type": "image_url", "image_url": {"url": data_or_url}}
    else:
        image_content = {"type": "image_url", "image_url": {"url": data_or_url}}

    return await complete_multimodal_text(
        openai_api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    image_content,
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        tracking_operation="vision",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool classes
# ──────────────────────────────────────────────────────────────────────────────

class DescribeImageTool(BaseTool):
    name = "describe_image"
    description = (
        "Describe what is visible in an image. "
        "Provide a local file path or a public URL."
    )
    parameters = [
        {
            "name": "source",
            "type": "str",
            "required": True,
            "description": "Path to a local image file or a public https:// URL.",
        },
        {
            "name": "detail",
            "type": "str",
            "required": False,
            "description": "Level of detail: 'brief' (default) or 'detailed'.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        source = str(params.get("source", "")).strip()
        detail = str(params.get("detail", "brief")).strip().lower()
        if not source:
            return ToolResult(tool_name=self.name, status="error", message="'source' parameter is required.")

        prompt = (
            "Describe this image in detail, noting all visible objects, "
            "people, text, colours, and context."
            if detail == "detailed"
            else "Briefly describe what you see in this image in 2-3 sentences."
        )

        try:
            result = await _call_vision(source, prompt)
            return ToolResult(tool_name=self.name, status="success", message=result)
        except Exception as exc:
            log.exception("[describe_image] failed")
            return ToolResult(tool_name=self.name, status="error", message=f"Image analysis failed: {exc}")


class ExtractTextFromImageTool(BaseTool):
    name = "extract_text_from_image"
    description = (
        "Extract all readable text from an image (OCR). "
        "Provide a local file path or a public URL."
    )
    parameters = [
        {
            "name": "source",
            "type": "str",
            "required": True,
            "description": "Path to a local image file or a public https:// URL.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        source = str(params.get("source", "")).strip()
        if not source:
            return ToolResult(tool_name=self.name, status="error", message="'source' parameter is required.")

        prompt = (
            "Extract every piece of text visible in this image. "
            "Preserve line breaks and formatting as closely as possible. "
            "Return ONLY the extracted text, nothing else."
        )

        try:
            result = await _call_vision(source, prompt, max_tokens=2048)
            return ToolResult(tool_name=self.name, status="success", message=result)
        except Exception as exc:
            log.exception("[extract_text_from_image] failed")
            return ToolResult(tool_name=self.name, status="error", message=f"Text extraction failed: {exc}")


class AnalyseImageTool(BaseTool):
    name = "analyse_image"
    description = (
        "Answer a specific question about an image. "
        "Provide a local file path or a public URL and a question."
    )
    parameters = [
        {
            "name": "source",
            "type": "str",
            "required": True,
            "description": "Path to a local image file or a public https:// URL.",
        },
        {
            "name": "question",
            "type": "str",
            "required": True,
            "description": "The question to answer about the image.",
        },
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        source = str(params.get("source", "")).strip()
        question = str(params.get("question", "")).strip()
        if not source:
            return ToolResult(tool_name=self.name, status="error", message="'source' parameter is required.")
        if not question:
            return ToolResult(tool_name=self.name, status="error", message="'question' parameter is required.")

        try:
            result = await _call_vision(source, question)
            return ToolResult(tool_name=self.name, status="success", message=result)
        except Exception as exc:
            log.exception("[analyse_image] failed")
            return ToolResult(tool_name=self.name, status="error", message=f"Image analysis failed: {exc}")
