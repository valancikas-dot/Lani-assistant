/**
 * WakeIndicator – small badge showing the current voice pipeline state.
 * Renders a coloured dot + label. Used inline in the chat header.
 */

import React from "react";
import type { WakeVoiceState } from "../../lib/types";

interface Props {
  state: WakeVoiceState;
  wakeWordEnabled: boolean;
}

const STATE_CONFIG: Record<
  WakeVoiceState,
  { label: string; color: string; pulse: boolean }
> = {
  idle:          { label: "Idle",        color: "#6b7280", pulse: false },
  wake_detected: { label: "Wake ✓",      color: "#f59e0b", pulse: true  },
  listening:     { label: "Listening…",  color: "#3b82f6", pulse: true  },
  verifying:     { label: "Verifying…",  color: "#8b5cf6", pulse: true  },
  unlocked:      { label: "Unlocked",    color: "#10b981", pulse: false },
  processing:    { label: "Processing…", color: "#f97316", pulse: true  },
  responding:    { label: "Responding…", color: "#06b6d4", pulse: true  },
  blocked:       { label: "Blocked",     color: "#ef4444", pulse: false },
  timeout:       { label: "Timeout",     color: "#9ca3af", pulse: false },
  speaking:      { label: "Speaking…",   color: "#06b6d4", pulse: true  },
  waiting_for_confirmation: { label: "Awaiting confirmation", color: "#f59e0b", pulse: false },
};

export const WakeIndicator: React.FC<Props> = ({ state, wakeWordEnabled }) => {
  if (!wakeWordEnabled && state === "idle") return null;

  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.idle;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "5px",
        fontSize: "12px",
        color: cfg.color,
        fontWeight: 500,
        userSelect: "none",
      }}
      title={`Voice state: ${state}`}
    >
      <span
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          backgroundColor: cfg.color,
          display: "inline-block",
          animation: cfg.pulse ? "pulse 1.2s ease-in-out infinite" : "none",
        }}
      />
      {cfg.label}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(1.3); }
        }
      `}</style>
    </span>
  );
};
