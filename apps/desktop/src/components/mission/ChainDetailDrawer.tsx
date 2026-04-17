/**
 * ChainDetailDrawer – side-panel showing full detail for a selected chain.
 *
 * Renders: intent preview, policy decision, approval events, checkpoints,
 * browser proofs via ReplayViewer, verification verdict, state delta, and
 * the eval summary.
 */

import React from "react";
import { useMissionControlStore } from "../../stores/missionControlStore";
import { OutcomeBadge } from "./OutcomeBadge";
import { SessionBadge } from "./SessionBadge";
import { ReplayViewer } from "./ReplayViewer";
import { useI18n } from "../../i18n/useI18n";

const RISK_CLS: Record<string, string> = {
  low:      "risk-badge--low",
  medium:   "risk-badge--medium",
  high:     "risk-badge--high",
  critical: "risk-badge--critical",
};

const RISK_LABEL_KEY: Record<string, string> = {
  low:      "risk_low",
  medium:   "risk_medium",
  high:     "risk_high",
  critical: "risk_critical",
};

export const ChainDetailDrawer: React.FC = () => {
  const { t } = useI18n();
  const {
    selectedChainId,
    chainDetail,
    checkpoints,
    isLoadingDetail,
    detailError,
    clearSelection,
  } = useMissionControlStore();

  // Checkpoints are fetched automatically by selectChain – nothing to do here.

  if (!selectedChainId) return null;

  return (
    <aside className="chain-drawer">
      <div className="chain-drawer__header">
        <h2 className="chain-drawer__title">
          {chainDetail?.tool_name ?? t("common", "loading")}
        </h2>
        <button
          className="chain-drawer__close btn btn--ghost"
          onClick={clearSelection}
          aria-label={t("common", "close")}
        >
          ✕
        </button>
      </div>

      {isLoadingDetail && (
        <p className="chain-drawer__loading">
          {t("mission_control", "loading_detail")}
        </p>
      )}

      {detailError && (
        <p className="chain-drawer__error">{detailError}</p>
      )}

      {chainDetail && (
        <div className="chain-drawer__body">
          {/* ── Outcome + risk badges ────────────────────────────────── */}
          <div className="chain-drawer__badges">
            <OutcomeBadge outcome={chainDetail.outcome} />
            <span
              className={`risk-badge ${RISK_CLS[chainDetail.risk_level] ?? "risk-badge--unknown"}`}
            >
              {t(
                "mission_control",
                (RISK_LABEL_KEY[chainDetail.risk_level] ?? "risk_unknown") as keyof typeof import("../../i18n/locales/en").en.mission_control
              )}
            </span>
            <SessionBadge sessionId={chainDetail.session_id} />
          </div>

          {/* ── Command ─────────────────────────────────────────────── */}
          <section className="chain-drawer__section">
            <h3 className="chain-drawer__section-title">
              {t("mission_control", "command")}
            </h3>
            <pre className="chain-drawer__command">{chainDetail.command}</pre>
          </section>

          {/* ── Policy decision ─────────────────────────────────────── */}
          <section className="chain-drawer__section">
            <h3 className="chain-drawer__section-title">
              {t("mission_control", "policy_verdict")}
            </h3>
            <p className="chain-drawer__field">
              <strong>{t("mission_control", "policy_verdict")}:</strong>{" "}
              {chainDetail.policy_verdict}
            </p>
            {chainDetail.policy_reason && (
              <p className="chain-drawer__field">
                <strong>{t("mission_control", "policy_reason")}:</strong>{" "}
                {chainDetail.policy_reason}
              </p>
            )}
          </section>

          {/* ── Approval events ─────────────────────────────────────── */}
          {chainDetail.approval_id && (
            <section className="chain-drawer__section">
              <h3 className="chain-drawer__section-title">
                {t("mission_control", "approval_status")}
              </h3>
              <p className="chain-drawer__field">
                <strong>ID:</strong> {chainDetail.approval_id}
              </p>
              <p className="chain-drawer__field">
                <strong>{t("mission_control", "approval_status")}:</strong>{" "}
                {chainDetail.approval_status}
              </p>
            </section>
          )}

          {/* ── State delta ─────────────────────────────────────────── */}
          {(chainDetail.state_before_summary || chainDetail.state_after_summary) && (
            <section className="chain-drawer__section">
              <h3 className="chain-drawer__section-title">
                {t("mission_control", "step_delta")}
              </h3>
              {chainDetail.state_before_summary && (
                <p className="chain-drawer__field">
                  <strong>{t("mission_control", "state_before")}:</strong>{" "}
                  {chainDetail.state_before_summary}
                </p>
              )}
              {chainDetail.state_after_summary && (
                <p className="chain-drawer__field">
                  <strong>{t("mission_control", "state_after")}:</strong>{" "}
                  {chainDetail.state_after_summary}
                </p>
              )}
            </section>
          )}

          {/* ── Changed fields ──────────────────────────────────────── */}
          {chainDetail.changed_fields.length > 0 && (
            <section className="chain-drawer__section">
              <h3 className="chain-drawer__section-title">
                {t("mission_control", "changed_fields")}
              </h3>
              <ul className="chain-drawer__tag-list">
                {chainDetail.changed_fields.map((f) => (
                  <li key={f} className="chain-drawer__tag">{f}</li>
                ))}
              </ul>
            </section>
          )}

          {/* ── Eval summary ────────────────────────────────────────── */}
          {chainDetail.eval_status && (
            <section className="chain-drawer__section">
              <h3 className="chain-drawer__section-title">
                {t("mission_control", "eval_status")}
              </h3>
              <p className="chain-drawer__field">{chainDetail.eval_status}</p>
            </section>
          )}

          {/* ── Checkpoints ─────────────────────────────────────────── */}
          {checkpoints && (
            <section className="chain-drawer__section">
              <h3 className="chain-drawer__section-title">
                {t("mission_control", "checkpoints")}
              </h3>
              {checkpoints.checkpoints.length === 0 ? (
                <p className="chain-drawer__empty">
                  {t("mission_control", "no_checkpoints")}
                </p>
              ) : (
                <ol className="chain-drawer__checkpoints">
                  {checkpoints.checkpoints.map((cp) => (
                    <li key={cp.step_number} className="checkpoint">
                      <div className="checkpoint__header">
                        <span className="checkpoint__num">#{cp.step_number}</span>
                        <span className="checkpoint__action">{cp.action}</span>
                        <span className={`checkpoint__status checkpoint__status--${cp.result_status}`}>
                          {cp.result_status}
                        </span>
                      </div>
                      {cp.result_summary && (
                        <p className="checkpoint__summary">{cp.result_summary}</p>
                      )}
                      {cp.verification_verdict && (
                        <p className="checkpoint__verify">
                          {t("mission_control", "step_verification")}: {cp.verification_verdict}
                        </p>
                      )}
                      {cp.failure_reason && (
                        <p className="checkpoint__failure">
                          {t("mission_control", "step_failure")}: {cp.failure_reason}
                        </p>
                      )}
                      {cp.state_delta_summary && (
                        <p className="checkpoint__delta">
                          {t("mission_control", "step_delta")}: {cp.state_delta_summary}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}

          {/* ── Replay viewer (timeline + steps + proofs + simulate) ── */}
          <section className="chain-drawer__section">
            <ReplayViewer chain={chainDetail} />
          </section>
        </div>
      )}
    </aside>
  );
};
