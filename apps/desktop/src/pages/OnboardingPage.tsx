/**
 * OnboardingPage – Phase 12: Home UX Layer
 *
 * Single-screen intent selector shown once after first-run setup completes.
 *
 *   "What do you want to do today?"
 *
 * Six intent cards, max 3 selections.  On "Continue", the selected intents
 * are mapped to backend mode slugs, those mode IDs are looked up, and
 * POST /api/v1/modes/select is called.  Then onComplete() is invoked.
 */

import React, { useEffect, useState } from "react";
import { listModes, selectModes } from "../lib/api";
import type { Mode } from "../lib/types";

// ─── Intent card definitions ──────────────────────────────────────────────────

export interface IntentCard {
  id: string;
  emoji: string;
  title: string;
  description: string;
  /** Corresponding backend mode slug (null = general, no specific mode). */
  slug: string | null;
}

export const INTENT_CARDS: IntentCard[] = [
  {
    id: "software",
    emoji: "💻",
    title: "Build software",
    description: "Code, APIs, debug, refactor",
    slug: "developer",
  },
  {
    id: "video",
    emoji: "🎬",
    title: "Create video / content",
    description: "Scripts, storyboards, assets",
    slug: "writer",
  },
  {
    id: "music",
    emoji: "🎵",
    title: "Create music",
    description: "Lyrics, structure, production ideas",
    slug: "writer",
  },
  {
    id: "marketing",
    emoji: "📈",
    title: "Marketing & growth",
    description: "Campaigns, copy, audience research",
    slug: "analyst",
  },
  {
    id: "automate",
    emoji: "⚙️",
    title: "Automate tasks",
    description: "Workflows, files, scheduling",
    slug: "productivity",
  },
  {
    id: "general",
    emoji: "🧠",
    title: "General AI assistant",
    description: "Research, writing, Q&A, anything",
    slug: null,
  },
];

const MAX_SELECTIONS = 3;

// ─── Styles ───────────────────────────────────────────────────────────────────

const PAGE_ANIM = `
@keyframes ob-fade-in {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
`;

// ─── IntentCardButton ─────────────────────────────────────────────────────────

interface IntentCardButtonProps {
  card: IntentCard;
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}

const IntentCardButton: React.FC<IntentCardButtonProps> = ({
  card,
  selected,
  disabled,
  onToggle,
}) => {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onClick={onToggle}
      disabled={disabled && !selected}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: "0.4rem",
        padding: "1.1rem 1.1rem 1rem",
        background: selected
          ? "rgba(108,99,255,0.18)"
          : hovered
          ? "rgba(108,99,255,0.08)"
          : "rgba(255,255,255,0.03)",
        border: `1.5px solid ${
          selected
            ? "var(--accent)"
            : hovered
            ? "rgba(108,99,255,0.5)"
            : "var(--border)"
        }`,
        borderRadius: "12px",
        cursor: disabled && !selected ? "default" : "pointer",
        transition: "all 0.18s",
        boxShadow: selected
          ? "0 0 18px var(--accent-glow), inset 0 0 12px rgba(108,99,255,0.06)"
          : "none",
        textAlign: "left",
        opacity: disabled && !selected ? 0.45 : 1,
        position: "relative",
      }}
    >
      {selected && (
        <span
          style={{
            position: "absolute",
            top: "0.5rem",
            right: "0.6rem",
            width: "18px",
            height: "18px",
            borderRadius: "50%",
            background: "var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "0.65rem",
            color: "#fff",
            fontWeight: 700,
          }}
        >
          ✓
        </span>
      )}
      <span style={{ fontSize: "1.75rem", lineHeight: 1 }}>{card.emoji}</span>
      <span
        style={{
          fontFamily: "var(--font)",
          fontWeight: 600,
          fontSize: "0.9rem",
          color: "var(--text-primary)",
          lineHeight: 1.2,
        }}
      >
        {card.title}
      </span>
      <span
        style={{
          fontSize: "0.75rem",
          color: selected ? "var(--accent)" : "var(--text-muted)",
          lineHeight: 1.4,
        }}
      >
        {card.description}
      </span>
    </button>
  );
};

// ─── OnboardingPage ───────────────────────────────────────────────────────────

interface OnboardingPageProps {
  onComplete: () => void;
}

export const OnboardingPage: React.FC<OnboardingPageProps> = ({ onComplete }) => {
  const [modes, setModes] = useState<Mode[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listModes()
      .then((r) => setModes(r.modes))
      .catch(() => {});
  }, []);

  const toggleCard = (cardId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(cardId)) {
        next.delete(cardId);
      } else if (next.size < MAX_SELECTIONS) {
        next.add(cardId);
      }
      return next;
    });
  };

  const handleContinue = async () => {
    setSaving(true);
    setError(null);
    try {
      const selectedCards = INTENT_CARDS.filter((c) => selectedIds.has(c.id));
      const slugs = [...new Set(selectedCards.map((c) => c.slug).filter(Boolean))] as string[];
      const modeIds = slugs
        .map((slug) => modes.find((m) => m.slug === slug)?.id)
        .filter((id): id is number => id !== undefined);
      if (modeIds.length > 0) {
        await selectModes({ mode_ids: modeIds });
      }
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
      setSaving(false);
    }
  };

  const canContinue = selectedIds.size > 0;
  const atMax = selectedIds.size >= MAX_SELECTIONS;

  return (
    <>
      <style>{PAGE_ANIM}</style>
      <div
        style={{
          minHeight: "100vh",
          background: "var(--bg-primary)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "2rem 1rem",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "radial-gradient(ellipse 700px 500px at 50% 30%, rgba(108,99,255,0.07) 0%, transparent 70%)",
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "relative",
            zIndex: 1,
            width: "100%",
            maxWidth: "680px",
            animation: "ob-fade-in 0.4s ease-out",
          }}
        >
          <div style={{ textAlign: "center", marginBottom: "2rem" }}>
            <div
              style={{
                fontFamily: "var(--font-hud)",
                fontSize: "1.1rem",
                letterSpacing: "0.3em",
                color: "var(--accent)",
              }}
            >
              ✦ LANI
            </div>
          </div>
          <div style={{ textAlign: "center", marginBottom: "2rem" }}>
            <h1
              style={{
                fontFamily: "var(--font)",
                fontSize: "1.75rem",
                fontWeight: 700,
                color: "var(--text-primary)",
                marginBottom: "0.5rem",
                lineHeight: 1.25,
              }}
            >
              What do you want to do today?
            </h1>
            <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
              Choose up to {MAX_SELECTIONS}. You can change this any time.
            </p>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: "0.75rem",
              marginBottom: "1.5rem",
            }}
          >
            {INTENT_CARDS.map((card) => (
              <IntentCardButton
                key={card.id}
                card={card}
                selected={selectedIds.has(card.id)}
                disabled={atMax && !selectedIds.has(card.id)}
                onToggle={() => toggleCard(card.id)}
              />
            ))}
          </div>
          <div
            style={{
              textAlign: "center",
              fontSize: "0.78rem",
              color: atMax ? "var(--accent)" : "var(--text-muted)",
              marginBottom: "1.25rem",
              transition: "color 0.2s",
            }}
          >
            {selectedIds.size}/{MAX_SELECTIONS} selected
          </div>
          {error && (
            <p
              style={{
                textAlign: "center",
                color: "var(--error)",
                fontSize: "0.82rem",
                marginBottom: "1rem",
              }}
            >
              {error}
            </p>
          )}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.6rem" }}>
            <button
              onClick={() => void handleContinue()}
              disabled={!canContinue || saving}
              style={{
                width: "100%",
                maxWidth: "320px",
                padding: "0.85rem",
                background:
                  canContinue && !saving
                    ? "linear-gradient(135deg, var(--accent), var(--cyan))"
                    : "rgba(255,255,255,0.06)",
                border: "none",
                borderRadius: "10px",
                color: canContinue && !saving ? "#fff" : "var(--text-muted)",
                fontSize: "0.95rem",
                fontWeight: 700,
                fontFamily: "var(--font-hud)",
                letterSpacing: "0.08em",
                cursor: canContinue && !saving ? "pointer" : "default",
                transition: "all 0.2s",
                boxShadow: canContinue && !saving ? "0 0 20px var(--accent-glow)" : "none",
              }}
            >
              {saving ? "SETTING UP…" : "CONTINUE →"}
            </button>
            <button
              onClick={onComplete}
              disabled={saving}
              style={{
                background: "none",
                border: "none",
                color: "var(--text-muted)",
                fontSize: "0.8rem",
                cursor: "pointer",
                padding: "0.25rem 0.75rem",
                letterSpacing: "0.04em",
              }}
            >
              Skip for now
            </button>
          </div>
        </div>
      </div>
    </>
  );
};
