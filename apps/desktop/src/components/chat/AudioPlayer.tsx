/**
 * AudioPlayer – inline play/stop button for TTS responses.
 *
 * Renders as a compact icon button next to assistant messages.
 * Delegates to voiceStore.playResponse / stopPlayback so the store
 * tracks global playback state and only one clip can play at a time.
 *
 * States: idle → loading (synthesis in-flight) → playing → error
 */

import React from "react";
import { useVoiceStore } from "../../stores/voiceStore";
import { useSettingsStore } from "../../stores/settingsStore";

interface AudioPlayerProps {
  /** The text to synthesize. */
  text: string;
}

// ── SVG icons ─────────────────────────────────────────────────────────────────

const PlayIcon: React.FC = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    width="14"
    height="14"
    aria-hidden="true"
  >
    <path d="M8 5v14l11-7z" />
  </svg>
);

const StopIcon: React.FC = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    width="14"
    height="14"
    aria-hidden="true"
  >
    <rect x="6" y="6" width="12" height="12" rx="1" />
  </svg>
);

const LoadingSpinner: React.FC = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    width="14"
    height="14"
    aria-hidden="true"
    style={{ animation: "spin 1s linear infinite" }}
  >
    <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
    <path d="M12 2a10 10 0 0 1 10 10" />
  </svg>
);

// ── Component ─────────────────────────────────────────────────────────────────

export const AudioPlayer: React.FC<AudioPlayerProps> = ({ text }) => {
  const { isPlaying, isTtsLoading, ttsError, playResponse, stopPlayback, clearTtsError } = useVoiceStore();
  const { settings } = useSettingsStore();

  // Use the configured TTS voice and speech output language
  const voice = settings?.tts_voice ?? "default";
  const language = settings?.speech_output_language ?? "en";

  const handleClick = () => {
    if (isTtsLoading) return; // prevent double-click during loading
    if (isPlaying) {
      stopPlayback();
    } else {
      if (ttsError) clearTtsError();
      void playResponse(text, voice, language);
    }
  };

  const isLoading = isTtsLoading;
  const hasError = !!ttsError && !isPlaying && !isTtsLoading;

  return (
    <button
      className={`audio-player-btn${hasError ? " audio-player-btn--error" : ""}${isLoading ? " audio-player-btn--loading" : ""}`}
      onClick={handleClick}
      disabled={isLoading}
      aria-label={
        isLoading ? "Synthesizing audio…" :
        isPlaying ? "Stop audio" :
        hasError ? `TTS error: ${ttsError}` :
        "Play response aloud"
      }
      title={
        isLoading ? "Synthesizing…" :
        isPlaying ? "Stop" :
        hasError ? ttsError ?? "Error" :
        "Speak"
      }
      type="button"
    >
      {isLoading ? <LoadingSpinner /> : isPlaying ? <StopIcon /> : <PlayIcon />}
    </button>
  );
};
