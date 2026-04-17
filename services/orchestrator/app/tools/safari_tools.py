"""
safari_tools.py – Safari valdymas per AppleScript.

Naudoja tikrą Safari su visomis vartotojo sesijomis/cookies –
Gmail, iCloud, bankai, socialiniai tinklai ir t.t.

Tools:
  safari_open        – atidaro URL Safari
  safari_read        – nuskaito aktyvaus tab'o turinį
  safari_click       – spaudžia elementą pagal tekstą (JavaScript inject)
  safari_fill        – užpildo formą
  safari_run_js      – vykdo JavaScript aktyvame tab'e
  safari_get_tabs    – grąžina visų atidarytų tab'ų sąrašą
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


# ── AppleScript helpers ───────────────────────────────────────────────────────

def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        timeout=30,
    )


async def _osa(script: str) -> tuple[int, str, str]:
    """Async wrapper aplink osascript."""
    proc = await asyncio.to_thread(_osascript, script)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace").strip(),
        proc.stderr.decode("utf-8", errors="replace").strip(),
    )


async def _safari_js(js: str) -> tuple[int, str, str]:
    """Vykdo JavaScript aktyvame Safari tab'e."""
    # Escape double quotes ir backslashes JS kode
    escaped = js.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Safari" to do JavaScript "{escaped}" in current tab of front window'
    return await _osa(script)


async def _ensure_safari_open(url: str | None = None) -> tuple[int, str, str]:
    """Įsitikina kad Safari atidarytas, ir jei reikia atidaro URL."""
    if url:
        script = f'''
tell application "Safari"
    activate
    if (count of windows) = 0 then
        make new document with properties {{URL:"{url}"}}
    else
        set URL of current tab of front window to "{url}"
    end if
end tell'''
    else:
        script = 'tell application "Safari" to activate'
    return await _osa(script)


# ── Tools ─────────────────────────────────────────────────────────────────────

class SafariOpenTool(BaseTool):
    name = "safari_open"
    description = (
        "Atidaro URL tikroje Safari naršyklėje su visomis vartotojo sesijomis. "
        "Naudoti kai vartotojas turi paskyras Safari (Gmail, iCloud, bankai ir kt.). "
        "Parametrai: url."
    )
    requires_approval = False
    parameters = [
        {"name": "url", "description": "Pilnas URL pvz. https://mail.google.com", "required": True},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult(tool_name=self.name, status="error", message="URL nenurodytas.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        rc, out, err = await _ensure_safari_open(url)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or f"Nepavyko atidaryti {url}")

        # Palaukiame kol puslapis pakyla
        await asyncio.sleep(2)
        rc2, title, _ = await _osa('tell application "Safari" to get name of current tab of front window')
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"Atidaryta Safari: {title or url}",
            data={"url": url, "title": title},
        )


class SafariReadTool(BaseTool):
    name = "safari_read"
    description = (
        "Nuskaito aktyvaus Safari tab'o turinį kaip tekstą. "
        "Veikia su visomis prisijungtomis paskyromis. "
        "Naudoti po safari_open kad perskaityti puslapio informaciją."
    )
    requires_approval = False
    parameters = [
        {"name": "url", "description": "URL atidaryti prieš skaitant (nebūtinas jei jau atidarytas)", "required": False},
        {"name": "max_chars", "description": "Maksimalus simbolių skaičius (default 3000)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        url: str = params.get("url", "").strip()
        max_chars: int = int(params.get("max_chars", 3000))

        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await _ensure_safari_open(url)
            await asyncio.sleep(2)

        js = (
            "["
            "document.title,"
            "document.location.href,"
            "(() => {"
            "  ['script','style','nav','header','footer','aside','[class*=ad]','[role=banner]']"
            "    .forEach(s => document.querySelectorAll(s).forEach(e => e.remove()));"
            f"  return (document.body?.innerText || '').trim().slice(0, {max_chars});"
            "})()].join('|||')"
        )
        rc, out, err = await _safari_js(js)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or "Nepavyko perskaityti puslapio.")

        parts = out.split("|||")
        title = parts[0] if len(parts) > 0 else ""
        current_url = parts[1] if len(parts) > 1 else ""
        text = parts[2] if len(parts) > 2 else out

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"# {title}\n{current_url}\n\n{text}",
            data={"title": title, "url": current_url, "text": text},
        )


class SafariClickTool(BaseTool):
    name = "safari_click"
    description = (
        "Spaudžia mygtuką ar nuorodą Safari puslapyje pagal jo tekstą. "
        "Parametrai: text (mygtuko/nuorodos tekstas), url (nebūtinas)."
    )
    requires_approval = True
    parameters = [
        {"name": "text", "description": "Mygtuko ar nuorodos tekstas", "required": True},
        {"name": "url", "description": "Puslapis kurį atidaryti prieš spaudžiant (nebūtinas)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        text: str = params.get("text", "").strip()
        url: str = params.get("url", "").strip()
        if not text:
            return ToolResult(tool_name=self.name, status="error", message="Tekstas nenurodytas.")

        if url:
            await _ensure_safari_open(url)
            await asyncio.sleep(2)

        # Ieško elemento pagal tekstą ir spaudžia
        js = (
            f"(function(){{"
            f"  var els = Array.from(document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button]'));"
            f"  var t = {repr(text.lower())};"
            f"  var el = els.find(e => (e.innerText||e.value||'').toLowerCase().includes(t));"
            f"  if (el) {{ el.click(); return 'clicked: ' + (el.innerText||el.value||el.href); }}"
            f"  return 'not found: ' + t;"
            f"}})()"
        )
        rc, out, err = await _safari_js(js)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or "Nepavyko spausti elemento.")
        if out.startswith("not found"):
            return ToolResult(tool_name=self.name, status="error", message=f"Elementas '{text}' nerastas puslapyje.")

        await asyncio.sleep(1)
        return ToolResult(
            tool_name=self.name, status="success",
            message=f"Paspaustas: {out}",
            data={"clicked": text, "result": out},
        )


class SafariFillTool(BaseTool):
    name = "safari_fill"
    description = (
        "Užpildo formą Safari puslapyje. "
        "Parametrai: selector (CSS selector arba placeholder), value, url (nebūtinas), submit (true/false)."
    )
    requires_approval = True
    parameters = [
        {"name": "selector", "description": "CSS selector arba placeholder tekstas", "required": True},
        {"name": "value", "description": "Įvesti tekstas", "required": True},
        {"name": "url", "description": "Puslapis (nebūtinas)", "required": False},
        {"name": "submit", "description": "Ar paspausti Enter (true/false)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        selector: str = params.get("selector", "").strip()
        value: str = params.get("value", "")
        url: str = params.get("url", "").strip()
        do_submit: bool = str(params.get("submit", "false")).lower() == "true"

        if not selector:
            return ToolResult(tool_name=self.name, status="error", message="Selector nenurodytas.")

        if url:
            await _ensure_safari_open(url)
            await asyncio.sleep(2)

        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped_sel = selector.replace("\\", "\\\\").replace('"', '\\"')

        js = (
            f"(function(){{"
            f"  var el = document.querySelector('{escaped_sel}') "
            f"        || document.querySelector('[placeholder*=\"{escaped_sel}\"]')"
            f"        || document.querySelector('[name*=\"{escaped_sel}\"]');"
            f"  if (!el) return 'not found';"
            f"  el.focus();"
            f"  el.value = '{escaped_value}';"
            f"  el.dispatchEvent(new Event('input', {{bubbles:true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles:true}}));"
            f"  return 'filled';"
            f"}})()"
        )
        rc, out, err = await _safari_js(js)
        if rc != 0 or out == "not found":
            return ToolResult(tool_name=self.name, status="error", message=f"Laukas '{selector}' nerastas.")

        if do_submit:
            await _safari_js(
                "(function(){ var f = document.activeElement?.closest('form'); "
                "if(f) f.submit(); else document.activeElement?.dispatchEvent("
                "new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); })()"
            )
            await asyncio.sleep(2)

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"Laukas '{selector}' užpildytas" + (" ir išsiųstas." if do_submit else "."),
        )


class SafariGetTabsTool(BaseTool):
    name = "safari_get_tabs"
    description = "Grąžina visų atidarytų Safari tab'ų sąrašą (pavadinimas + URL)."
    requires_approval = False

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        script = '''
tell application "Safari"
    set tabList to {}
    repeat with w in windows
        repeat with t in tabs of w
            set end of tabList to (name of t) & " | " & (URL of t)
        end repeat
    end repeat
    return tabList
end tell'''
        rc, out, err = await _osa(script)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or "Nepavyko gauti tab'ų sąrašo.")

        tabs = [line.strip() for line in out.split(",") if line.strip()]
        text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(tabs))
        return ToolResult(
            tool_name=self.name, status="success",
            message=text or "Nėra atidarytų tab'ų.",
            data={"tabs": tabs},
        )


class SafariRunJSTool(BaseTool):
    name = "safari_run_js"
    description = (
        "Vykdo JavaScript kodą aktyvame Safari tab'e. "
        "Naudoti sudėtingiems puslapio sąveikos scenarijams. "
        "Parametrai: code (JavaScript kodas)."
    )
    requires_approval = True
    parameters = [
        {"name": "code", "description": "JavaScript kodas", "required": True},
        {"name": "url", "description": "Puslapis atidaryti prieš vykdant (nebūtinas)", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        code: str = params.get("code", "").strip()
        url: str = params.get("url", "").strip()
        if not code:
            return ToolResult(tool_name=self.name, status="error", message="JavaScript kodas nenurodytas.")

        if url:
            await _ensure_safari_open(url)
            await asyncio.sleep(2)

        rc, out, err = await _safari_js(code)
        if rc != 0:
            return ToolResult(tool_name=self.name, status="error", message=err or "JavaScript klaida.")

        return ToolResult(
            tool_name=self.name, status="success",
            message=f"JS rezultatas: {out[:500]}",
            data={"result": out},
        )


# ── Export ────────────────────────────────────────────────────────────────────
SAFARI_TOOLS: list[BaseTool] = [
    SafariOpenTool(),
    SafariReadTool(),
    SafariClickTool(),
    SafariFillTool(),
    SafariGetTabsTool(),
    SafariRunJSTool(),
]
