/**
 * SecurityPage – security posture dashboard for Lani.
 *
 * Sections
 * ────────
 *   1. Environment & keys   – APP_ENV badge, encryption / secret-key status
 *   2. Voice security        – speaker verification, voice lock
 *   3. Fallback PIN           – enable / change the PIN with live form
 *   4. Approval policy        – colour-coded table of tool → level
 *   5. Recent security events – last 10 audit entries from the security router
 */

import React, { useEffect, useState } from "react";
import { useSecurityStore } from "../stores/securityStore";
import { useI18n } from "../i18n/useI18n";
import type { ApprovalLevel } from "../lib/types";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const ENV_BADGE: Record<string, { label: string; color: string }> = {
  production: { label: "production", color: "#e53935" },
  development: { label: "development", color: "#fb8c00" },
  test: { label: "test", color: "#039be5" },
};

const LEVEL_COLOR: Record<ApprovalLevel, string> = {
  read_safe: "#43a047",
  write_requires_approval: "#fb8c00",
  destructive_requires_approval: "#e53935",
  security_sensitive_requires_approval: "#8e24aa",
};

function EnvBadge({ env }: { env: string }) {
  const cfg = ENV_BADGE[env.toLowerCase()] ?? { label: env, color: "#546e7a" };
  return (
    <span
      style={{
        background: cfg.color,
        color: "#fff",
        borderRadius: 4,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: 1,
        textTransform: "uppercase",
      }}
    >
      {cfg.label}
    </span>
  );
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: ok ? "#43a047" : "#e53935",
          display: "inline-block",
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}

function levelLabel(level: string): string {
  const MAP: Record<string, string> = {
    read_safe: "Read-safe",
    write_requires_approval: "Write (approval)",
    destructive_requires_approval: "Destructive (approval)",
    security_sensitive_requires_approval: "Security-sensitive (approval)",
  };
  return MAP[level] ?? level;
}

// ─── Component ───────────────────────────────────────────────────────────────

export const SecurityPage: React.FC = () => {
  const {
    status,
    isLoading,
    error,
    fetchStatus,
    pinValue,
    confirmPinValue,
    pinSaving,
    pinMessage,
    pinError,
    setPinValue,
    setConfirmPinValue,
    savePin,
  } = useSecurityStore();

  const { t } = useI18n();
  const [showPinForm, setShowPinForm] = useState(false);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  if (isLoading && !status) {
    return <div style={{ padding: 32, color: "var(--color-muted)" }}>Loading security status…</div>;
  }

  if (error) {
    return (
      <div style={{ padding: 32 }}>
        <p style={{ color: "#e53935" }}>Failed to load security status: {error}</p>
        <button onClick={() => void fetchStatus()}>Retry</button>
      </div>
    );
  }

  return (
    <div style={{ padding: "24px 32px", maxWidth: 860 }}>
      {/* ── Header ── */}
      <h1 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 4px" }}>
        {t("security", "title")}
      </h1>
      <p style={{ color: "var(--color-muted)", margin: "0 0 28px" }}>
        {t("security", "subtitle")}
      </p>

      {status && (
        <>
          {/* ── 1. Environment & Keys ── */}
          <Section title={t("security", "environment")}>
            <Row label="Runtime environment">
              <EnvBadge env={status.app_env} />
            </Row>
            <Row label={t("security", "connector_encryption")}>
              <StatusDot
                ok={status.connector_encryption_configured}
                label={
                  status.connector_encryption_configured
                    ? t("security", "configured")
                    : t("security", "not_configured")
                }
              />
            </Row>
            <Row label="Secret key">
              <StatusDot
                ok={status.secret_key_configured}
                label={status.secret_key_configured ? t("security", "configured") : t("security", "not_configured")}
              />
            </Row>
          </Section>

          {/* ── 2. Voice Security ── */}
          <Section title={t("security", "speaker_verification")}>
            <Row label={t("security", "speaker_verification")}>
              <StatusDot
                ok={status.speaker_verification_enabled}
                label={status.speaker_verification_enabled ? "Enabled" : "Disabled"}
              />
            </Row>
          </Section>

          {/* ── 3. Fallback PIN ── */}
          <Section title={t("security", "fallback_pin")}>
            <Row label="PIN status">
              <StatusDot
                ok={status.fallback_pin_enabled}
                label={
                  status.fallback_pin_enabled
                    ? `Enabled (${status.fallback_pin_scheme})`
                    : "Not set"
                }
              />
            </Row>
            {!showPinForm ? (
              <button
                style={btnStyle}
                onClick={() => setShowPinForm(true)}
              >
                {status.fallback_pin_enabled
                  ? t("security", "update_pin")
                  : t("security", "set_pin")}
              </button>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 280 }}>
                <input
                  type="password"
                  placeholder={t("security", "pin_placeholder")}
                  value={pinValue}
                  onChange={(e) => setPinValue(e.target.value)}
                  style={inputStyle}
                />
                <input
                  type="password"
                  placeholder={t("security", "confirm_pin_placeholder")}
                  value={confirmPinValue}
                  onChange={(e) => setConfirmPinValue(e.target.value)}
                  style={inputStyle}
                />
                {pinError && (
                  <p style={{ color: "#e53935", fontSize: 13, margin: 0 }}>{pinError}</p>
                )}
                {pinMessage && (
                  <p style={{ color: "#43a047", fontSize: 13, margin: 0 }}>{pinMessage}</p>
                )}
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    style={{ ...btnStyle, opacity: pinSaving ? 0.6 : 1 }}
                    onClick={() => void savePin()}
                    disabled={pinSaving}
                  >
                    {pinSaving ? "Saving…" : "Save PIN"}
                  </button>
                  <button
                    style={{ ...btnStyle, background: "var(--color-surface-2, #2a2a2a)" }}
                    onClick={() => setShowPinForm(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </Section>

          {/* ── 4. Approval Policy ── */}
          <Section title={t("security", "approval_policy")}>
            {/* Summary counts */}
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
              {(Object.entries(status.approval_policy_summary) as [ApprovalLevel, number][]).map(
                ([level, count]) => (
                  <div
                    key={level}
                    style={{
                      background: LEVEL_COLOR[level] + "22",
                      border: `1px solid ${LEVEL_COLOR[level]}`,
                      borderRadius: 6,
                      padding: "6px 12px",
                      fontSize: 13,
                    }}
                  >
                    <span style={{ color: LEVEL_COLOR[level], fontWeight: 600 }}>
                      {levelLabel(level)}
                    </span>{" "}
                    <span style={{ color: "var(--color-muted)" }}>({count} tools)</span>
                  </div>
                )
              )}
            </div>
          </Section>

          {/* ── 5. Recent Security Events ── */}
          <Section title={t("security", "recent_events")}>
            {status.recent_security_events.length === 0 ? (
              <p style={{ color: "var(--color-muted)", margin: 0 }}>
                {t("security", "no_events")}
              </p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ color: "var(--color-muted)", textAlign: "left" }}>
                    <th style={thStyle}>Time</th>
                    <th style={thStyle}>Command</th>
                    <th style={thStyle}>Status</th>
                    <th style={thStyle}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {status.recent_security_events.map((ev) => (
                    <tr key={ev.id} style={{ borderTop: "1px solid var(--color-border, #333)" }}>
                      <td style={tdStyle}>
                        {ev.timestamp
                          ? new Date(ev.timestamp).toLocaleTimeString()
                          : "–"}
                      </td>
                      <td style={{ ...tdStyle, fontFamily: "monospace" }}>{ev.command}</td>
                      <td style={tdStyle}>
                        <span
                          style={{
                            color:
                              ev.status === "success"
                                ? "#43a047"
                                : ev.status === "failure" || ev.status === "error"
                                ? "#e53935"
                                : "var(--color-text)",
                            fontWeight: 600,
                          }}
                        >
                          {ev.status}
                        </span>
                      </td>
                      <td style={{ ...tdStyle, color: "var(--color-muted)" }}>
                        {ev.error_message ?? "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}
    </div>
  );
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 32 }}>
      <h2
        style={{
          fontSize: 15,
          fontWeight: 700,
          margin: "0 0 12px",
          paddingBottom: 6,
          borderBottom: "1px solid var(--color-border, #333)",
          color: "var(--color-text)",
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 0",
        borderBottom: "1px solid var(--color-border, #222)",
        fontSize: 14,
      }}
    >
      <span style={{ color: "var(--color-muted)" }}>{label}</span>
      <span>{children}</span>
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const btnStyle: React.CSSProperties = {
  padding: "7px 16px",
  borderRadius: 6,
  border: "none",
  background: "var(--color-accent, #6366f1)",
  color: "#fff",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  marginTop: 8,
};

const inputStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  border: "1px solid var(--color-border, #444)",
  background: "var(--color-surface, #1a1a1a)",
  color: "var(--color-text, #f0f0f0)",
  fontSize: 14,
  outline: "none",
};

const thStyle: React.CSSProperties = {
  padding: "4px 8px",
  fontWeight: 600,
  fontSize: 12,
};

const tdStyle: React.CSSProperties = {
  padding: "6px 8px",
};
