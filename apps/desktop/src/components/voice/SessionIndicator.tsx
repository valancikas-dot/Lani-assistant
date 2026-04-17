/**
 * SessionIndicator – shows voice session unlock status + countdown.
 * Displayed below the wake indicator when session is active.
 */

import React from "react";
import type { WakeSessionInfo, WakeVoiceState } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

interface Props {
  session: WakeSessionInfo;
  secondsRemaining: number | null;
  voiceState?: WakeVoiceState;
  sessionExpired?: boolean;
  reverificationRequired?: boolean;
  securityMode?: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Color + label configuration for each voice state. */
const STATE_CONFIG: Record<
  WakeVoiceState,
  { color: string; bg: string; border: string; pulse?: boolean }
> = {
  idle:                     { color: "#6b7280", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)" },
  wake_detected:            { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)" },
  listening:                { color: "#3b82f6", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.3)", pulse: true },
  verifying:                { color: "#8b5cf6", bg: "rgba(139,92,246,0.12)", border: "rgba(139,92,246,0.3)", pulse: true },
  unlocked:                 { color: "#10b981", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.3)" },
  processing:               { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)", pulse: true },
  responding:               { color: "#10b981", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.3)" },
  speaking:                 { color: "#06b6d4", bg: "rgba(6,182,212,0.12)", border: "rgba(6,182,212,0.3)", pulse: true },
  waiting_for_confirmation: { color: "#f59e0b", bg: "rgba(245,158,11,0.15)", border: "rgba(245,158,11,0.4)" },
  blocked:                  { color: "#ef4444", bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.3)" },
  timeout:                  { color: "#ef4444", bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.3)" },
};

const PULSE_KEYFRAMES = `
@keyframes lani-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
`;

export const SessionIndicator: React.FC<Props> = ({
  session,
  secondsRemaining,
  voiceState,
  sessionExpired,
  reverificationRequired,
  securityMode = "disabled",
}) => {
  const { t } = useI18n();

  // Show "re-activate" pill when session has timed out
  if (!session.unlocked && (sessionExpired || voiceState === "timeout")) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "4px 10px",
          borderRadius: "6px",
          background: reverificationRequired
            ? "rgba(139,92,246,0.12)"
            : "rgba(239,68,68,0.12)",
          border: `1px solid ${reverificationRequired ? "rgba(139,92,246,0.3)" : "rgba(239,68,68,0.3)"}`,
          fontSize: "12px",
          color: reverificationRequired ? "#8b5cf6" : "#ef4444",
          fontWeight: 500,
        }}
      >
        <span>
          {reverificationRequired
            ? t("session", "reverification_required")
            : t("session", "expired")}
        </span>
      </div>
    );
  }

  if (!session.unlocked) return null;

  const urgent = (secondsRemaining ?? 0) < 20;
  const stateKey = voiceState ?? "unlocked";
  const cfg = STATE_CONFIG[stateKey] ?? STATE_CONFIG.unlocked;

  // Override countdown urgency colours
  const bgColor = urgent ? "rgba(239,68,68,0.12)" : cfg.bg;
  const borderColor = urgent ? "rgba(239,68,68,0.3)" : cfg.border;
  const textColor = urgent ? "#ef4444" : cfg.color;

  /** Human-readable labels for each voice state (English fallback – locale injected via t() where possible). */
  const STATE_LABELS: Record<WakeVoiceState, string> = {
    idle: "Idle",
    wake_detected: "Wake detected",
    listening: "Listening…",
    verifying: "Verifying…",
    unlocked: t("session", "active"),
    processing: "Processing…",
    responding: "Responding…",
    speaking: "Speaking…",
    waiting_for_confirmation: "Awaiting confirmation",
    blocked: "Blocked",
    timeout: "Session expired",
  };

  return (
    <>
      {/* Inject pulse keyframes once (idempotent via style tag) */}
      <style>{PULSE_KEYFRAMES}</style>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "4px 10px",
          borderRadius: "6px",
          background: bgColor,
          border: `1px solid ${borderColor}`,
          fontSize: "12px",
          color: textColor,
          fontWeight: 500,
        }}
      >
        {/* Animated dot for active/pulse states */}
        {cfg.pulse && (
          <span
            style={{
              width: "7px",
              height: "7px",
              borderRadius: "50%",
              background: textColor,
              display: "inline-block",
              animation: "lani-pulse 1.2s ease-in-out infinite",
              flexShrink: 0,
            }}
          />
        )}
        {/* State label */}
        <span>{STATE_LABELS[stateKey] ?? t("session", "active")}</span>
        {/* Countdown */}
        {secondsRemaining !== null && stateKey === "unlocked" && (
          <span style={{ opacity: 0.8 }}>
            {t("session", "expires_in")} {formatTime(secondsRemaining)}
          </span>
        )}
        {/* Security mode badge */}
        {securityMode !== "disabled" && (
          <span
            style={{
              marginLeft: "4px",
              padding: "1px 6px",
              borderRadius: "4px",
              background: "rgba(139,92,246,0.15)",
              color: "#8b5cf6",
              fontSize: "10px",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            {securityMode}
          </span>
        )}
      </div>
    </>
  );
};
