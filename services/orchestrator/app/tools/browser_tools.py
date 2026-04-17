"""
browser_tools.py – Playwright-based browser automation tools.

Tools:
  browser_open    – atidaro URL naršyklėje (headless arba matoma)
  browser_search  – ieško Google ir grąžina rezultatus
  browser_read    – nuskaito puslapio tekstą
  browser_click   – spaudžia elementą pagal tekstą/selector
  browser_fill    – užpildo formą (field + value)
  browser_screenshot – daro ekrano nuotrauką

Naudoja Playwright su vartotojo Chrome profiliu (persistent context) –
todėl visos prisijungtos paskyros (Gmail, GitHub ir kt.) veikia iš karto.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

# ── Persistent browser context ────────────────────────────────────────────────
# Naudojame vartotojo tikrą Chrome profilį kad sesijos/cookies išliktų.
# Chrome profilio kelias macOS:
_CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"
# Atsarginis Playwright profilis (jei Chrome neįdiegtas)
_PW_PROFILE_DIR   = Path.home() / ".lani_browser_profile"

_browser_ctx = None   # globalus persistent context
_pw_instance  = None


async def _get_context():
    """Grąžina arba sukuria persistent Playwright kontekstą su Chrome profiliu."""
    global _browser_ctx, _pw_instance

    if _browser_ctx is not None:
        return _browser_ctx

    from playwright.async_api import async_playwright

    _pw_instance = await async_playwright().start()

    # Pirma bandome su realiu Chrome profiliu
    chrome_exec = _find_chrome()
    if chrome_exec and _CHROME_USER_DATA.exists():
        try:
            _browser_ctx = await _pw_instance.chromium.launch_persistent_context(
                user_data_dir=str(_CHROME_USER_DATA),
                executable_path=chrome_exec,
                headless=False,
                args=["--no-first-run", "--no-default-browser-check"],
                ignore_default_args=["--enable-automation"],
            )
            log.info("[browser] Naudojamas tikras Chrome profilis: %s", _CHROME_USER_DATA)
            return _browser_ctx
        except Exception as e:
            log.warning("[browser] Nepavyko naudoti Chrome profilio: %s", e)

    # Fallback – Playwright Chromium su persisitenciniu profiliu
    _PW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _browser_ctx = await _pw_instance.chromium.launch_persistent_context(
        user_data_dir=str(_PW_PROFILE_DIR),
        headless=False,
        args=["--no-first-run", "--no-default-browser-check"],
    )
    log.info("[browser] Naudojamas Playwright profilis: %s", _PW_PROFILE_DIR)
    return _browser_ctx


def _find_chrome() -> str | None:
    """Randa Google Chrome vykdomąjį failą macOS."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


async def _new_page(url: str | None = None):
    """Atidaro naują tab'ą persistent kontekste."""
    ctx = await _get_context()
    page = await ctx.new_page()
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    return page


# ── Tools ─────────────────────────────────────────────────────────────────────

class BrowserOpenTool(BaseTool):
    name = "browser_open"
    description = (
        "Atidaro nurodytą URL naršyklėje. "
        "Naudoti kai vartotojas prašo atidaryti konkretų puslapį ar svetainę. "
        "Parametrai: url (pilnas URL su https://), headless (true/false, default false)."
    )
    requires_approval = False
    parameters = [
        {"name": "url", "description": "Pilnas URL pvz. https://google.com", "required": True},
        {"name": "headless", "description": "Ar vykdyti fone (true/false)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, status="error", message="URL nenurodytas.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            page = await _new_page(url)
            await page.wait_for_timeout(1500)
            title = await page.title()
            return ToolResult(
                tool_name=self.name,
                status="success",
                message=f"Atidaryta: {title} ({url})",
                data={"url": url, "title": title},
            )
        except Exception as e:
            log.error("[browser_open] %s", e)
            return ToolResult(tool_name=self.name, status="error", message=str(e))


class BrowserSearchTool(BaseTool):
    name = "browser_search"
    description = (
        "Ieško Google ir grąžina tekstinius rezultatus (be naršyklės lango). "
        "Naudoti kai reikia greitai surasti informaciją internete. "
        "Parametrai: query (paieškos užklausa)."
    )
    requires_approval = False
    parameters = [
        {"name": "query", "description": "Paieškos užklausa", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult(tool_name=self.name, status="error", message="Užklausa tuščia.")

        try:
            import urllib.parse
            search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
            page = await _new_page(search_url)
            await page.wait_for_timeout(1500)

            results = await page.evaluate("""() => {
                const items = [];
                document.querySelectorAll('h3').forEach((h, i) => {
                    if (i >= 8) return;
                    const a = h.closest('a');
                    const snippet = h.closest('[data-sokoban-container]')
                        ?.querySelector('[data-sncf]')?.innerText
                        || h.parentElement?.nextElementSibling?.innerText || '';
                    if (h.innerText && a?.href) {
                        items.push({
                            title: h.innerText,
                            url: a.href,
                            snippet: snippet.slice(0, 200)
                        });
                    }
                });
                return items;
            }""")

            if not results:
                return ToolResult(tool_name=self.name, status="error", message="Nerasta rezultatų.")

            text = "\n".join(
                f"{i+1}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                for i, r in enumerate(results[:5])
            )
            return ToolResult(
                tool_name=self.name, status="success",
                message=text,
                data={"results": results[:5], "query": query},
            )
        except Exception as e:
            log.error("[browser_search] %s", e)
            return ToolResult(tool_name=self.name, status="error", message=str(e))


class BrowserReadTool(BaseTool):
    name = "browser_read"
    description = (
        "Nuskaito puslapio tekstą iš nurodyto URL. "
        "Naudoti kai reikia perskaityti straipsnio ar puslapio turinį. "
        "Parametrai: url."
    )
    requires_approval = False
    parameters = [
        {"name": "url", "description": "Pilnas URL", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, status="error", message="URL nenurodytas.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            page = await _new_page(url)
            await page.wait_for_timeout(1000)

            text = await page.evaluate("""() => {
                ['script','style','nav','header','footer','aside',
                 '[class*="ad"]','[class*="banner"]','[id*="ad"]']
                    .forEach(sel => document.querySelectorAll(sel)
                        .forEach(el => el.remove()));
                return (document.body?.innerText || '').trim().slice(0, 4000);
            }""")
            title = await page.title()

            return ToolResult(
                tool_name=self.name, status="success",
                message=f"# {title}\n\n{text}",
                data={"url": url, "title": title, "text_length": len(text)},
            )
        except Exception as e:
            log.error("[browser_read] %s", e)
            return ToolResult(tool_name=self.name, status="error", message=str(e))


class BrowserFillFormTool(BaseTool):
    name = "browser_fill"
    description = (
        "Atidaro URL ir užpildo formą. Įveda tekstą į nurodytą lauką ir paspaudžia submit. "
        "Parametrai: url, selector (CSS selector arba placeholder tekstas), value, submit (true/false)."
    )
    requires_approval = True  # formų pildymas – visuomet su approval
    parameters = [
        {"name": "url", "description": "Puslapis su forma", "required": True},
        {"name": "selector", "description": "Lauko CSS selector arba placeholder tekstas", "required": True},
        {"name": "value", "description": "Teksto reikšmė", "required": True},
        {"name": "submit", "description": "Ar paspausti submit (true/false)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        selector: str = params.get("selector", "").strip()
        value: str = params.get("value", "")
        do_submit: bool = str(params.get("submit", "false")).lower() == "true"

        if not url or not selector:
            return ToolResult(tool_name=self.name, status="error", message="URL arba selector nenurodytas.")

        try:
            page = await _new_page(url)
            await page.wait_for_timeout(1000)

            try:
                await page.fill(selector, value)
            except Exception:
                await page.fill(f"[placeholder*='{selector}']", value)

            if do_submit:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2000)

            return ToolResult(
                tool_name=self.name, status="success",
                message=f"Forma užpildyta: '{selector}' = '{value}'" + (" ir išsiųsta." if do_submit else "."),
            )
        except Exception as e:
            log.error("[browser_fill] %s", e)
            return ToolResult(tool_name=self.name, status="error", message=str(e))


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = (
        "Atidaro URL ir spaudžia mygtuką ar nuorodą pagal tekstą. "
        "Parametrai: url, text (mygtuko tekstas)."
    )
    requires_approval = True
    parameters = [
        {"name": "url", "description": "Puslapis", "required": True},
        {"name": "text", "description": "Mygtuko ar nuorodos tekstas", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        text: str = params.get("text", "").strip()
        if not url or not text:
            return ToolResult(tool_name=self.name, status="error", message="URL arba tekstas nenurodytas.")

        try:
            page = await _new_page(url)
            await page.wait_for_timeout(1000)
            await page.get_by_text(text, exact=False).first.click()
            await page.wait_for_timeout(2000)
            new_url = page.url

            return ToolResult(
                tool_name=self.name, status="success",
                message=f"Paspaustas '{text}'. Naujas URL: {new_url}",
                data={"clicked": text, "new_url": new_url},
            )
        except Exception as e:
            log.error("[browser_click] %s", e)
            return ToolResult(tool_name=self.name, status="error", message=str(e))


# ── Export list ───────────────────────────────────────────────────────────────
BROWSER_TOOLS: list[BaseTool] = [
    BrowserOpenTool(),
    BrowserSearchTool(),
    BrowserReadTool(),
    BrowserFillFormTool(),
    BrowserClickTool(),
]
