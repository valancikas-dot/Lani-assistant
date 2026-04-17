/**
 * WorkflowCard
 *
 * Renders a WorkflowResult as a rich card showing:
 *   - Goal banner with overall status badge
 *   - Step-by-step list with status icons and per-step artifacts
 *   - Flat artifact chips at the bottom (file, email draft, presentation, etc.)
 *   - Approval gate notice when overall_status === "approval_required"
 *   - Plain-text summary footer
 *
 * Layout
 * ──────
 *   ┌────────────────────────────────────────────────────────┐
 *   │ 🔀  Goal: "research ML trends and create a slides"      │
 *   │     [completed]                                         │
 *   ├────────────────────────────────────────────────────────┤
 *   │  ① ✔  Research: ML trends          [completed]          │
 *   │  ② ✔  Summarize research           [completed]  📄      │
 *   │  ③ ✔  Create presentation          [completed]  📊      │
 *   │  ④ ✔  Open presentation            [completed]          │
 *   ├────────────────────────────────────────────────────────┤
 *   │  Artifacts: 📊 ML Trends Overview.pptx                  │
 *   ├────────────────────────────────────────────────────────┤
 *   │  Workflow complete: 4/4 steps succeeded.                │
 *   └────────────────────────────────────────────────────────┘
 */

import React, { useState } from "react";
import type { WorkflowResult, WorkflowArtifact, WorkflowArtifactType, WorkflowStepSummary } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

// ─── Status helpers ───────────────────────────────────────────────────────────

const STEP_STATUS_ICON: Record<string, string> = {
  pending:           "○",
  running:           "◌",
  completed:         "✔",
  failed:            "✖",
  approval_required: "⏸",
  skipped:           "–",
};

const OVERALL_STATUS_CLASS: Record<string, string> = {
  completed:          "wf-badge wf-badge--success",
  failed:             "wf-badge wf-badge--error",
  approval_required:  "wf-badge wf-badge--warn",
  partial:            "wf-badge wf-badge--partial",
};

const ARTIFACT_ICON: Record<WorkflowArtifactType, string> = {
  file:             "📄",
  email_draft:      "📧",
  presentation:     "📊",
  url_list:         "🔗",
  text_summary:     "📝",
  calendar_event:   "📅",
  project_scaffold: "🗂",
  comparison:       "⚖",
  drive_file:       "☁",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function ArtifactChip({ artifact }: { artifact: WorkflowArtifact }) {
  const icon = ARTIFACT_ICON[artifact.type] ?? "📎";
  const label = artifact.name;
  const href = artifact.url ?? (artifact.path ? `file://${artifact.path}` : undefined);

  if (href) {
    return (
      <a
        className="wf-artifact-chip"
        href={href}
        target="_blank"
        rel="noreferrer"
        title={artifact.content ?? label}
      >
        <span className="wf-artifact-chip__icon">{icon}</span>
        <span className="wf-artifact-chip__name">{label}</span>
      </a>
    );
  }

  return (
    <span className="wf-artifact-chip" title={artifact.content ?? label}>
      <span className="wf-artifact-chip__icon">{icon}</span>
      <span className="wf-artifact-chip__name">{label}</span>
    </span>
  );
}

function StepRow({ step }: { step: WorkflowStepSummary }) {
  const [expanded, setExpanded] = useState(false);
  const icon = STEP_STATUS_ICON[step.status] ?? "?";
  const hasDetail = Boolean(step.message || step.artifact?.content);

  return (
    <li
      className={`wf-step wf-step--${step.status}`}
      onClick={() => hasDetail && setExpanded((v) => !v)}
      style={{ cursor: hasDetail ? "pointer" : "default" }}
    >
      <span className="wf-step__index">{step.index + 1}</span>
      <span className={`wf-step__icon wf-step__icon--${step.status}`}>{icon}</span>
      <span className="wf-step__description">{step.description}</span>
      {step.artifact && (
        <span
          className="wf-step__artifact-badge"
          title={step.artifact.name}
        >
          {ARTIFACT_ICON[step.artifact.type] ?? "📎"}
        </span>
      )}
      {hasDetail && (
        <span className="wf-step__expand-toggle">{expanded ? "▲" : "▼"}</span>
      )}
      {expanded && (
        <div className="wf-step__detail">
          {step.message && <p className="wf-step__message">{step.message}</p>}
          {step.artifact?.content && (
            <pre className="wf-step__content-preview">
              {step.artifact.content.slice(0, 300)}
              {step.artifact.content.length > 300 && "…"}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface WorkflowCardProps {
  result: WorkflowResult;
}

export function WorkflowCard({ result }: WorkflowCardProps) {
  const { t } = useI18n();
  const [showAllArtifacts, setShowAllArtifacts] = useState(false);

  const overallBadgeClass =
    OVERALL_STATUS_CLASS[result.overall_status] ?? "wf-badge wf-badge--muted";

  const overallLabel = (() => {
    switch (result.overall_status) {
      case "completed":         return t("workflow", "status_completed");
      case "failed":            return t("workflow", "status_failed");
      case "partial":           return t("workflow", "status_partial");
      case "approval_required": return t("workflow", "status_approval_required");
      default:                  return result.overall_status;
    }
  })();

  const visibleArtifacts = showAllArtifacts
    ? result.artifacts
    : result.artifacts.slice(0, 4);

  return (
    <div className="workflow-card">
      {/* ── Goal banner ── */}
      <div className="workflow-card__header">
        <span className="workflow-card__goal-icon">🔀</span>
        <span className="workflow-card__goal-text">{result.goal}</span>
        <span className={overallBadgeClass}>{overallLabel}</span>
      </div>

      {/* ── Approval notice ── */}
      {result.requires_approval && (
        <div className="workflow-card__approval-notice">
          ⚠ {t("workflow", "approval_needed")}
          {result.approval_id && (
            <span className="workflow-card__approval-id">
              &nbsp;(#{result.approval_id})
            </span>
          )}
        </div>
      )}

      {/* ── Step list ── */}
      {result.steps.length > 0 && (
        <section className="workflow-card__steps">
          <h4 className="workflow-card__section-title">{t("workflow", "steps")}</h4>
          <ol className="wf-steps-list">
            {result.steps.map((step) => (
              <StepRow key={step.index} step={step} />
            ))}
          </ol>
        </section>
      )}

      {/* ── Artifact chips ── */}
      {result.artifacts.length > 0 && (
        <section className="workflow-card__artifacts">
          <h4 className="workflow-card__section-title">{t("workflow", "artifacts")}</h4>
          <div className="wf-artifact-list">
            {visibleArtifacts.map((art, i) => (
              <ArtifactChip key={i} artifact={art} />
            ))}
            {result.artifacts.length > 4 && !showAllArtifacts && (
              <button
                className="wf-artifact-chip wf-artifact-chip--more"
                onClick={() => setShowAllArtifacts(true)}
              >
                +{result.artifacts.length - 4} more
              </button>
            )}
          </div>
        </section>
      )}

      {result.artifacts.length === 0 && result.overall_status === "completed" && (
        <p className="workflow-card__no-artifacts">{t("workflow", "no_artifacts")}</p>
      )}

      {/* ── Summary footer ── */}
      <div className="workflow-card__footer">
        <span className="workflow-card__summary">{result.message.split("\n")[0]}</span>
      </div>
    </div>
  );
}
