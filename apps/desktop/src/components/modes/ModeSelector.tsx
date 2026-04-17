/**
 * ModeSelector – Phase 11: Mode System
 *
 * Reusable multi-select card grid for choosing active modes.
 * Used by:
 *   • OnboardingPage (step 2) – first-run selection
 *   • ModesPage (settings) – ongoing management
 *
 * Props
 * ─────
 * modes          All available modes to display
 * selectedIds    Currently selected mode IDs (controlled)
 * onChange       Callback fired with the new set of selected IDs
 * multiSelect    Default true — allow toggling multiple.  Set false for single.
 * disabled       Disable all cards (e.g. while saving)
 */

import React from "react";
import type { Mode, ModeCategory } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

// ─── Icon map ─────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, string> = {
  code: "💻",
  search: "🔍",
  pen: "✍️",
  check: "✅",
  message: "💬",
  chart: "📊",
  book: "📚",
  default: "⚡",
};

function modeIcon(icon: string): string {
  return ICON_MAP[icon] ?? ICON_MAP.default;
}

// ─── Category colour map (Tailwind-safe strings) ──────────────────────────────

const CATEGORY_COLOUR: Record<ModeCategory, string> = {
  development:   "bg-blue-100 text-blue-700",
  research:      "bg-purple-100 text-purple-700",
  creative:      "bg-pink-100 text-pink-700",
  productivity:  "bg-green-100 text-green-700",
  communication: "bg-yellow-100 text-yellow-700",
  personal:      "bg-orange-100 text-orange-700",
  custom:        "bg-gray-100 text-gray-600",
};

// ─── Single card ──────────────────────────────────────────────────────────────

interface ModeCardProps {
  mode: Mode;
  selected: boolean;
  disabled?: boolean;
  onToggle: (id: number) => void;
}

const ModeCard: React.FC<ModeCardProps> = ({ mode, selected, disabled, onToggle }) => {
  const { t } = useI18n();

  const CATEGORY_LABELS: Record<string, string> = {
    productivity:  t("modes", "category_productivity"),
    development:   t("modes", "category_development"),
    research:      t("modes", "category_research"),
    creative:      t("modes", "category_creative"),
    communication: t("modes", "category_communication"),
    personal:      t("modes", "category_personal"),
    custom:        t("modes", "category_custom"),
  };
  const categoryLabel = CATEGORY_LABELS[mode.category] ?? mode.category;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onToggle(mode.id)}
      style={{
        cursor: disabled ? "not-allowed" : "pointer",
        border: selected ? "2px solid #6366f1" : "2px solid transparent",
        borderRadius: "0.75rem",
        padding: "1rem",
        background: selected ? "#eef2ff" : "#f9fafb",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: "0.5rem",
        textAlign: "left",
        transition: "all 0.15s",
        opacity: disabled ? 0.6 : 1,
        boxShadow: selected
          ? "0 0 0 2px #6366f1"
          : "0 1px 3px rgba(0,0,0,0.08)",
      }}
      aria-pressed={selected}
      aria-label={mode.name}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", width: "100%" }}>
        <span style={{ fontSize: "1.5rem" }}>{modeIcon(mode.icon)}</span>
        <span style={{ fontWeight: 600, fontSize: "0.95rem", flex: 1 }}>{mode.name}</span>
        {selected && (
          <span
            style={{
              fontSize: "0.75rem",
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

      {/* Tagline */}
      <span style={{ fontSize: "0.8rem", color: "#4b5563" }}>{mode.tagline}</span>

      {/* Category badge */}
      <span
        style={{
          fontSize: "0.7rem",
          borderRadius: "9999px",
          padding: "0.1rem 0.6rem",
        }}
        className={CATEGORY_COLOUR[mode.category as ModeCategory] ?? CATEGORY_COLOUR.custom}
      >
        {categoryLabel}
      </span>

      {mode.is_builtin && (
        <span style={{ fontSize: "0.68rem", color: "#9ca3af" }}>
          {t("modes", "builtin_badge")}
        </span>
      )}
    </button>
  );
};

// ─── ModeSelector ─────────────────────────────────────────────────────────────

interface ModeSelectorProps {
  modes: Mode[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  multiSelect?: boolean;
  disabled?: boolean;
}

export const ModeSelector: React.FC<ModeSelectorProps> = ({
  modes,
  selectedIds,
  onChange,
  multiSelect = true,
  disabled = false,
}) => {
  const handleToggle = (id: number) => {
    if (disabled) return;
    if (!multiSelect) {
      onChange(selectedIds.includes(id) ? [] : [id]);
      return;
    }
    const next = selectedIds.includes(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id];
    onChange(next);
  };

  if (!modes.length) return null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: "0.75rem",
      }}
    >
      {modes.map((m) => (
        <ModeCard
          key={m.id}
          mode={m}
          selected={selectedIds.includes(m.id)}
          disabled={disabled}
          onToggle={handleToggle}
        />
      ))}
    </div>
  );
};
