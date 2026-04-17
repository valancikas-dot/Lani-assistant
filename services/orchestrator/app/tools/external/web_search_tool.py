"""
web_search_tool.py – Real web search with Tavily primary and DuckDuckGo fallback.

Provider priority:
  1. Tavily (SEARCH_API_KEY set) – specialiai AI agentams, švarūs rezultatai
  2. DuckDuckGo HTML scrape – nemokamai, be key
  3. DuckDuckGo Instant Answers – nemokamai, be key
  4. Simulation – jei visi failina

Result schema (ToolResult.data):
  {
    "success":   bool,
    "simulation": bool,
    "provider":  "tavily" | "duckduckgo" | "simulation",
    "query":     str,
    "results":   List[{title, url, snippet, source}],
    "total":     int,
    "error":     str | None,
  }

Env vars:
  SEARCH_API_KEY  – Tavily key (https://app.tavily.com) – rekomenduojama
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Optional

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

_TAVILY_BASE = "https://api.tavily.com/search"
_DDG_BASE = "https://api.duckduckgo.com"
_SSL_CTX = ssl._create_unverified_context()

# ── Config helpers ─────────────────────────────────────────────────────────────

def _search_key() -> Optional[str]:
    from app.core.config import settings as cfg
    return (
        getattr(cfg, "SEARCH_API_KEY", "") or
        os.environ.get("SEARCH_API_KEY", "")
    ) or None


# ── Tavily Search ──────────────────────────────────────────────────────────────

async def _tavily_search(query: str, max_results: int, api_key: str) -> List[Dict]:
    """Tavily AI search – specialiai sukurta AI agentams."""
    payload = json.dumps({
        "query": query,
        "max_results": min(max_results, 10),
        "include_answer": False,
        "include_raw_content": False,
    }).encode()
    loop = asyncio.get_event_loop()
    def _do():
        req = urllib.request.Request(
            _TAVILY_BASE,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"Tavily {e.code}: {body}") from e

    data = await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=20)
    results = []
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title":   item.get("title", ""),
            "url":     item.get("url", ""),
            "snippet": item.get("content", ""),
            "source":  "tavily",
        })
    return results


# ── DuckDuckGo Instant Answers ─────────────────────────────────────────────────

async def _ddg_search(query: str, max_results: int) -> List[Dict]:
    """DuckDuckGo Instant Answer API – no key required."""
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    url = f"{_DDG_BASE}/?{params}"
    loop = asyncio.get_event_loop()
    def _do():
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Lani/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    data = await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=15)

    results: List[Dict] = []
    # Related topics
    for item in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(item, dict) and item.get("Text") and item.get("FirstURL"):
            results.append({
                "title":   item.get("Text", "")[:100],
                "url":     item.get("FirstURL", ""),
                "snippet": item.get("Text", ""),
                "source":  "duckduckgo",
            })
    # If no related topics, use Abstract
    if not results and data.get("Abstract"):
        results.append({
            "title":   data.get("Heading", query),
            "url":     data.get("AbstractURL", ""),
            "snippet": data.get("Abstract", ""),
            "source":  data.get("AbstractSource", "duckduckgo"),
        })
    return results[:max_results]


# ── DuckDuckGo HTML search (richer, no key) ───────────────────────────────────

async def _ddg_html_search(query: str, max_results: int) -> List[Dict]:
    """Scrape DuckDuckGo HTML results – more reliable than Instant Answers."""
    import re, html as htmllib
    params = urllib.parse.urlencode({"q": query, "ia": "web"})
    url = f"https://html.duckduckgo.com/html/?{params}"
    loop = asyncio.get_event_loop()
    def _do():
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read().decode(errors="replace")

    raw = await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=18)

    results: List[Dict] = []
    # Extract result titles + URLs + snippets
    pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
        r'.*?class="result__snippet"[^>]*>(.*?)</a>',
        re.S,
    )
    for m in pattern.finditer(raw):
        href = htmllib.unescape(m.group(1))
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        snippet = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if href.startswith("http"):
            results.append({"title": title, "url": href, "snippet": snippet, "source": "duckduckgo"})
        if len(results) >= max_results:
            break

    return results


# ── Tool class ─────────────────────────────────────────────────────────────────

class WebSearchExtTool(BaseTool):
    """
    Search the web using SerpAPI (if key configured) or DuckDuckGo (free).
    Falls back to simulation stub only if all providers fail.
    """
    name = "web_search_ext"
    description = (
        "Search the web for current information. "
        "Uses SerpAPI (richer) when SEARCH_API_KEY is set, otherwise DuckDuckGo (free). "
        "Returns structured results with title, URL, and snippet."
    )
    requires_approval = False
    parameters = [
        {"name": "query", "type": "str", "required": True,
         "description": "Search query."},
        {"name": "max_results", "type": "int", "required": False,
         "description": "Maximum number of results (default 8, max 20)."},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = str(params.get("query", "")).strip()
        max_results: int = min(int(params.get("max_results", 8)), 20)

        if not query:
            return ToolResult(
                tool_name=self.name, status="error",
                message="Parameter 'query' is required.",
                data={"success": False, "simulation": False, "provider": None, "error": "query required"},
            )

        # ── Try Tavily ───────────────────────────────────────────────────
        serp_key = _search_key()
        if serp_key:
            try:
                log.info("[search_ext] Tavily: %r", query[:80])
                results = await _tavily_search(query, max_results, serp_key)
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"Found {len(results)} result(s) via Tavily for '{query}'.",
                    data={
                        "success": True, "simulation": False, "provider": "tavily",
                        "query": query, "results": results, "total": len(results), "error": None,
                    },
                )
            except Exception as exc:
                log.warning("[search_ext] Tavily failed, falling back to DDG: %s", exc)

        # ── Try DuckDuckGo HTML ──────────────────────────────────────────
        try:
            log.info("[search_ext] DuckDuckGo HTML: %r", query[:80])
            results = await _ddg_html_search(query, max_results)
            if results:
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"Found {len(results)} result(s) via DuckDuckGo for '{query}'.",
                    data={
                        "success": True, "simulation": False, "provider": "duckduckgo",
                        "query": query, "results": results, "total": len(results), "error": None,
                    },
                )
        except Exception as exc:
            log.warning("[search_ext] DuckDuckGo HTML failed: %s", exc)

        # ── Try DuckDuckGo Instant Answers ────────────────────────────────
        try:
            results = await _ddg_search(query, max_results)
            if results:
                return ToolResult(
                    tool_name=self.name, status="success",
                    message=f"Found {len(results)} result(s) via DuckDuckGo for '{query}'.",
                    data={
                        "success": True, "simulation": False, "provider": "duckduckgo",
                        "query": query, "results": results, "total": len(results), "error": None,
                    },
                )
        except Exception as exc:
            log.warning("[search_ext] DuckDuckGo Instant Answers failed: %s", exc)

        # ── Simulation fallback ───────────────────────────────────────────
        log.info("[search_ext] all providers failed – simulation fallback for: %r", query)
        return ToolResult(
            tool_name=self.name, status="success",
            message=(
                f"⚠ SIMULATION: All search providers unavailable for '{query}'.\n"
                "Configure SEARCH_API_KEY (SerpAPI) for reliable search results."
            ),
            data={
                "success": True,
                "simulation": True,
                "provider": "simulation",
                "query": query,
                "results": [],
                "total": 0,
                "error": None,
                "setup_hint": "Add SEARCH_API_KEY=your_serpapi_key to .env (https://serpapi.com)",
            },
        )
