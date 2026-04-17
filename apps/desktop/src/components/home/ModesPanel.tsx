/**
 * ModesPanel – inline expandable panel for managing active modes from the
 * Home screen.
 *
 * Shows:
 *   - Active modes with deactivate (×) buttons
 *   - All inactive builtin modes with activate buttons
 *   - Top-3 mode suggestions if available
 *   - Close button
 */

import React, { useEffect, useState } from "react";
import {
  listModes,
  getActiveModes,
  activateMode,
  deactivateMode,
  getModeSuggestions,
} from "../../lib/api";
import type { Mode, ModeSuggestion } from "../../lib/types";

// ─── Styles ───────────────────────────────────────────────────────────────────

const panelStyle: React.CSSProperties = {
  position: "absolute",
  top: "3.5rem",
  left: 0,
  right: 0,
  zIndex: 100,
  background: "var(--bg-glass)",
  backdropFilter: "blur(24px)",
  WebkitBackdropFilter: "blur(24px)",
  border: "1px solid var(--border-bright)",
  borderRadius: "12px",
  padding: "1.25rem",
  boxShadow: "0 8px 48px rgba(108,99,255,0.18), 0 0 0 1px rgba(108,99,255,0.12)",
  maxHeight: "480px",
  overflowY: "auto",
};

const sectionLabel: React.CSSProperties = {
  fontSize: "0.65rem",
  fontFamily: "var(--font-hud)",
  letterSpacing: "0.12em",
  textTransform: "uppercase" as const,
  color: "var(--text-muted)",
  marginBottom: "0.5rem",
  marginTop: "1rem",
};

const modePillBase: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.35rem",
  padding: "0.3rem 0.7rem",
  borderRadius: "20px",
  fontSize: "0.8rem",
  fontFamily: "var(--font)",
  cursor: "pointer",
  border: "1px solid transparent",
  transition: "all 0.15s",
};

// ─── Component ────────────────────────────────────────────────────────────────

export interface ModesPanelProps {
  onClose: () => void;
  onActiveSlugsChange?: (slugs: string[]) => void;
}

export const ModesPanel: React.FC<ModesPanelProps> = ({ onClose, onActiveSlugsChange }) => {
  const [allModes, setAllModes] = useState<Mode[]>([]);
  const [activeIds, setActiveIds] = useState<Set<number>>(new Set());
  const [suggestions, setSuggestions] = useState<ModeSuggestion[]>([]);
  const [busy, setBusy] = useState<number | null>(null);

  const reload = async () => {
    const [modesRes, activeRes] = await Promise.all([listModes(), getActiveModes()]);
    setAllModes(modesRes.modes);
    const ids = new Set(activeRes.modes.map((m) => m.id));
    setActiveIds(ids);
    const slugs = activeRes.modes.map((m) => m.slug);
    onActiveSlugsChange?.(slugs);
  };

  const loadSuggestions = async () => {
    try {
      const res = await getModeSuggestions(undefined, 3);
      setSuggestions(res.suggestions);
    } catch {
      // non-fatal
    }
  };

  useEffect(() => {
    void reload();
    void loadSuggestions();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async (mode: Mode) => {
    setBusy(mode.id);
    try {
      if (activeIds.has(mode.id)) {
        await deactivateMode(mode.id);
      } else {
        await activateMode(mode.id);
      }
      await reload();
    } catch {
      // ignore
    } finally {
      setBusy(null);
    }
  };

  const activeModes = allModes.filter((m) => activeIds.has(m.id));
  const inactiveModes = allModes.filter((m) => !activeIds.has(m.id));
  const suggestedModes = suggestions
    .map((s) => s.mode)
    .filter((m) => !activeIds.has(m.id))
    .slice(0, 3);

  return (
    <div style={panelStyle}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <span style={{ fontFamily: "var(--font-hud)", fontSize: "0.85rem", letterSpacing: "0.08em", color: "var(--text-primary)" }}>
          MODES
        </span>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "1.1rem", padding: "0 0.25rem", lineHeight: 1 }}
        >
          ✕
        </button>
      </div>

      {/* Active modes */}
      {activeModes.length > 0 && (
        <>
          <div style={{ ...sectionLabel, marginTop: "0.25rem" }}>Active</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {activeModes.map((m) => (
              <button
                key={m.id}
                onClick={() => void toggle(m)}
                disabled={busy === m.id}
                title="Deactivate"
                style={{
                  ...modePillBase,
                  background: "rgba(108,99,255,0.18)",
                  border: "1px solid var(--accent)",
                  color: "var(--accent)",
                  boxShadow: "0 0 8px var(--accent-glow)",
                  opacity: busy === m.id ? 0.5 : 1,
                }}
              >
                <span>{m.icon ?? "⚡"}</span>
                <span>{m.name}</span>
                <span style={{ opacity: 0.6, fontSize: "0.7rem" }}>✕</span>
              </button>
            ))}
          </div>
        </>
      )}

      {/* Suggestions */}
      {suggestedModes.length > 0 && (
        <>
          <div style={sectionLabel}>💡 Suggested</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {suggestedModes.map((m) => (
              <button
                key={m.id}
                onClick={() => void toggle(m)}
                disabled={busy === m.id}
                title="Activate"
                style={{
                  ...modePillBase,
                  background: "rgba(0,212,255,0.08)",
                  border: "1px solid var(--cyan)",
                  color: "var(--cyan)",
                  opacity: busy === m.id ? 0.5 : 1,
                }}
              >
                <span>{m.icon ?? "⚡"}</span>
                <span>{m.name}</span>
                <span style={{ opacity: 0.6, fontSize: "0.7rem" }}>+</span>
              </button>
            ))}
          </div>
        </>
      )}

      {/* All inactive */}
      {inactiveModes.length > 0 && (
        <>
          <div style={sectionLabel}>All Modes</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {inactiveModes.map((m) => (
              <button
                key={m.id}
                onClick={() => void toggle(m)}
                disabled={busy === m.id}
                title="Activate"
                style={{
                  ...modePillBase,
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid var(--border)",
                  color: "var(--text-muted)",
                  opacity: busy === m.id ? 0.5 : 1,
                }}
              >
                <span>{m.icon ?? "⚡"}</span>
                <span>{m.name}</span>
                <span style={{ opacity: 0.5, fontSize: "0.7rem" }}>+</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};
