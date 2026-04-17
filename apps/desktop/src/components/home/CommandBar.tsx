/**
 * CommandBar – the central command input on the Home screen.
 *
 * A large, glowing text-area with a send button.
 * Supports pre-filling from starter-card clicks.
 */

import React, { useEffect, useRef } from "react";

export interface CommandBarProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  isLoading: boolean;
  placeholder?: string;
}

export const CommandBar: React.FC<CommandBarProps> = ({
  value,
  onChange,
  onSend,
  isLoading,
  placeholder = "What do you want Lani to do?",
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // Focus on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !isLoading) onSend();
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: "0.75rem",
        background: "var(--bg-tertiary)",
        border: "1px solid var(--border-bright)",
        borderRadius: "14px",
        padding: "0.85rem 1rem",
        boxShadow: "0 0 24px rgba(108,99,255,0.12), 0 0 0 1px rgba(108,99,255,0.08)",
        transition: "box-shadow 0.2s",
      }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={1}
        disabled={isLoading}
        style={{
          flex: 1,
          background: "transparent",
          border: "none",
          outline: "none",
          resize: "none",
          color: "var(--text-primary)",
          fontSize: "1rem",
          fontFamily: "var(--font)",
          lineHeight: 1.5,
          overflowY: "hidden",
          minHeight: "1.5rem",
        }}
      />
      <button
        onClick={onSend}
        disabled={!value.trim() || isLoading}
        style={{
          flexShrink: 0,
          background: value.trim() && !isLoading
            ? "linear-gradient(135deg, var(--accent), var(--cyan))"
            : "rgba(255,255,255,0.06)",
          color: value.trim() && !isLoading ? "#fff" : "var(--text-muted)",
          border: "none",
          borderRadius: "8px",
          padding: "0.55rem 1.1rem",
          fontWeight: 600,
          fontFamily: "var(--font-hud)",
          fontSize: "0.75rem",
          letterSpacing: "0.08em",
          textTransform: "uppercase" as const,
          cursor: value.trim() && !isLoading ? "pointer" : "default",
          transition: "all 0.2s",
          boxShadow: value.trim() && !isLoading ? "0 0 12px var(--accent-glow)" : "none",
          whiteSpace: "nowrap" as const,
        }}
      >
        {isLoading ? "···" : "Send ↵"}
      </button>
    </div>
  );
};
