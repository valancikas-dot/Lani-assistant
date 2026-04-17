/**
 * ModeSuggestionBanner – non-blocking banner that appears when Lani detects
 * the user might benefit from an additional mode.
 *
 * UI-only hook. Full detection logic not required — banner is driven by the
 * `suggestion` prop from the parent (which decides when to show it).
 */

import React, { useState } from "react";

export interface ModeSuggestionBannerProps {
  /** The human-readable mode name to suggest. */
  modeName: string;
  /** Called when the user clicks "Enable". */
  onEnable: () => void;
  /** Called when the user dismisses the banner. */
  onDismiss: () => void;
}

export const ModeSuggestionBanner: React.FC<ModeSuggestionBannerProps> = ({
  modeName,
  onEnable,
  onDismiss,
}) => {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  const dismiss = () => {
    setVisible(false);
    onDismiss();
  };

  return (
    <div
      style={{
        position: "fixed",
        bottom: "1.5rem",
        right: "1.5rem",
        zIndex: 200,
        background: "var(--bg-glass)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        border: "1px solid var(--border-bright)",
        borderRadius: "12px",
        padding: "0.85rem 1rem",
        boxShadow: "0 8px 32px rgba(108,99,255,0.2), 0 0 0 1px rgba(108,99,255,0.12)",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        maxWidth: "360px",
        animation: "banner-slide-in 0.25s ease-out",
      }}
    >
      <style>{`
        @keyframes banner-slide-in {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* Icon */}
      <span style={{ fontSize: "1.25rem", flexShrink: 0 }}>💡</span>

      {/* Text */}
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: "0.82rem", color: "var(--text-primary)", marginBottom: "0.2rem", lineHeight: 1.4 }}>
          Lani noticed you&apos;re working on{" "}
          <strong style={{ color: "var(--cyan)" }}>{modeName}</strong>.
        </p>
        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Enable {modeName} mode for better suggestions?
        </p>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", flexShrink: 0 }}>
        <button
          onClick={() => { onEnable(); dismiss(); }}
          style={{
            padding: "0.3rem 0.8rem",
            background: "linear-gradient(135deg, var(--accent), var(--cyan))",
            border: "none",
            borderRadius: "6px",
            color: "#fff",
            fontSize: "0.75rem",
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "var(--font-hud)",
            letterSpacing: "0.05em",
          }}
        >
          Enable
        </button>
        <button
          onClick={dismiss}
          style={{
            padding: "0.3rem 0.8rem",
            background: "transparent",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            color: "var(--text-muted)",
            fontSize: "0.72rem",
            cursor: "pointer",
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
};
