"""
creative_tools.py – Kūrybiniai AI įrankiai Lani asistentui.

Tools:
  brainstorm          – generuoja idėjų sąrašą duotai temai
  generate_content    – rašo tinklaraščio įrašą, socialinių tinklų postą,
                        video scenarijų, el. laišką, esė ar kitą turinio tipą
  expand_idea         – plečia vieną idėją į išsamų aprašymą
  summarize_for_voice – sutrumpina bet kokį tekstą į 1-3 balso sakinus

Visi įrankiai naudoja OpenAI chat completion.  Kai OPENAI_API_KEY nėra,
grąžinamas aiškus klaidos pranešimas (ne stack trace).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.schemas.commands import ToolResult
from app.services.llm_text_service import complete_text
from app.tools.base import BaseTool

log = logging.getLogger(__name__)


# ─── Shared LLM helper ────────────────────────────────────────────────────────

async def _llm(system: str, user: str, max_tokens: int = 2000) -> str:
    """Call OpenAI chat and return text.  Returns error string on failure."""
    try:
        from app.core.config import settings as cfg
        if not getattr(cfg, "OPENAI_API_KEY", ""):
            return "Klaida: OPENAI_API_KEY nenustatytas .env faile."
        return await complete_text(
            openai_api_key=cfg.OPENAI_API_KEY,
            openai_model=getattr(cfg, "LLM_MODEL", "gpt-4o-mini"),
            openai_messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.8,
        )
    except Exception as exc:
        log.error("[creative] LLM error: %s", exc)
        return f"LLM klaida: {exc}"


# ─── Brainstorm ───────────────────────────────────────────────────────────────

class BrainstormTool(BaseTool):
    name = "brainstorm"
    description = (
        "Generate a list of creative ideas for a given topic or problem. "
        "Returns a numbered list of diverse, actionable ideas. "
        "Parameters: topic (required), count (optional, default 10), "
        "style (optional: 'practical', 'creative', 'out_of_the_box')."
    )
    requires_approval = False
    parameters = [
        {"name": "topic",  "description": "The topic or problem to brainstorm ideas for", "required": True},
        {"name": "count",  "description": "Number of ideas to generate (default 10)", "required": False},
        {"name": "style",  "description": "Idea style: practical | creative | out_of_the_box", "required": False},
        {"name": "language", "description": "Response language code, e.g. 'lt' or 'en'", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        topic = str(params.get("topic", "")).strip()
        if not topic:
            return ToolResult(tool_name=self.name, status="error", message="'topic' is required.")

        count = int(params.get("count", 10))
        style = str(params.get("style", "creative")).lower()
        lang = str(params.get("language", "lt")).lower()

        style_desc = {
            "practical": "praktines, lengvai įgyvendinamas idėjas",
            "creative": "kūrybiškas, įdomias idėjas",
            "out_of_the_box": "nestandartines, drąsias, neįprastas idėjas",
        }.get(style, "kūrybiškas idėjas")

        lang_instruction = (
            "Atsakyk lietuviškai." if lang == "lt"
            else f"Respond in language: {lang}."
        )

        system = (
            f"Tu esi kūrybinis padėjėjas. Generuoji {style_desc}. "
            f"{lang_instruction} "
            "Pateik numeruotą sąrašą be paaiškinimų – tik idėjos, aiškiai ir glaustai."
        )
        user = f"Sugeneruok {count} idėjų temai: {topic}"

        result = await _llm(system, user, max_tokens=1500)

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=result,
            data={"topic": topic, "count": count, "style": style, "ideas_text": result},
        )


# ─── Generate Content ─────────────────────────────────────────────────────────

_CONTENT_TYPES = {
    "blog_post":       ("tinklaraščio įrašas",       "Parašyk išsamų tinklaraščio įrašą"),
    "social_post":     ("socialinių tinklų postas",   "Parašyk trumpą, patrauklų socialinių tinklų postą"),
    "video_script":    ("video scenarijus",            "Parašyk vaizdo įrašo scenarijų su įvadu, pagrindiniu turiniu ir išvada"),
    "email":           ("el. laiškas",                 "Parašyk profesionalų el. laišką"),
    "essay":           ("esė",                         "Parašyk struktūruotą esė"),
    "tweet_thread":    ("Twitter/X gijų serija",       "Parašyk 5-7 tweetų giją"),
    "product_desc":    ("produkto aprašymas",          "Parašyk patrauklų produkto aprašymą"),
    "landing_page":    ("nukreipimo puslapio tekstas", "Parašyk nukreipimo puslapio tekstą"),
    "story":           ("trumpa istorija",             "Parašyk kūrybinę trumpą istoriją"),
    "report":          ("ataskaita",                   "Parašyk struktūruotą ataskaitą"),
}


class GenerateContentTool(BaseTool):
    name = "generate_content"
    description = (
        "Write creative or professional content: blog post, social media post, "
        "video script, email, essay, tweet thread, product description, "
        "landing page copy, story, or report. "
        "Parameters: content_type (required), topic (required), "
        "tone (optional: 'professional', 'casual', 'humorous', 'inspirational'), "
        "length (optional: 'short', 'medium', 'long'), "
        "extra_instructions (optional: any additional requirements)."
    )
    requires_approval = False
    parameters = [
        {"name": "content_type", "description": "Type: blog_post | social_post | video_script | email | essay | tweet_thread | product_desc | landing_page | story | report", "required": True},
        {"name": "topic",        "description": "The subject/topic to write about", "required": True},
        {"name": "tone",         "description": "Tone: professional | casual | humorous | inspirational", "required": False},
        {"name": "length",       "description": "Length: short | medium | long", "required": False},
        {"name": "extra_instructions", "description": "Any additional requirements or context", "required": False},
        {"name": "language",     "description": "Response language code, e.g. 'lt' or 'en'", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        content_type = str(params.get("content_type", "blog_post")).lower().strip()
        topic = str(params.get("topic", "")).strip()
        if not topic:
            return ToolResult(tool_name=self.name, status="error", message="'topic' is required.")

        tone = str(params.get("tone", "professional")).lower()
        length = str(params.get("length", "medium")).lower()
        extra = str(params.get("extra_instructions", "")).strip()
        lang = str(params.get("language", "lt")).lower()

        type_lt, verb = _CONTENT_TYPES.get(content_type, ("turinys", "Sukurk"))

        length_map = {"short": "trumpas (200-300 žodžių)", "medium": "vidutinis (400-600 žodžių)", "long": "ilgas (800-1200 žodžių)"}
        length_desc = length_map.get(length, "vidutinis (400-600 žodžių)")

        tone_map = {
            "professional": "profesionalus, dalykiškas",
            "casual": "draugiškas, laisvas",
            "humorous": "humористiškas, linksmas",
            "inspirational": "įkvepiantis, motyvuojantis",
        }
        tone_desc = tone_map.get(tone, "profesionalus")

        lang_instruction = (
            "Parašyk lietuviškai." if lang == "lt"
            else f"Write in language: {lang}."
        )

        system = (
            f"Tu esi profesionalus turinio kūrėjas. {lang_instruction} "
            f"Tonas: {tone_desc}. Apimtis: {length_desc}. "
            "Rašyk tiesiai – be pratarmių apie tai, kad esi AI."
        )
        user = f"{verb} šia tema: {topic}"
        if extra:
            user += f"\n\nPapildomi reikalavimai: {extra}"

        max_tok = {"short": 600, "medium": 1000, "long": 2000}.get(length, 1000)
        result = await _llm(system, user, max_tokens=max_tok)

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=result,
            data={
                "content_type": content_type,
                "topic": topic,
                "tone": tone,
                "length": length,
                "content": result,
            },
        )


# ─── Expand Idea ──────────────────────────────────────────────────────────────

class ExpandIdeaTool(BaseTool):
    name = "expand_idea"
    description = (
        "Take a short idea or concept and expand it into a detailed plan, "
        "description, or outline. Great for fleshing out a project idea, "
        "business concept, or creative premise. "
        "Parameters: idea (required), format (optional: 'outline', 'narrative', 'bullet_points')."
    )
    requires_approval = False
    parameters = [
        {"name": "idea",   "description": "The idea or concept to expand", "required": True},
        {"name": "format", "description": "Output format: outline | narrative | bullet_points", "required": False},
        {"name": "language", "description": "Response language code", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        idea = str(params.get("idea", "")).strip()
        if not idea:
            return ToolResult(tool_name=self.name, status="error", message="'idea' is required.")

        fmt = str(params.get("format", "outline")).lower()
        lang = str(params.get("language", "lt")).lower()

        fmt_map = {
            "outline":       "struktūruotą kontūrą su skyriais ir posistemiais",
            "narrative":     "išsamų naratyvinį aprašymą",
            "bullet_points": "glaustų taškų sąrašą",
        }
        fmt_desc = fmt_map.get(fmt, "struktūruotą kontūrą")

        lang_instruction = "Atsakyk lietuviškai." if lang == "lt" else f"Respond in: {lang}."

        system = (
            f"Tu esi idėjų plėtotojas. Pateiki {fmt_desc}. "
            f"{lang_instruction} Būk konkretus ir praktiškas."
        )
        user = f"Išplėtok šią idėją: {idea}"

        result = await _llm(system, user, max_tokens=1500)

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=result,
            data={"idea": idea, "format": fmt, "expanded": result},
        )


# ─── Summarize for Voice ──────────────────────────────────────────────────────

class SummarizeForVoiceTool(BaseTool):
    name = "summarize_for_voice"
    description = (
        "Compress any text into 1-3 short sentences optimised for TTS playback. "
        "Strips markdown, lists, and jargon. Ideal for converting long "
        "research summaries or document content into a spoken response. "
        "Parameters: text (required), language (optional)."
    )
    requires_approval = False
    parameters = [
        {"name": "text",     "description": "The text to compress for voice output", "required": True},
        {"name": "language", "description": "Response language code", "required": False},
    ]

    async def run(self, params: Dict[str, Any]) -> ToolResult:
        text = str(params.get("text", "")).strip()
        if not text:
            return ToolResult(tool_name=self.name, status="error", message="'text' is required.")

        lang = str(params.get("language", "lt")).lower()
        lang_instruction = "Atsakyk lietuviškai." if lang == "lt" else f"Respond in: {lang}."

        system = (
            "Tu trumpini tekstą balso asistentui. "
            f"{lang_instruction} "
            "Sutrumpink iki 1-3 trumpų sakinių. Pašalink markdown, sąrašus, techninius terminus. "
            "Kalba turi skambėti natūraliai sakoma."
        )
        user = f"Sutrumpink šį tekstą balso atsakymui:\n\n{text[:4000]}"

        result = await _llm(system, user, max_tokens=200)

        return ToolResult(
            tool_name=self.name,
            status="success",
            message=result,
            data={"voice_summary": result},
        )
