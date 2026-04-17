/**
 * ChatInput – text input bar at the bottom of the chat page.
 *
 * Voice modes:
 *  • Single-shot mic (🎙 button) – click once to record, click again to send.
 *  • Wake/stop word mode – sakyk "lani <komanda> pabaiga" kad siųstum balso komandą.
 *    Aktyvuoti/išjungti spaudžiant 🎙 mygtuką ARBA visada aktyvus kai voice_enabled.
 */

import React, { useState, useRef, KeyboardEvent, useEffect, useCallback } from "react";
import { MicrophoneButton } from "./MicrophoneButton";
import { useVoiceStore } from "../../stores/voiceStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWakeStopVoice } from "../../hooks/useWakeStopVoice";
import { useChatStore } from "../../stores/chatStore";

interface ChatInputProps {
  onSend: (command: string, fileContent?: string, fileName?: string) => Promise<unknown> | void;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled }) => {
  const [value, setValue] = useState("");
  const [attachedFile, setAttachedFile] = useState<{ name: string; content: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { lastError, clearError, playResponse, stopPlayback, isPlaying } = useVoiceStore();
  const { settings } = useSettingsStore();
  const { sendCommandWithPlan } = useChatStore();
  const voiceEnabled = settings?.voice_enabled ?? false;
  // Normalise stored language codes to BCP-47 form expected by Web Speech API
  const _rawLang = settings?.speech_recognition_language ?? "lt";
  const language = _rawLang === "lt" ? "lt-LT" : _rawLang;
  const wakeWordEnabled = settings?.wake_word_enabled ?? false;
  const wakeMode = settings?.wake_mode ?? "manual";
  const continuousHandsFreeEnabled = wakeWordEnabled && wakeMode === "keyword_live";

  // ── Wake/Stop žodžių balso režimas ──────────────────────────────────────
  const handleVoiceCommand = useCallback(
    async (transcript: string) => {
      // Sustabdome bet kokį esamą TTS prieš siunčiant naują komandą
      stopPlayback();
      const response = await sendCommandWithPlan(transcript);
      // Jei gautas atsakymas su tts_text – grojame lietuviškai
      if (response?.tts_text && response.tts_text.length > 1) {
        await playResponse(response.tts_text, "default", language);
      }
    },
    [sendCommandWithPlan, playResponse, stopPlayback, language]
  );

  const { status: cvStatus, isActive: cvActive, activate: cvActivate, deactivate: cvDeactivate, lastTranscript: cvLastTranscript } =
    useWakeStopVoice({
      language,
      onCommand: handleVoiceCommand,
      onWakeDetected: () => { /* galima rodyti vizualinį signalą */ },
      // Kai TTS groja – mikrofonas nutildomas (nereaguoja į Lani balsą)
      isTtsPlaying: isPlaying ?? false,
    });

  const toggleContinuous = useCallback(() => {
    if (cvActive) {
      cvDeactivate();
    } else {
      cvActivate();
    }
  }, [cvActive, cvActivate, cvDeactivate]);

  // ── Auto-aktyvuoti kai voice_enabled = true ir settings užkrauti ────────
  useEffect(() => {
    if (voiceEnabled && continuousHandsFreeEnabled && !cvActive) {
      cvActivate();
    } else if ((!voiceEnabled || !continuousHandsFreeEnabled) && cvActive) {
      cvDeactivate();
    }
  // Tik kai voiceEnabled pasikeičia (settings užkrauna)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceEnabled, continuousHandsFreeEnabled]);

  // ── Wake word DOM event (iš kitų komponentų) ────────────────────────────
  useEffect(() => {
    const handler = () => { if (!cvActive) cvActivate(); };
    window.addEventListener("lani:wake", handler);
    return () => window.removeEventListener("lani:wake", handler);
  }, [cvActive, cvActivate]);

  const handleSend = () => {
    const trimmed = value.trim();
    if ((!trimmed && !attachedFile) || disabled) return;
    void onSend(trimmed, attachedFile?.content, attachedFile?.name);
    setValue("");
    setAttachedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = ev.target?.result as string;
      setAttachedFile({ name: file.name, content });
    };
    reader.readAsText(file, "utf-8");
  };

  // Wake/stop mode status label
  const cvLabel =
    cvStatus === "processing"
      ? "Vykdau komandą..."
      : "Klausau... sakyk: Lani, <komanda>";

  const cvTitle = cvActive
    ? "Balso režimas įjungtas. Sakyk: Lani, atidark safari."
    : "Įjungti balso režimą.";

  // "recording" pašalintas iš naujos architektūros – naudojame "processing"
  const isRecording = cvStatus === "processing";

  return (
    <div className="chat-input">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.md,.py,.ts,.tsx,.js,.jsx,.json,.yaml,.yml,.csv,.html,.css,.rs,.toml,.sh,.env,.log,.xml,.sql"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      {/* Attached file badge */}
      {attachedFile && (
        <div
          style={{
            position: "absolute",
            bottom: "100%",
            left: 0,
            right: 0,
            marginBottom: "4px",
            padding: "4px 12px",
            borderRadius: "8px",
            background: "rgba(99,102,241,0.1)",
            border: "1px solid rgba(99,102,241,0.3)",
            color: "#a5b4fc",
            fontSize: "12px",
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span>📎</span>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {attachedFile.name}
          </span>
          <button
            type="button"
            onClick={() => { setAttachedFile(null); if (fileInputRef.current) fileInputRef.current.value = ""; }}
            style={{ background: "none", border: "none", color: "#a5b4fc", cursor: "pointer", fontSize: "14px", padding: "0 2px" }}
            aria-label="Pašalinti failą"
          >
            ×
          </button>
        </div>
      )}
      {/* ── Wake/stop voice mode button ── */}
      {voiceEnabled && (
        <button
          className={`mic-btn mic-btn--continuous ${cvActive ? `mic-btn--active mic-btn--${cvStatus}` : ""}`}
          onClick={toggleContinuous}
          title={cvTitle}
          aria-label={cvTitle}
          aria-pressed={cvActive}
          disabled={disabled}
          type="button"
          style={{
            background: cvActive
              ? isRecording ? "rgba(239,68,68,0.15)" : "rgba(16,185,129,0.12)"
              : undefined,
            borderColor: cvActive
              ? isRecording ? "rgba(239,68,68,0.5)" : "rgba(16,185,129,0.4)"
              : undefined,
            color: cvActive
              ? isRecording ? "#ef4444" : "#10b981"
              : undefined,
          }}
        >
          {cvActive ? (
            isRecording ? "⏳" : "🎙"
          ) : (
            "🎙"
          )}
        </button>
      )}

      {/* ── Single-shot mic button (kai wake/stop režimas išjungtas) ── */}
      {voiceEnabled && !cvActive && (
        <MicrophoneButton language={language} disabled={disabled} />
      )}

      {/* ── Wake/stop mode status bar ── */}
      {cvActive && (
        <div
          style={{
            position: "absolute",
            bottom: "100%",
            left: 0,
            right: 0,
            marginBottom: "4px",
            padding: "4px 12px",
            borderRadius: "8px",
            background: isRecording
              ? "rgba(239,68,68,0.1)"
              : "rgba(16,185,129,0.08)",
            border: `1px solid ${isRecording ? "rgba(239,68,68,0.3)" : "rgba(16,185,129,0.2)"}`,
            color: isRecording ? "#ef4444" : "#10b981",
            fontSize: "12px",
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span style={{ animation: isRecording ? "lani-pulse 1s ease-in-out infinite" : undefined }}>
            {isRecording ? "⏳" : "🎙"}
          </span>
          <span>{cvLabel}</span>
          {cvLastTranscript && (
            <span style={{ opacity: 0.7, fontWeight: 400 }}>— „{cvLastTranscript}"</span>
          )}
        </div>
      )}

      <textarea
        ref={textareaRef}
        className="chat-input__textarea"
        value={value}
        placeholder={
          cvActive
            ? isRecording
              ? "Įrašau... baik žodžiu pabaiga"
              : "Sakyk: lani [komanda] pabaiga..."
            : voiceEnabled
              ? "Rašyk arba spustelėk kalbėti..."
              : "Rašyk komandą..."
        }
        disabled={disabled}
        rows={1}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
      />

      {/* ── Paperclip / attach file button ── */}
      <button
        type="button"
        className="chat-input__attach-btn"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled}
        title="Prisegti failą"
        aria-label="Prisegti failą"
        style={{
          background: attachedFile ? "rgba(99,102,241,0.15)" : undefined,
          borderColor: attachedFile ? "rgba(99,102,241,0.4)" : undefined,
          color: attachedFile ? "#a5b4fc" : undefined,
        }}
      >
        📎
      </button>

      <button
        className="chat-input__send-btn"
        onClick={handleSend}
        disabled={disabled || (!value.trim() && !attachedFile)}
        aria-label="Send"
      >
        ➤
      </button>

      {/* Inline voice error toast */}
      {lastError && (
        <div className="voice-error-toast" role="alert">
          <span>{lastError}</span>
          <button
            className="voice-error-toast__close"
            onClick={clearError}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
};
