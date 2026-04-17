/**
 * LogsPage – displays the audit log of all actions taken.
 */

import React from "react";
import { useAuditLogs } from "../hooks/useAuditLogs";
import { useI18n } from "../i18n/useI18n";

const STATUS_BADGE: Record<string, string> = {
  success: "badge--success",
  error: "badge--error",
  approval_required: "badge--warning",
};

export const LogsPage: React.FC = () => {
  const { logs, isLoading, error, refetch } = useAuditLogs(200);
  const { t } = useI18n();

  return (
    <div className="page logs-page">
      <div className="page__header">
        <h1>{t("logs", "title")}</h1>
        <button className="btn btn--secondary" onClick={() => void refetch()}>
          {t("logs", "refresh")}
        </button>
      </div>

      {isLoading && <p className="page__loading">{t("common", "loading")}</p>}
      {error && <p className="page__error">{error}</p>}

      {!isLoading && logs.length === 0 && (
        <div className="page__empty">
          <p>{t("logs", "no_logs")}</p>
        </div>
      )}

      {logs.length > 0 && (
        <div className="logs-page__table-wrapper">
          <table className="logs-table">
            <thead>
              <tr>
                <th>{t("logs", "col_id")}</th>
                <th>{t("logs", "col_time")}</th>
                <th>{t("logs", "col_tool")}</th>
                <th>{t("logs", "col_status")}</th>
                <th>{t("logs", "col_command")}</th>
                <th>{t("logs", "col_summary")}</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{log.id}</td>
                  <td className="logs-table__time">
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td>
                    <code>{log.tool_name}</code>
                  </td>
                  <td>
                    <span className={`badge ${STATUS_BADGE[log.status] ?? ""}`}>
                      {log.status}
                    </span>
                  </td>
                  <td className="logs-table__command">{log.command}</td>
                  <td className="logs-table__summary">
                    {log.result_summary ?? log.error_message ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
