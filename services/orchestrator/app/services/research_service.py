"""
Research Service – core logic for the Browser / Research Operator layer.

Responsibilities
────────────────
1. web_search(query, max_results)
   Uses DuckDuckGo (no API key required) to return structured search results.

2. fetch_and_extract(url, timeout)
   Downloads a web page with httpx and strips HTML → readable plain text
   via BeautifulSoup.  Returns (title, snippet, ok_flag).

3. summarize_urls(query, urls, max_sources)
   Fetches each URL, extracts text, builds overall_summary + key_points
   from the combined content.  Fails gracefully on per-source errors.

4. compare_urls(topic, urls, max_sources)
   Downloads the same set of pages, derives a simple criteria-based
   comparison table from the extracted text.

5. research_brief(query, max_sources, include_comparison)
   All-in-one: search → pick top sources → summarize → optionally compare.
   Returns a ResearchBrief ready for the planner or presentation tools.

Design notes
────────────
- All network calls are async (httpx.AsyncClient).
- Each URL fetch is fire-and-forget inside a TaskGroup; failures are caught
  individually so partial results are always returned.
- No fake data anywhere – real HTTP requests, real text extraction.
- Text summarization is rule-based (sentence extraction + dedup) to keep the
  implementation self-contained with no LLM key requirement.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import List, Optional, Tuple, cast
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.schemas.research import (
    CompareResponse,
    ComparedItem,
    ResearchBrief,
    SearchResult,
    SourceSummary,
    SummarizeResponse,
    WebSearchResponse,
)


# ─── Constants ────────────────────────────────────────────────────────────────

_FETCH_TIMEOUT = 10.0          # seconds per page
_MAX_TEXT_CHARS = 8_000        # chars to keep per page before summarising
_MIN_SENTENCE_LEN = 40         # chars; shorter "sentences" are noise
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Tags whose text we always skip
_SKIP_TAGS = {
    "script", "style", "noscript", "nav", "footer",
    "header", "aside", "form", "button", "input",
}


# ─── 1. Web search (DuckDuckGo, no key needed) ───────────────────────────────

async def web_search(query: str, max_results: int = 8) -> WebSearchResponse:
    """
    Return structured search results from DuckDuckGo.

    Falls back to an error response (not an exception) when the library or
    network is unavailable, so the rest of the plan can still proceed.
    """
    try:
        from ddgs import DDGS  # type: ignore[import]

        loop = asyncio.get_event_loop()

        def _sync_search() -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        raw: list[dict] = await loop.run_in_executor(None, _sync_search)

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
                source_domain=_domain(r.get("href", "")),
            )
            for r in raw
            if r.get("href")
        ]
        return WebSearchResponse(
            query=query,
            results=results,
            total_results=len(results),
        )
    except Exception as exc:
        return WebSearchResponse(
            query=query,
            results=[],
            total_results=0,
            error=f"Search failed: {exc}",
        )


# ─── 2. Single-page fetch + text extraction ───────────────────────────────────

async def fetch_and_extract(
    url: str,
    timeout: float = _FETCH_TIMEOUT,
) -> Tuple[str, str, bool]:
    """
    Fetch *url* and return (title, snippet, success).

    snippet is the first ~400 chars of clean body text.
    On failure returns ("", "", False).
    """
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        title, text = _extract_text(html)
        snippet = text[:400].strip()
        return title, snippet, True
    except Exception:
        return "", "", False


def _extract_text(html: str) -> Tuple[str, str]:
    """Strip HTML → (title, body_text)."""
    soup = BeautifulSoup(html, "lxml")

    # Remove noise tags
    for tag in soup.find_all(_SKIP_TAGS):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""

    # Collect paragraph / heading / list text
    parts: List[str] = []
    for elem in soup.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        txt = elem.get_text(separator=" ", strip=True)
        txt = _clean(txt)
        if len(txt) > 20:
            parts.append(txt)

    body = " ".join(parts)
    body = re.sub(r"\s{2,}", " ", body).strip()
    return title, body[:_MAX_TEXT_CHARS]


def _clean(text: str) -> str:
    """Normalise unicode and remove control characters."""
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return url


# ─── 3. Summarise multiple URLs ───────────────────────────────────────────────

async def summarize_urls(
    query: str,
    urls: List[str],
    max_sources: int = 5,
) -> SummarizeResponse:
    """
    Fetch up to *max_sources* URLs in parallel, extract text, build summary.
    """
    targets = urls[:max_sources]
    if not targets:
        return SummarizeResponse(
            query=query,
            overall_summary="No URLs provided.",
            key_points=[],
            sources=[],
            sources_attempted=0,
            sources_succeeded=0,
        )

    # Parallel fetch
    tasks = [fetch_and_extract(url) for url in targets]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    sources: List[SourceSummary] = []
    combined_text = ""
    succeeded = 0

    for url, result in zip(targets, raw_results):
        if isinstance(result, Exception):
            sources.append(SourceSummary(url=url, title="", snippet="", fetched=False))
            continue

        title, snippet, ok = cast(Tuple[str, str, bool], result)
        if not ok:
            sources.append(SourceSummary(url=url, title="", snippet="", fetched=False))
        else:
            sources.append(SourceSummary(url=url, title=title, snippet=snippet, fetched=True))
            combined_text += f"\n\n{title}\n{snippet}"
            succeeded += 1

    overall_summary, key_points = _extract_summary(query, combined_text)

    return SummarizeResponse(
        query=query,
        overall_summary=overall_summary,
        key_points=key_points,
        sources=sources,
        sources_attempted=len(targets),
        sources_succeeded=succeeded,
        error=None if succeeded > 0 else "All sources failed to load.",
    )


def _extract_summary(query: str, text: str) -> Tuple[str, List[str]]:
    """
    Rule-based extractive summarisation:
    1. Split text into sentences.
    2. Score sentences by keyword overlap with *query*.
    3. Return top-3 as overall_summary and up to 7 more as key_points.
    """
    if not text.strip():
        return "No content could be extracted from the provided sources.", []

    # Sentence split
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= _MIN_SENTENCE_LEN]

    query_words = set(re.findall(r"\w+", query.lower()))

    def score(s: str) -> int:
        words = set(re.findall(r"\w+", s.lower()))
        return len(words & query_words)

    ranked = sorted(sentences, key=score, reverse=True)
    top = list(dict.fromkeys(ranked[:10]))   # dedup while preserving order

    if not top:
        return "Could not extract meaningful content from sources.", []

    overall = " ".join(top[:3])
    key_points = [_shorten(s, 200) for s in top[3:10]]
    return overall, key_points


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


# ─── 4. Comparison ────────────────────────────────────────────────────────────

async def compare_urls(
    topic: str,
    urls: List[str],
    max_sources: int = 6,
) -> CompareResponse:
    """
    Fetch pages and produce a simple structured comparison.

    Criteria are inferred from the topic keywords. Each item gets a score
    per criterion based on how many times the criterion word appears in the
    extracted page text.
    """
    targets = urls[:max_sources]
    if not targets:
        return CompareResponse(
            topic=topic,
            criteria=[],
            compared_items=[],
            conclusion="No URLs to compare.",
            error="No URLs provided.",
        )

    tasks = [fetch_and_extract(url) for url in targets]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    criteria = _infer_criteria(topic)
    compared_items: List[ComparedItem] = []
    valid_urls: List[str] = []

    for url, result in zip(targets, raw_results):
        if isinstance(result, Exception):
            continue

        title, text, ok = cast(Tuple[str, str, bool], result)
        if not ok:
            continue

        scores = {c: _count_mentions(c, text) for c in criteria}
        summary_sent, _ = _extract_summary(topic, text)
        compared_items.append(ComparedItem(
            name=title or _domain(url),
            url=url,
            scores=scores,
            summary=_shorten(summary_sent, 300),
        ))
        valid_urls.append(url)

    if not compared_items:
        return CompareResponse(
            topic=topic,
            criteria=criteria,
            compared_items=[],
            conclusion="No sources could be loaded for comparison.",
            sources=targets,
            error="All sources failed to load.",
        )

    # Pick winner per criterion
    winner_lines: List[str] = []
    for crit in criteria:
        best = max(compared_items, key=lambda x: x.scores.get(crit, 0))
        winner_lines.append(f"{best.name} scores highest on '{crit}'.")

    conclusion = " ".join(winner_lines)
    return CompareResponse(
        topic=topic,
        criteria=criteria,
        compared_items=compared_items,
        conclusion=conclusion,
        sources=valid_urls,
    )


def _infer_criteria(topic: str) -> List[str]:
    """Return a small list of comparison criteria inferred from the topic."""
    common_criteria = [
        "pricing", "features", "ease of use", "integration",
        "performance", "security", "support", "scalability",
    ]
    words = set(re.findall(r"\w+", topic.lower()))
    # always include a few plus any topic-specific matches
    base = ["features", "ease of use", "pricing"]
    extras = [c for c in common_criteria if c not in base and any(w in c for w in words)]
    return base + extras[:3]


def _count_mentions(word: str, text: str) -> int:
    return len(re.findall(re.escape(word.lower()), text.lower()))


# ─── 5. All-in-one research brief ────────────────────────────────────────────

async def research_brief(
    query: str,
    max_sources: int = 5,
    include_comparison: bool = False,
) -> ResearchBrief:
    """
    Full pipeline: search → fetch top sources → summarize → optionally compare.

    Returns a ResearchBrief that can be used directly by the planner or fed
    into presentation_tools as slide content.
    """
    # Step 1: search
    search_resp = await web_search(query, max_results=max_sources + 3)

    if not search_resp.results:
        return ResearchBrief(
            query=query,
            summary=search_resp.error or "No search results found.",
            raw_search=search_resp,
            error=search_resp.error,
        )

    top_urls = [r.url for r in search_resp.results[:max_sources]]

    # Step 2: summarize
    summ = await summarize_urls(query, top_urls, max_sources=max_sources)

    # Step 3: optional comparison
    comparison: Optional[CompareResponse] = None
    if include_comparison and len(top_urls) >= 2:
        comparison = await compare_urls(query, top_urls, max_sources=max_sources)

    return ResearchBrief(
        query=query,
        summary=summ.overall_summary,
        key_points=summ.key_points,
        top_sources=search_resp.results[:max_sources],
        comparison=comparison,
        raw_search=search_resp,
        error=summ.error,
    )
