/**
 * WakeControls – action buttons and state feedback for the wake / voice session flow.
 *
 * Renders differently for each wake mode and voice state:
 *
 * manual / push_to_talk:
 *   idle/timeout  → "Activate Lani" button
 *   unlocked      → command input + "Send" button + push-to-talk button (PTT mode)
 *   processing    → spinner
 *   responding    → last response text
 *   verifying     → "Verify & Unlock" button
 *   blocked       → blocked banner
 *   listening     → "Listening…" badge (push-to-talk)
 *
 * wake_phrase_placeholder:
 *   unlocked      → same as manual
 *   not unlocked  → phrase input + "Activate" button
 *
 * All modes:
 *   unlocked      → "Lock Session" red button
 *
 * The component reads from wakeStore and calls store actions.
 * It does NOT own any response data – it reads `lastCommandResponse` from
 * the store so the parent (ChatPage) can also read and append to the thread.
 */

import React, { useState, useCallback } from "react";
import { useWakeStore } from "../../stores/wakeStore";
import { PushToTalkButton } from "./PushToTalkButton";
import { VoiceOrb } from "./VoiceOrb";
import { useVolumeAnalyser } from "../../hooks/useVolumeAnalyser";
import { useI18n } from "../../i18n/useI18n";
import { useWakeWordListener, isWakeWordSupported } from "../../hooks/useWakeWordListener";
import { useSettingsStore } from "../../stores/settingsStore";

const MODE_DESCRIPTIONS: Record<string, string> = {
  manual: "Manual mode — press Activate to start a session.",
  push_to_talk: "Push-to-talk — hold the mic button while speaking.",
  wake_phrase_placeholder:
    "⚠️ Keyword match — NOT always-on. Type the wake phrase to activate.",
  keyword_live: '🎙 Always-on — say "Lani" to activate.',
  provider_ready: "Always-on wake-word provider (not yet integrated).",
};export const WakeControls: React.FC = () => {
  const {
    voiceState,
    wakeMode,
    wakeWordEnabled,
    primaryWakePhrase,
    secondaryWakePhrase,
    session,
    loading,
    error,
    lastCommandResponse,
    sttState,
    sttError,
    sessionExpired,
    reverificationRequired,
    activate,
    verifyAndUnlock,
    lock,
    processCommand,
  } = useWakeStore();
  const { t } = useI18n();
    const settings = useSettingsStore((s) => s.settings);
  // Normalize stored language codes to BCP-47 for Web Speech API (lt -> lt-LT)
  const _recLangRaw = settings?.speech_recognition_language ?? settings?.assistant_language ?? "lt";
  const recognitionLanguage = _recLangRaw === "lt" ? "lt-LT" : _recLangRaw;

  const [phraseInput, setPhraseInput] = useState("");
  const [commandInput, setCommandInput] = useState("");
  const [pttStream, setPttStream] = useState<MediaStream | null>(null);
  // When true, the PushToTalkButton will auto-start recording (triggered by wake word).
  const [autoStartRecording, setAutoStartRecording] = useState(false);
  const isKeywordLiveMode = wakeMode === "keyword_live";

  // Volume for the orb – driven by the live mic stream from PushToTalkButton
  const orbVolume = useVolumeAnalyser(pttStream, session.unlocked || isKeywordLiveMode);

  const handlePttStream = useCallback((stream: MediaStream | null) => {
    setPttStream(stream);
  }, []);

  const handleSendCommand = useCallback(async () => {
    const cmd = commandInput.trim();
    if (!cmd) return;
    setCommandInput("");
    await processCommand(cmd, false);
  }, [commandInput, processCommand]);

  // PTT callbacks
  const handlePttResult = useCallback(() => {
    // Result is already reflected in wakeStore.lastCommandResponse and
    // picked up by ChatPage — nothing extra needed here.
  }, []);

  const handlePttError = useCallback((_msg: string) => {
    // sttError is already in the store; the error banner below will show it.
  }, []);

  // ── Always-on keyword listener ────────────────────────────────────────────
  // Fires only when wakeMode === "keyword_live" and wakeWordEnabled === true.
  const handleWakeDetected = useCallback(
    async (transcript: string) => {
      // 1. Activate the voice session (backend unlock)
      await activate(transcript, "keyword_live" as any);
      // 2. Signal PushToTalkButton to auto-start recording
      setAutoStartRecording(true);
      // 3. Signal ChatInput to activate continuous voice mode
      window.dispatchEvent(new Event("lani:wake"));
    },
    [activate]
  );

  const { isListening: isWakeListening } = useWakeWordListener({
    wakePhrase: primaryWakePhrase || "lani",
    secondaryPhrase: secondaryWakePhrase || "hey lani",
    language: recognitionLanguage,
    onWakeDetected: handleWakeDetected,
    enabled: wakeWordEnabled && isKeywordLiveMode,
    sessionUnlocked: session.unlocked,
  });

  if (!wakeWordEnabled) {
    return (
      <p style={{ fontSize: "12px", color: "#6b7280", fontStyle: "italic" }}>
        {t("wake", "disabled_hint")}
      </p>
    );
  }

  // Localised mode descriptions (computed inside component so t() is in scope)
  const modeDescription: Record<string, string> = {
    manual: t("wake", "mode_manual"),
    push_to_talk: t("wake", "mode_ptt"),
    wake_phrase_placeholder: t("wake", "mode_phrase"),
    keyword_live: t("wake", "mode_keyword_live"),
    provider_ready: t("wake", "mode_provider"),
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {/* Mode badge */}
      <div
        style={{
          fontSize: "11px",
          color: "#9ca3af",
          background: "rgba(255,255,255,0.05)",
          padding: "4px 8px",
          borderRadius: "4px",
        }}
      >
        {modeDescription[wakeMode] ?? wakeMode}
      </div>

      {/* ── Blocked banner ──────────────────────────────────────────────────── */}
      {voiceState === "blocked" && (
        <div
          style={{
            fontSize: "12px",
            color: "#ef4444",
            background: "rgba(239,68,68,0.1)",
            border: "1px solid rgba(239,68,68,0.3)",
            borderRadius: "6px",
            padding: "6px 10px",
          }}
        >
          🚫 {error ?? "Activation blocked."}
        </div>
      )}

      {/* ── Timeout banner ──────────────────────────────────────────────────── */}
      {voiceState === "timeout" && !reverificationRequired && (
        <div
          style={{
            fontSize: "12px",
            color: "#f59e0b",
            background: "rgba(245,158,11,0.1)",
            border: "1px solid rgba(245,158,11,0.3)",
            borderRadius: "6px",
            padding: "6px 10px",
          }}
        >
          {t("wake", "timeout_msg")}
        </div>
      )}

      {/* ── Re-verification required banner ─────────────────────────────────── */}
      {(reverificationRequired || (voiceState === "timeout" && sessionExpired && reverificationRequired)) && (
        <div
          style={{
            fontSize: "12px",
            color: "#8b5cf6",
            background: "rgba(139,92,246,0.1)",
            border: "1px solid rgba(139,92,246,0.3)",
            borderRadius: "6px",
            padding: "6px 10px",
          }}
        >
          {t("wake", "reverification_required_msg")}
        </div>
      )}

      {/* ── STT error banner (mic / transcription failures) ─────────────────── */}
      {sttState === "error" && sttError && (
        <div
          style={{
            fontSize: "12px",
            color: "#ef4444",
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.25)",
            borderRadius: "6px",
            padding: "6px 10px",
          }}
        >
          🎙 {sttError}
        </div>
      )}

      {/* ── Processing spinner ──────────────────────────────────────────────── */}
      {(voiceState === "processing" || (loading && session.unlocked)) && (
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "#9ca3af" }}>
          <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>⟳</span>
          {t("wake", "processing")}
        </div>
      )}

      {/* ── Last response ────────────────────────────────────────────────────── */}
      {voiceState === "responding" && lastCommandResponse && (
        <div
          style={{
            fontSize: "12px",
            color: "#d1fae5",
            background: "rgba(16,185,129,0.08)",
            border: "1px solid rgba(16,185,129,0.2)",
            borderRadius: "6px",
            padding: "8px 10px",
            maxWidth: "360px",
          }}
        >
          <strong style={{ color: "#6ee7b7" }}>Lani:</strong>{" "}
          {lastCommandResponse.message}
        </div>
      )}

      {/* ── keyword_live: always-on listening indicator (when not yet unlocked) ── */}
      {wakeMode === "keyword_live" && !session.unlocked && voiceState !== "verifying" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "12px",
            color: isWakeListening ? "#10b981" : "#6b7280",
            background: isWakeListening
              ? "rgba(16,185,129,0.08)"
              : "rgba(255,255,255,0.04)",
            border: `1px solid ${isWakeListening ? "rgba(16,185,129,0.3)" : "rgba(255,255,255,0.1)"}`,
            borderRadius: "6px",
            padding: "6px 10px",
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: isWakeListening ? "#10b981" : "#4b5563",
              animation: isWakeListening ? "pulse 1.5s infinite" : "none",
              flexShrink: 0,
            }}
          />
          {isWakeListening
            ? `🎙 Klausau… (pasakykite "${primaryWakePhrase || "Lani"}")`
            : isWakeWordSupported()
            ? "⏳ Mikrofono leidimas laukiamas…"
            : "⚠️ SpeechRecognition nepalaikoma šiame naršyklėje."}
        </div>
      )}

      {/* ── wake_phrase_placeholder: activate via phrase input ─────────────── */}
      {wakeMode === "wake_phrase_placeholder" &&
        !session.unlocked &&
        voiceState !== "verifying" && (
          <div style={{ display: "flex", gap: "6px" }}>
            <input
              type="text"
              placeholder={t("wake", "phrase_placeholder", { phrase: primaryWakePhrase ?? "" })}
              value={phraseInput}
              onChange={(e) => setPhraseInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") activate(phraseInput);
              }}
              style={inputStyle}
            />
            <button
              onClick={() => { activate(phraseInput); setPhraseInput(""); }}
              disabled={loading || !phraseInput.trim()}
              style={btnStyle("#3b82f6", loading || !phraseInput.trim())}
            >
              {t("wake", "activate")}
            </button>
          </div>
        )}

      {/* ── manual: Activate button ─────────────────────────────────────────── */}
      {wakeMode === "manual" &&
        !session.unlocked &&
        voiceState !== "verifying" &&
        voiceState !== "processing" && (
          <button
            onClick={() => activate()}
            disabled={loading}
            style={btnStyle("#10b981", loading)}
          >
            {loading ? t("wake", "activating") : t("wake", "activate")}
          </button>
        )}

      {/* ── push_to_talk: either PTT circle or Activate if not unlocked ──────── */}
      {wakeMode === "push_to_talk" && !session.unlocked && (
        <button
          onClick={() => activate()}
          disabled={loading}
          style={btnStyle("#10b981", loading)}
        >
          {loading ? t("wake", "activating") : t("wake", "activate_ptt")}
        </button>
      )}

      {/* ── Verify & Unlock button ──────────────────────────────────────────── */}
      {voiceState === "verifying" && (
        <button
          onClick={() => verifyAndUnlock(undefined, true)}
          disabled={loading}
          style={btnStyle("#8b5cf6", loading)}
          title="Placeholder verification – real speaker auth not yet integrated"
        >
          {loading ? t("wake", "verifying") : t("wake", "verify_unlock")}
        </button>
      )}

      {/* ── Unlocked: command input + push-to-talk ─────────────────────────── */}
      {session.unlocked && voiceState !== "processing" && (
        <>
          {(wakeMode === "push_to_talk" || wakeMode === "keyword_live") ? (
            <div className="voice-orb-container">
              <VoiceOrb volume={orbVolume} state={voiceState} size={220} />
              <PushToTalkButton
                onResult={handlePttResult}
                onError={handlePttError}
                onStream={handlePttStream}
                disabled={loading}
                blocked={voiceState === "blocked"}
                language={recognitionLanguage}
                autoStart={autoStartRecording}
                onAutoStartConsumed={() => setAutoStartRecording(false)}
              />
            </div>
          ) : (
              <div style={{ display: "flex", gap: "6px" }}>
              <input
                type="text"
                placeholder={t("wake", "command_placeholder")}
                value={commandInput}
                onChange={(e) => setCommandInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSendCommand();
                }}
                style={inputStyle}
              />
              <button
                onClick={handleSendCommand}
                disabled={loading || !commandInput.trim()}
                style={btnStyle("#3b82f6", loading || !commandInput.trim())}
              >
                {loading ? t("wake", "sending") : t("wake", "send")}
              </button>
            </div>
          )}

          {/* Lock button always visible when unlocked */}
          <button
            onClick={() => lock()}
            disabled={loading}
            style={btnStyle("#ef4444", loading)}
          >
            {loading ? t("wake", "locking") : t("wake", "lock_session")}
          </button>
        </>
      )}
    </div>
  );
};

// ─── Style helpers ─────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: "6px 10px",
  borderRadius: "6px",
  border: "1px solid rgba(255,255,255,0.15)",
  background: "rgba(255,255,255,0.06)",
  color: "#f1f5f9",
  fontSize: "13px",
  outline: "none",
};

function btnStyle(color: string, disabled: boolean): React.CSSProperties {
  return {
    padding: "7px 14px",
    borderRadius: "6px",
    border: "none",
    background: disabled ? "rgba(100,100,100,0.3)" : color,
    color: disabled ? "#6b7280" : "#fff",
    fontSize: "13px",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "background 0.15s",
    whiteSpace: "nowrap",
  };
}
