/**
 * SkillProposalsPage – Phase 6 / 6.5: Skill Proposal Engine
 *
 * Lists detected recurring behaviour patterns that Lani proposes as
 * automatable skills.  The user can approve, reject, dismiss, or leave
 * feedback on each proposal.  Approval is SAFE MODE ONLY – nothing is
 * executed or installed automatically.
 *
 * Phase 6.5 additions
 * ───────────────────
 * • Sort by relevance_score (pre-computed by backend)
 * • Feedback buttons: 👍 Useful / 👎 Not useful
 * • Dismiss button (soft-hide)
 * • "Why Lani suggested this" expandable section
 * • Duplicate-suppression hint when suppressed_by is non-null
 * • Dismissed filter tab
 * • feedback_score bar alongside confidence bar
 */

import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getSkillProposals,
  scanSkillProposals,
  approveSkillProposal,
  rejectSkillProposal,
  feedbackSkillProposal,
  dismissSkillProposal,
  generateSkillDraft,
} from "../lib/api";
import type { SkillProposal, SkillProposalStatus } from "../lib/types";

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

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CLASSES: Record<SkillProposalStatus, string> = {
  proposed: "status-badge status-badge--proposed",
  approved: "status-badge status-badge--approved",
  rejected: "status-badge status-badge--rejected",
};

const StatusBadge: React.FC<{ status: SkillProposalStatus }> = ({ status }) => (
  <span className={STATUS_CLASSES[status]}>{status}</span>
);

// ─── Score bar (generic) ──────────────────────────────────────────────────────

const ScoreBar: React.FC<{
  value: number | null;
  label: string;
  /** Optional colour override — CSS colour string */
  color?: string;
}> = ({ value, label, color }) => {
  if (value === null) return <span className="skill-confidence">—</span>;
  const pct = Math.round(value * 100);
  return (
    <div className="skill-confidence" title={`${label}: ${pct}%`}>
      <div className="skill-confidence__track">
        <div
          className="skill-confidence__fill"
          style={{ width: `${pct}%`, ...(color ? { background: color } : {}) }}
        />
      </div>
      <span className="skill-confidence__label">{pct}%</span>
    </div>
  );
};

// ─── Feedback score indicator ─────────────────────────────────────────────────
// feedback_score is in [-1, +1]; normalise to [0, 1] for the bar.

const FeedbackBar: React.FC<{ score: number; count: number }> = ({
  score,
  count,
}) => {
  if (count === 0)
    return (
      <span className="skill-confidence skill-confidence--muted">
        No feedback yet
      </span>
    );
  // Normalise [-1,+1] → [0,1]
  const normalised = (score + 1) / 2;
  const pct = Math.round(normalised * 100);
  const colour =
    score > 0.1 ? "var(--color-success, #22c55e)" : score < -0.1 ? "var(--color-danger, #ef4444)" : undefined;
  return (
    <div
      className="skill-confidence"
      title={`Feedback score: ${score.toFixed(2)} (${count} signal${count !== 1 ? "s" : ""})`}
    >
      <div className="skill-confidence__track">
        <div
          className="skill-confidence__fill"
          style={{ width: `${pct}%`, ...(colour ? { background: colour } : {}) }}
        />
      </div>
      <span className="skill-confidence__label">
        {score > 0 ? "+" : ""}
        {score.toFixed(2)}
      </span>
    </div>
  );
};

// ─── Proposal Card ────────────────────────────────────────────────────────────

const ProposalCard: React.FC<{
  proposal: SkillProposal;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onFeedback: (id: number, signal: "useful" | "not_useful" | "ignored") => void;
  onDismiss: (id: number) => void;
  onGenerateDraft: (id: number) => void;
  isBusy: boolean;
}> = ({ proposal, onApprove, onReject, onFeedback, onDismiss, onGenerateDraft, isBusy }) => {
  const [expanded, setExpanded] = useState(false);

  const isDismissed = Boolean(proposal.dismissed);
  const isSuppressed = Boolean(proposal.suppressed_by);

  return (
    <div
      className={[
        "skill-card",
        `skill-card--${proposal.status}`,
        isDismissed ? "skill-card--dismissed" : "",
        isSuppressed ? "skill-card--suppressed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* Dismissed / suppression overlay badge */}
      {isDismissed && (
        <span className="skill-card__overlay-badge skill-card__overlay-badge--dismissed">
          Dismissed
        </span>
      )}
      {isSuppressed && !isDismissed && (
        <span
          className="skill-card__overlay-badge skill-card__overlay-badge--suppressed"
          title={`Similar to a higher-ranked proposal (${proposal.suppressed_by})`}
        >
          Similar to higher-ranked proposal
        </span>
      )}

      {/* Header row */}
      <div className="skill-card__header">
        <div className="skill-card__title-row">
          <span className="skill-card__title">{proposal.title}</span>
          <StatusBadge status={proposal.status} />
          <RiskBadge level={proposal.risk_level} />
        </div>
        <div className="skill-card__meta">
          <span className="skill-card__meta-item">
            🔁 <strong>{proposal.frequency}</strong> occurrences
          </span>
          <span className="skill-card__meta-item">
            ⏱ {proposal.estimated_time_saved ?? "—"}
          </span>
          <span className="skill-card__meta-item skill-card__meta-item--bar">
            Confidence:{" "}
            <ScoreBar value={proposal.confidence} label="Confidence" />
          </span>
          <span className="skill-card__meta-item skill-card__meta-item--bar">
            Relevance:{" "}
            <ScoreBar
              value={proposal.relevance_score}
              label="Relevance"
              color="var(--color-accent, #6366f1)"
            />
          </span>
          <span className="skill-card__meta-item skill-card__meta-item--bar">
            Feedback:{" "}
            <FeedbackBar
              score={proposal.feedback_score}
              count={proposal.feedback_count}
            />
          </span>
          {proposal.created_at && (
            <span className="skill-card__meta-item skill-card__meta-item--muted">
              Detected {new Date(proposal.created_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      <p className="skill-card__description">{proposal.description}</p>

      {/* Expandable details */}
      <button
        className="skill-card__expand-btn"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        {expanded ? "▲ Hide details" : "▼ Show details"}
      </button>

      {expanded && (
        <div className="skill-card__details">
          {/* Why suggested */}
          {proposal.why_suggested && (
            <div className="skill-card__why">
              <h4 className="skill-card__section-label">
                💡 Why Lani suggested this
              </h4>
              <p className="skill-card__why-text">{proposal.why_suggested}</p>
            </div>
          )}

          {/* Suppression explanation */}
          {isSuppressed && (
            <div className="skill-card__suppression-hint">
              <h4 className="skill-card__section-label">ℹ Duplicate hint</h4>
              <p>
                This proposal is similar to pattern{" "}
                <code>{proposal.suppressed_by}</code>, which has a higher
                relevance score. Consider reviewing that proposal first.
              </p>
            </div>
          )}

          {/* Steps */}
          {proposal.steps.length > 0 && (
            <div className="skill-card__steps">
              <h4 className="skill-card__section-label">Detected steps</h4>
              <ol className="skill-card__step-list">
                {proposal.steps.map((step, i) => (
                  <li key={i} className="skill-card__step">
                    <code className="skill-card__step-tool">{step.tool_name}</code>
                    {" — "}
                    <span className="skill-card__step-cmd">
                      {step.command_template}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Related chains */}
          {proposal.chain_ids.length > 0 && (
            <div className="skill-card__chains">
              <h4 className="skill-card__section-label">
                Related execution chains
              </h4>
              <ul className="skill-card__chain-list">
                {proposal.chain_ids.slice(0, 5).map((cid) => (
                  <li key={cid}>
                    <Link
                      to="/mission"
                      state={{ highlightChainId: cid }}
                      className="skill-card__chain-link"
                      title={`Open chain ${cid} in Mission Control`}
                    >
                      ⛓ {cid}
                    </Link>
                  </li>
                ))}
                {proposal.chain_ids.length > 5 && (
                  <li className="skill-card__chain-more">
                    +{proposal.chain_ids.length - 5} more
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="skill-card__actions">
        {/* Approve / Reject (only for proposed status) */}
        {proposal.status === "proposed" && (
          <>
            <button
              className="btn btn--primary btn--sm"
              disabled={isBusy}
              onClick={() => onApprove(proposal.id)}
              title="Mark as accepted – does not install or execute anything"
            >
              ✓ Approve
            </button>
            <button
              className="btn btn--ghost btn--sm"
              disabled={isBusy}
              onClick={() => onReject(proposal.id)}
            >
              ✕ Reject
            </button>
            <span className="skill-card__safe-note">
              ⚠ Approval is safe – no code will be generated or executed
            </span>
          </>
        )}

        {/* Generate Draft (approved proposals only) */}
        {proposal.status === "approved" && (
          <button
            className="btn btn--primary btn--sm"
            disabled={isBusy}
            onClick={() => onGenerateDraft(proposal.id)}
            title="Generate an inspectable automation draft from this proposal"
          >
            🛠 Generate Draft
          </button>
        )}

        {/* Feedback buttons (proposed status only; not if dismissed) */}
        {proposal.status === "proposed" && !isDismissed && (
          <div className="skill-card__feedback">
            <button
              className="btn btn--ghost btn--xs"
              disabled={isBusy}
              title="Mark as useful — improves ranking"
              onClick={() => onFeedback(proposal.id, "useful")}
            >
              👍 Useful
            </button>
            <button
              className="btn btn--ghost btn--xs"
              disabled={isBusy}
              title="Mark as not useful — lowers ranking"
              onClick={() => onFeedback(proposal.id, "not_useful")}
            >
              👎 Not useful
            </button>
          </div>
        )}

        {/* Dismiss (not already dismissed) */}
        {!isDismissed && (
          <button
            className="btn btn--ghost btn--xs skill-card__dismiss-btn"
            disabled={isBusy}
            title="Hide this proposal from default view"
            onClick={() => onDismiss(proposal.id)}
          >
            ✖ Dismiss
          </button>
        )}
      </div>
    </div>
  );
};

// ─── Filter bar ───────────────────────────────────────────────────────────────

type FilterStatus = "all" | SkillProposalStatus | "dismissed";

const FILTER_LABELS: Record<FilterStatus, string> = {
  all:      "All",
  proposed: "Proposed",
  approved: "Approved",
  rejected: "Rejected",
  dismissed: "Dismissed",
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export const SkillProposalsPage: React.FC = () => {
  const [proposals, setProposals] = useState<SkillProposal[]>([]);
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [isLoading, setIsLoading] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const isDismissedView = filter === "dismissed";
      const statusFilter =
        filter === "all" || filter === "dismissed"
          ? undefined
          : (filter as SkillProposalStatus);
      const res = await getSkillProposals(statusFilter, 50, isDismissedView);

      // Client-side: if viewing dismissed tab, keep only dismissed proposals
      const filtered = isDismissedView
        ? res.proposals.filter((p) => p.dismissed)
        : res.proposals.filter((p) => !p.dismissed);

      // Sort by relevance_score desc (backend should do this too, but be safe)
      filtered.sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0));
      setProposals(filtered);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load proposals");
    } finally {
      setIsLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleScan = async () => {
    setIsScanning(true);
    setScanMessage(null);
    setError(null);
    try {
      const res = await scanSkillProposals(3);
      setScanMessage(
        res.proposals_created > 0
          ? `✓ Detected ${res.proposals_created} new proposal${res.proposals_created > 1 ? "s" : ""}.`
          : "✓ Scan complete – no new patterns found.",
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setIsScanning(false);
    }
  };

  const handleApprove = async (id: number) => {
    setBusyId(id);
    try {
      await approveSkillProposal(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (id: number) => {
    setBusyId(id);
    try {
      await rejectSkillProposal(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleFeedback = async (
    id: number,
    signal: "useful" | "not_useful" | "ignored",
  ) => {
    setBusyId(id);
    try {
      const res = await feedbackSkillProposal(id, signal);
      // Optimistically update the card in the list
      setProposals((prev) =>
        prev.map((p) => (p.id === id ? res.proposal : p)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Feedback failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleDismiss = async (id: number) => {
    setBusyId(id);
    try {
      await dismissSkillProposal(id);
      // Remove from current view (dismissed proposals are hidden by default)
      setProposals((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dismiss failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleGenerateDraft = async (id: number) => {
    setBusyId(id);
    setScanMessage(null);
    setError(null);
    try {
      await generateSkillDraft(id);
      setScanMessage(
        `✓ Draft generated for proposal #${id}. ` +
          "Open Skill Drafts to review and test it.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft generation failed");
    } finally {
      setBusyId(null);
    }
  };

  const proposedCount = proposals.filter(
    (p) => p.status === "proposed" && !p.dismissed,
  ).length;

  return (
    <div className="page skill-proposals-page">
      {/* Header */}
      <div className="page__header">
        <h1>
          Skill Proposals
          {proposedCount > 0 && (
            <span className="page__badge">{proposedCount}</span>
          )}
        </h1>
        <p className="page__subtitle">
          Lani detected recurring actions in your execution history and is
          suggesting automation shortcuts. Proposals are ranked by relevance.
          Approving is safe — nothing runs automatically.
        </p>
      </div>

      {/* Toolbar */}
      <div className="skill-proposals-page__toolbar">
        {/* Filter tabs */}
        <div className="filter-tabs" role="tablist">
          {(Object.keys(FILTER_LABELS) as FilterStatus[]).map((f) => (
            <button
              key={f}
              role="tab"
              aria-selected={filter === f}
              className={`filter-tab${filter === f ? " filter-tab--active" : ""}`}
              onClick={() => setFilter(f)}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="skill-proposals-page__actions">
          <button
            className="btn btn--secondary btn--sm"
            onClick={() => void load()}
            disabled={isLoading}
          >
            ↺ Refresh
          </button>
          <button
            className="btn btn--primary btn--sm"
            onClick={() => void handleScan()}
            disabled={isScanning || isLoading}
            title="Scan execution history for new patterns"
          >
            {isScanning ? "Scanning…" : "🔍 Scan for patterns"}
          </button>
          <Link
            to="/skill-drafts"
            className="btn btn--ghost btn--sm"
            title="View generated skill drafts"
          >
            🛠 Skill Drafts
          </Link>
        </div>
      </div>

      {/* Feedback messages */}
      {scanMessage && (
        <div className="skill-proposals-page__message skill-proposals-page__message--ok">
          {scanMessage}
        </div>
      )}
      {error && (
        <div className="skill-proposals-page__message skill-proposals-page__message--error">
          {error}
        </div>
      )}

      {/* Content */}
      {isLoading && proposals.length === 0 ? (
        <p className="page__loading">Loading proposals…</p>
      ) : proposals.length === 0 ? (
        <div className="page__empty">
          <p>
            No skill proposals yet.{" "}
            {filter === "dismissed"
              ? "No dismissed proposals."
              : filter !== "all"
              ? `Try switching to "All".`
              : 'Click "Scan for patterns" to analyse your execution history.'}
          </p>
          <p className="page__empty-hint">
            Proposals appear when Lani detects the same action performed 3+
            times.
          </p>
        </div>
      ) : (
        <div className="skill-proposals-page__list">
          {proposals.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              onApprove={handleApprove}
              onReject={handleReject}
              onFeedback={handleFeedback}
              onDismiss={handleDismiss}
              onGenerateDraft={handleGenerateDraft}
              isBusy={busyId === p.id}
            />
          ))}
        </div>
      )}
    </div>
  );
};
