/**
 * ChatPage – main chat interface.
 *
 * Integrates with the wake/session flow:
 *  - Watches lastCommandResponse from wakeStore and appends it to the chat
 *    thread whenever a voice command completes.
 *  - Shows the wake indicator, session indicator, and wake controls in the
 *    page header (only when wake word is enabled).
 *  - Shows stop-speaking button, follow-up hint, confirmation banner.
 */

import React, { useEffect, useRef } from "react";
import { v4 as uuidv4 } from "uuid";
import { useChatStore } from "../stores/chatStore";
import { useWakeStore } from "../stores/wakeStore";
import { useVoiceStore } from "../stores/voiceStore";
import { useSettingsStore } from "../stores/settingsStore";
import { ChatInput } from "../components/chat/ChatInput";
import { ChatMessageBubble } from "../components/chat/ChatMessageBubble";
import { WakeIndicator } from "../components/voice/WakeIndicator";
import { SessionIndicator } from "../components/voice/SessionIndicator";
import { WakeControls } from "../components/voice/WakeControls";
import { useI18n } from "../i18n/useI18n";
import { LaniOrb, OrbState } from "../components/avatar/LaniOrb";
import { LaniCore } from "../components/avatar/LaniCore";
import { useAudioLevel } from "../hooks/useAudioLevel";

export const ChatPage: React.FC = () => {
  const { messages, isLoading, sendChatStream } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  const { t, ta } = useI18n();
  const {
    voiceState,
    wakeWordEnabled,
    session,
    secondsRemaining,
    sessionExpired,
    reverificationRequired,
    securityMode,
    fetchStatus,
    lastCommandResponse,
    followUpHint,
    lastTtsText,
    stopSpeaking,
    replayLast,
  } = useWakeStore();
  const { autoPlayTts, isPlaying, stopPlayback } = useVoiceStore();
  const { settings } = useSettingsStore();

  // Ref to track which voice command responses we've already appended so we
  // don't double-add on re-renders.
  const lastAppendedSessionId = useRef<string | null>(null);
  const lastSpokenVoiceReplyRef = useRef<string | null>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Fetch wake status once on mount
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // When a voice command completes, append user + assistant messages to the thread
  useEffect(() => {
    if (!lastCommandResponse) return;
    // Deduplicate by session_id or command+timestamp
    const dedupeKey = lastCommandResponse.session.session_id
      ? `${lastCommandResponse.session.session_id}-${lastCommandResponse.command}`
      : null;
    if (dedupeKey && dedupeKey === lastAppendedSessionId.current) return;
    if (dedupeKey) lastAppendedSessionId.current = dedupeKey;

    const { addMessage } = useChatStore.getState();
    if (!addMessage) return; // fallback if store doesn't expose addMessage

    // Skip adding a message for pure interrupts (no command content)
    if (lastCommandResponse.was_interrupt) return;

    // User message
    addMessage({
      id: uuidv4(),
      role: "user",
      content: `🎙 ${lastCommandResponse.command}`,
      timestamp: new Date().toISOString(),
      input_mode: "voice",
      render_mode: "voice",
    });

    // Assistant response
    const statusIcon =
      lastCommandResponse.overall_status === "completed"
        ? "✔"
        : lastCommandResponse.overall_status === "blocked"
        ? "🚫"
        : lastCommandResponse.overall_status === "unrecognised"
        ? "❓"
        : lastCommandResponse.overall_status === "approval_required"
        ? "⏳"
        : "⚠";

    // Prefer the shaped tts_text (shorter) if available; fall back to message
    const displayText = lastCommandResponse.tts_text || lastCommandResponse.message;
    const responseText = `${statusIcon} ${displayText}`;

    addMessage({
      id: uuidv4(),
      role: "assistant",
      content: responseText,
      timestamp: new Date().toISOString(),
      input_mode: "voice",
      render_mode: settings?.tts_enabled ? "voice" : "text",
    });

    const ttsToSpeak = lastCommandResponse.tts_text || lastCommandResponse.message;
    const spokenKey = `${dedupeKey ?? lastCommandResponse.command}:${ttsToSpeak}`;
    if (settings?.tts_enabled && ttsToSpeak && lastSpokenVoiceReplyRef.current !== spokenKey) {
      lastSpokenVoiceReplyRef.current = spokenKey;
      // Normalize TTS language to BCP-47 (convert 'lt' -> 'lt-LT')
      const _ttsLangRaw = settings?.speech_output_language ?? settings?.assistant_language ?? "lt";
      const _ttsLang = _ttsLangRaw === "lt" ? "lt-LT" : _ttsLangRaw;
      void autoPlayTts(
        ttsToSpeak,
        settings?.tts_voice ?? "default",
        _ttsLang,
      );
    }
  }, [lastCommandResponse, autoPlayTts, settings]);

  // Auto-play TTS after text commands (sendChatStream)
  // NOTE: auto-play disabled — user uses manual AudioPlayer button or voice mode
  const lastMessageIdRef = useRef<string | null>(null);
  useEffect(() => {
    // auto-TTS disabled
    void lastMessageIdRef; // keep ref alive to avoid lint errors
  }, [messages, settings, autoPlayTts]);

  const isSpeaking = isPlaying || voiceState === "speaking";
  const isAwaitingConfirmation = voiceState === "waiting_for_confirmation";

  // Map voice state → orb visual state
  const orbState: OrbState =
    voiceState === "listening" ? "listening"
    : (voiceState === "speaking" || isPlaying) ? "speaking"
    : (voiceState === "processing" || voiceState === "responding") ? "thinking"
    : !session.unlocked ? "locked"
    : "idle";

  // Real-time mic amplitude — active while listening so the orb pulses with voice
  const isMicActive = voiceState === "listening" || voiceState === "verifying";
  const audioLevel  = useAudioLevel(isMicActive);
  const showVoiceFocusOrb = wakeWordEnabled && (session.unlocked || voiceState === "listening" || voiceState === "responding" || isPlaying);

  return (
    <div className="page chat-page">
      <div className="chat-page__header">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <LaniOrb state={orbState} audioLevel={audioLevel} size={44} />
            <h1>{t("chat", "title")}</h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            {isSpeaking && (
              <button
                onClick={() => { stopSpeaking(); stopPlayback(); }}
                title={t("voice_ux", "stop_speaking")}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "5px",
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: "1px solid rgba(239,68,68,0.4)",
                  background: "rgba(239,68,68,0.1)",
                  color: "#ef4444",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                  animation: "lani-pulse 1.2s ease-in-out infinite",
                }}
              >
                <span>■</span>
                <span>{t("voice_ux", "stop_speaking")}</span>
              </button>
            )}
            {lastTtsText && !isSpeaking && session.unlocked && (
              <button
                onClick={() => void replayLast(autoPlayTts)}
                title={t("voice_ux", "replay_last")}
                style={{
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: "1px solid rgba(16,185,129,0.3)",
                  background: "rgba(16,185,129,0.08)",
                  color: "#10b981",
                  fontSize: "12px",
                  cursor: "pointer",
                }}
              >
                ↩ {t("voice_ux", "replay_last")}
              </button>
            )}
            <WakeIndicator state={voiceState} wakeWordEnabled={wakeWordEnabled} />
          </div>
        </div>
        <p className="chat-page__subtitle">
          {t("chat", "subtitle")}
        </p>
        {wakeWordEnabled && (
          <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "6px" }}>
            <SessionIndicator
              session={session}
              secondsRemaining={secondsRemaining}
              voiceState={voiceState}
              sessionExpired={sessionExpired}
              reverificationRequired={reverificationRequired}
              securityMode={securityMode}
            />
            {/* Follow-up hint banner */}
            {followUpHint && !isSpeaking && !isAwaitingConfirmation && (
              <div
                style={{
                  padding: "5px 12px",
                  borderRadius: "6px",
                  background: "rgba(59,130,246,0.08)",
                  border: "1px solid rgba(59,130,246,0.2)",
                  color: "#3b82f6",
                  fontSize: "12px",
                }}
              >
                💬 {t("voice_ux", "follow_up_hint")}
              </div>
            )}
            {/* Confirmation state banner */}
            {isAwaitingConfirmation && (
              <div
                style={{
                  padding: "5px 12px",
                  borderRadius: "6px",
                  background: "rgba(245,158,11,0.12)",
                  border: "1px solid rgba(245,158,11,0.4)",
                  color: "#f59e0b",
                  fontSize: "12px",
                  fontWeight: 600,
                }}
              >
                ⏳ {t("voice_ux", "confirmation_banner")}
              </div>
            )}
            <WakeControls />
          </div>
        )}
      </div>

      <div className="chat-page__messages">
        {showVoiceFocusOrb && (
          <div className="chat-page__voice-focus" aria-live="polite">
            <LaniCore state={orbState} audioLevel={audioLevel} size={220} />
            <p className="chat-page__voice-focus-label">
              {voiceState === "listening"
                ? "Klausau jūsų balso…"
                : isPlaying || voiceState === "speaking"
                ? "Lani atsako balsu…"
                : voiceState === "processing" || voiceState === "responding"
                ? "Apdoroju balso komandą…"
                : session.unlocked
                ? "Balso sesija aktyvi"
                : ""}
            </p>
          </div>
        )}
        {messages.length === 0 ? (
          <div className="chat-page__empty">
            <div className="chat-page__empty-orb-wrapper">
              <LaniCore state={orbState} audioLevel={audioLevel} size={260} />
            </div>
            <p>{t("chat", "empty_greeting")}</p>
            <p>{t("chat", "empty_try")}</p>
            <ul>
              {ta("chat", "command_examples").map((ex, i) => (
                <li key={i}><code>{ex}</code></li>
              ))}
            </ul>
          </div>
        ) : (
          messages.map((msg) => (
            <ChatMessageBubble key={msg.id} message={msg} />
          ))
        )}
        {isLoading && (() => {
          // Only show typing dots before the first token arrives
          const last = messages[messages.length - 1];
          const waitingForFirstToken = !last || last.role !== "assistant" || last.content === "";
          return waitingForFirstToken ? (
            <div className="chat-page__typing">
              <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
            </div>
          ) : null;
        })()}
        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={sendChatStream} disabled={isLoading} />
    </div>
  );
};
