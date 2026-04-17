/**
 * ReplayViewer – shows the replay timeline text and replay steps for a chain,
 * plus a dry-run simulation panel.
 */

import React, { useState } from "react";
import type { ChainDetail, SimulateRequest, SimulateResponse } from "../../lib/types";
import { simulateSteps } from "../../lib/api";
import { useI18n } from "../../i18n/useI18n";
import { ProofPanel } from "./ProofPanel";

interface Props {
  chain: ChainDetail;
}

const STEP_STATUS_CLS: Record<string, string> = {
  success:  "replay-step--success",
  error:    "replay-step--error",
  skipped:  "replay-step--skipped",
  pending:  "replay-step--pending",
};

const SIM_OUTCOME_KEY: Record<string, string> = {
  would_succeed:           "sim_would_succeed",
  would_require_approval:  "sim_would_require_approval",
  would_be_blocked:        "sim_would_be_blocked",
  unknown:                 "sim_unknown",
};

export const ReplayViewer: React.FC<Props> = ({ chain }) => {
  const { t } = useI18n();
  const [simResult, setSimResult] = useState<SimulateResponse | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  const handleSimulate = async () => {
    if (chain.replay_steps.length === 0) return;
    const payload: SimulateRequest = {
      steps: chain.replay_steps.map((s) => ({
        action: s.action,
        inputs: s.inputs,
      })),
    };
    setIsSimulating(true);
    setSimError(null);
    try {
      const result = await simulateSteps(payload);
      setSimResult(result);
    } catch (err) {
      setSimError(String(err));
    } finally {
      setIsSimulating(false);
    }
  };

  const hasSteps = chain.replay_steps.length > 0;

  return (
    <div className="replay-viewer">
      {/* ── Timeline text ───────────────────────────────────────────────── */}
      {chain.replay_timeline_text && chain.replay_timeline_text.trim() !== "" && (
        <section className="replay-viewer__timeline">
          <h4 className="replay-viewer__heading">
            {t("mission_control", "replay_timeline")}
          </h4>
          <pre className="replay-viewer__timeline-text">
            {chain.replay_timeline_text}
          </pre>
        </section>
      )}

      {/* ── Replay steps ────────────────────────────────────────────────── */}
      <section className="replay-viewer__steps">
        <h4 className="replay-viewer__heading">
          {t("mission_control", "replay_steps")}
        </h4>

        {!hasSteps ? (
          <p className="replay-viewer__empty">{t("mission_control", "no_replay")}</p>
        ) : (
          <ol className="replay-viewer__step-list">
            {chain.replay_steps.map((step) => (
              <li
                key={step.step_number}
                className={`replay-step ${STEP_STATUS_CLS[step.result_status] ?? ""}`}
              >
                <div className="replay-step__header">
                  <span className="replay-step__num">#{step.step_number}</span>
                  <span className="replay-step__action">{step.action}</span>
                  <span className={`replay-step__status replay-step__status--${step.result_status}`}>
                    {step.result_status}
                  </span>
                </div>

                {Object.keys(step.inputs).length > 0 && (
                  <details className="replay-step__inputs">
                    <summary>{t("mission_control", "step_inputs")}</summary>
                    <pre>{JSON.stringify(step.inputs, null, 2)}</pre>
                  </details>
                )}

                {step.result_summary && (
                  <p className="replay-step__summary">{step.result_summary}</p>
                )}

                {step.state_delta_summary && step.state_delta_summary !== "" && (
                  <p className="replay-step__delta">
                    <span className="replay-step__label">
                      {t("mission_control", "step_delta")}:
                    </span>{" "}
                    {step.state_delta_summary}
                  </p>
                )}

                {step.failure_reason && (
                  <p className="replay-step__failure">
                    {t("mission_control", "step_failure")}: {step.failure_reason}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* ── Browser proofs ──────────────────────────────────────────────── */}
      {hasSteps && <ProofPanel steps={chain.replay_steps} />}

      {/* ── Dry-run simulate ────────────────────────────────────────────── */}
      {hasSteps && (
        <section className="replay-viewer__simulate">
          <h4 className="replay-viewer__heading">
            {t("mission_control", "simulate")}
          </h4>

          <button
            className="btn btn--simulate"
            onClick={() => void handleSimulate()}
            disabled={isSimulating}
          >
            {isSimulating
              ? t("mission_control", "simulate_running")
              : t("mission_control", "simulate")}
          </button>

          {simError && <p className="replay-viewer__error">{simError}</p>}

          {simResult && (
            <div className="replay-viewer__sim-result">
              <h5>{t("mission_control", "simulate_result")}</h5>
              <ol className="replay-viewer__sim-list">
                {simResult.steps.map((ss) => (
                  <li key={ss.step_number} className="sim-step">
                    <div className="sim-step__header">
                      <span className="sim-step__num">#{ss.step_number}</span>
                      <span className="sim-step__action">{ss.action}</span>
                      <span className={`sim-step__outcome sim-step__outcome--${ss.simulated_outcome}`}>
                        {t(
                          "mission_control",
                          (SIM_OUTCOME_KEY[ss.simulated_outcome] ?? "sim_unknown") as keyof typeof import("../../i18n/locales/en").en.mission_control
                        )}
                      </span>
                      {ss.approval_required && (
                        <span className="sim-step__approval-flag">
                          {t("mission_control", "outcome_approval_required")}
                        </span>
                      )}
                    </div>
                    {ss.notes && <p className="sim-step__notes">{ss.notes}</p>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>
      )}
    </div>
  );
};
