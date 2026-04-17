/**
 * ApprovalsPage – lists all pending approvals and lets the user decide.
 */

import React, { useEffect } from "react";
import { useApprovalsStore } from "../stores/approvalsStore";
import { ApprovalCard } from "../components/approvals/ApprovalCard";
import { useI18n } from "../i18n/useI18n";

export const ApprovalsPage: React.FC = () => {
  const { approvals, isLoading, fetchApprovals, decide } = useApprovalsStore();
  const { t } = useI18n();

  useEffect(() => {
    void fetchApprovals();
    // Poll every 5 seconds for new approvals
    const interval = setInterval(() => void fetchApprovals(), 5000);
    return () => clearInterval(interval);
  }, [fetchApprovals]);

  return (
    <div className="page approvals-page">
      <div className="page__header">
        <h1>{t("approvals", "title")}</h1>
        <p className="page__subtitle">
          {t("approvals", "subtitle")}
        </p>
      </div>

      {isLoading && approvals.length === 0 ? (
        <p className="page__loading">{t("common", "loading")}</p>
      ) : approvals.length === 0 ? (
        <div className="page__empty">
          <p>{t("approvals", "no_pending")}</p>
        </div>
      ) : (
        <div className="approvals-page__list">
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} onDecide={decide} />
          ))}
        </div>
      )}
    </div>
  );
};
