"""
Tool registry – single source of truth for all available tools.

Importing this module is all that is needed to make tools available
to the command router.

Plugin auto-discovery
─────────────────────
Any BaseTool subclass placed in  app/tools/plugins/<name>.py  is loaded
automatically at startup.  Class names that start with an underscore (_)
are treated as templates/examples and are skipped.
"""

import importlib
import logging
import pkgutil
from typing import Dict

import app.tools.plugins as _plugins_pkg
from app.tools.base import BaseTool
from app.tools.file_tools import (
    CreateFolderTool,
    CreateFileTool,
    MoveFileTool,
    SortDownloadsTool,
    SearchFilesTool,
)
from app.tools.doc_tools import ReadDocumentTool, SummarizeDocumentTool
from app.tools.presentation_tools import CreatePresentationTool
from app.tools.chart_tools import CreateChartTool
from app.tools.memory_tools import SaveMemoryTool, SearchMemoryTool, ListMemoryTool
from app.tools.self_edit_tools import ReadSelfTool, ListSelfTool, EditSelfTool, RestartBackendTool
from app.tools.research_tools import (
    WebSearchTool,
    SummarizeWebResultsTool,
    CompareResearchResultsTool,
    ResearchAndPrepareBriefTool,
)
from app.tools.scheduler_tools import (
    ScheduleTaskTool,
    ListScheduledTasksTool,
    DeleteScheduledTaskTool,
)
from app.tools.builder_tools import (
    CreateProjectScaffoldTool,
    CreateCodeFileTool,
    UpdateCodeFileTool,
    CreateReadmeTool,
    GenerateFeatureFilesTool,
    ListProjectTreeTool,
    ProposeTerminalCommandsTool,
)
from app.tools.connector_tools import (
    DriveListFilesTool,
    DriveSearchFilesTool,
    DriveGetFileTool,
    GmailListRecentTool,
    GmailGetMessageTool,
    GmailCreateDraftTool,
    GmailSendEmailTool,
    CalendarListEventsTool,
    CalendarCreateEventTool,
    CalendarDeleteEventTool,
)
from app.tools.operator_tools import OPERATOR_TOOLS
from app.tools.browser_tools import BROWSER_TOOLS
from app.tools.safari_tools import SAFARI_TOOLS
from app.tools.chat_tool import ChatTool
from app.tools.creative_tools import (
    BrainstormTool,
    GenerateContentTool,
    ExpandIdeaTool,
    SummarizeForVoiceTool,
)
from app.tools.workflow_tools import (
    SaveCustomWorkflowTool,
    ListCustomWorkflowsTool,
    DeleteCustomWorkflowTool,
)
from app.tools.vision_tool import (
    DescribeImageTool,
    ExtractTextFromImageTool,
    AnalyseImageTool,
)
from app.tools.video_tool import GenerateVideoTool, AnimateImageTool
from app.tools.music_tool import GenerateSongTool, WriteLyricsTool
from app.tools.image_tool import GenerateImageTool, EditImageTool, CreateImageVariationTool
from app.tools.code_execution_tool import (
    RunPythonTool,
    RunJavaScriptTool,
    RunShellCommandTool,
    InstallPackageTool,
    RunTestsTool,
)
from app.tools.deep_research_tool import (
    DeepResearchTool,
    ScrapeUrlTool,
    CompetitorAnalysisTool,
    FactCheckTool,
)
from app.tools.git_tool import (
    GitStatusTool,
    GitDiffTool,
    GitCommitTool,
    GitPushTool,
    GitPullTool,
    GitCloneTool,
    GitLogTool,
    GitCreateBranchTool,
    GitHubCreatePRTool,
)
from app.tools.system_tools import (
    SendNotificationTool,
    GetClipboardTool,
    SetClipboardTool,
    TakeScreenshotTool,
    GetScreenInfoTool,
    ListRunningAppsTool,
    GetBatteryStatusTool,
    GetDiskUsageTool,
    SpeakTextTool,
    SetVolumeTool,
    EmptyTrashTool,
)
from app.tools.pdf_tool import (
    ReadPdfTool,
    ReadDocxTool,
    ReadXlsxTool,
    ReadAnyDocumentTool,
    SummarizeDocumentFileTool,
)
from app.tools.external.voice_generation_tool import GenerateVoiceTool
from app.tools.external.video_generation_tool import GenerateVideoExtTool
from app.tools.external.image_generation_tool import GenerateImageExtTool
from app.tools.external.music_generation_tool import GenerateSongExtTool
from app.tools.external.web_search_tool import WebSearchExtTool

# Future tools can be added here without touching any other file.
_TOOL_LIST: list[BaseTool] = [
    CreateFolderTool(),
    CreateFileTool(),
    MoveFileTool(),
    SortDownloadsTool(),
    SearchFilesTool(),
    ReadDocumentTool(),
    SummarizeDocumentTool(),
    CreatePresentationTool(),
    CreateChartTool(),
    # ── Memory ──
    SaveMemoryTool(),
    SearchMemoryTool(),
    ListMemoryTool(),
    # ── Self-edit (Lani modifies her own code) ──
    ReadSelfTool(),
    ListSelfTool(),
    EditSelfTool(),
    RestartBackendTool(),
    # ── Research / Browser Operator ──
    WebSearchTool(),
    SummarizeWebResultsTool(),
    CompareResearchResultsTool(),
    ResearchAndPrepareBriefTool(),
    # ── Scheduler / Long-running tasks ──
    ScheduleTaskTool(),
    ListScheduledTasksTool(),
    DeleteScheduledTaskTool(),
    # ── Builder / Code Generator ──
    CreateProjectScaffoldTool(),
    CreateCodeFileTool(),
    UpdateCodeFileTool(),
    CreateReadmeTool(),
    GenerateFeatureFilesTool(),
    ListProjectTreeTool(),
    ProposeTerminalCommandsTool(),
    # ── Account Connectors ──
    DriveListFilesTool(),
    DriveSearchFilesTool(),
    DriveGetFileTool(),
    GmailListRecentTool(),
    GmailGetMessageTool(),
    GmailCreateDraftTool(),
    GmailSendEmailTool(),
    CalendarListEventsTool(),
    CalendarCreateEventTool(),
    CalendarDeleteEventTool(),
    # ── Computer Operator ──
    *OPERATOR_TOOLS,
    # ── Browser Automation (Playwright) ──
    *BROWSER_TOOLS,
    # ── Safari Automation (AppleScript – tikros sesijos) ──
    *SAFARI_TOOLS,
    # ── Creative AI ──
    BrainstormTool(),
    GenerateContentTool(),
    ExpandIdeaTool(),
    SummarizeForVoiceTool(),
    # ── Custom Workflows (user-defined) ──
    SaveCustomWorkflowTool(),
    ListCustomWorkflowsTool(),
    DeleteCustomWorkflowTool(),
    # ── Vision / Image analysis (GPT-4o) ──
    DescribeImageTool(),
    ExtractTextFromImageTool(),
    AnalyseImageTool(),
    # ── Video Generation (Runway ML Gen-4 Turbo) ──
    GenerateVideoTool(),
    AnimateImageTool(),
    # ── Music / Song Generation (Suno AI) ──
    GenerateSongTool(),
    WriteLyricsTool(),
    # ── Image Generation (DALL-E 3 / gpt-image-1) ──
    GenerateImageTool(),
    EditImageTool(),
    CreateImageVariationTool(),
    # ── Code Execution Sandbox ──
    RunPythonTool(),
    RunJavaScriptTool(),
    RunShellCommandTool(),
    InstallPackageTool(),
    RunTestsTool(),
    # ── Deep Research (multi-source + LLM synthesis) ──
    DeepResearchTool(),
    ScrapeUrlTool(),
    CompetitorAnalysisTool(),
    FactCheckTool(),
    # ── Git / GitHub ──
    GitStatusTool(),
    GitDiffTool(),
    GitCommitTool(),
    GitPushTool(),
    GitPullTool(),
    GitCloneTool(),
    GitLogTool(),
    GitCreateBranchTool(),
    GitHubCreatePRTool(),
    # ── macOS System Tools ──
    SendNotificationTool(),
    GetClipboardTool(),
    SetClipboardTool(),
    TakeScreenshotTool(),
    GetScreenInfoTool(),
    ListRunningAppsTool(),
    GetBatteryStatusTool(),
    GetDiskUsageTool(),
    SpeakTextTool(),
    SetVolumeTool(),
    EmptyTrashTool(),
    # ── PDF / Document Reading ──
    ReadPdfTool(),
    ReadDocxTool(),
    ReadXlsxTool(),
    ReadAnyDocumentTool(),
    SummarizeDocumentFileTool(),
    # ── External integrations (pipeline execution system) ──
    # These tools have graceful simulation fallback when API keys are absent.
    GenerateVoiceTool(),       # ElevenLabs / OpenAI TTS → simulation
    GenerateVideoExtTool(),    # Runway ML Gen-4 Turbo → simulation
    GenerateImageExtTool(),    # OpenAI gpt-image-1 → simulation
    GenerateSongExtTool(),     # Suno AI → simulation
    WebSearchExtTool(),        # SerpAPI / DuckDuckGo → simulation
    # ── Conversational AI (fallback for all non-computer requests) ──
    ChatTool(),
]

# ── Plugin auto-discovery ──────────────────────────────────────────────────────
_plugin_log = logging.getLogger(__name__)

for _finder, _mod_name, _is_pkg in pkgutil.iter_modules(_plugins_pkg.__path__):
    try:
        _mod = importlib.import_module(f"app.tools.plugins.{_mod_name}")
        for _attr_name, _obj in vars(_mod).items():
            if (
                isinstance(_obj, type)
                and issubclass(_obj, BaseTool)
                and _obj is not BaseTool
                and not _attr_name.startswith("_")
            ):
                _instance = _obj()
                # Avoid duplicate names
                if _instance.name not in {t.name for t in _TOOL_LIST}:
                    _TOOL_LIST.append(_instance)
                    _plugin_log.info("[registry] plugin loaded: %s", _instance.name)
    except Exception as _exc:
        _plugin_log.warning("[registry] failed to load plugin '%s': %s", _mod_name, _exc)

REGISTRY: Dict[str, BaseTool] = {tool.name: tool for tool in _TOOL_LIST}


def get_tool(name: str) -> BaseTool | None:
    """Return the tool with the given name, or None if not registered."""
    return REGISTRY.get(name)


def list_tools() -> list[dict]:
    """Return a description list of all registered tools."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "requires_approval": t.requires_approval,
            "parameters": getattr(t, "parameters", []),
        }
        for t in _TOOL_LIST
    ]
