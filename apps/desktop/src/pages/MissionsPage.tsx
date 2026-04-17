/**
 * MissionsPage – Phase 8: Autonomous Missions with Checkpoints
 *
 * Displays all autonomous missions.  Each card shows:
 *   • Title, goal, status badge
 *   • Progress bar (step counter + percent)
 *   • Budget indicators (tokens / time)
 *   • Checkpoint alerts for waiting_approval missions
 *   • Action buttons: Start | Pause | Resume | Cancel
 *
 * Clicking a mission in waiting_approval status expands the checkpoint
 * panel so the user can approve or deny the pending gate.
 *
 * Auto-refreshes every 8 seconds while any mission is active.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  listMissions,
  startMission,
  pauseMission,
  resumeMission,
  cancelMission,
  getMissionCheckpoints,
  resolveCheckpoint,
} from "../lib/api";
import type { Mission, MissionStatus, MissionCheckpoint } from "../lib/types";

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CLS: Record<MissionStatus, string> = {
  planned:          "status-badge status-badge--proposed",
  running:          "status-badge status-badge--info",
  waiting_approval: "status-badge status-badge--warning",
  paused:           "status-badge status-badge--info",
  completed:        "status-badge status-badge--success",
  failed:           "status-badge status-badge--rejected",
  cancelled:        "status-badge status-badge--rejected",
};

const STATUS_LABELS: Record<MissionStatus, string> = {
  planned:          "Planned",
  running:          "Running",
  waiting_approval: "Waiting Approval",
  paused:           "Paused",
  completed:        "Completed",
  failed:           "Failed",
  cancelled:        "Cancelled",
};

const StatusBadge: React.FC<{ status: MissionStatus }> = ({ status }) => (
  <span className={STATUS_CLS[status] ?? "status-badge"}>
    {STATUS_LABELS[status] ?? status}
  </span>
);

// ─── Progress bar ─────────────────────────────────────────────────────────────

const ProgressBar: React.FC<{ value: number }> = ({ value }) => {
  const pct = Math.min(Math.max(value, 0), 100);
  return (
    <div className="progress-bar" title={`${pct.toFixed(1)}%`}>
      <div className="progress-bar__fill" style={{ width: `${pct}%` }} />
    </div>
  );
};

// ─── Budget bar ───────────────────────────────────────────────────────────────

const BudgetBar: React.FC<{
  label: string;
  used: number;
  budget: number | null;
  unit?: string;
}> = ({ label, used, budget, unit = "" }) => {
  if (budget === null) return null;
  const pct = Math.min((used / budget) * 100, 100);
  const cls =
    pct >= 90
      ? "budget-bar__fill budget-bar__fill--critical"
      : pct >= 70
      ? "budget-bar__fill budget-bar__fill--warning"
      : "budget-bar__fill";
  return (
    <div className="budget-bar">
      <span className="budget-bar__label">
        {label}: {used.toLocaleString()}{unit} / {budget.toLocaleString()}{unit}
      </span>
      <div className="budget-bar__track">
        <div className={cls} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

// ─── Checkpoint panel ─────────────────────────────────────────────────────────

const CheckpointPanel: React.FC<{
  missionId: number;
  onResolved: () => void;
}> = ({ missionId, onResolved }) => {
  const [checkpoints, setCheckpoints] = useState<MissionCheckpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getMissionCheckpoints(missionId)
      .then((res) => setCheckpoints(res.checkpoints))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e))
      )
      .finally(() => setLoading(false));
  }, [missionId]);

  const pending = checkpoints.filter((cp) => cp.status === "pending");

  if (loading) return <p className="cp-panel__loading">Loading checkpoints…</p>;
  if (error) return <p className="cp-panel__error">Error: {error}</p>;
  if (pending.length === 0)
    return <p className="cp-panel__empty">No pending checkpoints.</p>;

  const handleResolve = async (cp: MissionCheckpoint, approved: boolean) => {
    setWorking(cp.id);
    setError(null);
    try {
      await resolveCheckpoint(missionId, cp.id, approved);
      onResolved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(null);
    }
  };

  return (
    <div className="cp-panel">
      {pending.map((cp) => (
        <div key={cp.id} className="cp-card">
          <p className="cp-card__reason">
            <strong>Step {cp.step_index}</strong> — {cp.reason}
          </p>
          {cp.summary && (
            <p className="cp-card__summary">{cp.summary}</p>
          )}
          <div className="cp-card__actions">
            <button
              className="btn btn--success btn--sm"
              disabled={working === cp.id}
              onClick={() => void handleResolve(cp, true)}
            >
              {working === cp.id ? "…" : "Approve"}
            </button>
            <button
              className="btn btn--danger btn--sm"
              disabled={working === cp.id}
              onClick={() => void handleResolve(cp, false)}
            >
              {working === cp.id ? "…" : "Deny"}
            </button>
          </div>
          {error && <p className="cp-card__error">{error}</p>}
        </div>
      ))}
    </div>
  );
};

// ─── Mission card ─────────────────────────────────────────────────────────────

const MissionCard: React.FC<{
  mission: Mission;
  onAction: () => void;
}> = ({ mission, onAction }) => {
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showCheckpoints, setShowCheckpoints] = useState(
    mission.status === "waiting_approval"
  );

  const act = async (fn: () => Promise<Mission>) => {
    setWorking(true);
    setErr(null);
    try {
      await fn();
      onAction();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };

  const terminal = ["completed", "failed", "cancelled"].includes(mission.status);

  return (
    <div className={`mission-card mission-card--${mission.status}`}>
      {/* ── Header ── */}
      <div className="mission-card__header">
        <span className="mission-card__title">{mission.title}</span>
        <StatusBadge status={mission.status as MissionStatus} />
      </div>

      {/* ── Goal ── */}
      <p className="mission-card__goal" title={mission.goal}>
        {mission.goal.length > 160
          ? `${mission.goal.slice(0, 157)}…`
          : mission.goal}
      </p>

      {/* ── Progress ── */}
      {mission.total_steps > 0 && (
        <div className="mission-card__progress">
          <span className="mission-card__steps">
            Step {mission.current_step} / {mission.total_steps}
          </span>
          <ProgressBar value={mission.progress_percent} />
          <span className="mission-card__pct">
            {mission.progress_percent.toFixed(1)}%
          </span>
        </div>
      )}

      {/* ── Budgets ── */}
      <BudgetBar
        label="Tokens"
        used={mission.tokens_used}
        budget={mission.budget_tokens}
      />
      <BudgetBar
        label="Time"
        used={Math.round(mission.elapsed_time_ms / 1000)}
        budget={
          mission.budget_time_ms !== null
            ? Math.round(mission.budget_time_ms / 1000)
            : null
        }
        unit="s"
      />

      {/* ── Last error ── */}
      {mission.last_error && (
        <p className="mission-card__error">{mission.last_error}</p>
      )}

      {/* ── Action buttons ── */}
      {!terminal && (
        <div className="mission-card__actions">
          {mission.status === "planned" && (
            <button
              className="btn btn--primary btn--sm"
              disabled={working}
              onClick={() => act(() => startMission(mission.id))}
            >
              {working ? "…" : "Start"}
            </button>
          )}
          {mission.status === "running" && (
            <button
              className="btn btn--warning btn--sm"
              disabled={working}
              onClick={() => act(() => pauseMission(mission.id))}
            >
              {working ? "…" : "Pause"}
            </button>
          )}
          {mission.status === "paused" && (
            <button
              className="btn btn--primary btn--sm"
              disabled={working}
              onClick={() => act(() => resumeMission(mission.id))}
            >
              {working ? "…" : "Resume"}
            </button>
          )}
          {mission.status === "waiting_approval" && (
            <button
              className="btn btn--info btn--sm"
              onClick={() => setShowCheckpoints((v) => !v)}
            >
              {showCheckpoints ? "Hide checkpoints" : "Review checkpoint"}
            </button>
          )}
          <button
            className="btn btn--danger btn--sm"
            disabled={working}
            onClick={() => act(() => cancelMission(mission.id))}
          >
            {working ? "…" : "Cancel"}
          </button>
        </div>
      )}

      {err && <p className="mission-card__action-error">{err}</p>}

      {/* ── Checkpoint panel ── */}
      {showCheckpoints && (
        <CheckpointPanel
          missionId={mission.id}
          onResolved={() => {
            setShowCheckpoints(false);
            onAction();
          }}
        />
      )}

      {/* ── Meta ── */}
      <div className="mission-card__meta">
        <span className="mission-card__meta-item">
          Policy: {mission.checkpoint_policy}
        </span>
        {mission.chain_ids.length > 0 && (
          <span className="mission-card__meta-item">
            Chains: {mission.chain_ids.length}
          </span>
        )}
        <span className="mission-card__meta-item mission-card__meta-item--time">
          {new Date(mission.created_at).toLocaleString()}
        </span>
      </div>
    </div>
  );
};

// ─── Status filter tabs ───────────────────────────────────────────────────────

const ALL_FILTER = "all";
const FILTER_TABS: { value: string; label: string }[] = [
  { value: ALL_FILTER,          label: "All" },
  { value: "planned",           label: "Planned" },
  { value: "running",           label: "Running" },
  { value: "waiting_approval",  label: "Waiting" },
  { value: "paused",            label: "Paused" },
  { value: "completed",         label: "Completed" },
  { value: "failed",            label: "Failed" },
  { value: "cancelled",         label: "Cancelled" },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

const POLL_MS = 8_000;

export const MissionsPage: React.FC = () => {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>(ALL_FILTER);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listMissions(
        filter === ALL_FILTER ? undefined : filter,
        100,
      );
      setMissions(res.missions);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  // Initial + filter change load
  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  // Auto-refresh while active missions exist
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    const hasActive = missions.some((m) =>
      ["running", "waiting_approval", "planned"].includes(m.status)
    );
    if (autoRefresh && hasActive) {
      intervalRef.current = setInterval(() => void load(), POLL_MS);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, missions, load]);

  return (
    <div className="missions-page">
      <div className="missions-page__header">
        <h1 className="missions-page__title">Autonomous Missions</h1>
        <div className="missions-page__controls">
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => void load()}
            title="Refresh"
          >
            ↻ Refresh
          </button>
          <label className="missions-page__auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            {" "}Auto-refresh
          </label>
        </div>
      </div>

      {/* ── Filter tabs ── */}
      <div className="missions-page__filters" role="tablist">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            aria-selected={filter === tab.value}
            className={`filter-tab${filter === tab.value ? " filter-tab--active" : ""}`}
            onClick={() => setFilter(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Content ── */}
      {loading && <p className="missions-page__loading">Loading…</p>}
      {error && <p className="missions-page__error">Error: {error}</p>}

      {!loading && !error && missions.length === 0 && (
        <div className="missions-page__empty">
          <p>No missions found.</p>
          <p className="missions-page__empty-hint">
            Missions are created by the assistant when executing multi-step goals.
          </p>
        </div>
      )}

      <div className="missions-page__list">
        {missions.map((m) => (
          <MissionCard key={m.id} mission={m} onAction={() => void load()} />
        ))}
      </div>
    </div>
  );
};
