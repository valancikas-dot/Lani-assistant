"""
deep_research_tool.py – Multi-source web research with synthesis.

Goes far beyond simple web_search:
  1. Searches multiple queries in parallel
  2. Scrapes full page text from top results
  3. Cross-references facts across sources
  4. Synthesizes a structured report with citations
  5. Saves the report as Markdown

Tools:
  deep_research       – full multi-source research on a topic
  scrape_url          – extract full article text from a URL
  fact_check          – verify a claim against multiple web sources
  competitor_analysis – structured competitive research report
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Optional
from pathlib import Path

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_OUTPUT_DIR = Path.home() / "Desktop" / "Lani_Research"
_MAX_PAGE_CHARS = 8_000
_DEFAULT_SOURCES = 6


def _research_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower())[:50].strip("_")


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>",  " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


async def _fetch_url(url: str, timeout: int = 12) -> str:
    """Fetch page text, return stripped text or empty string on error."""
    loop = asyncio.get_event_loop()
    def _do():
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9,lt;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(200_000).decode(errors="replace")
                return _strip_html(raw)[:_MAX_PAGE_CHARS]
        except Exception:
            return ""
    return await loop.run_in_executor(None, _do)


async def _ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """DuckDuckGo search – returns list of {title, url, snippet}."""
    try:
        from app.services import research_service
        resp = await research_service.web_search(query, max_results=max_results)
        return [{"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in resp.results]
    except Exception as e:
        log.warning("[deep_research] ddg error: %s", e)
        return []


async def _llm_synthesize(system: str, user: str, max_tokens: int = 3000) -> str:
    """Call LLM for synthesis step."""
    try:
        from app.core.config import settings as cfg
        from app.services.llm_text_service import complete_text
        if not getattr(cfg, "OPENAI_API_KEY", ""):
            return "LLM nepasiekiamas (nėra OPENAI_API_KEY)."
        return await complete_text(
            openai_api_key=cfg.OPENAI_API_KEY,
            openai_model=getattr(cfg, "RESEARCH_MODEL", getattr(cfg, "LLM_MODEL", "gpt-4o")),
            openai_messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
    except Exception as e:
        return f"Sintezės klaida: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Deep Research Tool
# ─────────────────────────────────────────────────────────────────────────────

class DeepResearchTool(BaseTool):
    name = "deep_research"
    description = (
        "Perform comprehensive multi-source research on any topic. "
        "Searches the web, scrapes top pages, cross-references facts, and synthesizes "
        "a structured Markdown report with citations saved to Desktop/Lani_Research/. "
        "Parameters: topic (required), queries (optional list of specific search queries, "
        "auto-generated if omitted), sources (number of pages to read, default 6), "
        "language ('en'|'lt', default 'en'), save (bool, default true), "
        "focus (optional: 'pricing'|'technical'|'marketing'|'general')."
    )
    requires_approval = False
    parameters = [
        {"name": "topic",    "description": "Research topic", "required": True},
        {"name": "queries",  "description": "List of search queries (auto-generated if omitted)", "required": False},
        {"name": "sources",  "description": "Number of web sources to read (default 6, max 15)", "required": False},
        {"name": "language", "description": "Report language: 'en' or 'lt'", "required": False},
        {"name": "save",     "description": "Save report to Desktop/Lani_Research/ (default true)", "required": False},
        {"name": "focus",    "description": "Research focus: 'pricing', 'technical', 'marketing', 'general'", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        topic: str   = params.get("topic", "").strip()
        if not topic:
            return ToolResult(tool_name=self.name, status="error", message="topic is required")

        n_sources: int = min(int(params.get("sources", _DEFAULT_SOURCES)), 15)
        language: str  = params.get("language", "en")
        save: bool     = params.get("save", True)
        focus: str     = params.get("focus", "general")

        # ── Step 1: Build search queries
        user_queries: list = params.get("queries", [])
        if not user_queries:
            # Generate queries with LLM
            query_prompt = (
                f"Generate 4 specific, diverse web search queries to comprehensively research: '{topic}'. "
                f"Focus: {focus}. Return ONLY a JSON array of strings, nothing else."
            )
            raw = await _llm_synthesize(
                "You are a research assistant. Return ONLY valid JSON arrays.",
                query_prompt, max_tokens=200,
            )
            try:
                import json
                # extract JSON array even if LLM wraps it in markdown
                m = re.search(r"\[.*?\]", raw, re.S)
                user_queries = json.loads(m.group()) if m else [topic]
            except Exception:
                user_queries = [topic, f"{topic} overview", f"{topic} analysis"]

        # ── Step 2: Search all queries in parallel
        search_tasks = [_ddg_search(q, max_results=4) for q in user_queries[:4]]
        search_results_nested = await asyncio.gather(*search_tasks)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        all_results: list[dict] = []
        for batch in search_results_nested:
            for r in batch:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)

        if not all_results:
            return ToolResult(tool_name=self.name, status="error",
                              message="Nepavyko rasti jokių rezultatų internete")

        # ── Step 3: Scrape top pages in parallel
        top_urls = [r["url"] for r in all_results[:n_sources]]
        scrape_tasks = [_fetch_url(url) for url in top_urls]
        page_texts = await asyncio.gather(*scrape_tasks)

        # Build context chunks
        context_parts: list[str] = []
        citations: list[dict] = []
        for i, (result, text) in enumerate(zip(all_results[:n_sources], page_texts)):
            if text and len(text) > 200:
                chunk = f"### Source {i+1}: {result['title']}\nURL: {result['url']}\n\n{text[:_MAX_PAGE_CHARS]}"
                context_parts.append(chunk)
                citations.append({"n": i+1, "title": result["title"], "url": result["url"]})
            else:
                # Use snippet if page scrape failed
                if result.get("snippet"):
                    context_parts.append(f"### Source {i+1}: {result['title']}\n{result['snippet']}")
                    citations.append({"n": i+1, "title": result["title"], "url": result["url"]})

        full_context = "\n\n---\n\n".join(context_parts)

        # ── Step 4: Synthesize report
        focus_instructions = {
            "pricing":    "Focus on pricing, tiers, cost structures, and value propositions.",
            "technical":  "Focus on technical details, architecture, APIs, and capabilities.",
            "marketing":  "Focus on marketing messages, target audiences, positioning, and brand.",
            "general":    "Provide a comprehensive balanced overview.",
            "competitor": "Focus on strengths, weaknesses, differentiators, and market position.",
        }
        focus_note = focus_instructions.get(focus, focus_instructions["general"])

        lang_note = "Write the entire report in Lithuanian (lietuvių kalba)." if language == "lt" else "Write in English."

        system_prompt = f"""You are a senior research analyst. {lang_note}
{focus_note}
Create a well-structured Markdown research report. Include:
- Executive Summary (2-3 sentences)
- Key Findings (bullet points)
- Detailed Analysis (sections with headers)
- Comparison table (if applicable)
- Conclusions and Recommendations
- Citations as [1], [2] etc referencing sources
Be factual, cite sources, and note any conflicting information."""

        user_prompt = f"""Research topic: {topic}

Here are the scraped sources:

{full_context[:12000]}

Write a comprehensive research report with all sections."""

        report_md = await _llm_synthesize(system_prompt, user_prompt, max_tokens=3000)

        # Append citations section
        cite_section = "\n\n---\n## Sources\n" + "\n".join(
            f"[{c['n']}] [{c['title']}]({c['url']})" for c in citations
        )
        full_report = report_md + cite_section

        # ── Step 5: Save
        saved_path: str | None = None
        if save:
            filename = f"research_{_slug(topic)}.md"
            out_path = _research_dir() / filename
            out_path.write_text(full_report, encoding="utf-8")
            saved_path = str(out_path)

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"✅ Tyrimas baigtas: {len(citations)} šaltiniai, {len(full_report)} simboliai",
            data={
                "topic":      topic,
                "report":     full_report,
                "saved_path": saved_path,
                "citations":  citations,
                "queries":    user_queries,
                "sources_read": len(citations),
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scrape URL
# ─────────────────────────────────────────────────────────────────────────────

class ScrapeUrlTool(BaseTool):
    name = "scrape_url"
    description = (
        "Extract and return the full clean text content from a web page URL. "
        "Better than browser_read for articles, documentation, and product pages. "
        "Parameters: url (required), max_chars (default 8000)."
    )
    requires_approval = False
    parameters = [
        {"name": "url",       "description": "Web page URL to scrape", "required": True},
        {"name": "max_chars", "description": "Max characters to return (default 8000)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, status="error", message="url is required")
        max_chars: int = int(params.get("max_chars", _MAX_PAGE_CHARS))
        text = await _fetch_url(url)
        if not text:
            return ToolResult(tool_name=self.name, status="error",
                              message=f"Nepavyko nuskaityti: {url}")
        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"✅ Nuskaityti {len(text)} simboliai",
            data={"url": url, "text": text[:max_chars], "total_chars": len(text)},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Competitor Analysis
# ─────────────────────────────────────────────────────────────────────────────

class CompetitorAnalysisTool(BaseTool):
    name = "competitor_analysis"
    description = (
        "Research and compare competitors for a product/service. "
        "Generates a structured comparison with pricing, features, positioning, and insights. "
        "Parameters: product (your product/niche, required), competitors (list of names, optional), "
        "language ('en'|'lt', default 'en'), save (bool, default true)."
    )
    requires_approval = False
    parameters = [
        {"name": "product",     "description": "Your product or niche to analyze", "required": True},
        {"name": "competitors", "description": "List of competitor names (auto-discovered if empty)", "required": False},
        {"name": "language",    "description": "'en' or 'lt'", "required": False},
        {"name": "save",        "description": "Save report to file", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        product: str      = params.get("product", "").strip()
        competitors: list = params.get("competitors", [])
        language: str     = params.get("language", "en")
        save: bool        = params.get("save", True)

        if not product:
            return ToolResult(tool_name=self.name, status="error", message="product is required")

        # Build topic
        if competitors:
            topic = f"Compare {product} vs {', '.join(competitors)}: pricing, features, pros cons"
        else:
            topic = f"Top competitors of {product}: pricing, features, market position 2025 2026"

        # Reuse DeepResearchTool
        research_tool = DeepResearchTool()
        return await research_tool.run({
            "topic":    topic,
            "focus":    "competitor",
            "language": language,
            "sources":  8,
            "save":     save,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Fact Check
# ─────────────────────────────────────────────────────────────────────────────

class FactCheckTool(BaseTool):
    name = "fact_check"
    description = (
        "Verify a claim or statement against multiple web sources. "
        "Returns: verdict (true/false/disputed/unverified), evidence, and source citations. "
        "Parameters: claim (required), language ('en'|'lt', default 'en')."
    )
    requires_approval = False
    parameters = [
        {"name": "claim",    "description": "The claim or statement to verify", "required": True},
        {"name": "language", "description": "'en' or 'lt'", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        claim: str    = params.get("claim", "").strip()
        language: str = params.get("language", "en")
        if not claim:
            return ToolResult(tool_name=self.name, status="error", message="claim is required")

        results = await _ddg_search(f'"{claim}"', max_results=6)
        results += await _ddg_search(f"fact check {claim}", max_results=4)

        context = "\n".join(
            f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in results[:8]
        )

        lang_note = "Respond in Lithuanian." if language == "lt" else "Respond in English."
        report = await _llm_synthesize(
            f"You are a fact-checker. {lang_note} Be objective. "
            "Return a JSON object with keys: verdict (true/false/disputed/unverified), "
            "confidence (0-100), summary (2 sentences), evidence (list of strings), sources (list of URLs).",
            f"Claim: {claim}\n\nEvidence from web:\n{context}",
            max_tokens=600,
        )

        import json as _json
        try:
            m = re.search(r"\{.*\}", report, re.S)
            data = _json.loads(m.group()) if m else {"verdict": "unverified", "summary": report}
        except Exception:
            data = {"verdict": "unverified", "summary": report}

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=f"Verdict: {data.get('verdict', 'unverified')}",
            data={"claim": claim, **data},
        )
