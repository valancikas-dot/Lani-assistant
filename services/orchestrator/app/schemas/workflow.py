"""
Workflow schemas – typed contracts for multi-step cross-tool automation.

A *workflow* is a higher-level concept than a plan:
  - It tracks structured artifacts produced at each step.
  - Intermediate outputs (file content, summaries, URLs) flow into subsequent steps.
  - The final response includes a dedicated artifacts list + a human-readable summary.
"""

import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

# ── Artifact types ────────────────────────────────────────────────────────────

WorkflowArtifactType = Literal[
    "file",            # local file created or referenced
    "email_draft",     # Gmail draft created
    "presentation",    # .pptx / slides file
    "url_list",        # list of researched URLs
    "text_summary",    # summarised text content
    "calendar_event",  # calendar event created
    "project_scaffold",# scaffolded project directory
    "comparison",      # comparison table / analysis text
    "drive_file",      # file retrieved from Google Drive
]


class WorkflowArtifact(BaseModel):
    """A structured output produced by a single workflow step."""

    type: WorkflowArtifactType
    name: str                               # human-readable label
    step_index: int                         # which step produced this artifact
    path: Optional[str] = None             # local filesystem path (files, projects)
    url: Optional[str] = None              # remote URL (Drive share link, web URL)
    content: Optional[str] = None         # inline text (summaries, comparison text)
    metadata: Dict[str, Any] = Field(default_factory=dict)  # e.g. {"email_to": "...", "slides": 5}


# ── Request / response ────────────────────────────────────────────────────────

class WorkflowRequest(BaseModel):
    """Body for POST /workflow/run."""

    goal: str
    context: Optional[Dict[str, Any]] = None   # optional caller-supplied hints
    tts_response: bool = False                  # include tts_text in response
    include_context: bool = True                # inject memory context into steps


class WorkflowStepSummary(BaseModel):
    """Compact per-step summary included in WorkflowResult."""

    index: int
    tool: str
    description: str
    status: str                                 # pending | completed | failed | approval_required
    message: Optional[str] = None
    artifact: Optional[WorkflowArtifact] = None  # artifact produced by this step (if any)


class WorkflowResult(BaseModel):
    """Full workflow response returned to the caller."""

    workflow_id: str
    goal: str
    overall_status: str  # completed | failed | approval_required | partial
    steps: List[WorkflowStepSummary]
    artifacts: List[WorkflowArtifact]
    message: str
    tts_text: Optional[str] = None
    memory_hints: List[str] = Field(default_factory=list)
    requires_approval: bool = False
    approval_id: Optional[int] = None
    created_at: str = Field(
        default_factory=_utcnow_iso
    )
