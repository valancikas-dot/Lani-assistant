/**
 * ProofPanel – displays browser proof entries attached to a replay step.
 *
 * "Proofs" are the verification artefacts captured by BrowserVerifier:
 * URL, page title, screenshot confidence score, expected vs observed values.
 * The backend surfaces these inside ReplayStep.result_summary / notes as
 * structured text.  We parse a lightweight JSON-like format if present, or
 * fall back to displaying the raw strings.
 */

import React from "react";
import type { ReplayStep } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

interface Props {
  steps: ReplayStep[];
}

interface ParsedProof {
  url?: string;
  title?: string;
  confidence?: number;
  expected?: string;
  observed?: string;
  verdict?: string;
}

function tryParseProof(notes: string): ParsedProof | null {
  try {
    const obj = JSON.parse(notes);
    if (typeof obj === "object" && obj !== null) return obj as ParsedProof;
  } catch {
    // not JSON — fall through
  }
  return null;
}

const ProofEntry: React.FC<{ step: ReplayStep }> = ({ step }) => {
  const { t } = useI18n();
  const proof = tryParseProof(step.notes);

  const confidence = proof?.confidence ?? null;
  const barWidth = confidence !== null ? `${Math.round(confidence * 100)}%` : null;
  const barCls =
    confidence === null       ? ""
    : confidence >= 0.8       ? "proof-entry__bar--high"
    : confidence >= 0.5       ? "proof-entry__bar--medium"
    :                           "proof-entry__bar--low";

  return (
    <div className="proof-entry">
      <div className="proof-entry__header">
        <span className="proof-entry__step">#{step.step_number}</span>
        <span className="proof-entry__action">{step.action}</span>
        <span
          className={`proof-entry__verdict proof-entry__verdict--${step.verification_verdict ?? "none"}`}
        >
          {step.verification_verdict ?? t("common", "unknown")}
        </span>
      </div>

      {proof?.url && (
        <div className="proof-entry__url" title={proof.url}>
          {proof.url}
        </div>
      )}
      {proof?.title && (
        <div className="proof-entry__page-title">{proof.title}</div>
      )}

      {barWidth && (
        <div className="proof-entry__confidence">
          <span className="proof-entry__confidence-label">
            {t("mission_control", "step_verification")}
          </span>
          <div className="proof-entry__bar-track">
            <div
              className={`proof-entry__bar ${barCls}`}
              style={{ width: barWidth }}
            />
          </div>
          <span className="proof-entry__confidence-pct">
            {Math.round((proof?.confidence ?? 0) * 100)}%
          </span>
        </div>
      )}

      {proof?.expected && (
        <div className="proof-entry__compare">
          <span className="proof-entry__label">{t("mission_control", "step_result")}</span>
          <span className="proof-entry__expected">
            expected: <em>{proof.expected}</em>
          </span>
          {proof.observed && (
            <span className="proof-entry__observed">
              observed: <em>{proof.observed}</em>
            </span>
          )}
        </div>
      )}

      {!proof && step.notes && step.notes !== "" && (
        <p className="proof-entry__notes">{step.notes}</p>
      )}

      {step.failure_reason && (
        <p className="proof-entry__failure">
          {t("mission_control", "step_failure")}: {step.failure_reason}
        </p>
      )}
    </div>
  );
};

export const ProofPanel: React.FC<Props> = ({ steps }) => {
  const { t } = useI18n();

  const stepsWithProof = steps.filter(
    (s) => s.verification_verdict || s.notes || s.failure_reason
  );

  if (stepsWithProof.length === 0) {
    return (
      <div className="proof-panel proof-panel--empty">
        <p>{t("mission_control", "no_proofs")}</p>
      </div>
    );
  }

  return (
    <div className="proof-panel">
      <h4 className="proof-panel__heading">{t("mission_control", "proof_panel")}</h4>
      {stepsWithProof.map((s) => (
        <ProofEntry key={s.step_number} step={s} />
      ))}
    </div>
  );
};
