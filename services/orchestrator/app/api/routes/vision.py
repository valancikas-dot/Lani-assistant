"""
vision.py – HTTP endpoint for image analysis.

POST /api/v1/vision
  • Accepts multipart/form-data with:
      file     – image file upload (jpg/png/gif/webp)
      question – optional question to answer about the image
      mode     – "describe" | "extract_text" | "analyse" (default: describe)
  • OR application/json with:
      url      – public image URL
      question – optional question
      mode     – same as above

Returns:
  { "ok": true, "result": "…" }
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}


# ──────────────────────────────────────────────────────────────────────────────
# Multipart upload endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/vision")
async def analyse_upload(
    file: UploadFile = File(...),
    question: Optional[str] = Form(None),
    mode: Optional[str] = Form("describe"),
):
    """
    Analyse an uploaded image file.

    Modes:
      describe      – general description of the image
      extract_text  – OCR / text extraction
      analyse       – answer the provided *question* about the image
    """
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Allowed: {sorted(_ALLOWED_MIME)}",
        )

    # Save to a temp file so vision_tool can read it by path
    suffix = Path(file.filename or "img.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = await _dispatch(tmp_path, mode or "describe", question)
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        log.exception("[vision] upload analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# JSON URL endpoint
# ──────────────────────────────────────────────────────────────────────────────

class VisionUrlRequest(BaseModel):
    url: str
    question: Optional[str] = None
    mode: Optional[str] = "describe"


@router.post("/vision/url")
async def analyse_url(body: VisionUrlRequest):
    """
    Analyse a publicly accessible image URL.
    """
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="'url' must start with http(s)://")

    try:
        result = await _dispatch(body.url, body.mode or "describe", body.question)
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        log.exception("[vision] URL analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

async def _dispatch(source: str, mode: str, question: Optional[str]) -> str:
    from app.tools.vision_tool import _call_vision

    if mode == "extract_text":
        prompt = (
            "Extract every piece of text visible in this image. "
            "Preserve line breaks and formatting. Return ONLY the extracted text."
        )
        return await _call_vision(source, prompt, max_tokens=2048)

    if mode == "analyse":
        if not question:
            raise ValueError("'question' is required for mode='analyse'")
        return await _call_vision(source, question)

    # Default: describe
    return await _call_vision(
        source,
        "Describe what you see in this image clearly and concisely.",
    )
