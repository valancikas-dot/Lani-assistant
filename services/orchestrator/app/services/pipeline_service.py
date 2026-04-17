"""
Pipeline Service – Lani's structured multi-step execution system.

Transforms Lani from a "smart assistant" into a TRUE EXECUTION AGENT that
produces real output structures (artifacts, files, plans) via orchestrated
tool chains.

Architecture
────────────
• Every pipeline is a named, ordered sequence of PipelineSteps.
• Each PipelineStep specifies WHICH registered tool to call and HOW to
  build its parameters from the running prompt + accumulated artifacts.
• Every step is executed through execution_guard (capability check,
  policy evaluation, approval gate, audit chain, rollback).
• Pipelines are tracked as Missions so checkpoints, budgets, and the
  existing approval/replay infrastructure work out of the box.
• Simulated steps are clearly marked; they fall back gracefully when the
  external integration (Runway, Suno) is not configured.

Five built-in pipelines
───────────────────────
  video      – Script → voiceover → visual style → asset plan → video gen → captions
  music      – Lyrics → structure → mood/style → beat plan → music export
  app        – Requirements → project plan → scaffold → files → tests → summary
  marketing  – Audience → messaging → variants → content batch → channel strategy
  research   – Query → multi-source research → findings → insights → action output

Usage (from command_router)
───────────────────────────
    from app.services.pipeline_service import run_pipeline

    result = await run_pipeline(
        pipeline_id="video",
        prompt="create a 60s Instagram Reel about sustainable fashion",
        db=db,
        settings_row=settings_row,
        active_modes=["writer"],
    )
    # result.status  → "completed" | "paused_for_approval" | "failed"
    # result.artifacts → {"script": "...", "voiceover": "...", ...}
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class PipelineStep:
    """
    Single step within a Pipeline.

    Attributes
    ----------
    step_id         : Snake-case identifier (unique within the pipeline).
    name            : Human-readable step label shown to the user.
    description     : What this step does.
    tool_name       : Registered tool name (must exist in tool registry).
    param_builder   : Callable(prompt, context, artifacts) → Dict.
                      Builds the params dict for guarded_execute.
    artifact_key    : Key under which the result is stored in PipelineResult.artifacts.
    extract_result  : Callable(ToolResult) → Any.
                      Extracts the relevant artifact value from the tool result.
    requires_approval : Override tool's default – force an approval gate.
    simulation_mode : Marks the step as a simulation/stub.
    """
    step_id:         str
    name:            str
    description:     str
    tool_name:       str
    param_builder:   Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
    artifact_key:    str
    extract_result:  Callable[[Any], Any]
    requires_approval: bool = False
    simulation_mode: bool = False


@dataclass
class Pipeline:
    """Complete pipeline definition."""
    pipeline_id:   str
    name:          str
    description:   str
    domain:        str  # "video" | "music" | "app" | "marketing" | "research"
    steps:         List[PipelineStep]
    output_schema: Dict[str, str]    # artifact_key → human description
    required_tools: List[str] = field(default_factory=list)
    next_action_templates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_id":   self.pipeline_id,
            "name":          self.name,
            "description":   self.description,
            "domain":        self.domain,
            "steps":         [{"step_id": s.step_id, "name": s.name, "description": s.description,
                                "tool": s.tool_name, "simulation": s.simulation_mode}
                               for s in self.steps],
            "output_schema": self.output_schema,
            "required_tools": self.required_tools,
        }


@dataclass
class PipelineResult:
    """
    Structured outcome of a pipeline execution.

    Matches the JSON shape the frontend expects:
    {
      "pipeline": "video",
      "steps_completed": [...],
      "artifacts": {...},
      "next_actions": [...]
    }
    """
    pipeline:          str           # pipeline_id
    pipeline_name:     str
    status:            str           # "completed" | "paused_for_approval" | "failed" | "partial"
    steps_completed:   List[Dict[str, Any]]
    artifacts:         Dict[str, Any]
    next_actions:      List[str]
    mission_id:        Optional[int] = None
    approval_id:       Optional[int] = None
    error:             Optional[str] = None
    simulation:        bool = False   # True if any step ran in simulation mode

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline":        self.pipeline,
            "pipeline_name":   self.pipeline_name,
            "status":          self.status,
            "steps_completed": self.steps_completed,
            "artifacts":       self.artifacts,
            "next_actions":    self.next_actions,
            "mission_id":      self.mission_id,
            "approval_id":     self.approval_id,
            "error":           self.error,
            "simulation":      self.simulation,
        }


# ─── Artifact extractor helpers ───────────────────────────────────────────────

def _text_from_result(tool_result: Any) -> str:
    """Extract text content from any ToolResult."""
    if tool_result is None:
        return ""
    # chat tool returns message text
    msg = getattr(tool_result, "message", None) or ""
    # data may contain richer info
    data = getattr(tool_result, "data", None) or {}
    if isinstance(data, dict):
        return data.get("text") or data.get("content") or data.get("result") or msg
    if isinstance(data, str):
        return data
    return msg


def _data_from_result(tool_result: Any) -> Any:
    """Extract data dict from a ToolResult."""
    if tool_result is None:
        return {}
    data = getattr(tool_result, "data", None)
    if data:
        return data
    return getattr(tool_result, "message", "") or ""


def _scaffold_from_result(tool_result: Any) -> Dict[str, Any]:
    """Extract scaffold info (project structure, files) from builder tool result."""
    data = _data_from_result(tool_result)
    if isinstance(data, dict):
        return data
    return {"output": str(data)}


def _format_web_results(web_data: Any) -> str:
    """Format web_search_ext result dict into a readable string for LLM context."""
    if not web_data or not isinstance(web_data, dict):
        return "(no web results)"
    results = web_data.get("results", [])
    if not results:
        return "(no web results)"
    lines = []
    for r in results[:8]:
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"• {title}\n  {url}\n  {snippet}")
    return "\n\n".join(lines)


# ─── LLM prompt builders ──────────────────────────────────────────────────────
# These produce the `message` param for the chat tool so that each step
# gets a purpose-built LLM prompt that yields structured output.

def _chat_params(message: str) -> Dict[str, Any]:
    return {"message": message}


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO CREATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_VIDEO_STEPS: List[PipelineStep] = [

    PipelineStep(
        step_id="generate_script",
        name="Generate Script",
        description="Write a complete video script with scene descriptions, dialogue, and pacing.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"You are a professional video scriptwriter. Write a complete, production-ready video script for:\n\n"
            f"\"{prompt}\"\n\n"
            f"Include: scene descriptions, on-screen text, dialogue/narration, pacing notes, and estimated duration per scene.\n"
            f"Format as a structured script with SCENE markers. Be specific and actionable."
        ),
        artifact_key="script",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_voiceover_text",
        name="Generate Voiceover Text",
        description="Extract and polish the voiceover/narration text from the script.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on this video script:\n\n{arts.get('script', '')[:2000]}\n\n"
            f"Extract and write ONLY the voiceover/narration text as it would be spoken aloud. "
            f"Remove scene directions and on-screen text. Output clean, natural spoken language. "
            f"Mark pauses with [pause] and emphasis with *word*."
        ),
        artifact_key="voiceover",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_voiceover_audio",
        name="Generate Voiceover Audio",
        description="Convert the voiceover text to speech using ElevenLabs or OpenAI TTS.",
        tool_name="generate_voice",
        param_builder=lambda prompt, ctx, arts: {
            "text": arts.get("voiceover", "")[:4000] or prompt,
            "output_filename": "voiceover.mp3",
        },
        artifact_key="voiceover_audio",
        extract_result=_data_from_result,
    ),

    PipelineStep(
        step_id="select_visual_style",
        name="Select Visual Style",
        description="Define the visual language, colour palette, typography, and aesthetic.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"For a video about \"{prompt}\", define a complete visual style guide.\n\n"
            f"Include:\n"
            f"- Overall aesthetic (e.g. minimalist, cinematic, lo-fi, corporate)\n"
            f"- Colour palette (primary, secondary, accent – with hex codes)\n"
            f"- Typography style\n"
            f"- Shot style (b-roll suggestions, camera angles)\n"
            f"- Lighting mood\n"
            f"- Transition style\n"
            f"Format as a clear style guide document."
        ),
        artifact_key="visual_style",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_asset_plan",
        name="Generate Asset Plan",
        description="List every visual asset, stock clip, graphic, and animation needed.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on this script:\n\n{arts.get('script', '')[:1500]}\n\n"
            f"And visual style:\n{arts.get('visual_style', '')[:500]}\n\n"
            f"Create a complete ASSET LIST for production. For each asset include:\n"
            f"- Asset ID (A001, A002...)\n"
            f"- Type (b-roll clip, graphic, animation, text overlay, music track)\n"
            f"- Description (what it shows)\n"
            f"- Source suggestion (stock library, AI-generated, custom)\n"
            f"- Duration / usage (which scene, how long)\n"
            f"Output as a numbered list."
        ),
        artifact_key="asset_plan",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_visual_assets",
        name="Generate Visual Assets",
        description="Generate key visual assets / thumbnail images using AI image generation.",
        tool_name="generate_image_ext",
        param_builder=lambda prompt, ctx, arts: {
            "prompt": (
                f"{arts.get('visual_style', '')[:300]} — "
                f"cinematic still for video about: {prompt}"
            ),
            "count": 2,
            "size": "1792x1024",
            "filename_prefix": "video_asset",
        },
        artifact_key="visual_assets",
        extract_result=_data_from_result,
    ),

    PipelineStep(
        step_id="generate_video_clip",
        name="Generate Video Clip",
        description="Generate video using Runway ML Gen-4 Turbo (or simulation if API key not set).",
        tool_name="generate_video_ext",
        param_builder=lambda prompt, ctx, arts: {
            "prompt": (
                f"{arts.get('visual_style', '')[:300]} | "
                f"{arts.get('script', '')[:400]}"
            ),
            "duration": 10,
            "ratio": "9:16",
            "output_filename": "lani_video.mp4",
        },
        artifact_key="video_reference",
        extract_result=_data_from_result,
        requires_approval=True,
    ),

    PipelineStep(
        step_id="generate_captions",
        name="Generate Captions",
        description="Create accurate, well-timed captions/subtitles for accessibility.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on this voiceover text:\n\n{arts.get('voiceover', '')}\n\n"
            f"Generate SRT-format captions. Break into 2-line segments of maximum 42 characters. "
            f"Estimate timecodes based on natural speech rhythm (approx. 150 words/minute). "
            f"Output valid SRT format starting from 00:00:01,000."
        ),
        artifact_key="captions",
        extract_result=_text_from_result,
    ),
]

VIDEO_PIPELINE = Pipeline(
    pipeline_id="video",
    name="Video Creation",
    description="End-to-end video production: script → voiceover text → voiceover audio → visual style → assets → video generation → captions.",
    domain="video",
    steps=_VIDEO_STEPS,
    output_schema={
        "script":           "Complete video script with scene descriptions",
        "voiceover":        "Polished narration/voiceover text",
        "voiceover_audio":  "ElevenLabs/OpenAI TTS audio result (path or simulation)",
        "visual_style":     "Visual style guide with colours, typography, shot style",
        "asset_plan":       "Numbered list of every asset needed for production",
        "visual_assets":    "AI-generated key visual stills (OpenAI Images result)",
        "video_reference":  "Runway ML generation result (path/URL or simulation stub)",
        "captions":         "SRT-format captions",
    },
    required_tools=["chat", "generate_voice", "generate_image_ext", "generate_video_ext"],
    next_action_templates=[
        "Download the generated video clip",
        "Upload assets to your editing timeline",
        "Play the voiceover audio",
        "Export final video for {platform}",
    ],
)


# ══════════════════════════════════════════════════════════════════════════════
# MUSIC CREATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_MUSIC_STEPS: List[PipelineStep] = [

    PipelineStep(
        step_id="generate_lyrics",
        name="Generate Lyrics",
        description="Write complete song lyrics with verse/chorus/bridge structure.",
        tool_name="write_lyrics",
        param_builder=lambda prompt, ctx, arts: {
            "prompt": prompt,
            "style":  ctx.get("style", ""),
        },
        artifact_key="lyrics",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="define_song_structure",
        name="Define Song Structure",
        description="Lay out the song architecture: BPM, key, sections, timing.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"For a song about \"{prompt}\" with these lyrics:\n\n{arts.get('lyrics', '')[:1000]}\n\n"
            f"Define a complete SONG STRUCTURE:\n"
            f"- Tempo (BPM)\n"
            f"- Musical key\n"
            f"- Time signature\n"
            f"- Section breakdown: [Intro duration] [Verse 1 duration] [Chorus] [Verse 2] [Bridge] [Outro]\n"
            f"- Approximate total duration\n"
            f"Be specific with numbers."
        ),
        artifact_key="song_structure",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_mood_and_style",
        name="Mood & Style Profile",
        description="Define the sonic mood, genre, instrumentation, and production style.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"For a song about \"{prompt}\", create a detailed PRODUCTION STYLE GUIDE:\n\n"
            f"- Genre and sub-genre\n"
            f"- Emotional mood / energy level (0-10)\n"
            f"- Primary instruments\n"
            f"- Vocal style (if any)\n"
            f"- Reference artists (3-5 comparable acts)\n"
            f"- Production tags for AI generation (e.g. 'cinematic, emotional, piano-driven, 85 BPM')\n"
            f"- Suitable platforms (Spotify playlist type, sync licensing mood)"
        ),
        artifact_key="mood_style",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_song_audio",
        name="Generate Song Audio",
        description="Generate the full song using Suno AI (or simulation if API key not set).",
        tool_name="generate_song_ext",
        param_builder=lambda prompt, ctx, arts: {
            "prompt": (
                f"{arts.get('mood_style', '')[:300]} | "
                f"Structure: {arts.get('song_structure', '')[:200]}"
            ),
            "lyrics":  arts.get("lyrics", ""),
            "style":   arts.get("mood_style", ""),
            "title":   prompt[:50],
        },
        artifact_key="song_generation",
        extract_result=_data_from_result,
        requires_approval=True,
    ),

    PipelineStep(
        step_id="export_music_plan",
        name="Export Production Plan",
        description="Package all artifacts into a production-ready music brief.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Compile a MUSIC PRODUCTION BRIEF document for:\n\n"
            f"Song: \"{prompt}\"\n\n"
            f"Lyrics:\n{arts.get('lyrics', '')[:600]}\n\n"
            f"Structure: {arts.get('song_structure', '')[:300]}\n\n"
            f"Mood/Style: {arts.get('mood_style', '')[:300]}\n\n"
            f"Format this as a professional brief ready to hand off to a producer or use with AI tools. "
            f"Include: title suggestion, 3 alternate title options, marketing one-liner, and platform fit."
        ),
        artifact_key="production_plan",
        extract_result=_text_from_result,
    ),
]

MUSIC_PIPELINE = Pipeline(
    pipeline_id="music",
    name="Music Creation",
    description="Full music production: lyrics → structure → mood/style → real song generation (Suno AI) → production plan.",
    domain="music",
    steps=_MUSIC_STEPS,
    output_schema={
        "lyrics":           "Complete song lyrics",
        "song_structure":   "BPM, key, section breakdown, timing",
        "mood_style":       "Genre, mood, instrumentation, AI generation tags",
        "song_generation":  "Suno AI result with track_paths / track_urls (or simulation stub)",
        "production_plan":  "Complete production brief for handoff",
    },
    required_tools=["write_lyrics", "chat", "generate_song_ext"],
    next_action_templates=[
        "Play the generated track",
        "Record live vocals over the backing track",
        "Submit to Spotify for Artists",
        "Create a lyric video",
        "License the track for sync",
    ],
)


# ══════════════════════════════════════════════════════════════════════════════
# APP BUILDER PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_APP_STEPS: List[PipelineStep] = [

    PipelineStep(
        step_id="analyze_requirements",
        name="Analyse Requirements",
        description="Parse the user's app idea into structured technical requirements.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"You are a senior software architect. Analyse this app request and produce a structured REQUIREMENTS DOCUMENT:\n\n"
            f"\"{prompt}\"\n\n"
            f"Include:\n"
            f"- App type and platform (web, mobile, desktop, API, CLI)\n"
            f"- Core features (prioritised: P0, P1, P2)\n"
            f"- Tech stack recommendation (with rationale)\n"
            f"- Data models (entities + relationships)\n"
            f"- API endpoints (if applicable)\n"
            f"- Non-functional requirements (auth, performance, security)\n"
            f"- Estimated complexity (hours per feature)\n"
            f"Be specific and technical."
        ),
        artifact_key="requirements",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_project_plan",
        name="Generate Project Plan",
        description="Create a phased implementation plan with milestones.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on these requirements:\n\n{arts.get('requirements', '')[:2000]}\n\n"
            f"Create a PHASED PROJECT PLAN:\n"
            f"- Phase 1: Foundation (project setup, core models, basic API)\n"
            f"- Phase 2: Core features (P0 items)\n"
            f"- Phase 3: Extended features (P1 items)\n"
            f"- Phase 4: Polish & deployment\n\n"
            f"For each phase list: tasks, estimated hours, acceptance criteria, and key files to create.\n"
            f"Also define the folder structure for the entire project."
        ),
        artifact_key="project_plan",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="scaffold_project",
        name="Scaffold Project",
        description="Create the project folder structure and boilerplate files.",
        tool_name="create_project_scaffold",
        param_builder=lambda prompt, ctx, arts: {
            "description": prompt,
            "output_dir":  "~/Desktop/lani_projects",
        },
        artifact_key="scaffold",
        extract_result=_scaffold_from_result,
        requires_approval=True,
    ),

    PipelineStep(
        step_id="generate_files",
        name="Generate Source Files",
        description="Write the core source files based on the project plan.",
        tool_name="generate_feature_files",
        param_builder=lambda prompt, ctx, arts: {
            "feature_description": (
                f"{prompt}. Requirements: {arts.get('requirements', '')[:800]}"
            ),
            "project_dir": arts.get("scaffold", {}).get("project_dir", "~/Desktop/lani_projects"),
        },
        artifact_key="generated_files",
        extract_result=_data_from_result,
        requires_approval=True,
    ),

    PipelineStep(
        step_id="run_tests",
        name="Run Tests",
        description="Execute the generated test suite and report results.",
        tool_name="run_tests",
        param_builder=lambda prompt, ctx, arts: {
            "test_path": arts.get("scaffold", {}).get("project_dir", "~/Desktop/lani_projects"),
            "framework": "pytest",
        },
        artifact_key="test_results",
        extract_result=_data_from_result,
        requires_approval=True,
    ),

    PipelineStep(
        step_id="build_summary",
        name="Build Summary",
        description="Produce a README and developer handoff notes.",
        tool_name="create_readme",
        param_builder=lambda prompt, ctx, arts: {
            "project_description": prompt,
            "project_dir": arts.get("scaffold", {}).get("project_dir", "~/Desktop/lani_projects"),
        },
        artifact_key="readme",
        extract_result=_text_from_result,
    ),
]

APP_PIPELINE = Pipeline(
    pipeline_id="app",
    name="App Builder",
    description="Full-stack app generation: requirements → plan → scaffold → files → tests → README.",
    domain="app",
    steps=_APP_STEPS,
    output_schema={
        "requirements":    "Structured technical requirements document",
        "project_plan":    "Phased project plan with folder structure",
        "scaffold":        "Project directory structure and boilerplate",
        "generated_files": "Generated source code files",
        "test_results":    "Test suite execution results",
        "readme":          "README and developer handoff notes",
    },
    required_tools=["chat", "create_project_scaffold", "generate_feature_files", "run_tests", "create_readme"],
    next_action_templates=[
        "Open the project in VS Code",
        "Run `npm install` / `pip install -r requirements.txt`",
        "Deploy to {platform}",
        "Set up CI/CD pipeline",
    ],
)


# ══════════════════════════════════════════════════════════════════════════════
# MARKETING PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_MARKETING_STEPS: List[PipelineStep] = [

    PipelineStep(
        step_id="audience_analysis",
        name="Audience Analysis",
        description="Research and define target personas with psychographic depth.",
        tool_name="research_and_prepare_brief",
        param_builder=lambda prompt, ctx, arts: {
            "query": f"target audience analysis and buyer personas for: {prompt}",
        },
        artifact_key="audience",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="messaging_strategy",
        name="Messaging Strategy",
        description="Develop core value propositions and messaging pillars.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on this audience analysis:\n\n{arts.get('audience', '')[:1500]}\n\n"
            f"Develop a MESSAGING STRATEGY for: \"{prompt}\"\n\n"
            f"Include:\n"
            f"- Primary value proposition (1 sentence)\n"
            f"- 3 messaging pillars (each with headline + 2-sentence explanation)\n"
            f"- Tone of voice (3-5 descriptive words + what to avoid)\n"
            f"- Key pain points addressed (per persona)\n"
            f"- Proof points / social proof required\n"
            f"- Competitive differentiators"
        ),
        artifact_key="messaging",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_variants",
        name="Generate Copy Variants",
        description="Write multiple A/B-testable ad copy and headline variants.",
        tool_name="generate_content",
        param_builder=lambda prompt, ctx, arts: {
            "content_type": "ad_copy",
            "topic":        prompt,
            "context":      arts.get("messaging", "")[:500],
            "tone":         "persuasive",
        },
        artifact_key="copy_variants",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="content_batch",
        name="Content Batch",
        description="Generate a full batch of posts, ads, and emails for multiple channels.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Create a CONTENT BATCH for the campaign: \"{prompt}\"\n\n"
            f"Messaging: {arts.get('messaging', '')[:600]}\n\n"
            f"Generate:\n"
            f"1. 5× Instagram captions (with hashtag sets)\n"
            f"2. 3× Facebook/LinkedIn posts (longer form)\n"
            f"3. 3× Twitter/X posts (≤280 chars)\n"
            f"4. 2× Email subject lines (with preview text)\n"
            f"5. 1× Google Ads headline set (3 headlines + 2 descriptions)\n"
            f"6. 1× TikTok/Reel hook (first 3 seconds script)\n\n"
            f"Clearly label each format."
        ),
        artifact_key="content_batch",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="channel_strategy",
        name="Channel Strategy",
        description="Build the channel plan, budget allocation, and KPI framework.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"For the campaign \"{prompt}\" targeting:\n{arts.get('audience', '')[:500]}\n\n"
            f"Create a CHANNEL STRATEGY:\n"
            f"- Recommended channel mix (with % budget split)\n"
            f"- Posting frequency per channel\n"
            f"- Content format priority per channel\n"
            f"- KPIs to track (per channel)\n"
            f"- 30-day launch calendar overview\n"
            f"- Budget recommendation breakdown (if budget = $1,000/month)\n"
            f"Format as a clear, actionable plan."
        ),
        artifact_key="channel_strategy",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_campaign_images",
        name="Generate Campaign Visuals",
        description="Generate AI ad creatives and social images using OpenAI Images.",
        tool_name="generate_image_ext",
        param_builder=lambda prompt, ctx, arts: {
            "prompt": (
                f"Professional advertising creative for campaign: {prompt}. "
                f"Style: {arts.get('messaging', '')[:200]}. "
                f"Clean, modern, high-impact social media visual."
            ),
            "count": 3,
            "size": "1024x1024",
            "filename_prefix": "campaign_visual",
        },
        artifact_key="campaign_visuals",
        extract_result=_data_from_result,
    ),
]

MARKETING_PIPELINE = Pipeline(
    pipeline_id="marketing",
    name="Marketing Campaign",
    description="Full campaign build: audience analysis → messaging → copy variants → content batch → channel plan → AI visuals.",
    domain="marketing",
    steps=_MARKETING_STEPS,
    output_schema={
        "audience":         "Detailed buyer personas with psychographic depth",
        "messaging":        "Value propositions, messaging pillars, tone of voice",
        "copy_variants":    "A/B-testable ad copy and headline variants",
        "content_batch":    "Full content set across Instagram, LinkedIn, Twitter, Email, Ads",
        "channel_strategy": "Channel mix, budget split, KPIs, 30-day calendar",
        "campaign_visuals": "AI-generated ad creative images (OpenAI Images result)",
    },
    required_tools=["research_and_prepare_brief", "chat", "generate_content", "generate_image_ext"],
    next_action_templates=[
        "Upload content to scheduling tool",
        "Download campaign visuals",
        "Set up campaign in ad manager",
        "A/B test the copy variants",
        "Track KPIs in analytics dashboard",
    ],
)


# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_RESEARCH_STEPS: List[PipelineStep] = [

    PipelineStep(
        step_id="define_query",
        name="Define Research Query",
        description="Decompose the user's question into precise sub-queries.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"You are a research specialist. Decompose this research request into actionable queries:\n\n"
            f"\"{prompt}\"\n\n"
            f"Output:\n"
            f"1. Primary research question (precise, answerable)\n"
            f"2. 3-5 specific sub-questions to investigate\n"
            f"3. Key terms and synonyms to search\n"
            f"4. Expected source types (academic, news, company data, expert opinion)\n"
            f"5. Success criteria: what a 'complete' answer looks like"
        ),
        artifact_key="research_query",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="web_search",
        name="Web Search",
        description="Perform real web search using SerpAPI or DuckDuckGo for current data.",
        tool_name="web_search_ext",
        param_builder=lambda prompt, ctx, arts: {
            "query":       f"{prompt} {arts.get('research_query', '')[:100]}",
            "max_results": 10,
        },
        artifact_key="web_results",
        extract_result=_data_from_result,
    ),

    PipelineStep(
        step_id="multi_source_research",
        name="Deep Multi-Source Research",
        description="Search multiple sources, scrape key pages, and synthesise initial findings.",
        tool_name="deep_research",
        param_builder=lambda prompt, ctx, arts: {
            "query":        prompt,
            "max_sources":  8,
        },
        artifact_key="raw_research",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="summarize_findings",
        name="Summarise Findings",
        description="Distil the raw research into a clear, structured summary.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"You have conducted research on: \"{prompt}\"\n\n"
            f"Research query context:\n{arts.get('research_query', '')[:600]}\n\n"
            f"Web search results:\n{_format_web_results(arts.get('web_results'))}\n\n"
            f"Deep research data:\n{arts.get('raw_research', '')[:2000]}\n\n"
            f"Write a RESEARCH SUMMARY:\n"
            f"- Executive summary (3-5 sentences)\n"
            f"- Key findings (bulleted, ordered by importance)\n"
            f"- Conflicting evidence or gaps found\n"
            f"- Confidence level (Low/Medium/High) with rationale\n"
            f"Be factual. Cite source types where possible."
        ),
        artifact_key="summary",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="extract_insights",
        name="Extract Insights",
        description="Identify non-obvious patterns, implications, and opportunities.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Based on this research summary:\n\n{arts.get('summary', '')[:2000]}\n\n"
            f"Extract STRATEGIC INSIGHTS:\n"
            f"1. Non-obvious patterns or connections\n"
            f"2. What this means for the user (implications)\n"
            f"3. Opportunities or risks identified\n"
            f"4. What experts in this field are NOT saying (gaps)\n"
            f"5. Second-order effects to consider\n"
            f"Be analytical and specific."
        ),
        artifact_key="insights",
        extract_result=_text_from_result,
    ),

    PipelineStep(
        step_id="generate_actionable_output",
        name="Generate Actionable Output",
        description="Convert research into concrete recommendations and next steps.",
        tool_name="chat",
        param_builder=lambda prompt, ctx, arts: _chat_params(
            f"Research topic: \"{prompt}\"\n\n"
            f"Insights: {arts.get('insights', '')[:1000]}\n\n"
            f"Create an ACTIONABLE RESEARCH REPORT:\n"
            f"- TL;DR (2 sentences)\n"
            f"- 3-5 concrete recommendations (ranked by impact)\n"
            f"- Each recommendation: action + rationale + effort (Low/Med/High)\n"
            f"- Resources / further reading (3-5 specific suggestions)\n"
            f"- 30-60-90 day action plan\n"
            f"Make it directly usable without further research."
        ),
        artifact_key="action_report",
        extract_result=_text_from_result,
    ),
]

RESEARCH_PIPELINE = Pipeline(
    pipeline_id="research",
    name="Research Report",
    description="Structured research: query decomposition → web search → deep multi-source research → findings → insights → action plan.",
    domain="research",
    steps=_RESEARCH_STEPS,
    output_schema={
        "research_query": "Precise sub-questions and search terms",
        "web_results":    "Real-time web search results (SerpAPI / DuckDuckGo)",
        "raw_research":   "Deep multi-source research data and citations",
        "summary":        "Distilled findings with confidence level",
        "insights":       "Non-obvious patterns, implications, gaps",
        "action_report":  "TL;DR, ranked recommendations, 90-day plan",
    },
    required_tools=["chat", "web_search_ext", "deep_research"],
    next_action_templates=[
        "Export report as PDF",
        "Share findings with team",
        "Schedule follow-up research in 30 days",
        "Implement the top recommendation",
    ],
)


# ─── Pipeline Registry ────────────────────────────────────────────────────────

PIPELINES: Dict[str, Pipeline] = {
    "video":     VIDEO_PIPELINE,
    "music":     MUSIC_PIPELINE,
    "app":       APP_PIPELINE,
    "marketing": MARKETING_PIPELINE,
    "research":  RESEARCH_PIPELINE,
}


def list_pipelines() -> List[Dict[str, Any]]:
    """Return summary list of all pipelines for the frontend."""
    return [p.to_dict() for p in PIPELINES.values()]


def get_pipeline(pipeline_id: str) -> Optional[Pipeline]:
    return PIPELINES.get(pipeline_id)


# ─── Pipeline Runner ──────────────────────────────────────────────────────────

async def run_pipeline(
    pipeline_id: str,
    prompt: str,
    db: Any,              # AsyncSession
    settings_row: Any,    # UserSettings ORM row
    active_modes: Optional[List[str]] = None,
    profile_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> PipelineResult:
    """
    Execute a named pipeline step-by-step through execution_guard.

    Each step:
      1. Builds parameters via the step's param_builder.
      2. Calls guarded_execute → capability check, policy, approval gate,
         audit chain, rollback on failure.
      3. If a step requires approval → pauses and returns partial result.
      4. Extracts the artifact from the tool result.
      5. Advances the linked Mission checkpoint.

    The Mission tracks overall progress so callers / the missions API
    can query status independently.
    """
    from app.services.execution_guard import (
        guarded_execute,
        OUTCOME_APPROVAL_REQUIRED,
        OUTCOME_BLOCKED,
        OUTCOME_FAILED_NONRETRYABLE,
        OUTCOME_ROLLED_BACK,
        OUTCOME_ROLLBACK_FAILED,
    )
    from app.services.mission_service import (
        create_mission,
        start_mission,
        advance_step,
        cancel_mission,
        MISSION_STATUS_COMPLETED,
        MISSION_STATUS_FAILED,
    )

    pipeline = PIPELINES.get(pipeline_id)
    if pipeline is None:
        return PipelineResult(
            pipeline=pipeline_id,
            pipeline_name=pipeline_id,
            status="failed",
            steps_completed=[],
            artifacts={},
            next_actions=[],
            error=f"Unknown pipeline '{pipeline_id}'.",
        )

    ctx = context or {}
    artifacts: Dict[str, Any] = {}
    steps_completed: List[Dict[str, Any]] = []
    any_simulation = False

    # ── Create a Mission to track progress ───────────────────────────────────
    mission_id: Optional[int] = None
    try:
        mission = await create_mission(
            db,
            title=f"[Pipeline] {pipeline.name}: {prompt[:80]}",
            goal=f"Execute {pipeline.name} pipeline: {pipeline.description}",
            total_steps=len(pipeline.steps),
        )
        await db.commit()
        mission_id = mission.id
        await start_mission(db, mission_id)
        await db.commit()
    except Exception as _me:
        log.warning("[pipeline] Mission creation failed (non-fatal): %s", _me)

    # ── Execute steps ─────────────────────────────────────────────────────────
    for step_idx, step in enumerate(pipeline.steps):
        log.info(
            "[pipeline:%s] step %d/%d → %s (tool=%s)",
            pipeline_id, step_idx + 1, len(pipeline.steps), step.step_id, step.tool_name,
        )

        # Build params
        try:
            params = step.param_builder(prompt, ctx, artifacts)
        except Exception as pb_exc:
            log.error("[pipeline:%s] param_builder failed for %s: %s", pipeline_id, step.step_id, pb_exc)
            params = {}

        # Label for audit/logs
        step_command = f"[pipeline:{pipeline_id}:{step.step_id}] {step.name}"

        # Execute through the guard
        try:
            guard_result = await guarded_execute(
                tool_name=step.tool_name,
                params=params,
                command=step_command,
                db=db,
                settings_row=settings_row,
                execution_context={
                    "pipeline_id":    pipeline_id,
                    "step_id":        step.step_id,
                    "mission_id":     mission_id,
                    "executor_type":  "pipeline",
                    "profile_id":     profile_id,
                    "active_modes":   active_modes or [],
                },
                caller="pipeline",
            )
        except Exception as ge_exc:
            log.error("[pipeline:%s] guarded_execute failed for %s: %s", pipeline_id, step.step_id, ge_exc)
            steps_completed.append({
                "step_id":   step.step_id,
                "name":      step.name,
                "status":    "failed",
                "error":     str(ge_exc),
                "simulation": step.simulation_mode,
            })
            # Fail mission
            try:
                if mission_id:
                    await advance_step(db, mission_id)
                    await db.commit()
            except Exception:
                pass
            return PipelineResult(
                pipeline=pipeline_id,
                pipeline_name=pipeline.name,
                status="failed",
                steps_completed=steps_completed,
                artifacts=artifacts,
                next_actions=[],
                mission_id=mission_id,
                error=f"Step '{step.step_id}' raised: {ge_exc}",
                simulation=any_simulation,
            )

        # ── Handle approval pause ─────────────────────────────────────────
        if guard_result.needs_approval:
            steps_completed.append({
                "step_id":    step.step_id,
                "name":       step.name,
                "status":     "approval_required",
                "approval_id": guard_result.approval_id,
                "simulation": step.simulation_mode,
            })
            log.info("[pipeline:%s] paused at step %s – approval %s required",
                     pipeline_id, step.step_id, guard_result.approval_id)
            return PipelineResult(
                pipeline=pipeline_id,
                pipeline_name=pipeline.name,
                status="paused_for_approval",
                steps_completed=steps_completed,
                artifacts=artifacts,
                next_actions=[f"Approve step '{step.name}' to continue the pipeline."],
                mission_id=mission_id,
                approval_id=guard_result.approval_id,
                simulation=any_simulation,
            )

        # ── Handle hard block ─────────────────────────────────────────────
        if guard_result.blocked:
            steps_completed.append({
                "step_id": step.step_id,
                "name":    step.name,
                "status":  "blocked",
                "reason":  guard_result.policy_reason,
                "simulation": step.simulation_mode,
            })
            try:
                if mission_id:
                    await advance_step(db, mission_id)
                    await db.commit()
            except Exception:
                pass
            return PipelineResult(
                pipeline=pipeline_id,
                pipeline_name=pipeline.name,
                status="failed",
                steps_completed=steps_completed,
                artifacts=artifacts,
                next_actions=[],
                mission_id=mission_id,
                error=f"Step '{step.step_id}' blocked: {guard_result.policy_reason}",
                simulation=any_simulation,
            )

        # ── Handle terminal failures ──────────────────────────────────────
        if guard_result.outcome in (OUTCOME_FAILED_NONRETRYABLE, OUTCOME_ROLLED_BACK, OUTCOME_ROLLBACK_FAILED):
            # For simulation-marked steps, produce a stub artifact and continue
            if step.simulation_mode:
                log.info("[pipeline:%s] step %s failed but simulation_mode=True – using stub",
                         pipeline_id, step.step_id)
                stub_artifact = _simulation_stub(pipeline_id, step.step_id, prompt)
                artifacts[step.artifact_key] = stub_artifact
                any_simulation = True
                steps_completed.append({
                    "step_id":    step.step_id,
                    "name":       step.name,
                    "status":     "simulated",
                    "simulation": True,
                    "artifact":   step.artifact_key,
                })
                try:
                    if mission_id:
                        await advance_step(db, mission_id)
                        await db.commit()
                except Exception:
                    pass
                continue

            steps_completed.append({
                "step_id":   step.step_id,
                "name":      step.name,
                "status":    "failed",
                "outcome":   guard_result.outcome,
                "simulation": step.simulation_mode,
            })
            try:
                if mission_id:
                    await advance_step(db, mission_id)
                    await db.commit()
            except Exception:
                pass
            return PipelineResult(
                pipeline=pipeline_id,
                pipeline_name=pipeline.name,
                status="failed",
                steps_completed=steps_completed,
                artifacts=artifacts,
                next_actions=[],
                mission_id=mission_id,
                error=f"Step '{step.step_id}' failed: {guard_result.outcome}",
                simulation=any_simulation,
            )

        # ── SUCCESS: extract artifact ─────────────────────────────────────
        try:
            artifact_value = step.extract_result(guard_result.tool_result)
        except Exception as ext_exc:
            log.warning("[pipeline:%s] artifact extract failed for %s: %s",
                        pipeline_id, step.step_id, ext_exc)
            artifact_value = _text_from_result(guard_result.tool_result)

        artifacts[step.artifact_key] = artifact_value

        # Detect simulation from the tool result data (external tools set data["simulation"])
        if step.simulation_mode:
            any_simulation = True
        elif isinstance(artifact_value, dict) and artifact_value.get("simulation"):
            any_simulation = True
            log.info("[pipeline:%s] step %s returned simulation=True (no API key)", pipeline_id, step.step_id)

        steps_completed.append({
            "step_id":    step.step_id,
            "name":       step.name,
            "status":     "completed",
            "simulation": step.simulation_mode,
            "artifact":   step.artifact_key,
        })

        try:
            if mission_id:
                await advance_step(db, mission_id)
                await db.commit()
        except Exception as ms_exc:
            log.warning("[pipeline:%s] mission advance failed: %s", pipeline_id, ms_exc)

    # ── Build next actions ────────────────────────────────────────────────────
    next_actions = [
        t.replace("{platform}", ctx.get("platform", "your platform"))
        for t in pipeline.next_action_templates
    ]

    log.info("[pipeline:%s] completed %d/%d steps", pipeline_id, len(steps_completed), len(pipeline.steps))

    return PipelineResult(
        pipeline=pipeline_id,
        pipeline_name=pipeline.name,
        status="completed",
        steps_completed=steps_completed,
        artifacts=artifacts,
        next_actions=next_actions,
        mission_id=mission_id,
        simulation=any_simulation,
    )


# ─── Simulation stubs ─────────────────────────────────────────────────────────

def _simulation_stub(pipeline_id: str, step_id: str, prompt: str) -> Dict[str, Any]:
    """
    Return a clearly-marked simulation stub when a real integration is unavailable.
    These stubs are transparent about being simulations — they never fabricate
    external execution results.
    """
    ts = datetime.datetime.utcnow().isoformat()
    return {
        "simulation":  True,
        "step_id":     step_id,
        "pipeline_id": pipeline_id,
        "note":        (
            f"⚠ SIMULATION: This step requires an external API key that is not "
            f"currently configured. To enable real execution, add the required "
            f"API key to your .env file. Prompt: '{prompt[:80]}'"
        ),
        "generated_at": ts,
        "status":        "ready_for_integration",
    }
