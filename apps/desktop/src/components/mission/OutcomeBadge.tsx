/**
 * OutcomeBadge – compact coloured pill showing a chain outcome.
 */

import React from "react";
import type { ChainOutcome } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

interface Props {
  outcome: ChainOutcome;
}

const OUTCOME_CLS: Record<ChainOutcome, string> = {
  blocked:               "outcome-badge--blocked",
  approval_required:     "outcome-badge--approval",
  executed_unverified:   "outcome-badge--unverified",
  executed_verified:     "outcome-badge--verified",
  failed_retryable:      "outcome-badge--warn",
  failed_nonretryable:   "outcome-badge--error",
  rolled_back:           "outcome-badge--rolled-back",
  rollback_failed:       "outcome-badge--error",
  unknown:               "outcome-badge--unknown",
};

export const OutcomeBadge: React.FC<Props> = ({ outcome }) => {
  const { t } = useI18n();
  return (
    <span className={`outcome-badge ${OUTCOME_CLS[outcome] ?? "outcome-badge--unknown"}`}>
      {t("mission_control", `outcome_${outcome}` as keyof typeof import("../../i18n/locales/en").en.mission_control)}
    </span>
  );
};
