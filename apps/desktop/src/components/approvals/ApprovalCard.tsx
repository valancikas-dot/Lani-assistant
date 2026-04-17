/**
 * ApprovalCard – displays a single pending approval with Approve/Deny buttons.
 *
 * Shows risk level badge, session/account context, voice-approval eligibility
 * (only allowed for low/medium risk), and a "what happens next" hint.
 */

import React from "react";
import type { ApprovalRequest } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

interface Props {
  approval: ApprovalRequest;
  onDecide: (id: number, decision: "approved" | "denied") => void;
}

const RISK_LEVELS = ["low", "medium", "high", "critical"] as const;
type RiskLevel = (typeof RISK_LEVELS)[number];

function inferRisk(approval: ApprovalRequest): RiskLevel {
  // ApprovalRequest may carry a risk_level field (backend enrichment).
  // Fall back to "medium" if absent.
  const raw = (approval as unknown as Record<string, unknown>)["risk_level"];
  if (typeof raw === "string" && (RISK_LEVELS as readonly string[]).includes(raw)) {
    return raw as RiskLevel;
  }
  return "medium";
}

const RISK_CLS: Record<RiskLevel, string> = {
  low:      "risk-badge--low",
  medium:   "risk-badge--medium",
  high:     "risk-badge--high",
  critical: "risk-badge--critical",
};

const RISK_LABEL_KEY: Record<RiskLevel, string> = {
  low:      "risk_low",
  medium:   "risk_medium",
  high:     "risk_high",
  critical: "risk_critical",
};

export const ApprovalCard: React.FC<Props> = ({ approval, onDecide }) => {
  const { t } = useI18n();
  const risk = inferRisk(approval);
  const voiceAllowed = risk === "low" || risk === "medium";

  // Optional session / account context fields injected by the backend
  const extra = approval as unknown as Record<string, unknown>;
  const sessionId   = extra["session_id"]   as string | undefined;
  const accountName = extra["account_name"] as string | undefined;
  const intentHint  = extra["intent"]       as string | undefined;

  return (
    <div className="approval-card">
      <div className="approval-card__header">
        <span className="approval-card__tool">{approval.tool_name}</span>
        <span className={`risk-badge ${RISK_CLS[risk]}`}>
          {t(
            "mission_control",
            RISK_LABEL_KEY[risk] as keyof typeof import("../../i18n/locales/en").en.mission_control
          )}
        </span>
        <span className="approval-card__time">
          {new Date(approval.created_at).toLocaleString()}
        </span>
      </div>

      {/* Intent preview */}
      {intentHint && (
        <p className="approval-card__intent">
          <em>{intentHint}</em>
        </p>
      )}

      <p className="approval-card__command">
        <strong>{t("approvals", "command_label")}</strong> {approval.command}
      </p>

      {/* Session / account context */}
      {(sessionId || accountName) && (
        <div className="approval-card__context">
          {sessionId && (
            <span className="approval-card__context-item">
              {t("mission_control", "session")}: <code>{sessionId}</code>
            </span>
          )}
          {accountName && (
            <span className="approval-card__context-item">
              {t("mission_control", "tool")}: <code>{accountName}</code>
            </span>
          )}
        </div>
      )}

      {Object.keys(approval.params).length > 0 && (
        <details className="approval-card__params">
          <summary>{t("approvals", "parameters")}</summary>
          <pre>{JSON.stringify(approval.params, null, 2)}</pre>
        </details>
      )}

      {/* Voice approval eligibility hint */}
      {voiceAllowed && (
        <p className="approval-card__voice-hint">
          🎙 {t("approvals", "voice_approval_allowed") as string}
        </p>
      )}

      <div className="approval-card__actions">
        <button
          className="btn btn--approve"
          onClick={() => onDecide(approval.id, "approved")}
        >
          {t("approvals", "approve")}
        </button>
        <button
          className="btn btn--deny"
          onClick={() => onDecide(approval.id, "denied")}
        >
          {t("approvals", "deny")}
        </button>
      </div>
    </div>
  );
};
