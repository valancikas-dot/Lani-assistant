import React, { useEffect, useState, useCallback, useRef } from "react";
import { getWorldState } from "../lib/api";
import type { WorldState } from "../lib/types";

const Section: React.FC<{ title: string; count?: number; children: React.ReactNode }> = ({
  title,
  count,
  children,
}) => (
  <div
    style={{
      background: "var(--color-bg-surface, #1a1a1a)",
      border: "1px solid var(--color-border, #333)",
      borderRadius: 8,
      padding: "0.875rem 1rem",
      marginBottom: "0.75rem",
    }}
  >
    <h3 style={{ margin: "0 0 0.625rem", fontSize: 13, fontWeight: 600, color: "var(--color-text-muted, #aaa)", textTransform: "uppercase", letterSpacing: 0.5, display: "flex", alignItems: "center", gap: "0.5rem" }}>
      {title}
      {count !== undefined && (
        <span style={{ background: "var(--color-bg, #111)", borderRadius: 10, padding: "1px 7px", fontSize: 11, color: "var(--color-text-muted, #888)", fontWeight: 400 }}>
          {count}
        </span>
      )}
    </h3>
    {children}
  </div>
);

const Empty: React.FC<{ label: string }> = ({ label }) => (
  <p style={{ margin: 0, fontSize: 13, color: "var(--color-text-muted, #555)", fontStyle: "italic" }}>{label}</p>
);

const StatusDot: React.FC<{ live: boolean }> = ({ live }) => (
  <span
    style={{
      display: "inline-block",
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: live ? "#22c55e" : "#6b7280",
      marginRight: 6,
      boxShadow: live ? "0 0 6px #22c55e" : "none",
    }}
  />
);

const POLL_INTERVAL = 5000;

export const StateViewerPage: React.FC = () => {
  const [state, setState] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchState = useCallback(async () => {
    try {
      const s = await getWorldState();
      setState(s);
      setLastRefresh(new Date());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load world state");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchState();
  }, [fetchState]);

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => { void fetchState(); }, POLL_INTERVAL);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [autoRefresh, fetchState]);

  return (
    <div className="page state-viewer-page" style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>
            <StatusDot live={autoRefresh} />
            World State
          </h1>
          <p style={{ margin: "0.25rem 0 0", color: "var(--color-text-muted, #888)", fontSize: 13 }}>
            Live desktop context snapshot
            {lastRefresh && ` · Updated ${lastRefresh.toLocaleTimeString()}`}
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh (5s)
          </label>
          <button className="btn" onClick={() => { void fetchState(); }} style={{ fontSize: 13 }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p style={{ color: "#ef4444" }}>Error: {error}</p>}

      {state && (
        <>
          {/* Open apps */}
          <Section title="Open Apps" count={state.open_apps.length}>
            {state.open_apps.length === 0 ? (
              <Empty label="No apps detected" />
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                {state.open_apps.map((app, i) => (
                  <span
                    key={`${app.name}-${i}`}
                    style={{
                      background: app.is_frontmost ? "#1e3a5f" : "var(--color-bg, #111)",
                      color: app.is_frontmost ? "#60a5fa" : "inherit",
                      borderRadius: 6,
                      padding: "3px 10px",
                      fontSize: 13,
                      border: "1px solid var(--color-border, #333)",
                    }}
                  >
                    {app.is_frontmost ? "▶ " : ""}{app.name}
                    {app.pid !== undefined && <span style={{ color: "var(--color-text-muted, #666)", fontSize: 11 }}> ({app.pid})</span>}
                  </span>
                ))}
              </div>
            )}
          </Section>

          {/* Active windows */}
          <Section title="Active Windows" count={state.active_windows.length}>
            {state.active_windows.length === 0 ? (
              <Empty label="No windows tracked" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {state.active_windows.map((w, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                    <span style={{ color: "var(--color-text-muted, #aaa)", minWidth: 120, fontWeight: 500 }}>{w.app_name}</span>
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{w.title || "—"}</span>
                    {w.is_minimized && <span style={{ fontSize: 11, color: "var(--color-text-muted, #666)" }}>minimised</span>}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Browser tabs */}
          <Section title="Browser Tabs" count={state.browser_tabs.length}>
            {state.browser_tabs.length === 0 ? (
              <Empty label="No tabs tracked" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {state.browser_tabs.map((tab, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                    {tab.active && <span style={{ color: "#22c55e", fontSize: 10 }}>●</span>}
                    <a
                      href={tab.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: tab.active ? "#60a5fa" : "inherit", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textDecoration: "none" }}
                      title={tab.url}
                    >
                      {tab.title || tab.url}
                    </a>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Recent files */}
          <Section title="Recent Files" count={state.recent_files.length}>
            {state.recent_files.length === 0 ? (
              <Empty label="No recent files" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {state.recent_files.map((f, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                    <span style={{ color: "var(--color-text-muted, #888)", fontSize: 11, minWidth: 60, fontFamily: "monospace" }}>{f.operation}</span>
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace", fontSize: 12 }} title={f.path}>{f.path}</span>
                    <span style={{ color: "var(--color-text-muted, #666)", fontSize: 11 }}>{f.tool}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Last actions */}
          <Section title="Last Actions" count={state.last_actions.length}>
            {state.last_actions.length === 0 ? (
              <Empty label="No actions recorded yet" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {state.last_actions.slice(0, 10).map((a, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                    <span
                      style={{
                        minWidth: 60,
                        fontSize: 11,
                        padding: "2px 6px",
                        borderRadius: 4,
                        background: a.status === "success" ? "#14532d" : a.status === "error" ? "#4c0519" : "#1a1a1a",
                        color: a.status === "success" ? "#4ade80" : a.status === "error" ? "#f87171" : "#aaa",
                        textAlign: "center",
                      }}
                    >
                      {a.status}
                    </span>
                    <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-text-muted, #aaa)", minWidth: 120 }}>{a.tool}</span>
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.summary}</span>
                    {a.duration_ms !== undefined && (
                      <span style={{ fontSize: 11, color: "var(--color-text-muted, #666)" }}>{a.duration_ms}ms</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Pending tasks */}
          <Section title="Pending Tasks" count={state.pending_tasks.length}>
            {state.pending_tasks.length === 0 ? (
              <Empty label="No pending tasks" />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                {state.pending_tasks.map((t) => (
                  <div key={t.task_id} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: 13 }}>
                    <span style={{ fontFamily: "monospace", fontSize: 11, color: "var(--color-text-muted, #888)" }}>{t.tool}</span>
                    <span style={{ flex: 1 }}>{t.description}</span>
                    {t.scheduled_at && (
                      <span style={{ fontSize: 11, color: "var(--color-text-muted, #666)" }}>
                        @ {new Date(t.scheduled_at).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Clipboard & Screenshot */}
          {(state.clipboard_preview || state.last_screenshot) && (
            <div style={{ display: "grid", gridTemplateColumns: state.last_screenshot ? "1fr 1fr" : "1fr", gap: "0.75rem" }}>
              {state.clipboard_preview && (
                <Section title="Clipboard Preview">
                  <pre style={{ margin: 0, fontSize: 12, overflow: "auto", maxHeight: 80, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--color-text-muted, #aaa)" }}>
                    {state.clipboard_preview}
                  </pre>
                </Section>
              )}
              {state.last_screenshot && (
                <Section title="Last Screenshot">
                  <img
                    src={`data:image/png;base64,${state.last_screenshot}`}
                    alt="Last screenshot"
                    style={{ maxWidth: "100%", borderRadius: 4, border: "1px solid var(--color-border, #333)" }}
                  />
                </Section>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default StateViewerPage;
