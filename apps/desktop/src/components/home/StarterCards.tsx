/**
 * StarterCards – mode-specific quick-action cards shown on the Home screen.
 *
 * Exports:
 *   STARTERS   — map of mode slug → array of action cards (icon, label, prompt)
 *   StarterCards — React component rendering all active-mode starter cards
 */

import React, { useState } from "react";

// ─── Data ─────────────────────────────────────────────────────────────────────

export interface StarterCard {
  icon: string;
  label: string;
  /** Pre-filled prompt sent to the command bar when this card is clicked. */
  prompt: string;
}

export const STARTERS: Record<string, StarterCard[]> = {
  developer: [
    { icon: "🚀", label: "Create a new app",     prompt: "Create a new app project with setup instructions" },
    { icon: "🐛", label: "Fix a bug",             prompt: "Help me diagnose and fix a bug in my code" },
    { icon: "♻️", label: "Refactor code",         prompt: "Refactor this code to improve readability and performance" },
    { icon: "🔌", label: "Generate API",          prompt: "Generate a REST API with CRUD endpoints for" },
    { icon: "📋", label: "Write tests",           prompt: "Write unit tests for my code" },
  ],
  writer: [
    { icon: "🎬", label: "Generate video script", prompt: "Write a video script for" },
    { icon: "🖼️", label: "Create storyboard",    prompt: "Create a storyboard outline for my video idea about" },
    { icon: "📝", label: "Write blog post",       prompt: "Write a compelling blog post about" },
    { icon: "🎵", label: "Write lyrics",          prompt: "Write song lyrics for" },
    { icon: "📖", label: "Create content outline",prompt: "Create a detailed content outline for" },
  ],
  researcher: [
    { icon: "🔍", label: "Research topic",        prompt: "Research and summarise information about" },
    { icon: "⚖️", label: "Compare options",       prompt: "Compare these options and give me a recommendation:" },
    { icon: "📄", label: "Summarise document",    prompt: "Summarise this document:" },
    { icon: "🧪", label: "Fact check",            prompt: "Fact check these claims:" },
    { icon: "📊", label: "Competitive analysis",  prompt: "Do a competitive analysis for" },
  ],
  analyst: [
    { icon: "📈", label: "Create campaign",       prompt: "Create a marketing campaign strategy for" },
    { icon: "✍️", label: "Write ad copy",         prompt: "Write compelling ad copy for" },
    { icon: "📊", label: "Analyse data",          prompt: "Analyse this dataset and identify key patterns:" },
    { icon: "👥", label: "Audience analysis",     prompt: "Analyse target audience and create personas for" },
    { icon: "📋", label: "Content batch",         prompt: "Generate a batch of content ideas for" },
  ],
  productivity: [
    { icon: "⚡", label: "Automate workflow",     prompt: "Help me automate this repetitive workflow:" },
    { icon: "📁", label: "Organise files",        prompt: "Organise and rename files in my project folder" },
    { icon: "📅", label: "Plan my week",          prompt: "Help me plan and prioritise my tasks for this week" },
    { icon: "📧", label: "Draft email",           prompt: "Draft a professional email for" },
    { icon: "📋", label: "Create checklist",      prompt: "Create a detailed task checklist for" },
  ],
  communicator: [
    { icon: "💬", label: "Draft message",         prompt: "Draft a clear message for" },
    { icon: "📧", label: "Write email",           prompt: "Write a professional email about" },
    { icon: "🎤", label: "Talking points",        prompt: "Prepare talking points for my meeting about" },
    { icon: "📝", label: "Summarise thread",      prompt: "Summarise this conversation thread:" },
  ],
  student: [
    { icon: "📚", label: "Explain concept",       prompt: "Explain this concept in simple terms:" },
    { icon: "📝", label: "Study notes",           prompt: "Create concise study notes for" },
    { icon: "❓", label: "Quiz me",              prompt: "Quiz me on the topic:" },
    { icon: "✍️", label: "Help with essay",       prompt: "Help me write and structure an essay on" },
    { icon: "🗂️", label: "Summarise chapter",    prompt: "Summarise this chapter / document:" },
  ],
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const sectionStyle: React.CSSProperties = {
  marginBottom: "1.5rem",
};

const sectionHeadingStyle: React.CSSProperties = {
  fontSize: "0.7rem",
  fontFamily: "var(--font-hud)",
  letterSpacing: "0.1em",
  textTransform: "uppercase" as const,
  color: "var(--text-muted)",
  marginBottom: "0.6rem",
};

const gridStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: "0.5rem",
};

// ─── SingleCard ───────────────────────────────────────────────────────────────

interface SingleCardProps {
  card: StarterCard;
  onSelect: (prompt: string) => void;
}

const SingleCard: React.FC<SingleCardProps> = ({ card, onSelect }) => {
  const [hovered, setHovered] = useState(false);

  return (
    <button
      onClick={() => onSelect(card.prompt)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.45rem",
        padding: "0.4rem 0.85rem",
        background: hovered ? "rgba(108,99,255,0.12)" : "rgba(255,255,255,0.03)",
        border: `1px solid ${hovered ? "var(--accent)" : "var(--border)"}`,
        borderRadius: "20px",
        color: hovered ? "var(--accent)" : "var(--text-primary)",
        fontSize: "0.82rem",
        cursor: "pointer",
        transition: "all 0.15s",
        whiteSpace: "nowrap" as const,
        boxShadow: hovered ? "0 0 10px var(--accent-glow)" : "none",
        fontFamily: "var(--font)",
      }}
    >
      <span style={{ fontSize: "0.9rem" }}>{card.icon}</span>
      <span>{card.label}</span>
    </button>
  );
};

// ─── StarterCards ─────────────────────────────────────────────────────────────

export interface StarterCardsProps {
  /** Slugs of currently active modes. */
  activeSlugs: string[];
  /** Called when a card is clicked; receives the pre-filled prompt string. */
  onSelect: (prompt: string) => void;
}

export const StarterCards: React.FC<StarterCardsProps> = ({ activeSlugs, onSelect }) => {
  if (activeSlugs.length === 0) return null;

  // Show cards for modes that have a STARTERS entry
  const modesWithCards = activeSlugs.filter((s) => STARTERS[s]);

  if (modesWithCards.length === 0) return null;

  return (
    <div style={{ marginBottom: "1.25rem" }}>
      {modesWithCards.map((slug) => (
        <div key={slug} style={sectionStyle}>
          <div style={sectionHeadingStyle}>
            {slug.charAt(0).toUpperCase() + slug.slice(1)} — quick actions
          </div>
          <div style={gridStyle}>
            {STARTERS[slug].map((card) => (
              <SingleCard key={card.label} card={card} onSelect={onSelect} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};
