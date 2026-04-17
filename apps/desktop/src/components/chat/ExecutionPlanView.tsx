/**
 * ExecutionPlanView
 *
 * Renders a PlanExecutionResponse as a step-by-step timeline.
 *
 * Layout
 * ──────
 *   ┌─────────────────────────────────────────────────────┐
 *   │ 🎯  Goal: "sort downloads then summarize PDFs"       │
 *   │  overall badge: completed / failed / approval_req…  │
 *   ├─────────────────────────────────────────────────────┤
 *   │  ① ✔  Sort Downloads folder          [completed]    │
 *   │  ② ✔  Summarize discovered documents [completed]    │
 *   │     └─ result / message                             │
 *   └─────────────────────────────────────────────────────┘
 *
 * The component is intentionally self-contained so it can be dropped
 * into any chat bubble without extra context providers.
 */

import React, { useState } from "react";
import type { PlanExecutionResponse, StepResult, StepStatus } from "../../lib/types";

// ─── Status helpers ───────────────────────────────────────────────────────────

const STATUS_ICON: Record<StepStatus, string> = {
  pending:          "○",
  running:          "◌",
  completed:        "✔",
  failed:           "✖",
  approval_required:"⏸",
  skipped:          "–",
};

const STATUS_LABEL: Record<StepStatus, string> = {
  pending:          "pending",
  running:          "running…",
  completed:        "done",
  failed:           "failed",
  approval_required:"needs approval",
  skipped:          "skipped",
};

function overallBadgeClass(status: StepStatus): string {
  switch (status) {
    case "completed":          return "plan-badge plan-badge--success";
    case "failed":             return "plan-badge plan-badge--error";
    case "approval_required":  return "plan-badge plan-badge--warn";
    case "running":            return "plan-badge plan-badge--info";
    default:                   return "plan-badge plan-badge--muted";
  }
}

function stepClass(status: StepStatus): string {
  switch (status) {
    case "completed":         return "plan-step plan-step--done";
    case "failed":            return "plan-step plan-step--failed";
    case "approval_required": return "plan-step plan-step--approval";
    case "running":           return "plan-step plan-step--running";
    case "skipped":           return "plan-step plan-step--skipped";
    default:                  return "plan-step";
  }
}

// ─── Step detail ──────────────────────────────────────────────────────────────

interface StepDetailProps {
  result: StepResult;
}

function StepDetail({ result }: StepDetailProps) {
  const [expanded, setExpanded] = useState(false);

  const hasData = result.data !== undefined && result.data !== null;

  return (
    <div className="plan-step__detail">
      {result.message && (
        <p className="plan-step__message">{result.message}</p>
      )}
      {result.approval_id !== undefined && (
        <p className="plan-step__approval-hint">
          Approval #{result.approval_id} — accept in the Approvals tab to continue.
        </p>
      )}
      {hasData && (
        <button
          className="plan-step__toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? "▾ Hide result" : "▸ Show result"}
        </button>
      )}
      {hasData && expanded && (
        <pre className="plan-step__data">
          {typeof result.data === "string"
            ? result.data
            : JSON.stringify(result.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface ExecutionPlanViewProps {
  response: PlanExecutionResponse;
  /** Called when user clicks "Re-run" on a failed plan (optional). */
  onRetry?: (command: string) => void;
}

export function ExecutionPlanView({ response, onRetry }: ExecutionPlanViewProps) {
  const { plan, step_results, overall_status, message } = response;

  // Build a quick lookup: step_index → StepResult
  const resultByIndex: Record<number, StepResult> = {};
  for (const r of step_results) {
    resultByIndex[r.step_index] = r;
  }

  return (
    <div className="plan-view">
      {/* ── Header ── */}
      <div className="plan-view__header">
        <span className="plan-view__goal-icon" aria-hidden>🎯</span>
        <span className="plan-view__goal">{plan.goal}</span>
        <span className={overallBadgeClass(overall_status)}>
          {STATUS_LABEL[overall_status] ?? overall_status}
        </span>
      </div>

      {/* ── Summary message ── */}
      {message && (
        <p className="plan-view__summary">{message}</p>
      )}

      {/* ── Step list ── */}
      <ol className="plan-view__steps">
        {plan.steps.map((step) => {
          const result = resultByIndex[step.index];
          const displayStatus: StepStatus = result?.status ?? step.status;

          return (
            <li key={step.index} className={stepClass(displayStatus)}>
              <div className="plan-step__header">
                <span
                  className={`plan-step__icon plan-step__icon--${displayStatus}`}
                  aria-label={STATUS_LABEL[displayStatus]}
                >
                  {STATUS_ICON[displayStatus]}
                </span>
                <span className="plan-step__index">{step.index + 1}.</span>
                <span className="plan-step__description">{step.description}</span>
                <span className="plan-step__tool-badge">{step.tool}</span>
              </div>

              {result && <StepDetail result={result} />}
            </li>
          );
        })}
      </ol>

      {/* ── Retry button ── */}
      {overall_status === "failed" && onRetry && (
        <button
          className="plan-view__retry-btn"
          onClick={() => onRetry(plan.goal)}
        >
          ↺ Re-try
        </button>
      )}
    </div>
  );
}

export default ExecutionPlanView;
