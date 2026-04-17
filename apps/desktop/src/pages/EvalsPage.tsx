import React, { useEffect, useState, useCallback } from "react";
import { getEvals, getEvalStats, rateEval } from "../lib/api";
import type { EvalEntry, EvalStats } from "../lib/types";

// ─── Stat Card ────────────────────────────────────────────────────────────────

const StatCard: React.FC<{ label: string; value: string | number; sub?: string; accent?: string }> = ({
  label,
  value,
  sub,
  accent,
}) => (
  <div
    style={{
      background: "var(--color-bg-surface, #1a1a1a)",
      border: "1px solid var(--color-border, #333)",
      borderRadius: 8,
      padding: "0.875rem 1rem",
      minWidth: 130,
      flex: 1,
    }}
  >
    <div style={{ fontSize: 22, fontWeight: 700, color: accent ?? "inherit" }}>{value}</div>
    <div style={{ fontSize: 12, color: "var(--color-text-muted, #888)", marginTop: 2 }}>{label}</div>
    {sub && <div style={{ fontSize: 11, color: "var(--color-text-muted, #666)", marginTop: 2 }}>{sub}</div>}
  </div>
);

// ─── Rating stars ─────────────────────────────────────────────────────────────

const Stars: React.FC<{ evalId: number; current?: number; onRate: (id: number, r: number) => void }> = ({
  evalId,
  current,
  onRate,
}) => (
  <span style={{ display: "inline-flex", gap: 1 }}>
    {[1, 2, 3, 4, 5].map((n) => (
      <button
        key={n}
        onClick={(e) => { e.stopPropagation(); onRate(evalId, n); }}
        title={`Rate ${n}`}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: "0 1px",
          fontSize: 14,
          color: current !== undefined && n <= current ? "#f59e0b" : "var(--color-text-muted, #444)",
          lineHeight: 1,
        }}
      >
        ★
      </button>
    ))}
  </span>
);

// ─── Mini timeline bar ────────────────────────────────────────────────────────

const Timeline: React.FC<{ data: EvalStats["daily_timeline"] }> = ({ data }) => {
  const days = Object.keys(data).sort().slice(-14);
  if (days.length === 0) return <p style={{ color: "var(--color-text-muted, #555)", fontSize: 13, fontStyle: "italic" }}>No timeline data</p>;
  const maxTotal = Math.max(...days.map((d) => data[d].total), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 50 }}>
      {days.map((day) => {
        const { success, error, total } = data[day];
        const h = Math.max((total / maxTotal) * 50, 2);
        const errFrac = total > 0 ? error / total : 0;
        return (
          <div
            key={day}
            title={`${day}: ${success} ok, ${error} err`}
            style={{
              flex: 1,
              height: h,
              borderRadius: "2px 2px 0 0",
              background: errFrac > 0.3 ? "#ef4444" : errFrac > 0 ? "#f59e0b" : "#22c55e",
              opacity: 0.85,
              cursor: "default",
            }}
          />
        );
      })}
    </div>
  );
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export const EvalsPage: React.FC = () => {
  const [stats, setStats] = useState<EvalStats | null>(null);
  const [evals, setEvals] = useState<EvalEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [toolFilter, setToolFilter] = useState("");
  const [ratings, setRatings] = useState<Record<number, number>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statsRes, evalsRes] = await Promise.all([
        getEvalStats(30, toolFilter || undefined),
        getEvals({ limit: 50, tool: toolFilter || undefined }),
      ]);
      setStats(statsRes);
      setEvals(evalsRes.evals);
      setTotal(evalsRes.total);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load evals");
    } finally {
      setLoading(false);
    }
  }, [toolFilter]);

  useEffect(() => { void load(); }, [load]);

  const handleRate = useCallback(async (id: number, rating: number) => {
    setRatings((prev) => ({ ...prev, [id]: rating }));
    try {
      await rateEval(id, rating);
    } catch {
      /* noop — optimistic */
    }
  }, []);

  const tools = Array.from(new Set(evals.map((e) => e.tool_name))).sort();

  const fmt = (n: number) => (n * 100).toFixed(1) + "%";
  const fmtMs = (n: number) => n > 1000 ? (n / 1000).toFixed(2) + "s" : n.toFixed(0) + "ms";

  return (
    <div className="page evals-page" style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>📊 Evaluations</h1>
          <p style={{ margin: "0.25rem 0 0", color: "var(--color-text-muted, #888)", fontSize: 13 }}>
            Task quality metrics · {total} entries
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <select
            value={toolFilter}
            onChange={(e) => setToolFilter(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 6, border: "1px solid var(--color-border, #333)", background: "var(--color-bg-surface, #1a1a1a)", color: "inherit", fontSize: 13 }}
          >
            <option value="">All tools</option>
            {tools.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <button className="btn" onClick={() => { void load(); }} style={{ fontSize: 13 }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p style={{ color: "#ef4444" }}>Error: {error}</p>}

      {stats && (
        <>
          {/* Stats cards */}
          <div style={{ display: "flex", gap: "0.625rem", flexWrap: "wrap", marginBottom: "1rem" }}>
            <StatCard label="Total tasks" value={stats.total_tasks} />
            <StatCard label="Success rate" value={fmt(stats.task_success_rate)} accent="#22c55e" />
            <StatCard label="Failure rate" value={fmt(stats.task_failure_rate)} accent={stats.task_failure_rate > 0.2 ? "#ef4444" : "#aaa"} />
            <StatCard label="Approval freq." value={fmt(stats.approval_frequency)} accent="#60a5fa" />
            <StatCard label="Retry rate" value={fmt(stats.retry_rate)} accent={stats.retry_rate > 0.1 ? "#f59e0b" : "#aaa"} />
            <StatCard
              label="Avg exec time"
              value={fmtMs(stats.avg_execution_time_ms)}
              sub={stats.avg_quality_score !== undefined ? `Quality: ${stats.avg_quality_score.toFixed(2)}` : undefined}
            />
          </div>

          {/* Timeline + top failing tools */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1rem" }}>
            <div style={{ background: "var(--color-bg-surface, #1a1a1a)", border: "1px solid var(--color-border, #333)", borderRadius: 8, padding: "0.875rem 1rem" }}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5, color: "var(--color-text-muted, #888)" }}>
                Daily Timeline (14d)
              </h3>
              <Timeline data={stats.daily_timeline} />
              <div style={{ display: "flex", gap: "1rem", marginTop: 6, fontSize: 11, color: "var(--color-text-muted, #666)" }}>
                <span style={{ color: "#22c55e" }}>■</span> Success
                <span style={{ color: "#f59e0b" }}>■</span> Some errors
                <span style={{ color: "#ef4444" }}>■</span> Many errors
              </div>
            </div>

            <div style={{ background: "var(--color-bg-surface, #1a1a1a)", border: "1px solid var(--color-border, #333)", borderRadius: 8, padding: "0.875rem 1rem" }}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5, color: "var(--color-text-muted, #888)" }}>
                Top Failing Tools
              </h3>
              {stats.top_failing_tools.length === 0 ? (
                <p style={{ margin: 0, fontSize: 13, color: "var(--color-text-muted, #555)", fontStyle: "italic" }}>No failures</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                  {stats.top_failing_tools.map((t) => (
                    <div key={t.tool} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                      <span style={{ fontFamily: "monospace", flex: 1, fontSize: 12 }}>{t.tool}</span>
                      <span style={{ color: "#ef4444", minWidth: 30, textAlign: "right" }}>{t.errors}</span>
                      <span style={{ color: "var(--color-text-muted, #666)", fontSize: 11 }}>/ {t.total}</span>
                      <span
                        style={{
                          fontSize: 11,
                          padding: "1px 6px",
                          borderRadius: 4,
                          background: t.error_rate > 0.5 ? "#4c0519" : "#2a1a0a",
                          color: t.error_rate > 0.5 ? "#f87171" : "#f59e0b",
                        }}
                      >
                        {fmt(t.error_rate)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Recent evals table */}
      <div style={{ background: "var(--color-bg-surface, #1a1a1a)", border: "1px solid var(--color-border, #333)", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "0.75rem 1rem", borderBottom: "1px solid var(--color-border, #333)" }}>
          <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Recent Entries</h3>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--color-border, #333)", color: "var(--color-text-muted, #888)", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>
                <th style={{ textAlign: "left", padding: "6px 12px", fontWeight: 500 }}>Time</th>
                <th style={{ textAlign: "left", padding: "6px 12px", fontWeight: 500 }}>Tool</th>
                <th style={{ textAlign: "left", padding: "6px 12px", fontWeight: 500 }}>Command</th>
                <th style={{ textAlign: "center", padding: "6px 12px", fontWeight: 500 }}>Status</th>
                <th style={{ textAlign: "right", padding: "6px 12px", fontWeight: 500 }}>Duration</th>
                <th style={{ textAlign: "center", padding: "6px 12px", fontWeight: 500 }}>Rate</th>
              </tr>
            </thead>
            <tbody>
              {evals.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: "1.5rem", textAlign: "center", color: "var(--color-text-muted, #555)", fontStyle: "italic" }}>
                    No evaluation data yet
                  </td>
                </tr>
              )}
              {evals.map((e) => (
                <tr
                  key={e.id}
                  style={{ borderBottom: "1px solid var(--color-border, #222)" }}
                >
                  <td style={{ padding: "7px 12px", color: "var(--color-text-muted, #888)", whiteSpace: "nowrap", fontSize: 11 }}>
                    {new Date(e.timestamp).toLocaleTimeString()}
                  </td>
                  <td style={{ padding: "7px 12px", fontFamily: "monospace", fontSize: 12, color: "var(--color-text-muted, #aaa)" }}>
                    {e.tool_name}
                  </td>
                  <td style={{ padding: "7px 12px", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={e.command}>
                    {e.command}
                  </td>
                  <td style={{ padding: "7px 12px", textAlign: "center" }}>
                    <span
                      style={{
                        fontSize: 11,
                        padding: "2px 7px",
                        borderRadius: 4,
                        background: e.status === "success" ? "#14532d" : e.status === "error" ? "#4c0519" : "#1a1a2e",
                        color: e.status === "success" ? "#4ade80" : e.status === "error" ? "#f87171" : "#93c5fd",
                      }}
                    >
                      {e.status}
                    </span>
                    {e.required_approval && (
                      <span style={{ marginLeft: 4, fontSize: 10, color: "#60a5fa" }}>✋</span>
                    )}
                  </td>
                  <td style={{ padding: "7px 12px", textAlign: "right", color: "var(--color-text-muted, #888)", fontSize: 12, whiteSpace: "nowrap" }}>
                    {e.duration_ms !== undefined ? fmtMs(e.duration_ms) : "—"}
                  </td>
                  <td style={{ padding: "7px 12px", textAlign: "center" }}>
                    <Stars
                      evalId={e.id}
                      current={ratings[e.id] ?? e.quality_score}
                      onRate={handleRate}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default EvalsPage;
