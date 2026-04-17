/**
 * ModesPage – Phase 11: Mode System
 *
 * Full management page for modes:
 *   • Card grid of all built-in + custom modes with activate/deactivate toggles
 *   • Suggested modes section (based on usage history)
 *   • "Create custom mode" form
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  listModes,
  getActiveModes,
  activateMode,
  deactivateMode,
  getModeSuggestions,
  createMode,
  archiveMode,
} from "../lib/api";
import type { Mode, ModeSuggestion, ModeCategory, CreateModeRequest } from "../lib/types";
import { ModeSelector } from "../components/modes/ModeSelector";
import { useI18n } from "../i18n/useI18n";

const EMPTY_CREATE: CreateModeRequest = {
  name: "",
  description: "",
  tagline: "",
  icon: "default",
  system_prompt_hint: "",
  preferred_tools: [],
  capability_tags: [],
  category: "custom",
};

export const ModesPage: React.FC = () => {
  const { t } = useI18n();

  const [modes, setModes] = useState<Mode[]>([]);
  const [activeIds, setActiveIds] = useState<Set<number>>(new Set());
  const [suggestions, setSuggestions] = useState<ModeSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateModeRequest>(EMPTY_CREATE);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [mRes, aRes] = await Promise.all([listModes(), getActiveModes()]);
      setModes(mRes.modes);
      setActiveIds(new Set(aRes.modes.map((m) => m.id)));
      try {
        const sRes = await getModeSuggestions(undefined, 3);
        setSuggestions(sRes.suggestions);
      } catch {
        // Suggestions are non-critical
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load modes.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggle = async (modeId: number) => {
    setToggling(modeId);
    try {
      if (activeIds.has(modeId)) {
        await deactivateMode(modeId);
        setActiveIds((prev) => {
          const next = new Set(prev);
          next.delete(modeId);
          return next;
        });
      } else {
        await activateMode(modeId);
        setActiveIds((prev) => new Set([...prev, modeId]));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to toggle mode.");
    } finally {
      setToggling(null);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await createMode(createForm);
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create mode.");
    } finally {
      setCreating(false);
    }
  };

  const handleArchive = async (modeId: number) => {
    if (!window.confirm(t("modes", "archive_confirm"))) return;
    try {
      await archiveMode(modeId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to archive mode.");
    }
  };

  // Split modes into groups
  const activeModes = modes.filter((m) => activeIds.has(m.id));
  const inactiveModes = modes.filter((m) => !activeIds.has(m.id) && m.status !== "archived");

  return (
    <div style={{ padding: "2rem", maxWidth: "900px" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem" }}>
        {t("modes", "title")}
      </h1>
      <p style={{ color: "#6b7280", marginBottom: "2rem" }}>{t("modes", "subtitle")}</p>

      {error && (
        <div style={{ color: "#ef4444", marginBottom: "1rem", fontSize: "0.9rem" }}>{error}</div>
      )}

      {isLoading ? (
        <p style={{ color: "#9ca3af" }}>Loading…</p>
      ) : (
        <>
          {/* Active modes */}
          {activeModes.length > 0 && (
            <section style={{ marginBottom: "2rem" }}>
              <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#374151" }}>
                {t("modes", "active_label")} ({activeModes.length})
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: "0.75rem",
                }}
              >
                {activeModes.map((m) => (
                  <ModeCard
                    key={m.id}
                    mode={m}
                    isActive
                    isToggling={toggling === m.id}
                    onToggle={handleToggle}
                    onArchive={!m.is_builtin ? handleArchive : undefined}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <section style={{ marginBottom: "2rem" }}>
              <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.5rem", color: "#6366f1" }}>
                💡 {t("modes", "suggestions_title")}
              </h2>
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                {suggestions.map((s) => (
                  <div
                    key={s.mode.id}
                    style={{
                      border: "1px dashed #a5b4fc",
                      borderRadius: "0.75rem",
                      padding: "0.75rem 1rem",
                      background: "#f5f3ff",
                      fontSize: "0.85rem",
                      maxWidth: "260px",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{s.mode.name}</div>
                    <div style={{ color: "#6b7280", marginBottom: "0.5rem" }}>{s.reason}</div>
                    <button
                      onClick={() => handleToggle(s.mode.id)}
                      style={{
                        background: "#6366f1",
                        color: "#fff",
                        border: "none",
                        borderRadius: "0.4rem",
                        padding: "0.3rem 0.8rem",
                        fontSize: "0.8rem",
                        cursor: "pointer",
                      }}
                    >
                      {t("modes", "activate")}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* All inactive modes */}
          {inactiveModes.length > 0 && (
            <section style={{ marginBottom: "2rem" }}>
              <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#374151" }}>
                All modes
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: "0.75rem",
                }}
              >
                {inactiveModes.map((m) => (
                  <ModeCard
                    key={m.id}
                    mode={m}
                    isActive={false}
                    isToggling={toggling === m.id}
                    onToggle={handleToggle}
                    onArchive={!m.is_builtin ? handleArchive : undefined}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Create custom mode */}
          <section>
            {!showCreate ? (
              <button
                onClick={() => setShowCreate(true)}
                style={{
                  border: "1px dashed #d1d5db",
                  background: "transparent",
                  borderRadius: "0.5rem",
                  padding: "0.6rem 1.2rem",
                  color: "#6b7280",
                  cursor: "pointer",
                  fontSize: "0.9rem",
                }}
              >
                + {t("modes", "create_custom")}
              </button>
            ) : (
              <form
                onSubmit={handleCreate}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: "0.75rem",
                  padding: "1.5rem",
                  maxWidth: "420px",
                  background: "#fafafa",
                }}
              >
                <h3 style={{ fontWeight: 600, marginBottom: "1rem" }}>
                  {t("modes", "create_custom")}
                </h3>
                <LabelInput
                  label={t("modes", "new_mode_name")}
                  value={createForm.name ?? ""}
                  onChange={(v) => setCreateForm((f) => ({ ...f, name: v }))}
                  required
                />
                <LabelInput
                  label={t("modes", "new_mode_tagline")}
                  value={createForm.tagline ?? ""}
                  onChange={(v) => setCreateForm((f) => ({ ...f, tagline: v }))}
                />
                <LabelInput
                  label={t("modes", "new_mode_description")}
                  value={createForm.description ?? ""}
                  onChange={(v) => setCreateForm((f) => ({ ...f, description: v }))}
                  multiline
                />
                <LabelInput
                  label={t("modes", "new_mode_hint")}
                  value={createForm.system_prompt_hint ?? ""}
                  onChange={(v) => setCreateForm((f) => ({ ...f, system_prompt_hint: v }))}
                  multiline
                />
                <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.75rem" }}>
                  <button type="submit" disabled={creating} style={primaryBtnStyle}>
                    {creating ? "…" : t("modes", "save")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    style={ghostBtnStyle}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </section>
        </>
      )}
    </div>
  );
};

// ─── Internal ModeCard for ModesPage ─────────────────────────────────────────

const ICON_MAP: Record<string, string> = {
  code: "💻", search: "🔍", pen: "✍️", check: "✅",
  message: "💬", chart: "📊", book: "📚", default: "⚡",
};

interface ModeCardProps {
  mode: Mode;
  isActive: boolean;
  isToggling: boolean;
  onToggle: (id: number) => void;
  onArchive?: (id: number) => void;
}

const ModeCard: React.FC<ModeCardProps> = ({
  mode, isActive, isToggling, onToggle, onArchive,
}) => {
  const { t } = useI18n();
  const icon = ICON_MAP[mode.icon] ?? ICON_MAP.default;

  return (
    <div
      style={{
        border: isActive ? "2px solid #6366f1" : "1px solid #e5e7eb",
        borderRadius: "0.75rem",
        padding: "1rem",
        background: isActive ? "#eef2ff" : "#fff",
        display: "flex",
        flexDirection: "column",
        gap: "0.5rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <span style={{ fontSize: "1.4rem" }}>{icon}</span>
        <span style={{ fontWeight: 600 }}>{mode.name}</span>
        {isActive && (
          <span
            style={{
              marginLeft: "auto",
              fontSize: "0.7rem",
              background: "#6366f1",
              color: "#fff",
              borderRadius: "9999px",
              padding: "0.1rem 0.5rem",
            }}
          >
            {t("modes", "active_label")}
          </span>
        )}
      </div>
      <p style={{ fontSize: "0.8rem", color: "#4b5563", margin: 0 }}>{mode.tagline}</p>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "auto" }}>
        <button
          onClick={() => onToggle(mode.id)}
          disabled={isToggling}
          style={{
            ...primaryBtnStyle,
            background: isActive ? "#e5e7eb" : "#6366f1",
            color: isActive ? "#374151" : "#fff",
            fontSize: "0.8rem",
            padding: "0.3rem 0.8rem",
            opacity: isToggling ? 0.6 : 1,
          }}
        >
          {isToggling
            ? "…"
            : isActive
            ? t("modes", "deactivate")
            : t("modes", "activate")}
        </button>
        {onArchive && (
          <button
            onClick={() => onArchive(mode.id)}
            style={{ ...ghostBtnStyle, fontSize: "0.75rem", padding: "0.3rem 0.6rem" }}
          >
            Archive
          </button>
        )}
      </div>
    </div>
  );
};

// ─── LabelInput helper ────────────────────────────────────────────────────────

interface LabelInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  multiline?: boolean;
}

const LabelInput: React.FC<LabelInputProps> = ({
  label, value, onChange, required, multiline,
}) => (
  <div style={{ marginBottom: "0.75rem" }}>
    <label style={{ fontSize: "0.85rem", fontWeight: 500, display: "block", marginBottom: "0.25rem" }}>
      {label}
    </label>
    {multiline ? (
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        style={inputStyle}
      />
    ) : (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        style={inputStyle}
      />
    )}
  </div>
);

// ─── Styles ───────────────────────────────────────────────────────────────────

const primaryBtnStyle: React.CSSProperties = {
  background: "#6366f1",
  color: "#fff",
  border: "none",
  borderRadius: "0.4rem",
  padding: "0.5rem 1.1rem",
  fontWeight: 600,
  fontSize: "0.85rem",
  cursor: "pointer",
};

const ghostBtnStyle: React.CSSProperties = {
  background: "transparent",
  color: "#6b7280",
  border: "1px solid #e5e7eb",
  borderRadius: "0.4rem",
  padding: "0.5rem 1rem",
  fontWeight: 500,
  fontSize: "0.85rem",
  cursor: "pointer",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.45rem 0.75rem",
  border: "1px solid #d1d5db",
  borderRadius: "0.4rem",
  fontSize: "0.9rem",
  boxSizing: "border-box",
};
