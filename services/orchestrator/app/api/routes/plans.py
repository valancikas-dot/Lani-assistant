"""
Plans API routes.

POST /api/v1/plans
    Submit a command; the planner creates an ExecutionPlan and the executor
    runs it immediately.  Returns PlanExecutionResponse.

POST /api/v1/plans/resume/{approval_id}
    After the user approves a paused plan step, resume execution from
    that step.  Returns an updated PlanExecutionResponse.

GET  /api/v1/plans/tools
    List all registered tools with their names, descriptions, and
    requires_approval flags (useful for the frontend "What can you do?" panel).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import UserSettings
from app.schemas.commands import CommandRequest, CommandResponse
from app.schemas.plan import ExecutionPlan, PlanExecutionResponse, PlanStep
from app.services.command_router import route_command, _classify_with_llm
from app.services.plan_executor import execute_plan
from app.services.task_planner import plan_command
from app.services.voice_shaper import shape_for_voice
from app.tools.registry import list_tools, get_tool

log = logging.getLogger(__name__)
router = APIRouter()

# ─── Language map for TTS messages ───────────────────────────────────────────

_LANG_MESSAGES: dict[str, dict[str, str]] = {
    "lt": {
        "completed": "Atlikta.",
        "failed": "Nepavyko.",
        "approval_required": "Reikia patvirtinimo.",
        "running": "Vykdoma…",
        "opened": "Atidaryta.",
        "done": "Padaryta.",
    },
    "en": {
        "completed": "Done.",
        "failed": "Failed.",
        "approval_required": "Approval required.",
        "running": "Running…",
        "opened": "Opened.",
        "done": "Done.",
    },
}

def _tts_from_result(result: PlanExecutionResponse, lang: str) -> str:
    """Build a short localised TTS string from a PlanExecutionResponse."""
    msgs = _LANG_MESSAGES.get(lang, _LANG_MESSAGES["en"])

    # Ieškome pirmojo sėkmingo žingsnio su pranešimu
    if result.step_results:
        for sr in result.step_results:
            raw = (sr.message or "").strip()
            if not raw:
                continue

            # Chat tool grąžina jau suformatuotą LT tekstą – nereikia versti.
            # Tik apribojame ilgį ir valome markdown.
            if sr.tool == "chat":
                shaped = shape_for_voice(raw, max_chars=600, language=lang)
                return shaped if shaped else msgs["done"]

            shaped = shape_for_voice(raw, language=lang)
            if not shaped:
                continue
            if lang != "en":
                return _translate_simple(shaped, lang, sr.tool)
            return shaped

    # Fallback: statusu paremtas pranešimas
    return msgs.get(result.overall_status, msgs["done"])


def _translate_simple(text: str, lang: str, tool: str) -> str:
    """Translate common English tool messages to the target language without LLM."""
    if lang != "lt":
        return text

    import re as _re

    # Pašaliname kabutes aplink app/failo pavadinimą: 'Safari' → Safari
    text = _re.sub(r"['\"]([^'\"]+)['\"]", r"\1", text)
    # Pašaliname galutinį tašką prieš vertimą – pridėsime patys
    text = text.strip().rstrip(".")

    # Tool-specific translations (greedy – pirmoji atitikimo taisyklė laimi)
    _LT: list[tuple[str, str]] = [
        # Klaidos – pirma, kad nepatektų į sėkmės šablonus
        (r"[Uu]nable to find application named?\s*['\"]?(.+?)['\"]?\s*$", r"Programos '\1' nerasta. Patikrink pavadinimą."),
        (r"[Cc]ould not open\s*(.+)",                r"Nepavyko atidaryti: \1"),
        (r"[Ee]rror[:\s]+(.+)",                      r"Klaida: \1"),
        (r"[Ff]ailed[:\s]+(.+)",                     r"Nepavyko: \1"),
        (r"[Ff]ailed",                               r"Nepavyko"),
        # Sėkmingi veiksmai – konkrečios programos
        (r"[Oo]pened?\s*['\"]?Safari['\"]?",         r"Safari atidaryta"),
        (r"[Oo]pened?\s*['\"]?Chrome['\"]?",         r"Chrome atidaryta"),
        (r"[Oo]pened?\s*['\"]?Google Chrome['\"]?",  r"Chrome atidaryta"),
        (r"[Oo]pened?\s*['\"]?Finder['\"]?",         r"Finder atidaryta"),
        (r"[Oo]pened?\s*['\"]?Terminal['\"]?",       r"Terminalas atidarytas"),
        (r"[Oo]pened?\s*['\"]?Mail['\"]?",           r"Paštas atidarytas"),
        (r"[Oo]pened?\s*['\"]?Spotify['\"]?",        r"Spotify atidarytas"),
        (r"[Oo]pened?\s*['\"]?Music['\"]?",          r"Muzika atidaryta"),
        (r"[Oo]pened?\s*['\"]?VS Code['\"]?",        r"VS Code atidarytas"),
        (r"[Oo]pened?\s*['\"]?Visual Studio Code['\"]?", r"VS Code atidarytas"),
        (r"[Oo]pened?\s*['\"]?Slack['\"]?",          r"Slack atidarytas"),
        (r"[Oo]pened?\s*['\"]?Telegram['\"]?",       r"Telegram atidarytas"),
        (r"[Oo]pened?\s*['\"]?WhatsApp['\"]?",       r"WhatsApp atidarytas"),
        (r"[Oo]pened?\s*['\"]?Notes['\"]?",          r"Užrašai atidaryti"),
        (r"[Oo]pened?\s*['\"]?Messages['\"]?",       r"Žinutės atidarytos"),
        (r"[Oo]pened?\s*['\"]?Photos['\"]?",         r"Nuotraukos atidarytos"),
        (r"[Oo]pened?\s*['\"]?System Settings['\"]?", r"Sistemos nustatymai atidaryti"),
        (r"[Oo]pened?\s*['\"]?System Preferences['\"]?", r"Sistemos nustatymai atidaryti"),
        (r"[Oo]pened?\s*['\"]?(.+?)['\"]?\s+→\s+https?://\S+", r"\1 atidaryta naršyklėje"),
        (r"[Oo]pened?\s+(.+)",                       r"\1 atidaryta"),
        # Failų operacijos
        (r"[Cc]reated?\s+folder\s+(.+)",             r"Aplankas '\1' sukurtas"),
        (r"[Cc]reated?\s+file\s+(.+)",               r"Failas '\1' sukurtas"),
        (r"[Dd]eleted?\s+(.+)",                      r"'\1' ištrinta"),
        (r"[Mm]oved?\s+(.+)\s+to\s+(.+)",            r"Perkelta į '\2'"),
        (r"[Mm]oved?\s+(.+)",                        r"Perkelta"),
        (r"[Ss]orted?\s+(.+)",                       r"Surikiuota"),
        (r"[Dd]ownloaded?\s+(.+)",                   r"Atsisiųsta"),
        (r"[Ss]aved?\s+(.+)",                        r"Išsaugota"),
        # Bendri statusai
        (r"[Dd]one\.?",                              r"Atlikta"),
        (r"[Ss]uccess\.?",                           r"Sėkmingai"),
        (r"[Cc]ompleted\.?",                         r"Atlikta"),
        (r"[Ff]ocused?\s+(.+)",                      r"'\1' perkelta į priekį"),
    ]
    for pattern, replacement in _LT:
        m = _re.search(pattern, text, flags=_re.IGNORECASE)
        if m:
            result = _re.sub(pattern, replacement, text, flags=_re.IGNORECASE)
            return result.strip().rstrip(".") + "."
    # Neatitiko jokios taisyklės – grąžiname originalą su tašku
    return text + "."


async def _get_language(db: AsyncSession) -> str:
    """Return configured assistant language (defaults to 'lt')."""
    row_res = await db.execute(select(UserSettings).where(UserSettings.id == 1))
    row = row_res.scalar_one_or_none()
    lang = getattr(row, "assistant_language", None) or "lt"
    return lang.split("-")[0].lower()


# ─── Submit a new planned command ────────────────────────────────────────────

@router.post("/plans", response_model=PlanExecutionResponse)
async def submit_plan(
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> PlanExecutionResponse:
    """
    Analyse *command*, build an ExecutionPlan, execute it, and return results.

    • Single-step commands: behaves like /commands but with richer response.
    • Multi-step commands:  runs each step in order, pausing on approval gates.
    • Falls back to LLM classifier when regex planner finds no match.
    """
    plan = plan_command(request.command)

    # plan_command now always returns a valid plan (chat fallback guaranteed).
    # We still try LLM classification when the plan landed on the chat fallback
    # AND we have an API key, giving the LLM a chance to route to a more
    # specific tool.
    if (
        plan
        and len(plan.steps) == 1
        and plan.steps[0].tool == "chat"
    ):
        tool_name, params = await _classify_with_llm(request.command, force_tool=True)
        if tool_name not in ("unknown", "chat"):
            # LLM rado konkretų įrankį – naudojame jį
            t = get_tool(tool_name)
            step = PlanStep(
                index=0,
                tool=tool_name,
                description=f"Execute: {tool_name}",
                args=params,
                requires_approval=t.requires_approval if t else False,
            )
            plan = ExecutionPlan(goal=request.command, steps=[step], is_multi_step=False)
        # Jei LLM grąžino "chat" arba "unknown" – paliekame originalų chat planą
        # su teisingais params (message = visa komanda)

    result = await execute_plan(plan, db)

    # ── Attach localised tts_text ──────────────────────────────────────────
    lang = await _get_language(db)
    result.tts_text = _tts_from_result(result, lang)

    return result


# ─── Resume after approval ────────────────────────────────────────────────────

@router.post("/plans/resume/{approval_id}", response_model=PlanExecutionResponse)
async def resume_plan(
    approval_id: int,
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> PlanExecutionResponse:
    """
    Resume a paused plan after the user has approved the pending step.

    The client must re-send the original command in the request body so the
    planner can reconstruct the plan.  The executor skips already-completed
    steps and continues from the approved step.

    NOTE: In a production system you would persist the plan to the DB and
    look it up by approval_id; this stateless re-plan approach is safe for
    single-server use.
    """
    plan = plan_command(request.command)

    # plan_command always returns a valid plan now, but keep defensive check
    # in case the command string is somehow corrupted.
    if not plan or not plan.steps:
        raise HTTPException(status_code=422, detail="Could not reconstruct the plan.")

    # Find which step triggered the approval so we can resume from there
    paused_index: int = 0
    for step in plan.steps:
        if step.requires_approval:
            paused_index = step.index
            break

    return await execute_plan(plan, db, start_from_step=paused_index)


# ─── Tool catalogue ───────────────────────────────────────────────────────────

@router.get("/plans/tools")
async def get_tools() -> list:
    """Return all registered tools – name, description, requires_approval."""
    return list_tools()
