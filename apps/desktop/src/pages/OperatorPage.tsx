/**
 * OperatorPage – desktop automation control panel.
 *
 * Sections:
 *  1. Platform banner
 *  2. Quick actions (screenshot, list windows, open app)
 *  3. Capability grid
 *  4. Open windows list
 *  5. Recent actions history
 */

import React, { useEffect, useState } from "react";
import { useOperatorStore } from "../stores/operatorStore";
import { useI18n } from "../i18n/useI18n";
import type { OperatorActionName, OperatorCapability } from "../lib/types";

// ─── Risk badge ───────────────────────────────────────────────────────────────

const RiskBadge: React.FC<{ level: "low" | "medium" | "high" }> = ({ level }) => {
  const { t } = useI18n();
  const colours: Record<string, string> = {
    low: "#28a745",
    medium: "#fd7e14",
    high: "#dc3545",
  };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: "#fff",
        background: colours[level] ?? "#999",
        borderRadius: 4,
        padding: "1px 6px",
        marginLeft: 4,
      }}
    >
      {t("operator", `risk_${level}` as "risk_low" | "risk_medium" | "risk_high")}
    </span>
  );
};

// ─── Capability card ─────────────────────────────────────────────────────────

const CapabilityCard: React.FC<{ cap: OperatorCapability; onRun: (name: OperatorActionName) => void; busy: boolean }> = ({
  cap,
  onRun,
  busy,
}) => {
  const { t } = useI18n();
  return (
    <div
      className="operator-cap-card"
      style={{
        border: "1px solid #e0e0e0",
        borderRadius: 8,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        background: "#fafafa",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <strong style={{ fontSize: 13 }}>{cap.name}</strong>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {cap.requires_approval && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "#856404",
                background: "#fff3cd",
                border: "1px solid #ffc107",
                borderRadius: 4,
                padding: "1px 6px",
              }}
            >
              {t("operator", "approval_required_badge")}
            </span>
          )}
          <RiskBadge level={cap.risk_level} />
        </div>
      </div>
      <p style={{ fontSize: 12, color: "#555", margin: 0 }}>{cap.description}</p>
      {Object.keys(cap.params_schema).length > 0 && (
        <details style={{ fontSize: 12 }}>
          <summary style={{ cursor: "pointer", color: "#666" }}>
            {t("operator", "params_schema_title")}
          </summary>
          <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
            {Object.entries(cap.params_schema).map(([k, v]) => (
              <li key={k}>
                <code>{k}</code> — {v}
              </li>
            ))}
          </ul>
        </details>
      )}
      <button
        onClick={() => onRun(cap.name)}
        disabled={busy}
        style={{
          marginTop: 4,
          padding: "4px 10px",
          fontSize: 12,
          borderRadius: 5,
          border: "1px solid #aaa",
          background: "#fff",
          cursor: busy ? "not-allowed" : "pointer",
          alignSelf: "flex-start",
        }}
      >
        {busy ? t("operator", "executing") : "▶ Run"}
      </button>
    </div>
  );
};

// ─── Main page ────────────────────────────────────────────────────────────────

export const OperatorPage: React.FC = () => {
  const { t } = useI18n();
  const {
    manifest,
    capabilities,
    platform,
    platformAvailable,
    windows,
    recentActions,
    isLoadingCapabilities,
    isLoadingWindows,
    isExecuting,
    error,
    lastScreenshotPath,
    fetchCapabilities,
    fetchWindows,
    execute,
    clearError,
    clearRecent,
  } = useOperatorStore();

  const [appNameInput, setAppNameInput] = useState("");

  useEffect(() => {
    void fetchCapabilities();
  }, [fetchCapabilities]);

  const handleRun = async (action: OperatorActionName, params: Record<string, unknown> = {}) => {
    await execute(action, params);
  };

  const platformLabel = platform === "macos"
    ? "macOS"
    : platform === "windows"
    ? "Windows"
    : platform === "linux"
    ? "Linux"
    : t("common", "unknown");

  return (
    <div className="page operator-page" style={{ padding: "24px 32px", maxWidth: 900 }}>
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="page__header" style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{t("operator", "title")}</h1>
        <p style={{ color: "#666", marginTop: 4 }}>{t("operator", "subtitle")}</p>
      </div>

      {/* ── Platform banner ──────────────────────────────────────────────── */}
      <div
        style={{
          background: platformAvailable ? "#e8f5e9" : "#fff3cd",
          border: `1px solid ${platformAvailable ? "#a5d6a7" : "#ffc107"}`,
          borderRadius: 8,
          padding: "10px 16px",
          marginBottom: 24,
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 13,
        }}
      >
        <span>{platformAvailable ? "🖥️" : "⚠️"}</span>
        <span>
          <strong>{t("operator", "platform_label")}:</strong> {platformLabel}
        </span>
        {!platformAvailable && (
          <span style={{ marginLeft: 8, color: "#856404" }}>
            — {t("operator", "platform_unavailable")}
          </span>
        )}
      </div>

      {error && (
        <div
          style={{
            background: "#fdecea",
            border: "1px solid #f5c6cb",
            borderRadius: 8,
            padding: "10px 16px",
            marginBottom: 20,
            color: "#721c24",
            fontSize: 13,
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>⚠ {error}</span>
          <button onClick={clearError} style={{ background: "none", border: "none", cursor: "pointer" }}>
            ✕
          </button>
        </div>
      )}

      {isLoadingCapabilities ? (
        <p style={{ color: "#888" }}>{t("common", "loading")}</p>
      ) : (
        <>
          {/* ── Quick actions ─────────────────────────────────────────── */}
          <section style={{ marginBottom: 28 }}>
            <h2 style={{ fontSize: 15, marginBottom: 12 }}>{t("operator", "quick_actions_title")}</h2>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <button
                disabled={isExecuting || !platformAvailable}
                onClick={() => handleRun("take_screenshot")}
                style={quickBtnStyle}
              >
                📸 {t("operator", "screenshot_btn")}
              </button>

              <button
                disabled={isExecuting || isLoadingWindows || !platformAvailable}
                onClick={() => { void fetchWindows(); }}
                style={quickBtnStyle}
              >
                🪟 {t("operator", "list_windows_btn")}
              </button>

              {/* Open app mini-form */}
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  type="text"
                  placeholder={t("operator", "open_app_placeholder")}
                  value={appNameInput}
                  onChange={(e) => setAppNameInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && appNameInput.trim()) {
                      void handleRun("open_app", { app_name: appNameInput.trim() });
                      setAppNameInput("");
                    }
                  }}
                  style={{
                    padding: "6px 10px",
                    borderRadius: 5,
                    border: "1px solid #ccc",
                    fontSize: 13,
                    width: 200,
                  }}
                />
                <button
                  disabled={isExecuting || !appNameInput.trim() || !platformAvailable}
                  onClick={() => {
                    if (appNameInput.trim()) {
                      void handleRun("open_app", { app_name: appNameInput.trim() });
                      setAppNameInput("");
                    }
                  }}
                  style={quickBtnStyle}
                >
                  {t("operator", "open_app_submit")}
                </button>
              </div>
            </div>

            {/* Screenshot path feedback */}
            {lastScreenshotPath && (
              <p style={{ marginTop: 10, fontSize: 12, color: "#555" }}>
                ✅ {t("operator", "screenshot_saved")}: <code>{lastScreenshotPath}</code>
              </p>
            )}
          </section>

          {/* ── Open windows ─────────────────────────────────────────── */}
          {windows.length > 0 && (
            <section style={{ marginBottom: 28 }}>
              <h2 style={{ fontSize: 15, marginBottom: 10 }}>{t("operator", "windows_title")}</h2>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {windows.map((w, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 6,
                      border: "1px solid #ddd",
                      fontSize: 13,
                      background: "#f8f8f8",
                      cursor: "pointer",
                    }}
                    onClick={() => handleRun("focus_window", { window_title: w.app })}
                    title="Click to focus"
                  >
                    🪟 {w.app}
                  </div>
                ))}
              </div>
              {isLoadingWindows && <p style={{ fontSize: 12, color: "#888", marginTop: 6 }}>Refreshing…</p>}
            </section>
          )}

          {/* ── Capability grid ──────────────────────────────────────── */}
          <section style={{ marginBottom: 28 }}>
            <h2 style={{ fontSize: 15, marginBottom: 12 }}>{t("operator", "capabilities_title")}</h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                gap: 12,
              }}
            >
              {capabilities.map((cap) => (
                <CapabilityCard
                  key={cap.name}
                  cap={cap}
                  busy={isExecuting}
                  onRun={(name) => handleRun(name)}
                />
              ))}
            </div>
          </section>

          {/* ── Recent actions ───────────────────────────────────────── */}
          <section>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <h2 style={{ fontSize: 15, margin: 0 }}>{t("operator", "recent_title")}</h2>
              {recentActions.length > 0 && (
                <button onClick={clearRecent} style={{ fontSize: 12, color: "#888", background: "none", border: "none", cursor: "pointer" }}>
                  {t("operator", "clear_recent")}
                </button>
              )}
            </div>
            {recentActions.length === 0 ? (
              <p style={{ fontSize: 13, color: "#999" }}>{t("operator", "no_recent")}</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {recentActions.map((entry, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "10px 14px",
                      borderRadius: 7,
                      border: `1px solid ${entry.response.ok ? (entry.response.requires_approval ? "#ffc107" : "#a5d6a7") : "#f5c6cb"}`,
                      background: entry.response.ok
                        ? entry.response.requires_approval
                          ? "#fffde7"
                          : "#f1f8f4"
                        : "#fdecea",
                      fontSize: 13,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>
                        {entry.response.ok
                          ? entry.response.requires_approval
                            ? "⏳"
                            : "✅"
                          : "❌"}{" "}
                        {entry.action}
                      </strong>
                      <span style={{ color: "#888", fontSize: 11 }}>
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p style={{ margin: "4px 0 0", color: "#555" }}>{entry.response.message}</p>
                    {entry.response.approval_id && (
                      <p style={{ margin: "2px 0 0", fontSize: 11, color: "#856404" }}>
                        Approval #{entry.response.approval_id}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};

// ─── Shared button style ─────────────────────────────────────────────────────

const quickBtnStyle: React.CSSProperties = {
  padding: "7px 14px",
  borderRadius: 6,
  border: "1px solid #ccc",
  background: "#fff",
  fontSize: 13,
  cursor: "pointer",
  fontWeight: 500,
};
