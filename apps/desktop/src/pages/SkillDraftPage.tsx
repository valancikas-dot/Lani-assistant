/**
 * SkillDraftPage – Phase 7: Proposal → Skill Scaffold Generator
 *
 * Displays all skill drafts.  Each draft shows:
 *   • Spec summary (name, description, steps, required tools, risk)
 *   • Scaffold preview (JSON workflow structure)
 *   • Sandbox test results (errors / warnings)
 *   • Action buttons: Test → Approve → Request Install | Discard
 *
 * Safety
 * ──────
 * • "Test" runs a structural sandbox check — nothing is executed.
 * • "Request Install" creates an ApprovalRequest only; nothing auto-runs.
 * • Discard sets status=discarded (record kept for audit).
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  listSkillDrafts,
  testSkillDraft,
  approveSkillDraft,
  installSkillDraft,
  discardSkillDraft,
  finalizeSkillInstall,
} from "../lib/api";
import type {
  SkillDraft,
  SkillDraftStatus,
  SandboxTestReport,
  SandboxIssue,
} from "../lib/types";

// ─── Risk badge ───────────────────────────────────────────────────────────────

const RISK_CLASSES: Record<string, string> = {
  low:      "risk-badge risk-badge--low",
  medium:   "risk-badge risk-badge--medium",
  high:     "risk-badge risk-badge--high",
  critical: "risk-badge risk-badge--critical",
};

const RiskBadge: React.FC<{ level: string }> = ({ level }) => (
  <span className={RISK_CLASSES[level] ?? "risk-badge risk-badge--unknown"}>
    {level}
  </span>
);

// ─── Draft status badge ───────────────────────────────────────────────────────

const STATUS_CLASSES: Record<SkillDraftStatus, string> = {
  draft:             "status-badge status-badge--proposed",
  tested:            "status-badge status-badge--info",
  approved:          "status-badge status-badge--approved",
  install_requested: "status-badge status-badge--warning",
  installed:         "status-badge status-badge--success",
  discarded:         "status-badge status-badge--rejected",
};

const STATUS_LABELS: Record<SkillDraftStatus, string> = {
  draft:             "Draft",
  tested:            "Tested",
  approved:          "Approved",
  install_requested: "Install Requested",
  installed:         "Installed",
  discarded:         "Discarded",
};

const DraftStatusBadge: React.FC<{ status: SkillDraftStatus }> = ({ status }) => (
  <span className={STATUS_CLASSES[status] ?? "status-badge"}>
    {STATUS_LABELS[status] ?? status}
  </span>
);

// ─── Sandbox issue list ───────────────────────────────────────────────────────

const ISSUE_ICON: Record<string, string> = {
  error:   "🔴",
  warning: "🟡",
  info:    "🔵",
};

const IssueList: React.FC<{ report: SandboxTestReport }> = ({ report }) => (
  <div className="sandbox-report">
    <div
      className={`sandbox-report__summary ${
        report.passed ? "sandbox-report__summary--pass" : "sandbox-report__summary--fail"
      }`}
    >
      {report.passed ? "✅ Passed" : "❌ Failed"} — {report.summary}
    </div>
    {report.issues.length > 0 && (
      <ul className="sandbox-report__issue-list">
        {report.issues.map((issue: SandboxIssue, i: number) => (
          <li key={i} className={`sandbox-report__issue sandbox-report__issue--${issue.severity}`}>
            <span className="sandbox-report__issue-icon">{ISSUE_ICON[issue.severity] ?? "ℹ"}</span>
            <span className="sandbox-report__issue-location">
              <code>{issue.location}</code>
            </span>
            <span className="sandbox-report__issue-message">{issue.message}</span>
            {issue.suggestion && (
              <span className="sandbox-report__issue-suggestion">
                💡 {issue.suggestion}
              </span>
            )}
          </li>
        ))}
      </ul>
    )}
  </div>
);

// ─── JSON preview ─────────────────────────────────────────────────────────────

const JsonPreview: React.FC<{ data: unknown; label: string }> = ({ data, label }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="json-preview">
      <button
        className="btn btn--ghost btn--xs json-preview__toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? "▲ Hide" : "▼ Show"} {label}
      </button>
      {open && (
        <pre className="json-preview__content">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
};

// ─── Draft Card ───────────────────────────────────────────────────────────────

const DraftCard: React.FC<{
  draft: SkillDraft;
  onTest: (id: number) => void;
  onApprove: (id: number) => void;
  onInstall: (id: number) => void;
  onFinalize: (id: number) => void;
  onDiscard: (id: number) => void;
  isBusy: boolean;
}> = ({ draft, onTest, onApprove, onInstall, onFinalize, onDiscard, isBusy }) => {
  const spec = draft.spec_json;
  const scaffold = draft.scaffold_json as Record<string, unknown>;
  const meta = scaffold?.metadata as Record<string, unknown> | undefined;

  const isDiscarded = draft.status === "discarded";
  const isInstalled = draft.status === "installed";

  return (
    <div
      className={[
        "skill-card",
        `skill-card--${draft.status}`,
        isDiscarded ? "skill-card--dismissed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* Header */}
      <div className="skill-card__header">
        <div className="skill-card__title-row">
          <span className="skill-card__title">{draft.name}</span>
          <DraftStatusBadge status={draft.status} />
          <RiskBadge level={draft.risk_level} />
        </div>
        <div className="skill-card__meta">
          <span className="skill-card__meta-item">
            📋 Proposal #{draft.proposal_id}
          </span>
          {spec?.required_tools && spec.required_tools.length > 0 && (
            <span className="skill-card__meta-item">
              🔧 Tools: {spec.required_tools.join(", ")}
            </span>
          )}
          {meta?.estimated_time_saved != null && (
            <span className="skill-card__meta-item">
              ⏱ Saves ~{String(meta.estimated_time_saved as string)}
            </span>
          )}
          {draft.tested_at && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Tested {new Date(draft.tested_at).toLocaleString()}
            </span>
          )}
          {draft.created_at && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Created {new Date(draft.created_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      {draft.description && (
        <p className="skill-card__description">{draft.description}</p>
      )}

      {/* Spec steps */}
      {spec?.steps && Array.isArray(spec.steps) && spec.steps.length > 0 && (
        <div className="skill-card__steps">
          <h4 className="skill-card__section-label">Generated steps</h4>
          <ol className="skill-card__step-list">
            {spec.steps.map((step, i) => (
              <li key={i} className="skill-card__step">
                <code className="skill-card__step-tool">{step.tool_name}</code>
                {" — "}
                <span className="skill-card__step-cmd">
                  {step.command_template}
                </span>
                {!step.is_required && (
                  <span className="skill-card__step-optional">(optional)</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* I/O summary */}
      {spec && (
        <div className="skill-card__io">
          {spec.expected_inputs && spec.expected_inputs.length > 0 && (
            <div className="skill-card__io-row">
              <span className="skill-card__io-label">Inputs:</span>
              <span className="skill-card__io-values">
                {spec.expected_inputs.join(", ")}
              </span>
            </div>
          )}
          {spec.expected_outputs && spec.expected_outputs.length > 0 && (
            <div className="skill-card__io-row">
              <span className="skill-card__io-label">Outputs:</span>
              <span className="skill-card__io-values">
                {spec.expected_outputs.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Scaffold JSON preview */}
      <JsonPreview data={scaffold} label="scaffold JSON" />

      {/* Sandbox test report */}
      {draft.test_report && <IssueList report={draft.test_report} />}

      {/* Safety note */}
      <p className="skill-card__safe-note">
        🔒 Scaffold preview only — nothing executes until you approve and grant
        the install request.
      </p>

      {/* Actions */}
      {!isDiscarded && !isInstalled && (
        <div className="skill-card__actions">
          {/* Test — always available while not installed/discarded */}
          {["draft", "tested"].includes(draft.status) && (
            <button
              className="btn btn--secondary btn--sm"
              disabled={isBusy}
              onClick={() => onTest(draft.id)}
              title="Run sandbox validation — does not execute anything"
            >
              {isBusy ? "Testing…" : "🔬 Run Test"}
            </button>
          )}

          {/* Approve — only after passing test */}
          {draft.status === "tested" &&
            draft.test_report?.passed === true && (
              <button
                className="btn btn--primary btn--sm"
                disabled={isBusy}
                onClick={() => onApprove(draft.id)}
                title="Mark as reviewed and approved for installation"
              >
                ✓ Approve
              </button>
            )}

          {/* Request Install — only after approval */}
          {draft.status === "approved" && (
            <button
              className="btn btn--primary btn--sm"
              disabled={isBusy}
              onClick={() => onInstall(draft.id)}
              title="Create an install request — nothing executes automatically"
            >
              📦 Request Install
            </button>
          )}

          {/* Finalize Install — only when install was requested and is now approved */}
          {draft.status === "install_requested" && (
            <button
              className="btn btn--primary btn--sm"
              disabled={isBusy}
              onClick={() => onFinalize(draft.id)}
              title="Finalize installation once the ApprovalRequest has been approved"
            >
              ✅ Finalize Install
            </button>
          )}

          {/* Discard */}
          <button
            className="btn btn--ghost btn--xs skill-card__dismiss-btn"
            disabled={isBusy}
            title="Discard this draft (keeps record for audit)"
            onClick={() => onDiscard(draft.id)}
          >
            ✖ Discard
          </button>
        </div>
      )}

      {/* Install-requested status note */}
      {draft.status === "install_requested" && draft.approval_request_id && (
        <div className="skill-card__install-note">
          ⏳ Waiting for approval — ApprovalRequest #{draft.approval_request_id}{" "}
          has been created. Go to{" "}
          <a href="/approvals" className="skill-card__chain-link">
            Approvals
          </a>{" "}
          to grant it, then click <strong>"Finalize Install"</strong> above.
        </div>
      )}

      {/* Installed note */}
      {isInstalled && (
        <div className="skill-card__install-note skill-card__install-note--success">
          ✅ Installed.{" "}
          <a href="/installed-skills" className="skill-card__chain-link">
            View in Registry →
          </a>
        </div>
      )}
    </div>
  );
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export const SkillDraftPage: React.FC = () => {
  const [drafts, setDrafts] = useState<SkillDraft[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listSkillDrafts();
      setDrafts(res.drafts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load drafts");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleTest = async (id: number) => {
    setBusyId(id);
    setMessage(null);
    try {
      const res = await testSkillDraft(id);
      setDrafts((prev) => prev.map((d) => (d.id === id ? res.draft : d)));
      setMessage(
        res.report.passed
          ? `✅ Draft #${id} passed sandbox test.`
          : `❌ Draft #${id} failed sandbox test — review issues below.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleApprove = async (id: number) => {
    setBusyId(id);
    setMessage(null);
    try {
      const res = await approveSkillDraft(id);
      setDrafts((prev) => prev.map((d) => (d.id === id ? res.draft : d)));
      setMessage(`✅ Draft #${id} approved. You can now request installation.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleInstall = async (id: number) => {
    setBusyId(id);
    setMessage(null);
    try {
      const res = await installSkillDraft(id);
      setDrafts((prev) => prev.map((d) => (d.id === id ? res.draft : d)));
      setMessage(
        `📦 Install request created for draft #${id}. ` +
          "Check Approvals to grant it, then click Finalize Install.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install request failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleFinalize = async (id: number) => {
    setBusyId(id);
    setMessage(null);
    try {
      const res = await finalizeSkillInstall(id);
      setDrafts((prev) => prev.map((d) => (d.id === id ? res.draft : d)));
      setMessage(
        `✅ Draft #${id} finalized! Skill "${res.skill.name}" v${res.skill.current_version} ` +
          "is now in the Installed Skills registry.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Finalize failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleDiscard = async (id: number) => {
    setBusyId(id);
    setMessage(null);
    try {
      const res = await discardSkillDraft(id);
      setDrafts((prev) => prev.map((d) => (d.id === id ? res.draft : d)));
      setMessage(`Draft #${id} discarded.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discard failed");
    } finally {
      setBusyId(null);
    }
  };

  const activeDrafts = drafts.filter((d) => d.status !== "discarded");
  const discardedDrafts = drafts.filter((d) => d.status === "discarded");

  return (
    <div className="page skill-drafts-page">
      {/* Header */}
      <div className="page__header">
        <h1>
          Skill Drafts
          {activeDrafts.length > 0 && (
            <span className="page__badge">{activeDrafts.length}</span>
          )}
        </h1>
        <p className="page__subtitle">
          Generated automation drafts from approved skill proposals. Each draft
          is a non-executing scaffold that must be reviewed, tested, and
          approved before any install request is created.
        </p>
      </div>

      {/* Toolbar */}
      <div className="skill-proposals-page__toolbar">
        <div className="skill-proposals-page__actions">
          <button
            className="btn btn--secondary btn--sm"
            onClick={() => void load()}
            disabled={isLoading}
          >
            ↺ Refresh
          </button>
          <a
            href="/skill-proposals"
            className="btn btn--ghost btn--sm"
          >
            ← Back to Proposals
          </a>
        </div>
      </div>

      {/* Messages */}
      {message && (
        <div className="skill-proposals-page__message skill-proposals-page__message--ok">
          {message}
        </div>
      )}
      {error && (
        <div className="skill-proposals-page__message skill-proposals-page__message--error">
          {error}
        </div>
      )}

      {/* Content */}
      {isLoading && drafts.length === 0 ? (
        <p className="page__loading">Loading skill drafts…</p>
      ) : activeDrafts.length === 0 && discardedDrafts.length === 0 ? (
        <div className="page__empty">
          <p>No skill drafts yet.</p>
          <p className="page__empty-hint">
            Go to{" "}
            <a href="/skill-proposals" className="skill-card__chain-link">
              Skill Proposals
            </a>
            , approve a proposal, then click{" "}
            <strong>"Generate Draft"</strong> to create one.
          </p>
        </div>
      ) : (
        <>
          {activeDrafts.length > 0 && (
            <div className="skill-proposals-page__list">
              {activeDrafts.map((d) => (
                <DraftCard
                  key={d.id}
                  draft={d}
                  onTest={handleTest}
                  onApprove={handleApprove}
                  onInstall={handleInstall}
                  onFinalize={handleFinalize}
                  onDiscard={handleDiscard}
                  isBusy={busyId === d.id}
                />
              ))}
            </div>
          )}

          {discardedDrafts.length > 0 && (
            <details className="skill-drafts-page__discarded">
              <summary className="skill-drafts-page__discarded-toggle">
                🗑 Discarded drafts ({discardedDrafts.length})
              </summary>
              <div className="skill-proposals-page__list">
                {discardedDrafts.map((d) => (
                  <DraftCard
                    key={d.id}
                    draft={d}
                    onTest={handleTest}
                    onApprove={handleApprove}
                    onInstall={handleInstall}
                    onFinalize={handleFinalize}
                    onDiscard={handleDiscard}
                    isBusy={busyId === d.id}
                  />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
};
