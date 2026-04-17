"""
Research API routes.

Endpoints
─────────
POST /api/v1/research/search
    Run a web search and return structured results.

POST /api/v1/research/summarize
    Fetch + summarise a list of URLs.

POST /api/v1/research/compare
    Fetch + compare a list of URLs on a given topic.

POST /api/v1/research/brief
    All-in-one: search → summarize → (optionally compare).
    Returns a ResearchBrief directly without going through the planner.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

from app.schemas.research import (
    CompareResponse,
    ResearchBrief,
    ResearchRequest,
    SummarizeResponse,
    WebSearchResponse,
)
from app.services import research_service

router = APIRouter()


# ─── Request bodies ───────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=8, ge=1, le=20)


class SummarizeRequest(BaseModel):
    query: str = Field(default="")
    urls: List[str] = Field(..., min_length=1)
    max_sources: int = Field(default=5, ge=1, le=10)


class CompareRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    urls: List[str] = Field(..., min_length=1)
    max_sources: int = Field(default=6, ge=1, le=10)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/research/search", response_model=WebSearchResponse)
async def search(body: SearchRequest) -> WebSearchResponse:
    """Run a DuckDuckGo web search and return structured results."""
    return await research_service.web_search(body.query, max_results=body.max_results)


@router.post("/research/summarize", response_model=SummarizeResponse)
async def summarize(body: SummarizeRequest) -> SummarizeResponse:
    """Fetch the given URLs and produce a summary with key points."""
    return await research_service.summarize_urls(
        query=body.query,
        urls=body.urls,
        max_sources=body.max_sources,
    )


@router.post("/research/compare", response_model=CompareResponse)
async def compare(body: CompareRequest) -> CompareResponse:
    """Compare the given URLs on a topic and return a structured table."""
    return await research_service.compare_urls(
        topic=body.topic,
        urls=body.urls,
        max_sources=body.max_sources,
    )


@router.post("/research/brief", response_model=ResearchBrief)
async def brief(body: ResearchRequest) -> ResearchBrief:
    """All-in-one research brief: search → fetch → summarize → compare."""
    result = await research_service.research_brief(
        query=body.query,
        max_sources=body.max_sources,
        include_comparison=body.include_comparison,
    )
    return result
