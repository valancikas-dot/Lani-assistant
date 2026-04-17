"""
Pydantic schemas for the Research / Browser Operator layer.

These types are the stable contract between:
  - research_service (produces them)
  - research_tools    (wraps service calls, returns ToolResult with .data)
  - plan_executor     (stores them in step_results[].data)
  - API route         (serialises them to JSON)
  - Frontend          (renders them as structured research cards)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl


# ─── Individual search result ─────────────────────────────────────────────────

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source_domain: str


class WebSearchResponse(BaseModel):
    query: str
    results: List[SearchResult] = Field(default_factory=list)
    total_results: int = 0
    error: Optional[str] = None


# ─── Summarise response ───────────────────────────────────────────────────────

class SourceSummary(BaseModel):
    url: str
    title: str
    snippet: str           # first meaningful paragraph / excerpt
    fetched: bool = True   # False when page could not be fetched


class SummarizeResponse(BaseModel):
    query: str
    overall_summary: str
    key_points: List[str] = Field(default_factory=list)
    sources: List[SourceSummary] = Field(default_factory=list)
    sources_attempted: int = 0
    sources_succeeded: int = 0
    error: Optional[str] = None


# ─── Comparison response ──────────────────────────────────────────────────────

class ComparedItem(BaseModel):
    name: str                          # e.g. "Notion"
    url: str
    scores: Dict[str, Any] = Field(default_factory=dict)  # criterion → value/score
    summary: str = ""


class CompareResponse(BaseModel):
    topic: str
    criteria: List[str] = Field(default_factory=list)
    compared_items: List[ComparedItem] = Field(default_factory=list)
    conclusion: str = ""
    sources: List[str] = Field(default_factory=list)
    error: Optional[str] = None


# ─── All-in-one research brief ────────────────────────────────────────────────

class ResearchBrief(BaseModel):
    query: str
    summary: str
    key_points: List[str] = Field(default_factory=list)
    top_sources: List[SearchResult] = Field(default_factory=list)
    comparison: Optional[CompareResponse] = None
    raw_search: Optional[WebSearchResponse] = None
    error: Optional[str] = None


# ─── Request bodies ───────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    max_sources: int = Field(default=5, ge=1, le=20)
    include_comparison: bool = False
