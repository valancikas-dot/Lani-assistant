/**
 * MissionControlPage – observe, replay, and audit every execution chain.
 *
 * Lists all recent chains from the audit ring buffer.  Clicking a row opens
 * the ChainDetailDrawer with the full detail, replay timeline, checkpoints,
 * browser proofs, and a dry-run simulate panel.
 *
 * Auto-refreshes every 10 seconds.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMissionControlStore } from "../stores/missionControlStore";
import { useApprovalsStore } from "../stores/approvalsStore";
import { OutcomeBadge } from "../components/mission/OutcomeBadge";
import { SessionBadge } from "../components/mission/SessionBadge";
import { ChainDetailDrawer } from "../components/mission/ChainDetailDrawer";
import { useI18n } from "../i18n/useI18n";
import { getSkillProposals } from "../lib/api";
import type { ChainSummary } from "../lib/types";

const POLL_MS = 10_000;

const RISK_CLS: Record<string, string> = {
  low:      "risk-dot--low",
  medium:   "risk-dot--medium",
  high:     "risk-dot--high",
  critical: "risk-dot--critical",
};

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

const ChainRow: React.FC<{
  chain: ChainSummary;
  isSelected: boolean;
  onSelect: (id: string) => void;
}> = ({ chain, isSelected, onSelect }) => (
  <tr
    className={`chain-row${isSelected ? " chain-row--selected" : ""}`}
    onClick={() => onSelect(chain.chain_id)}
    role="button"
    tabIndex={0}
    onKeyDown={(e) => e.key === "Enter" && onSelect(chain.chain_id)}
  >
    <td className="chain-row__tool">{chain.tool_name}</td>
    <td className="chain-row__command" title={chain.command}>
      <span className="chain-row__command-text">{chain.command}</span>
    </td>
    <td className="chain-row__outcome">
      <OutcomeBadge outcome={chain.outcome} />
    </td>
    <td className="chain-row__risk">
      <span className={`risk-dot ${RISK_CLS[chain.risk_level] ?? "risk-dot--unknown"}`} />
      {chain.risk_level}
    </td>
    <td className="chain-row__eval">{chain.eval_status ?? "—"}</td>
    <td className="chain-row__session"><SessionBadge sessionId={chain.session_id} /></td>
    <td className="chain-row__time">{fmt(chain.timestamp)}</td>
  </tr>
);

export const MissionControlPage: React.FC = () => {
  const { t } = useI18n();

  const { chains, isLoading, error, fetchChains, selectChain, selectedChainId } =
    useMissionControlStore();
  const approvals = useApprovalsStore((s) => s.approvals);
  const pendingCount = approvals.length;

  const [autoRefresh, setAutoRefresh] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Skill proposal hint ─────────────────────────────────────────────────
  const [pendingProposals, setPendingProposals] = useState(0);
  useEffect(() => {
    getSkillProposals("proposed", 50)
      .then((res) => setPendingProposals(res.total))
      .catch(() => setPendingProposals(0));
  }, []);
  // ───────────────────────────────────────────────────────────────────────

  const refresh = useCallback(() => {
    void fetchChains();
  }, [fetchChains]);

  // Initial load
  useEffect(() => {
    void fetchChains();
  }, [fetchChains]);

  // Auto-refresh
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (autoRefresh) {
      intervalRef.current = setInterval(refresh, POLL_MS);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, refresh]);

  const handleRowSelect = (id: string) => {
    if (selectedChainId === id) {
      void selectChain(null);
    } else {
      void selectChain(id);
    }
  };

  const drawerOpen = Boolean(selectedChainId);

  return (
    <div className={`page mission-page${drawerOpen ? " mission-page--drawer-open" : ""}`}>
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="page__header">
        <div className="page__header-left">
          <h1>{t("mission_control", "title")}</h1>
          <p className="page__subtitle">{t("mission_control", "subtitle")}</p>
        </div>
        <div className="page__header-right">
          {pendingCount > 0 && (
            <Link to="/approvals" className="mission-page__approval-banner">
              <span className="mission-page__approval-count">{pendingCount}</span>{" "}
              {pendingCount === 1
                ? t("mission_control", "pending_approvals")
                : t("mission_control", "pending_approvals_plural")}
              {" — "}
              {t("mission_control", "go_to_approvals")}
            </Link>
          )}
          {pendingProposals > 0 && (
            <Link to="/skill-proposals" className="mission-page__skill-hint">
              ✦ {pendingProposals} skill proposal{pendingProposals > 1 ? "s" : ""} awaiting review
            </Link>
          )}
          <label className="mission-page__toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            {t("mission_control", "auto_refresh")}
          </label>
          <button
            className="btn btn--secondary"
            onClick={refresh}
            disabled={isLoading}
          >
            {isLoading ? t("common", "loading") : t("mission_control", "refresh")}
          </button>
        </div>
      </div>

      {/* ── Error state ──────────────────────────────────────────────── */}
      {error && <p className="page__error">{t("mission_control", "error_load")}: {error}</p>}

      {/* ── Content split: table + optional drawer ───────────────────── */}
      <div className="mission-page__content">
        {/* Chain list */}
        <div className="mission-page__list">
          {chains.length === 0 && !isLoading ? (
            <div className="page__empty">
              <p>{t("mission_control", "no_chains")}</p>
            </div>
          ) : (
            <table className="chain-table">
              <thead>
                <tr>
                  <th>{t("mission_control", "tool")}</th>
                  <th>{t("mission_control", "command")}</th>
                  <th>{t("mission_control", "outcome")}</th>
                  <th>{t("mission_control", "risk")}</th>
                  <th>{t("mission_control", "eval_status")}</th>
                  <th>{t("mission_control", "session")}</th>
                  <th>{t("mission_control", "timestamp")}</th>
                </tr>
              </thead>
              <tbody>
                {chains.map((c) => (
                  <ChainRow
                    key={c.chain_id}
                    chain={c}
                    isSelected={c.chain_id === selectedChainId}
                    onSelect={handleRowSelect}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail drawer */}
        {drawerOpen && <ChainDetailDrawer />}
      </div>
    </div>
  );
};
