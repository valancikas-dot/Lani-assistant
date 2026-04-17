"""
Command router – classifies user intent and dispatches to the correct tool.

Uses OpenAI function-calling when OPENAI_API_KEY is set, with a keyword-based
regex fallback for offline / no-key mode.
"""

import json
import logging
import re
import time as _time
from typing import Any, Dict, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import UserSettings
from app.schemas.commands import CommandRequest, CommandResponse, ToolResult
from app.services.audit_service import record_action
from app.services.llm_tool_calling_service import create_tool_choice
from app.services.execution_guard import guarded_execute
from app.tools.file_tools import set_runtime_allowed_dirs
from app.tools.registry import list_tools

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM-based classifier (OpenAI function calling)
# ---------------------------------------------------------------------------

async def _classify_with_llm(command: str, force_tool: bool = False, mode_context_hint: str = "") -> Tuple[str, Dict[str, Any]]:
    """Use OpenAI tool-calling to map a free-text command to a tool + parameters."""
    try:
        # ── Pirma bandome regex – greičiau, jokio API skambučio ─────────────
        tool_name, params = _classify_with_regex(command)
        if tool_name != "unknown":
            log.info("Regex classify: %r → %s %s", command[:60], tool_name, params)
            return tool_name, params

        from app.core.config import settings as cfg

        if not cfg.OPENAI_API_KEY:
            log.info("No OpenAI key, falling back to regex")
            return _classify_with_regex(command)

        log.info("LLM classify: calling OpenAI for command: %r", command[:80])

        # Build tools list — dots are not allowed in function names, replace with _
        tools_meta = list_tools()
        name_map: Dict[str, str] = {}  # safe_name -> real_name
        oai_tools = []
        for t in tools_meta:
            real_name: str = t["name"]
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", real_name)
            name_map[safe_name] = real_name

            param_props: Dict[str, Any] = {}
            required = []
            for p in t.get("parameters", []):
                param_props[p["name"]] = {
                    "type": "string",
                    "description": p.get("description", ""),
                }
                if p.get("required", True):
                    required.append(p["name"])

            oai_tools.append({
                "type": "function",
                "function": {
                    "name": safe_name,
                    "description": t.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": param_props,
                        "required": required,
                    },
                },
            })

        # Fast cheap router – gpt-4o-mini still best for classification (2026-03)
        model = getattr(cfg, "ROUTER_MODEL", "gpt-4o-mini")
        response = await create_tool_choice(
            openai_api_key=cfg.OPENAI_API_KEY,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Lani's command router. The user speaks Lithuanian, English, or a MIX of both.\n"
                        "Your ONLY job: map the user's message to the BEST matching tool function.\n"
                        "You MUST always call a function. NEVER respond with plain text.\n\n"

                        "━━ LANGUAGE UNDERSTANDING ━━\n"
                        "The user may mix Lithuanian and English freely. Examples:\n"
                        "  'atidaryk my facebook' → safari_open(url='https://www.facebook.com')\n"
                        "  'open naršyklę' → operator_open_app(app_name='Safari')\n"
                        "  'parodyk mano gmail inbox' → safari_open(url='https://mail.google.com')\n"
                        "  'check my inbox' → safari_open(url='https://mail.google.com')\n"
                        "  'kas yra machine learning' → chat(message=...)\n"
                        "  'kaip to do X' → chat(message=...)\n\n"

                        "━━ ROUTING RULES (follow in ORDER, stop at first match) ━━\n\n"

                        "RULE 0 — WEB ACCOUNTS & WEBSITES (HIGHEST PRIORITY):\n"
                        "  When user mentions a website/service name AND wants to visit/open/see it → safari_open\n"
                        "  Key signals: 'paskyrą', 'puslapį', 'svetainę', 'account', 'page', 'profile', 'feed'\n"
                        "  OR any of: facebook, instagram, gmail, youtube, twitter, tiktok, github, netflix,\n"
                        "             linkedin, reddit, google, drive, firebase, play console, chatgpt\n"
                        "  Examples:\n"
                        "    'atidaryk mano facebook paskyrą' → safari_open(url='https://www.facebook.com')\n"
                        "    'eik į instagram' → safari_open(url='https://www.instagram.com')\n"
                        "    'parodyk gmail' → safari_open(url='https://mail.google.com')\n"
                        "    'open my github' → safari_open(url='https://github.com')\n"
                        "    'atvesk youtube' → safari_open(url='https://www.youtube.com')\n"
                        "    'patikrink inbox' → safari_open(url='https://mail.google.com')\n"
                        "  ⚠ CRITICAL: 'atidaryk mano X paskyrą' is NEVER operator_open_app — it's ALWAYS safari_open!\n\n"

                        "RULE 1 — COMPUTER APPS (only when user clearly means a local Mac app):\n"
                        "  Use operator_open_app ONLY for native Mac apps:\n"
                        "  Spotify, VS Code, Terminal, Finder, Music, Photos, Notes, Reminders,\n"
                        "  System Settings, Calculator, Preview, Xcode, Activity Monitor\n"
                        "  Examples:\n"
                        "    'atidaryk Spotify' → operator_open_app(app_name='Spotify')\n"
                        "    'atidaryk naršyklę' → operator_open_app(app_name='Safari')\n"
                        "    'atidaryti terminalą' → operator_open_app(app_name='Terminal')\n"
                        "  ⚠ If app_name contains 'paskyrą', 'puslapį', 'svetainę' or 'my' → use safari_open instead!\n\n"

                        "RULE 2 — COMPUTER CONTROL:\n"
                        "  • Take a screenshot → operator_take_screenshot\n"
                        "  • Press keyboard shortcut → operator_press_shortcut\n"
                        "  • Open a file/folder path → operator_open_path\n"
                        "  • Reveal file in Finder → operator_reveal_file\n"
                        "  • Copy text to clipboard → operator_copy_to_clipboard\n\n"

                        "RULE 3 — FILE OPERATIONS:\n"
                        "  • Create folder → create_folder\n"
                        "  • Create file → create_file\n"
                        "  • Move/rename file → move_file\n"
                        "  • Sort downloads → sort_downloads\n\n"

                        "RULE 4 — DOCUMENTS:\n"
                        "  • Read/open a document → read_document\n"
                        "  • Summarize a document → summarize_document\n\n"

                        "RULE 5 — SEARCH & RESEARCH:\n"
                        "  • Web search (quick fact) → web_search\n"
                        "  • Deep research/analysis → research_and_prepare_brief\n\n"

                        "RULE 6 — MEMORY:\n"
                        "  • Save/remember something → save_memory\n"
                        "  • Recall/search memory → search_memory\n\n"

                        "RULE 7 — SELF-MODIFICATION or APP CREATION:\n"
                        "  'pakeisk savo kodą', 'pridėk naują įrankį', 'edit your code', 'add a tool',\n"
                        "  'sukurk programą', 'build an app', 'create a project', 'parašyk kodą'\n"
                        "  → ALWAYS use 'chat' tool\n\n"

                        "RULE 8 — PIPELINE EXECUTION (structured multi-step production):\n"
                        "  When the user wants to PRODUCE a real artifact that needs multiple steps:\n"
                        "  • 'create a video / reel / clip' → run_pipeline(pipeline='video', prompt=...)\n"
                        "  • 'create a song / write music / compose lyrics' → run_pipeline(pipeline='music', prompt=...)\n"
                        "  • 'build an app / create a web app / scaffold a project' → run_pipeline(pipeline='app', prompt=...)\n"
                        "  • 'create a marketing campaign / write ad copy / content plan' → run_pipeline(pipeline='marketing', prompt=...)\n"
                        "  • 'deep research / investigate / analyze a topic in depth' → run_pipeline(pipeline='research', prompt=...)\n"
                        "  NOTE: Only use run_pipeline when the user clearly wants a FULL PRODUCTION OUTPUT,\n"
                        "  not just a quick answer. Quick questions → chat tool.\n\n"

                        "RULE 9 — EVERYTHING ELSE → 'chat' tool:\n"
                        "  • Any question (kas, kaip, kodėl, ką, ar, what, how, why, who, when)\n"
                        "  • Conversation, opinions, advice, explanations\n"
                        "  • 'kas tu esi', 'ką gali', 'pasiūlyk', 'patark man'\n"
                        "  • Anything unclear or ambiguous → chat\n\n"

                        "━━ COMMON MISTAKES TO AVOID ━━\n"
                        "✗ WRONG: 'atidaryk mano facebook paskyrą' → operator_open_app(app_name='Mano Facebook Paskyrą')\n"
                        "✓ RIGHT: 'atidaryk mano facebook paskyrą' → safari_open(url='https://www.facebook.com')\n"
                        "✗ WRONG: 'patikrink gmail' → operator_open_app(app_name='Gmail')\n"
                        "✓ RIGHT: 'patikrink gmail' → safari_open(url='https://mail.google.com')\n"
                        "✗ WRONG: 'kas yra AI' → web_search(query='kas yra AI')\n"
                        "✓ RIGHT: 'kas yra AI' → chat(message='kas yra AI')\n"
                    ) + (
                        f"\n\n{mode_context_hint}" if mode_context_hint else ""
                    ),
                },
                {"role": "user", "content": command},
            ],
            tools=oai_tools,
            tool_choice="required" if force_tool else "auto",
            temperature=0,
        )

        msg = response.choices[0].message

        # Tool call response
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            fn = getattr(tc, "function", None)
            if fn is None:
                log.warning("LLM returned a tool call without function payload; falling back to regex")
                return _classify_with_regex(command)

            safe_tool_name = getattr(fn, "name", "") or ""
            try:
                params = json.loads(getattr(fn, "arguments", "{}") or "{}")
            except json.JSONDecodeError:
                params = {}
            real_tool_name = name_map.get(safe_tool_name, safe_tool_name)
            log.info("LLM chose tool: %s -> %s params=%s", safe_tool_name, real_tool_name, params)
            return real_tool_name, params

        # No tool chosen — LLM replied with text
        log.info("LLM chose no tool for: %r", command)
        return "unknown", {}

    except Exception as exc:
        log.warning("LLM classify failed (%s), falling back to regex", exc)
        return _classify_with_regex(command)


# ---------------------------------------------------------------------------
# Regex / keyword fallback
# ---------------------------------------------------------------------------

def _classify_with_regex(command: str) -> Tuple[str, Dict[str, Any]]:
    cmd = command.strip()

    # ── Pokalbio klausimai – tiesiai į chat, nešvaistome laiko LLM classify ──
    # Bet kuris klausimas ar patarimo prašymas → chat tool
    _CHAT_PATTERNS = [
        r"^k[aą]\s",                          # ką, ka daryti...
        r"^kaip\s",                            # kaip tai padaryti
        r"^kod[eė]l\s",                        # kodėl
        r"^ar\s+(?:gali|yra|tu|tai|man|turi)", # ar gali, ar yra...
        r"^pasiūlyk",                          # pasiūlyk
        r"^pasiulyk",
        r"^patark",                            # patark man
        r"^patar[yk]",                         # pataryki
        r"^paaiškink",                         # paaiškink
        r"^paaiskink",
        r"^papasakok",                         # papasakok apie
        r"^išaiškink",
        r"^isaiškink",
        r"^ką\s+(?:gali|galėtum|manai|žinai)", # ką gali, ką manai
        r"^ka\s+(?:gali|galetum|manai|zinai)",
        r"^kas\s+(?:yra|tai|bus|gali)",        # kas yra, kas tai
        r"^kokia?\s",                          # kokia, koks...
        r"^kur\s",                             # kur galiu...
        r"^kada\s",                            # kada...
        r"^kiek\s",                            # kiek kainuoja...
        r"^papasakok",
        r"^pasakyk\s+(?:man\s+)?(?:k[aą]|kaip|apie)", # pasakyk man ką
        r"^nuomone",                           # nuomonė
        r"^ką\s+manai",                        # ką manai apie
        r"^ka\s+manai",
        r"^apie\s+k[aą]",                      # apie ką kalbame
        r"^rekomenduok",                       # rekomenduok
        r"^paaiškink",
        r"^paaišk",
        r"^how\s",                             # how to...
        r"^what\s",                            # what is...
        r"^why\s",                             # why...
        r"^can\s+you\s",                       # can you...
        r"^tell\s+me\s",                       # tell me about...
        r"^explain\s",                         # explain...
        r"^suggest\s",                         # suggest...
        r"^recommend\s",                       # recommend...
    ]
    for pat in _CHAT_PATTERNS:
        if re.match(pat, cmd, re.I | re.UNICODE):
            log.debug("Regex → chat (pokalbis): %r", cmd[:60])
            return "chat", {"message": cmd}

    # ── Pipeline intent detection (before web/app routing) ─────────────────
    # These patterns catch multi-step production requests that map to pipelines.
    _PIPELINE_PATTERNS = [
        # Video pipeline
        (r"(?:create|make|generate|produce|sukurk|padaryk)\s+(?:a\s+)?(?:short\s+)?(?:video|reel|clip|filmą|vaizdo\s+klipą|reklamą)", "video"),
        (r"video\s+(?:creation|production|script|for)", "video"),
        (r"(?:sukurk|padaryk)\s+(?:video|reklam)", "video"),
        # Music pipeline
        (r"(?:create|make|write|compose|generate|sukurk|parašyk)\s+(?:a\s+)?(?:song|music|track|dainą|dainą|melodiją|lyrics|žodžius)", "music"),
        (r"(?:music|song)\s+(?:creation|production|about|for)", "music"),
        (r"(?:sukurk|parašyk)\s+(?:dainom|melodiją|muzik)", "music"),
        # App builder pipeline
        (r"(?:build|create|develop|make|scaffold)\s+(?:a\s+|an\s+)?(?:web\s+)?(?:app|application|website|api|tool|program|project)", "app"),
        (r"(?:app|application)\s+(?:builder|scaffold|generator|for)", "app"),
        (r"(?:sukurk|sukurk)\s+(?:programą|app|aplikaciją|projektą)", "app"),
        # Marketing pipeline
        (r"(?:create|build|generate|run|launch|design)\s+(?:a\s+)?(?:marketing|advertising|ad|campaign|content\s+plan)", "marketing"),
        (r"marketing\s+(?:campaign|strategy|plan|content)", "marketing"),
        (r"(?:write|generate)\s+(?:ads?|ad\s+copy|marketing\s+copy|social\s+media\s+content)", "marketing"),
        (r"(?:sukurk|padaryk)\s+(?:marketing|reklamos)", "marketing"),
        # Research pipeline
        (r"(?:research|investigate|analyse|analyze|study)\s+(?:the\s+|a\s+)?(?:topic|subject|question|market|company|trend)", "research"),
        (r"deep\s+(?:research|dive|analysis)\s+(?:on|into|about)", "research"),
        (r"(?:do|run|conduct)\s+(?:a\s+)?(?:research|analysis|investigation)\s+(?:on|about|into)", "research"),
        (r"(?:atlik|atlik)\s+(?:tyrima|tyrimas|analizę)", "research"),
    ]
    for pat, pipeline_id in _PIPELINE_PATTERNS:
        if re.search(pat, cmd, re.I | re.UNICODE):
            log.debug("Regex → pipeline:%s: %r", pipeline_id, cmd[:60])
            return "run_pipeline", {"pipeline": pipeline_id, "prompt": cmd}


    # ── Web svetainės / paskyros — PRIEŠ atidaryk, nes „atidaryk mano X paskyrą" ──
    # Žodžiai nurodantys interneto paskyrą ar svetainę, ne kompiuterio programą
    _WEB_URL_MAP = {
        # Socialiniai tinklai
        "facebook":     "https://www.facebook.com",
        "facebook.com": "https://www.facebook.com",
        "instagram":    "https://www.instagram.com",
        "twitter":      "https://twitter.com",
        "x.com":        "https://x.com",
        "tiktok":       "https://www.tiktok.com",
        "youtube":      "https://www.youtube.com",
        "linkedin":     "https://www.linkedin.com",
        "reddit":       "https://www.reddit.com",
        "snapchat":     "https://www.snapchat.com",
        "pinterest":    "https://www.pinterest.com",
        # El. paštas
        "gmail":        "https://mail.google.com",
        "inbox":        "https://mail.google.com",
        "outlook":      "https://outlook.live.com",
        "yahoo mail":   "https://mail.yahoo.com",
        # Google
        "google":       "https://www.google.com",
        "google drive": "https://drive.google.com",
        "google docs":  "https://docs.google.com",
        "google sheets":"https://sheets.google.com",
        "google calendar":"https://calendar.google.com",
        "firebase":     "https://console.firebase.google.com",
        "play console": "https://play.google.com/console",
        # Kitos
        "github":       "https://github.com",
        "netflix":      "https://www.netflix.com",
        "amazon":       "https://www.amazon.com",
        "ebay":         "https://www.ebay.com",
        "wikipedia":    "https://www.wikipedia.org",
        "chatgpt":      "https://chatgpt.com",
        "openai":       "https://platform.openai.com",
        "anthropic":    "https://console.anthropic.com",
    }

    # Frazių šablonai nurodantys web → safari_open
    # „atidaryk mano facebook paskyrą", „eik į gmail", „parodyk facebook"

    # Native Mac programos — NIEKADA neturėtų eiti į safari_open
    _NATIVE_APPS = {
        "safari", "chrome", "firefox", "edge",
        "spotify", "music", "itunes",
        "terminal", "iterm", "iterm2",
        "finder", "notes", "reminders", "calendar",
        "mail", "messages", "facetime",
        "photos", "preview", "keynote", "pages", "numbers",
        "xcode", "vscode", "vs code", "visual studio code",
        "slack", "telegram", "whatsapp", "zoom",
        "system settings", "system preferences",
        "activity monitor", "calculator",
        # LT variantai
        "naršyklė", "naršyklę", "narsykle",
        "muzika", "terminalas", "terminalą",
        "nuotraukos", "nustatymai", "paštas", "paštą",
        "žinutės", "zinutes", "rodytuvas", "priminimai",
    }

    def _extract_web_site(cmd_text: str) -> str:
        """Ištraukia svetainės pavadinimą iš komandos ir grąžina _WEB_URL_MAP raktą arba ''.
        Grąžina '' jei tai yra native Mac programa."""
        c = cmd_text.strip().lower()

        def _is_native(name: str) -> bool:
            n = name.strip().lower()
            return n in _NATIVE_APPS

        # 1. „atidaryk [mano] <site> [paskyrą|puslapį|svetainę|...]"
        #    Jei YRA paskyros žodis → web (net jei programa)
        #    Jei NĖRA → tik jei žinoma web paslauga
        m1 = re.match(
            r"atidar(?:yk|k|yti)\s+(?:mano\s+)?([a-zA-Z][a-zA-Z0-9\s.]*?)"
            r"\s*(paskyr[ąa]|paskyros|puslap[įi]|svetain[ęe]|svetaines|tinklalap[įi]|account|page|profile|feed)?\s*$",
            c, re.I,
        )
        if m1:
            site = m1.group(1).strip().rstrip(".,!?")
            has_web_suffix = bool(m1.group(2))
            if has_web_suffix:
                # „atidaryk mano facebook paskyrą" → web net jei native
                return site
            # Nėra sufikso → tik jei žinoma web paslauga (ne native app)
            if _is_native(site):
                return ""  # → eis į operator.open_app regex
            # Žinoma web paslauga?
            if site in _WEB_URL_MAP:
                return site
            for n in (2, 1):
                short = " ".join(site.split()[:n])
                if short in _WEB_URL_MAP:
                    return short
            return ""  # nežinoma → LLM

        # 2. „eik į / nueik į / go to / navigate to <site>"
        m2 = re.match(
            r"(?:eik|ieik|nueik|navigok|navigate|go)\s+(?:į\s+|i\s+|to\s+)(?:mano\s+)?([a-zA-Z][a-zA-Z0-9\s.]*)",
            c, re.I,
        )
        if m2:
            site = m2.group(1).strip().rstrip(".,!?")
            if _is_native(site):
                return ""
            return site

        # 3. „parodyk/atvesk/patikrink/tikrink/check/visit/show <site>" — tik žinomos
        m3 = re.match(
            r"(?:parodyk|atvesk|patikrink|tikrink|check|visit|show)\s+(?:mano\s+)?([a-zA-Z][a-zA-Z0-9\s.]*)",
            c, re.I,
        )
        if m3:
            candidate = m3.group(1).strip().rstrip(".,!?")
            if candidate in _WEB_URL_MAP:
                return candidate
            for n in (2, 1):
                short = " ".join(candidate.split()[:n])
                if short in _WEB_URL_MAP:
                    return short
            return ""  # nežinoma → LLM

        # 4a. „open my <site>" (EN mix) — atskiras pattern prieš bendrą open
        m4a = re.match(
            r"open\s+my\s+([a-zA-Z][a-zA-Z0-9\s.]*?)\s*(?:account|page|profile|feed|website|site)?\s*$",
            c, re.I,
        )
        if m4a:
            site = m4a.group(1).strip().rstrip(".,!?")
            if site in _WEB_URL_MAP:
                return site
            for n in (2, 1):
                short = " ".join(site.split()[:n])
                if short in _WEB_URL_MAP:
                    return short
            # Nežinoma svetainė — konstruosim URL (ne native app check, nes „open my X" → web)
            return site

        # 4. „open [my] <site> [account/page/...]" (EN)
        m4 = re.match(
            r"open\s+(?:my\s+)?([a-zA-Z][a-zA-Z0-9\s.]*?)"
            r"\s*(?:account|page|profile|feed|website|site)?\s*$",
            c, re.I,
        )
        if m4:
            raw = m4.group(0)  # full match
            site = m4.group(1).strip().rstrip(".,!?")
            has_web_suffix = bool(re.search(
                r"\s+(?:account|page|profile|feed|website|site)$", raw, re.I
            ))
            # Pašaliname "my" prefiksą jei yra
            site_no_my = re.sub(r"^my\s+", "", site, flags=re.I).strip()
            if has_web_suffix:
                return site_no_my
            # Tikrinti be "my" prefikso
            if _is_native(site_no_my):
                return ""
            if site_no_my in _WEB_URL_MAP:
                return site_no_my
            for n in (2, 1):
                short = " ".join(site_no_my.split()[:n])
                if short in _WEB_URL_MAP:
                    return short
            # Taip pat tikrinti su "my" (pvz "my drive")
            if site in _WEB_URL_MAP:
                return site
            return ""  # nežinoma → LLM

        return ""

    site_raw = _extract_web_site(cmd)
    if site_raw:
        url = _WEB_URL_MAP.get(site_raw)
        if not url:
            # Bandome pirmus 2 žodžius (pvz „google drive")
            two = " ".join(site_raw.split()[:2])
            url = _WEB_URL_MAP.get(two)
        if not url:
            # Nežinoma svetainė — konstruojame URL patys
            if "." not in site_raw:
                url = f"https://www.{site_raw}.com"
            else:
                url = f"https://{site_raw}" if not site_raw.startswith("http") else site_raw
        log.debug("Regex → safari_open: %r → %s", site_raw, url)
        return "safari_open", {"url": url}

    # Tiesioginis URL (http/https arba www.)
    m_url = re.match(r"(?:atidar(?:yk|k)|open|go\s+to)\s+(https?://\S+|www\.\S+)", cmd, re.I)
    if m_url:
        raw_url = m_url.group(1)
        if not raw_url.startswith("http"):
            raw_url = "https://" + raw_url
        return "safari_open", {"url": raw_url}

    # ── Lietuviški modeliai (greičiau nei LLM) ──────────────────────────────

    # Lietuviški→angliški app pavadinimai (Whisper kartais grąžina lietuvišką)
    _LT_APP_MAP = {
        "naršyklę": "Safari", "naršyklė": "Safari", "narsykle": "Safari",
        "muzika": "Music", "muzikos": "Music",
        "nuotraukos": "Photos", "nuotraukų": "Photos",
        "paštas": "Mail", "paštą": "Mail", "pastas": "Mail",
        "užrašai": "Notes", "užrašus": "Notes",
        "priminimai": "Reminders",
        "žinutės": "Messages", "zinutes": "Messages",
        "terminalas": "Terminal", "terminalą": "Terminal",
        "nustatymai": "System Settings", "nustatymų": "System Settings",
        "rodytuvas": "Finder",
        "kalendorius": "Calendar",
    }

    # "atidaryk Safari" / "atidark chrome" / "atidaryti terminal"
    m = re.match(r"atidar(?:yk|k|yti)\s+(.+)", cmd, re.I)
    if m:
        raw_app = m.group(1).strip().rstrip(".").lower()
        # Pirma žiūrime į lietuvišką žodyną
        app = _LT_APP_MAP.get(raw_app) or m.group(1).strip().rstrip(".").title()
        return "operator.open_app", {"app_name": app}

    # "uždaryk Safari" / "uzdark chrome"
    m = re.match(r"u[žz]dar(?:yk|k|yti)\s+(.+)", cmd, re.I)
    if m:
        app = m.group(1).strip().rstrip(".").title()
        return "operator.close_app", {"app_name": app}

    # "tipuok/rašyk tekstą" – klaviatūra
    m = re.match(r"(?:tipuok|rašyk|rasyk|įvesk)\s+(.+)", cmd, re.I)
    if m:
        return "operator.type_text", {"text": m.group(1).strip()}

    # "spustelėk/spausk/paspausk [Enter/OK/...]"
    m = re.match(r"(?:spustelėk|spustelk|spausk|paspausk)\s+(.+)", cmd, re.I)
    if m:
        return "operator.press_key", {"key": m.group(1).strip()}

    # "padidink/padidinti garsą"
    if re.search(r"padidink\s+garsa|padidinti\s+garsa|garsa\s+didesn", cmd, re.I):
        return "operator.set_volume", {"direction": "up"}

    # "sumažink garsą"
    if re.search(r"suma[žz]ink\s+garsa|sumažinti\s+garsa|garsa\s+mažesn", cmd, re.I):
        return "operator.set_volume", {"direction": "down"}

    # "nutildyk" / "išjunk garsą"
    if re.search(r"nutildyk|i[šs]junk\s+garsa|mute", cmd, re.I):
        return "operator.mute", {}

    # "sukurk aplanką ..."
    m = re.search(r"(?:sukurk|sukurti)\s+aplanką\s+['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "create_folder", {"path": m.group(1).strip()}

    # "perskaityk/skaityk dokumentą ..."
    m = re.search(r"(?:perskaityk|skaityk)\s+(?:dokumentą\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "read_document", {"path": m.group(1).strip()}

    # "susumuok ..." (Lithuanian "summarize")
    m = re.search(r"susumuok\s+['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "summarize_document", {"path": m.group(1).strip()}

    # ── Angliški modeliai ───────────────────────────────────────────────────

    m = re.search(r"open\s+(?:app\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        app = m.group(1).strip().rstrip(".")
        # „open my X" arba „open X" kur X yra žinoma web svetainė → safari_open
        app_lower = app.lower()
        app_no_my = re.sub(r"^my\s+", "", app_lower).strip()
        _WEB_URL_MAP_EN = {
            "facebook", "instagram", "twitter", "tiktok", "youtube", "linkedin",
            "reddit", "snapchat", "pinterest", "gmail", "inbox", "outlook",
            "google", "google drive", "google docs", "google sheets",
            "github", "netflix", "amazon", "chatgpt", "openai",
        }
        if app_no_my in _WEB_URL_MAP_EN or app_lower in _WEB_URL_MAP_EN:
            key = app_no_my if app_no_my in _WEB_URL_MAP else app_lower
            url = _WEB_URL_MAP.get(key) or f"https://www.{app_no_my}.com"
            return "safari_open", {"url": url}
        return "operator.open_app", {"app_name": app}

    m = re.search(r"create\s+(?:a\s+)?folder\s+(?:at\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "create_folder", {"path": m.group(1).strip()}

    m = re.search(r"create\s+(?:a\s+)?file\s+['\"]?(.+?)['\"]?(?:\s+with\s+content\s+['\"]?(.+?)['\"]?)?\s*$", cmd, re.I)
    if m:
        return "create_file", {"path": m.group(1).strip(), "content": m.group(2) or ""}

    m = re.search(r"move\s+['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "move_file", {"src": m.group(1).strip(), "dst": m.group(2).strip()}

    m = re.search(r"sort\s+(?:my\s+)?downloads(?:\s+in\s+['\"]?(.+?)['\"]?)?\s*$", cmd, re.I)
    if m:
        path = m.group(1) or "~/Downloads"
        return "sort_downloads", {"base_path": path.strip()}

    m = re.search(r"read\s+(?:document\s+)?['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "read_document", {"path": m.group(1).strip()}

    m = re.search(r"summar(?:ize|ise)\s+['\"]?(.+?)['\"]?\s*$", cmd, re.I)
    if m:
        return "summarize_document", {"path": m.group(1).strip()}

    m = re.search(r"create\s+(?:a\s+)?presentation\s+['\"]?(.+?)['\"]?\s+with\s+outline\s+(.+)", cmd, re.I)
    if m:
        title = m.group(1).strip()
        outline = [s.strip() for s in re.split(r"[,;]+", m.group(2).strip()) if s.strip()]
        return "create_presentation", {"title": title, "outline": outline, "output_path": f"~/Desktop/{title}.pptx"}

    return "unknown", {}


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

async def route_command(request: CommandRequest, db: AsyncSession) -> CommandResponse:
    """Classify, dispatch, and log a user command."""
    result_row = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    settings_row = result_row.scalar_one_or_none()
    if settings_row and settings_row.allowed_directories:
        db_dirs: list = json.loads(settings_row.allowed_directories)
    else:
        db_dirs = []
    set_runtime_allowed_dirs(db_dirs)

    # ── Phase 11: resolve active modes for this profile ───────────────────────
    profile_id = (request.context or {}).get("profile_id")
    try:
        from app.services.mode_service import build_mode_context_block, get_active_modes
        active_modes_list = await get_active_modes(db, profile_id=profile_id)
        mode_hint = build_mode_context_block(active_modes_list)
    except Exception as _mode_exc:
        log.debug("Mode context fetch skipped: %s", _mode_exc)
        active_modes_list = []
        mode_hint = ""

    # Use LLM if available, otherwise regex
    tool_name, params = await _classify_with_llm(request.command, mode_context_hint=mode_hint)

    if tool_name == "unknown":
        result = ToolResult(
            tool_name="unknown",
            status="error",
            message=(
                "Negaliu suprasti šios komandos. Bandyk: "
                "'sukurk aplanką ~/Desktop/Projektas', "
                "'susumuok ~/Documents/failas.pdf', "
                "arba 'atidaryk Safari'."
            ),
        )
        await record_action(db, request.command, "unknown", "error", result.message or "unknown command")
        return CommandResponse(command=request.command, result=result)

    # ── Central execution guard (capability + policy + approval + execute +
    #    world state + state delta + audit chain + eval) ──────────────────────

    # ── Pipeline shortcut: run_pipeline bypasses single guarded_execute ──────
    # Pipelines are orchestrators: they call guarded_execute internally per step.
    if tool_name == "run_pipeline":
        try:
            from app.services.pipeline_service import run_pipeline
            pipeline_result = await run_pipeline(
                pipeline_id=params.get("pipeline", "research"),
                prompt=params.get("prompt", request.command),
                db=db,
                settings_row=settings_row,
                active_modes=[m.slug for m in active_modes_list],
                profile_id=profile_id,
                context=request.context or {},
            )
            status: str
            if pipeline_result.status == "completed":
                status = "success"
            elif pipeline_result.status == "paused_for_approval":
                status = "approval_required"
            else:
                status = "error"
            result = ToolResult(
                tool_name="run_pipeline",
                status=status,  # type: ignore[arg-type]
                data=pipeline_result.to_dict(),
                message=(
                    f"✓ Pipeline '{pipeline_result.pipeline_name}' completed "
                    f"({len(pipeline_result.steps_completed)} steps)."
                    if status == "success"
                    else (
                        f"Pipeline paused – approval required."
                        if status == "approval_required"
                        else f"Pipeline failed: {pipeline_result.error}"
                    )
                ),
            )
            return CommandResponse(
                command=request.command,
                result=result,
                approval_id=pipeline_result.approval_id,
            )
        except Exception as pipe_exc:
            log.error("[router] pipeline dispatch failed: %s", pipe_exc)
            result = ToolResult(
                tool_name="run_pipeline",
                status="error",
                message=f"Pipeline execution error: {pipe_exc}",
            )
            return CommandResponse(command=request.command, result=result)

    guard_result = await guarded_execute(
        tool_name,
        params,
        request.command,
        db,
        settings_row=settings_row,
        execution_context={
            "executor_type": "command",
            "active_modes": [m.slug for m in active_modes_list],
            "profile_id": profile_id,
        },
        caller="router",
    )

    if guard_result.status == "error":
        result = ToolResult(
            tool_name=tool_name,
            status="error",
            message=guard_result.policy_reason or f"Įrankis '{tool_name}' nerastas.",
        )
        return CommandResponse(command=request.command, result=result)

    if guard_result.needs_approval:
        result = ToolResult(
            tool_name=tool_name,
            status="approval_required",
            message=f"Veiksmas '{tool_name}' reikalauja tavo patvirtinimo.",
            data={"params": params},
        )
        return CommandResponse(
            command=request.command,
            result=result,
            approval_id=guard_result.approval_id,
        )

    if guard_result.blocked:
        result = ToolResult(
            tool_name=tool_name,
            status="error",
            message=guard_result.policy_reason or "Veiksmas blokuotas politikos.",
        )
        return CommandResponse(command=request.command, result=result)

    return CommandResponse(command=request.command, result=guard_result.tool_result)
