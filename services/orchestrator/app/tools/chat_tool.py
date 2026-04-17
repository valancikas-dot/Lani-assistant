"""
chat_tool.py – Lani's conversational AI brain.

Two modes:
  1. Normal chat   — questions, conversation, explanations, creative tasks.
  2. Agent mode    — user asks Lani to modify herself, add features, fix bugs
                     → delegates to agent_loop.run_agent() (full ReAct loop).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, cast

from app.schemas.commands import ToolResult
from app.services.llm_text_service import complete_text
from app.tools.base import BaseTool

log = logging.getLogger(__name__)

# ─── Response TTL cache ────────────────────────────────────────────────────────
# Identical chat messages get served from this dict for up to TTL seconds,
# avoiding redundant LLM calls for repeated / idempotent questions.
# Format: { md5_hex: (response_text, monotonic_timestamp) }
_RESPONSE_CACHE: dict[str, tuple[str, float]] = {}
_RESPONSE_CACHE_TTL: float = 300.0  # seconds (5 minutes)
_RESPONSE_CACHE_MAX: int = 256      # max entries (safety bound)


def _cache_response(key: str, text: str) -> None:
    """Store a response in the TTL cache, evicting the oldest entry if full."""
    import time
    if len(_RESPONSE_CACHE) >= _RESPONSE_CACHE_MAX:
        oldest = next(iter(_RESPONSE_CACHE))
        del _RESPONSE_CACHE[oldest]
    _RESPONSE_CACHE[key] = (text, time.monotonic())

# ── Self-modification detection ───────────────────────────────────────────────
# These patterns trigger the autonomous agent_loop instead of plain LLM call.

_SELF_MOD_PATTERNS = [
    # Lithuanian — code changes
    r"pakeisk\s+savo",              # pakeisk savo kodą / elgesį
    r"keisk\s+savo",                # keisk savo kodą
    r"atnaujink\s+savo",            # atnaujink savo kodą
    r"pagerink\s+savo",             # pagerink savo kodą
    r"perrašyk\s+(?:savo|tai)",     # perrašyk savo / tai
    r"modifikuok",                   # modifikuok
    r"optimizuok\s+savo",           # optimizuok savo kodą
    # Lithuanian — adding features
    r"prid[eė]k\s+(?:(?:nauj[ąa]|dar\s+vien[ąa])\s+)?(?:įranki|funkcij|galimyb|tool|feature)",
    r"prid[eė]k\s+(?:nauj[ąa]\s+)?(?:įrankį|funkciją|galimybę)",
    r"pridek\s+(?:nauja\s+)?(?:irankį|irankj|funkcija|tool|feature)",
    r"sukurk\s+(?:nauj[ąa]\s+)?(?:įranki|funkcij|tool|įrankį|funkciją)",
    r"išmok\s+",                    # išmok kaip / išmok X
    r"pasidaryk\s+(?:nauj|galimyb)",# pasidaryk naują
    # Lithuanian — fixing
    r"ištaisyk\s+(?:klaida|bug)",
    r"pataisyk\s+(?:klaida|bug|savo)",
    r"surask\s+(?:ir\s+)?(?:pataisyk|ištaisyk)\s+klaida",
    # Lithuanian — self-programming
    r"koduok\s+(?:save|pati)",
    r"programuok\s+save",
    r"rašyk\s+(?:savo\s+)?kod[ąa]",
    # English
    r"edit\s+(?:your|the)\s+(?:code|source)",
    r"modify\s+(?:your|the)\s+(?:code|source|self)",
    r"update\s+(?:your|the)\s+(?:code|source)",
    r"rewrite\s+(?:your|the)",
    r"add\s+(?:a\s+)?new\s+tool",
    r"add\s+(?:a\s+)?(?:feature|capability)",
    r"fix\s+(?:a\s+)?bug\s+in\s+(?:your|the)\s+code",
    r"improve\s+(?:your|the)\s+(?:code|self)",
    r"change\s+your\s+(?:code|behavior|behaviour)",
    r"teach\s+yourself",
]

_SELF_MOD_RE = re.compile("|".join(_SELF_MOD_PATTERNS), re.IGNORECASE | re.UNICODE)


def _is_self_modify_request(text: str) -> bool:
    return bool(_SELF_MOD_RE.search(text))


# ── Browser/account request detection ────────────────────────────────────────
# These patterns trigger safari_open + safari_read via command_router
# instead of a plain LLM text response.

_BROWSER_PATTERNS = [
    # Email — bet koks email/paštas prašymas
    r"(perskaityk|atidary[kti]+|parodyk|patikrink|atnešk|rask|gauk)\s+(?:\w+\s+){0,3}(?:email|laišk|gmail|pašt|inbox|gautus)",
    r"(atidaryk|perskaityk|patikrink)\s+(?:man\s+)?(?:inbox|gautus|laiškus|el\.?\s*paštą)",
    r"kiek\s+(?:neperskaitytų|naujų)\s+(?:laiškų|email)",
    r"kas\s+(?:man\s+)?(?:parašė|siuntė|atsiuntė)",
    r"(?:email|laišk|gmail|pašt)\w*\s+(?:perskaityk|atidaryk|patikrink|parodyk)",
    # Social media
    r"(atidaryk|perskaityk|patikrink|parodyk|ieik|užeik)\s+(?:\w+\s+){0,2}(?:facebook|instagram|twitter|linkedin|x\.com)",
    r"(perskaityk|parodyk)\s+(?:mano\s+)?(?:žinutes|pranešimus|feed|naujinimus)",
    # Google services
    r"(atidaryk|parodyk|patikrink)\s+(?:\w+\s+){0,2}(?:google\s+play|play\s+console|firebase|google\s+cloud)",
    r"(atidaryk|parodyk)\s+(?:mano\s+)?(?:drive|docs|sheets|calendar)",
    # Accounts — "prisijunk", "įeik", "užeik į paskyrą"
    r"(prisijungk|įeik|užeik|atidaryk)\s+(?:prie\s+)?(?:mano\s+)?paskyros?",
    r"(prisijunk|eik)\s+(?:į\s+)?(?:mano\s+)?(?:paskyrą|account)",
    r"safari\s+(atidaryk|parodyk|perskaityk|patikrink)",
    r"(atidaryk|pereik)\s+(?:į\s+)?https?://",
    r"naršyklė[je]?\s+(atidaryk|parodyk)",
    # English
    r"(open|read|check|show)\s+(my\s+)?(email|gmail|inbox|mail)",
    r"(open|check|show)\s+(my\s+)?(facebook|instagram|twitter|linkedin)",
    r"(open|show)\s+(my\s+)?(play\s+console|firebase|google\s+cloud|drive)",
    r"(log\s*in|sign\s*in)\s+to\s+(my\s+)?\w+",
]

_BROWSER_RE = re.compile("|".join(_BROWSER_PATTERNS), re.IGNORECASE | re.UNICODE)


def _is_browser_request(text: str) -> bool:
    return bool(_BROWSER_RE.search(text))


# ── System prompt for normal chat ─────────────────────────────────────────────

_SYSTEM_PROMPT_LT = """Tu esi Lani — autonomiškas asmeninis AI agentas, veikiantis Mac kompiuteryje.

━━ KAS TU ESI ━━
Tu ne chat botas. Tu esi pilnavertis agentas su prieiga prie kompiuterio ir savo pačios kodo.
Tave sukūrė vartotojas kaip savo asmeninį asistentą. Vartotojas kalba su tavimi balsu.
Kai vartotojas prašo kurti programą, rašyti kodą, projektuoti sistemą ar pridėti naują funkciją, tu PRIIMI tai kaip vykdytiną agento užduotį, o ne kaip teorinį klausimą.

━━ TAVO GALIMYBĖS (konkrečios komandos) ━━

🖥  KOMPIUTERIO VALDYMAS:
  • Atidaro bet kurią programą: "atidaryti Spotify", "atidaryti Safari"
  • Daro ekrano nuotraukas
  • Valdo klaviatūros trumpinius
  • Atidaro failus ir aplankus

🦁 NARŠYKLĖS (Safari – tikros sesijos):
  • safari_open — atidaro bet kurį URL tikroje Safari (su VISOMIS vartotojo sesijomis)
  • safari_read — perskaito puslapio turinį (Gmail laiškai, Facebook feed, Firebase projektai ir t.t.)
  • safari_click — spaudžia mygtukus/nuorodas
  • safari_fill — užpildo formas
  • safari_get_tabs — mato visus atidarytus tab'us
  SVARBU: Lani PRIVALO naudoti šiuos įrankius kai vartotojas prašo skaityti paštą,
  žiūrėti socialinių tinklų turinį, tikrinti paskyras.

📁 FAILŲ SISTEMA:
  • Kuria failus ir aplankus bet kur kompiuteryje
  • Perkelia, ištrino failus
  • Rūšiuoja atsisiuntimus

🔍 PAIEŠKA IR TYRIMAI:
  • Ieško internete realiu laiku
  • Atlieka giluminius tyrimus (keli šaltiniai)
  • Skaito PDF ir Word dokumentus

🧠 ATMINTIS:
  • Įsimena faktus apie vartotoją: "prisimink, kad mano gimtadienis sausio 15"
  • Paieška tarp įsimintų dalykų

🔧 SAVĘS KEITIMAS:
  • Pati perskaito ir keičia savo kodą
  • Gali pridėti naujus įrankius, funkcijas
  • Pati save perkrauna po pakeitimų

💻 PROGRAMAVIMAS IR PROGRAMŲ KŪRIMAS:
    • Gali kurti naujus projektų karkasus (React, FastAPI, Node, Python ir kt.)
    • Gali rašyti naujus kodo failus, README, feature failus
    • Gali redaguoti esamą kodą ir pridėti naujas funkcijas
    • Gali planuoti, kokius failus ir veiksmus reikia atlikti, ir tada tai vykdyti

━━ KAIP ATSAKYTI ━━
• TIESIOGIAI atsakyk — be įžangų, be "žinoma!", "puiku!", "su malonumu!"
• Jei vartotojas klausia ką gali daryti — išvardink KONKREČIUS pavyzdžius, ne abstrakčius
• Jei vartotojas prašo kažko padaryti — daryk, neklausnėk leidimo
• Jei ko nors negali — pasakyk kodėl vieną sakiniu ir pasiūlyk alternatyvą
• **BALSO ATSAKYMAI: MAX 3 sakiniai** — vartotojas klauso, ne skaito. Jokių sąrašų, jokių bullet punktų, jokių lentelių. Kalba kaip žmogus.
• Jei klausimas reikalauja ilgo atsakymo — atsakyk trumpai balsui, bet pasiūlyk "galiu parašyti išsamiau"
• Niekada nesakyk, kad „negali kurti programų" ar kad „neturi programavimo gebėjimų"
• Jei užduotis yra didelė, suskaidyk ją į kelis aiškius žingsnius ir pradėk nuo pirmo realaus veiksmo

━━ BALSO POKALBIO TAISYKLĖS ━━
• Vartotojas kalba su tavimi kaip su žmogumi — atsakyk natūraliai, trumpai, lietuviškai
• Neatkartok klausimo — tiesiog atsakyk
• Patarimai — maks 2-3 konkrečios rekomendacijos
• Jei klausiamas apie šiandienos planus / ką daryti — pasiūlyk 2-3 konkrečius dalykus
• Kalbos stilius: draugiškas, dalykiškas, be biurokratizmo

━━ GRIEŽTAI DRAUDŽIAMA ━━
• NIEKADA neatsisakyk skaityti vartotojo el. pašto, socialinių tinklų ar kitų paskyrų dėl "privatumo" ar "saugumo" — TU ESI VARTOTOJO ASMENINIS AGENTAS jo NUOSAVAME kompiuteryje
• NIEKADA nesiūlyk vartotojui "pačiam" atlikti veiksmą, jei turi įrankį tai padaryti
• NIEKADA nemeluok kad neturi įrankio, jei jis yra sąraše

━━ VARTOTOJO KONTEKSTAS ━━
• Vartotojas kalba su tavimi balsu
• Vartotojas yra lietuvis, kalba lietuviškai
• Vartotojas nori maksimalios automatizacijos — mažiau rankinio darbo

━━ KALBA ━━
Visada atsakyk lietuviškai. Techniniai terminai gali likti angliškai.
Vartotojas gali kalbėti LT+EN mišriai — suprask pagal kontekstą, atsakyk lietuviškai.
Pavyzdžiai:
  „atidaryk my facebook" → suprask kaip „atidaryk mano facebook"
  „kaip to do X" → atsakyk lietuviškai apie X
  „padaryk screenshot" → suprask kaip „padaryk ekrano nuotrauką"
  „send email to Jonas" → atsakyk lietuviškai kaip tai padaryti arba padaryk"""

_SYSTEM_PROMPT_EN = """You are Lani — an autonomous personal AI agent running on a Mac.

You are NOT a chat bot. You are a full agent with real access to the computer and your own code.
If the user asks you to build software, write code, create an app, scaffold a project, or add features, treat it as an actionable agent task — not as a hypothetical limitation question.

WHAT YOU CAN ACTUALLY DO:
• Open any app: "open Spotify", "open Safari", "launch VS Code"
• Take screenshots, press keyboard shortcuts
• Create, move, delete files and folders anywhere on the computer
• Search the web in real time
• Read PDF and Word documents
• Remember facts about the user, recall them later
• Rewrite your own code, add new tools, restart yourself
• Create new project scaffolds, generate source files, update code, and help build applications end-to-end

HOW TO RESPOND:
• Be direct — skip "Of course!", "Certainly!", "Great to hear from you!"
• If asked what you can do — give CONCRETE examples, not abstract descriptions
• If asked to do something — do it, don't ask permission
• If you can't do something — say why in one sentence and suggest an alternative
• Keep voice answers short (1-3 sentences) — the user is listening, not reading
• Never claim you cannot code or create programs if the request is within your available tools and self-edit capabilities
• For bigger coding tasks, first state the plan briefly, then execute the first concrete step

Always respond in English."""


class ChatTool(BaseTool):
    name = "chat"
    description = (
        "Use for ALL conversational requests: questions, explanations, creative writing, "
        "advice, translations, general knowledge, opinions, or any request that is a "
        "question rather than a computer action. Also handles self-modification requests "
        "(user asks Lani to change her own code). "
        "Parameter: message (the user's full message)."
    )
    requires_approval = False
    parameters = [
        {
            "name": "message",
            "description": "The user's message or question to respond to",
            "required": True,
        }
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        message = params.get("message", "").strip()
        if not message:
            return ToolResult(tool_name="chat", status="error", message="No message provided.")

        try:
            # Get language setting
            lang = await _get_lang()
            lang_instruction = (
                "Always respond in Lithuanian (lietuvių kalba)."
                if lang == "lt"
                else f"Always respond in language: {lang}."
            )

            # Load conversation history
            history = await _load_history()

            # Load recent negative feedback hints
            negative_hint = await _load_negative_feedback_hint()

            # Self-modification → agent loop
            if _is_self_modify_request(message):
                log.info("[chat_tool] self-modify detected → agent_loop")
                try:
                    from app.services.agent_loop import run_agent
                    reply = await run_agent(message, lang)
                except Exception as ae:
                    log.error("[chat_tool] agent_loop error: %s", ae)
                    reply = await _call_llm(
                        f"Vartotojas prašo tave modifikuoti save: {message}\n\n"
                        "Paaiškink ką darytum, bet nurodyk, kad agent_loop nepavyko: " + str(ae),
                        lang_instruction,
                        history=history,
                        negative_hint=negative_hint,
                    )
            else:
                reply = await _call_llm(message, lang_instruction, history=history,
                                        negative_hint=negative_hint)

            # Save both turns to history
            await _save_history(message, reply)

            return ToolResult(tool_name="chat", status="success", message=reply)

        except Exception as exc:
            log.error("[chat_tool] error: %s", exc)
            return ToolResult(
                tool_name="chat",
                status="error",
                message=f"Klaida: {exc}",
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_lang() -> str:
    """Read assistant_language from DB. Default: 'lt'."""
    try:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.settings import UserSettings
        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(UserSettings).where(UserSettings.id == 1)
            )
            s = row.scalar_one_or_none()
            if s and getattr(s, "assistant_language", None):
                return s.assistant_language
    except Exception:
        pass
    return "lt"


# ── Conversation history ──────────────────────────────────────────────────────
_HISTORY_SESSION = "default"
_HISTORY_MAX = 20  # max žinučių poros (user+assistant = 2 žinutės)


async def _load_history() -> list[dict]:
    """Load last N conversation turns from DB."""
    try:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.conversation import ConversationMessage
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == _HISTORY_SESSION)
                .order_by(ConversationMessage.created_at.desc())
                .limit(_HISTORY_MAX * 2)
            )
            rows = list(reversed(result.scalars().all()))
            return [{"role": r.role, "content": r.content} for r in rows]
    except Exception as e:
        log.warning("[chat_tool] history load failed: %s", e)
        return []


async def _save_history(user_msg: str, assistant_msg: str) -> None:
    """Save user + assistant turn to DB. Prune old messages. Also log episodic memory."""
    try:
        from sqlalchemy import select, delete
        from app.core.database import AsyncSessionLocal
        from app.models.conversation import ConversationMessage
        async with AsyncSessionLocal() as db:
            db.add(ConversationMessage(
                session_id=_HISTORY_SESSION, role="user", content=user_msg
            ))
            db.add(ConversationMessage(
                session_id=_HISTORY_SESSION, role="assistant", content=assistant_msg
            ))
            await db.commit()

            # Prune: palikti tik paskutines _HISTORY_MAX*2 žinutes
            result = await db.execute(
                select(ConversationMessage.id)
                .where(ConversationMessage.session_id == _HISTORY_SESSION)
                .order_by(ConversationMessage.created_at.desc())
                .offset(_HISTORY_MAX * 2)
            )
            old_ids = [r for (r,) in result.all()]
            if old_ids:
                await db.execute(
                    delete(ConversationMessage)
                    .where(ConversationMessage.id.in_(old_ids))
                )
                await db.commit()
    except Exception as e:
        log.warning("[chat_tool] history save failed: %s", e)

    # Log to episodic memory (autobiographical record – never pruned aggressively)
    try:
        from app.services.episodic_memory_service import log_conversation
        await log_conversation(_HISTORY_SESSION, user_msg, assistant_msg)
    except Exception as e:
        log.debug("[chat_tool] episodic log failed: %s", e)


async def _load_negative_feedback_hint() -> str:
    """
    Return a short system-prompt addition listing recently down-voted commands.
    Helps the LLM avoid repeating patterns the user disliked.
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.feedback_service import get_negative_commands
        async with AsyncSessionLocal() as db:
            bad = await get_negative_commands(db, limit=10)
        if not bad:
            return ""
        items = "\n".join(f"  - {c}" for c in bad[:10])
        return (
            "\n\n━━ NEGATYVUS GRĮŽTAMASIS RYŠYS ━━\n"
            "Šie atsakymai anksčiau sulaukė neigiamo įvertinimo – stenkis nepakartoti šių klaidų:\n"
            + items
        )
    except Exception:
        return ""


async def _call_llm(
    message: str,
    lang_instruction: str,
    history: list[dict] | None = None,
    negative_hint: str = "",
) -> str:
    """Call Anthropic (preferred) or OpenAI with conversation history. Raises if both fail.

    Identical (message, lang_instruction) pairs are served from an in-process
    TTL cache for up to _RESPONSE_CACHE_TTL seconds, saving API cost and latency
    for repeated questions.
    """
    import hashlib
    import time

    cache_key = hashlib.md5(
        f"{lang_instruction}|{message.lower().strip()}".encode()
    ).hexdigest()
    now = time.monotonic()
    cached_entry = _RESPONSE_CACHE.get(cache_key)
    if cached_entry is not None:
        cached_text, cached_at = cached_entry
        if now - cached_at < _RESPONSE_CACHE_TTL:
            log.debug("[chat_tool] cache hit for %r", message[:60])
            return cached_text

    from app.core.config import settings as cfg

    system = (
        _SYSTEM_PROMPT_LT
        if "Lithuanian" in lang_instruction
        else _SYSTEM_PROMPT_EN
    )
    full_system = system + f"\n\n{lang_instruction}"
    if negative_hint:
        full_system += negative_hint

    # Inject accumulated self-improvement lessons
    try:
        from app.services.self_reflection_service import get_behaviour_guidelines
        guidelines = await get_behaviour_guidelines()
        if guidelines:
            full_system += (
                "\n\n━━ IŠMOKTOS PAMOKOS (iš ankstesnių klaidų) ━━\n"
                + guidelines
            )
    except Exception:
        pass

    history = history or []

    # Build messages list: history + new message
    messages = cast(list[dict[str, str]], history + [{"role": "user", "content": message}])

    openai_key = getattr(cfg, "OPENAI_API_KEY", "") or ""
    anthropic_key = getattr(cfg, "ANTHROPIC_API_KEY", "") or ""
    if openai_key or anthropic_key:
        _complex_kw = ("analiz", "palygink", "paaiškink", "detali", "kodėl",
                       "explain", "analyze", "compare", "research", "summarize")
        if len(message) < 120 and not any(kw in message.lower() for kw in _complex_kw):
            openai_model = getattr(cfg, "ROUTER_MODEL", "gpt-4o-mini")
        else:
            openai_model = getattr(cfg, "LLM_MODEL", "gpt-4.5-preview")
        anthropic_model = getattr(cfg, "ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
        log.debug("[chat_tool] routing to %s (msg_len=%d)", openai_model, len(message))
        reply = await complete_text(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            openai_model=openai_model,
            anthropic_model=anthropic_model,
            openai_messages=[{"role": "system", "content": full_system}] + messages,
            anthropic_messages=messages,
            system_prompt=full_system,
            max_tokens=2048,
            temperature=0.7,
            provider_preference="anthropic_first" if anthropic_key else "openai_first",
            tracking_operation="chat",
        )
        _cache_response(cache_key, reply)
        return reply

    # ── Ollama (offline / local fallback) ────────────────────────────────────
    try:
        reply = await _call_ollama(full_system, messages)
        _cache_response(cache_key, reply)
        return reply
    except Exception as ollama_exc:
        log.debug("[chat_tool] Ollama not available: %s", ollama_exc)

    raise RuntimeError("No LLM configured (set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env).")


# ── Ollama helper ─────────────────────────────────────────────────────────────

async def _call_ollama(system_prompt: str, messages: list[dict]) -> str:
    """
    Attempt to call a locally running Ollama instance.

    Requires Ollama running at http://localhost:11434 (or OLLAMA_BASE_URL env).
    Model defaults to "llama3.2" but can be overridden via OLLAMA_MODEL env.

    Raises RuntimeError if Ollama is not reachable or returns an error.
    """
    import json
    import os
    import urllib.request

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")

    # Quick reachability check first (saves time if Ollama is not running)
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"Accept": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception as exc:
        raise RuntimeError(f"Ollama not reachable at {base_url}: {exc}") from exc

    # Build payload – Ollama chat API
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    import asyncio
    loop = asyncio.get_event_loop()
    # Run blocking urllib call in a thread to avoid blocking the event loop
    def _do_request():
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    data = await loop.run_in_executor(None, _do_request)

    # Track usage if available
    try:
        from app.services.token_tracker import record_usage
        prompt_eval = data.get("prompt_eval_count", 0)
        eval_count = data.get("eval_count", 0)
        record_usage(f"ollama/{model}", prompt_eval, eval_count, "chat")
    except Exception:
        pass

    content = data.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Empty response from Ollama: {data}")

    log.info("[chat_tool] answered via Ollama (%s)", model)
    return content.strip()
