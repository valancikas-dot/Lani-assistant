/**
 * HomePage – the primary experience surface.
 *
 * Layout (single-screen):
 *
 *   ┌──────────────────────────────────────────────┐
 *   │  [Active mode badges]     [+ Add mode]       │  ← header bar
 *   ├──────────────────────────────────────────────┤
 *   │                    │                         │
 *   │  Starter cards     │   PlanPanel             │
 *   │                    │   (approvals)           │
 *   │  Response area     │                         │
 *   │                    │   ─────────────────     │
 *   │  CommandBar        │   StatusPanel           │
 *   │                    │                         │
 *   └──────────────────────────────────────────────┘
 *
 *  The right aside is only rendered when there are pending approvals or
 *  active loading state.  ModesPanel drops down from the header.
 *  ModeSuggestionBanner floats bottom-right via fixed positioning.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useChatStore } from "../stores/chatStore";
import { useApprovalsStore } from "../stores/approvalsStore";
import { getActiveModes, activateMode } from "../lib/api";
import type { Mode } from "../lib/types";
import { StarterCards } from "../components/home/StarterCards";
import { ModesPanel } from "../components/home/ModesPanel";
import { CommandBar } from "../components/home/CommandBar";
import { PlanPanel } from "../components/home/PlanPanel";
import { StatusPanel, type HomeStatus } from "../components/home/StatusPanel";
import { ModeSuggestionBanner } from "../components/home/ModeSuggestionBanner";

// ─── Mode badge ───────────────────────────────────────────────────────────────

interface ModeBadgeProps {
  mode: Mode;
}

const ModeBadge: React.FC<ModeBadgeProps> = ({ mode }) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: "0.3rem",
      padding: "0.2rem 0.65rem",
      background: "rgba(108,99,255,0.14)",
      border: "1px solid var(--accent)",
      borderRadius: "20px",
      fontSize: "0.75rem",
      color: "var(--accent)",
      fontFamily: "var(--font-hud)",
      letterSpacing: "0.05em",
      boxShadow: "0 0 8px var(--accent-glow)",
    }}
  >
    {mode.icon && <span style={{ fontSize: "0.85rem" }}>{mode.icon}</span>}
    {mode.name}
  </span>
);

// ─── Response area ────────────────────────────────────────────────────────────

interface ResponseAreaProps {
  messages: ReturnType<typeof useChatStore.getState>["messages"];
}

const ResponseArea: React.FC<ResponseAreaProps> = ({ messages }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          fontSize: "0.9rem",
          padding: "2rem 0",
          textAlign: "center",
          letterSpacing: "0.03em",
        }}
      >
        <div>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem", opacity: 0.4 }}>✦</div>
          <div>Ask Lani anything, or pick a quick action above.</div>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "0.5rem 0",
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
      }}
    >
      {messages.map((msg) => (
        <div
          key={msg.id}
          style={{
            display: "flex",
            flexDirection: msg.role === "user" ? "row-reverse" : "row",
            gap: "0.6rem",
            alignItems: "flex-start",
          }}
        >
          {/* Avatar dot */}
          <div
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "50%",
              background: msg.role === "user"
                ? "linear-gradient(135deg, var(--accent), var(--cyan))"
                : "rgba(255,255,255,0.06)",
              border: msg.role === "assistant" ? "1px solid var(--border)" : "none",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "0.7rem",
              color: msg.role === "user" ? "#fff" : "var(--text-muted)",
              flexShrink: 0,
            }}
          >
            {msg.role === "user" ? "U" : "✦"}
          </div>

          {/* Bubble */}
          <div
            style={{
              maxWidth: "72%",
              background: msg.role === "user"
                ? "rgba(108,99,255,0.15)"
                : "rgba(255,255,255,0.04)",
              border: `1px solid ${msg.role === "user" ? "rgba(108,99,255,0.3)" : "var(--border)"}`,
              borderRadius: "10px",
              padding: "0.6rem 0.85rem",
              fontSize: "0.87rem",
              color: "var(--text-primary)",
              lineHeight: 1.6,
              wordBreak: "break-word" as const,
              whiteSpace: "pre-wrap" as const,
            }}
          >
            {msg.content}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
};

// ─── HomePage ─────────────────────────────────────────────────────────────────

export const HomePage: React.FC = () => {
  const { messages, isLoading, sendChatStream } = useChatStore();
  const { approvals } = useApprovalsStore();

  const [input, setInput] = useState("");
  const [activeModes, setActiveModes] = useState<Mode[]>([]);
  const [activeSlugs, setActiveSlugs] = useState<string[]>([]);
  const [modesPanelOpen, setModesPanelOpen] = useState(false);
  const [status, setStatus] = useState<HomeStatus>("idle");
  const [suggestion, setSuggestion] = useState<{ mode: Mode } | null>(null);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<number>>(new Set());

  // Load active modes
  const loadActiveModes = useCallback(async () => {
    try {
      const res = await getActiveModes();
      setActiveModes(res.modes);
      setActiveSlugs(res.modes.map((m) => m.slug));
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    void loadActiveModes();
  }, [loadActiveModes]);

  // Derive status from loading state
  useEffect(() => {
    if (isLoading) {
      setStatus("responding");
    } else if (status === "responding") {
      setStatus("done");
      const timer = setTimeout(() => setStatus("idle"), 3000);
      return () => clearTimeout(timer);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading]);

  // Show aside when there are approvals or activity
  const showAside = approvals.length > 0 || status !== "idle";

  const handleSend = useCallback(async () => {
    const cmd = input.trim();
    if (!cmd || isLoading) return;
    setInput("");
    setStatus("thinking");
    try {
      await sendChatStream(cmd);
    } finally {
      // status will update via isLoading effect
    }
  }, [input, isLoading, sendChatStream]);

  const handleStarterSelect = (prompt: string) => {
    setInput(prompt);
  };

  const handleActiveSlugsChange = (slugs: string[]) => {
    setActiveSlugs(slugs);
    void loadActiveModes();
    setModesPanelOpen(false);
  };

  const handleSuggestionEnable = async () => {
    if (!suggestion) return;
    try {
      await activateMode(suggestion.mode.id);
      void loadActiveModes();
    } catch {
      // ignore
    }
    setSuggestion(null);
  };

  const handleSuggestionDismiss = () => {
    if (suggestion) {
      setDismissedSuggestions((prev) => new Set([...prev, suggestion.mode.id]));
    }
    setSuggestion(null);
  };

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* ── Header bar ────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.75rem 1.25rem",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-glass)",
          backdropFilter: "blur(16px)",
          flexShrink: 0,
          flexWrap: "wrap" as const,
          position: "relative",
        }}
      >
        {/* Logo */}
        <span
          style={{
            fontFamily: "var(--font-hud)",
            fontSize: "0.75rem",
            letterSpacing: "0.15em",
            color: "var(--accent)",
            marginRight: "0.5rem",
          }}
        >
          ✦ LANI
        </span>

        {/* Active mode badges */}
        {activeModes.map((m) => (
          <ModeBadge key={m.id} mode={m} />
        ))}

        {activeModes.length === 0 && (
          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
            No modes active
          </span>
        )}

        {/* Add mode button */}
        <button
          onClick={() => setModesPanelOpen((v) => !v)}
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: "0.3rem",
            padding: "0.3rem 0.75rem",
            background: modesPanelOpen ? "rgba(108,99,255,0.15)" : "rgba(255,255,255,0.04)",
            border: `1px solid ${modesPanelOpen ? "var(--accent)" : "var(--border)"}`,
            borderRadius: "20px",
            color: modesPanelOpen ? "var(--accent)" : "var(--text-muted)",
            fontSize: "0.78rem",
            cursor: "pointer",
            fontFamily: "var(--font-hud)",
            letterSpacing: "0.05em",
            transition: "all 0.15s",
          }}
        >
          {modesPanelOpen ? "✕ Close" : "+ Add mode"}
        </button>

        {/* Modes panel dropdown */}
        {modesPanelOpen && (
          <ModesPanel
            onClose={() => setModesPanelOpen(false)}
            onActiveSlugsChange={handleActiveSlugsChange}
          />
        )}
      </div>

      {/* ── Body ──────────────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          display: "flex",
          overflow: "hidden",
          gap: "0",
        }}
      >
        {/* Main column */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            padding: "1rem 1.25rem",
            overflow: "hidden",
            gap: "0.5rem",
          }}
        >
          {/* Starter cards */}
          <StarterCards activeSlugs={activeSlugs} onSelect={handleStarterSelect} />

          {/* Response area */}
          <ResponseArea messages={messages} />

          {/* Command bar */}
          <div style={{ flexShrink: 0, paddingTop: "0.25rem" }}>
            <CommandBar
              value={input}
              onChange={setInput}
              onSend={() => void handleSend()}
              isLoading={isLoading}
            />
            <p style={{
              fontSize: "0.68rem",
              color: "var(--text-dim)",
              textAlign: "center" as const,
              marginTop: "0.35rem",
              letterSpacing: "0.04em",
            }}>
              Enter to send · Shift+Enter for new line · All actions require your approval
            </p>
          </div>
        </div>

        {/* Aside (plan + status) */}
        {showAside && (
          <div
            style={{
              width: "280px",
              flexShrink: 0,
              borderLeft: "1px solid var(--border)",
              padding: "1rem",
              display: "flex",
              flexDirection: "column",
              gap: "0.75rem",
              overflowY: "auto",
              background: "rgba(10,13,26,0.4)",
            }}
          >
            {/* Status pill */}
            <StatusPanel status={status} />

            {/* Plan panel */}
            <PlanPanel />
          </div>
        )}
      </div>

      {/* Smart mode suggestion banner (fixed, bottom-right) */}
      {suggestion && !dismissedSuggestions.has(suggestion.mode.id) && (
        <ModeSuggestionBanner
          modeName={suggestion.mode.name}
          onEnable={() => void handleSuggestionEnable()}
          onDismiss={handleSuggestionDismiss}
        />
      )}
    </div>
  );
};
