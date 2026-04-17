/**
 * StatusPanel – shows the current Lani execution status on the Home screen.
 *
 * States:
 *   idle       — "Ready"
 *   thinking   — spinner + "Thinking…"
 *   executing  — spinner + "Executing…"
 *   responding — spinner + "Responding…"
 *   done       — green tick + last tool name
 */

import React from "react";

export type HomeStatus = "idle" | "thinking" | "executing" | "responding" | "done";

export interface StatusPanelProps {
  status: HomeStatus;
  /** Optional last-used tool name shown in done state. */
  lastTool?: string;
}

const DOT_STYLE: React.CSSProperties = {
  width: "8px",
  height: "8px",
  borderRadius: "50%",
  flexShrink: 0,
};

const PULSE_ANIM = `
@keyframes sp-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.75); }
}
`;

export const StatusPanel: React.FC<StatusPanelProps> = ({ status, lastTool }) => {
  const isActive = status !== "idle";

  if (!isActive) return null;

  const label =
    status === "thinking"   ? "Thinking…"
    : status === "executing"  ? "Executing…"
    : status === "responding" ? "Responding…"
    : status === "done"       ? `Done${lastTool ? ` — ${lastTool}` : ""}`
    : "Ready";

  const dotColour =
    status === "done"       ? "var(--green)"
    : status === "thinking"   ? "var(--accent)"
    : status === "executing"  ? "var(--cyan)"
    : "var(--warning)";

  const borderColour =
    status === "done"       ? "rgba(0,255,136,0.2)"
    : status === "thinking"   ? "rgba(108,99,255,0.2)"
    : status === "executing"  ? "rgba(0,212,255,0.2)"
    : "rgba(255,183,0,0.2)";

  return (
    <>
      <style>{PULSE_ANIM}</style>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.45rem 0.85rem",
          background: "var(--bg-glass)",
          backdropFilter: "blur(12px)",
          border: `1px solid ${borderColour}`,
          borderRadius: "20px",
          fontSize: "0.78rem",
          fontFamily: "var(--font-hud)",
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            ...DOT_STYLE,
            background: dotColour,
            boxShadow: `0 0 6px ${dotColour}`,
            animation: status !== "done" ? "sp-pulse 1.2s ease-in-out infinite" : "none",
          }}
        />
        <span style={{ color: dotColour }}>{label}</span>
      </div>
    </>
  );
};
