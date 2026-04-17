/**
 * MicrophoneButton – click-to-toggle voice recording.
 *
 * Visual states
 * ─────────────
 *   idle        → microphone icon, neutral colour
 *   listening   → pulsing red ring, "Recording…" aria-label
 *   processing  → spinner overlay, "Processing…" aria-label
 *
 * Interaction
 * ───────────
 *   Click once  → start recording
 *   Click again → stop recording and send to STT
 *
 * NOTE: No hold/mousedown pattern — avoids macOS Siri intercept.
 */

import React, { useCallback, useEffect } from "react";
import { useVoiceStore } from "../../stores/voiceStore";
import type { VoiceState } from "../../lib/types";

interface MicrophoneButtonProps {
  /** BCP-47 language tag forwarded to the transcription endpoint. */
  language?: string;
  disabled?: boolean;
}

// ── SVG icons ─────────────────────────────────────────────────────────────────

const MicIcon: React.FC = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    width="18"
    height="18"
    aria-hidden="true"
  >
    <path d="M12 2a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4Zm6.36 8.91A6 6 0 0 1 6 12H4a8 8 0 0 0 7 7.93V22h2v-2.07A8 8 0 0 0 20 12h-1.64Z" />
  </svg>
);

const SpinnerIcon: React.FC = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    width="18"
    height="18"
    className="mic-btn__spinner"
    aria-hidden="true"
  >
    <path
      strokeLinecap="round"
      d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"
    />
  </svg>
);

// ── Helpers ───────────────────────────────────────────────────────────────────

const ARIA_LABELS: Record<VoiceState, string> = {
  idle: "Spustelėkite kad pradėtumėte įrašymą",
  listening: "Įrašoma… spustelėkite kad sustabdytumėte",
  processing: "Apdorojama…",
};

// ── Component ─────────────────────────────────────────────────────────────────

export const MicrophoneButton: React.FC<MicrophoneButtonProps> = ({
  language = "lt-LT",
  disabled = false,
}) => {
  const { voiceState, startListening, stopListening } = useVoiceStore();
  const isListening = voiceState === "listening";
  const isProcessing = voiceState === "processing";

  // Single click toggles recording on/off
  const onClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (disabled || isProcessing) return;
      if (voiceState === "idle") {
        void startListening(language);
      } else if (voiceState === "listening") {
        void stopListening();
      }
    },
    [disabled, isProcessing, voiceState, startListening, stopListening, language]
  );

  // Keyboard: Space / Enter also toggles
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== " " && e.key !== "Enter") return;
      e.preventDefault();
      if (disabled || isProcessing) return;
      if (voiceState === "idle") {
        void startListening(language);
      } else if (voiceState === "listening") {
        void stopListening();
      }
    },
    [disabled, isProcessing, voiceState, startListening, stopListening, language]
  );

  // Safety: stop recording when window loses focus
  useEffect(() => {
    const handleBlur = () => {
      if (voiceState === "listening") {
        void stopListening();
      }
    };
    window.addEventListener("blur", handleBlur);
    return () => window.removeEventListener("blur", handleBlur);
  }, [voiceState, stopListening]);

  const stateClass =
    isListening
      ? "mic-btn--listening"
      : isProcessing
        ? "mic-btn--processing"
        : "";

  return (
    <button
      className={`mic-btn ${stateClass}`}
      aria-label={ARIA_LABELS[voiceState]}
      aria-pressed={isListening}
      disabled={disabled || isProcessing}
      onClick={onClick}
      onKeyDown={onKeyDown}
      type="button"
    >
      {isProcessing ? <SpinnerIcon /> : <MicIcon />}
    </button>
  );
};
