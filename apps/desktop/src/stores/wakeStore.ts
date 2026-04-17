/**
 * Zustand store for wake-word and voice-session state.
 *
 * Keeps a local mirror of backend WakeStatus so components can read it
 * reactively without extra prop-drilling. The store also manages:
 *  - session countdown timer (runs in-process, syncs with backend expires_at)
 *  - processCommand: session-gated text command → planner/executor pipeline
 *  - transcribeAndCommand: full STT round-trip (audio blob → transcript → command)
 */

import { create } from "zustand";
import { useVoiceStore } from "./voiceStore";
import type {
  WakeVoiceState,
  WakeMode,
  WakeSessionInfo,
  WakeStatus,
  WakeSettings,
  VoiceCommandResponse,
  SttRecordingState,
} from "../lib/types";
import {
  getWakeStatus,
  updateWakeSettings,
  activateWake,
  verifyAndUnlock,
  lockWakeSession,
  sendVoiceCommand,
  transcribeAudio,
  getVoiceContext,
  clearVoiceContext,
} from "../lib/api";

interface WakeStore {
  // ── State ──────────────────────────────────────────────────────────────────
  voiceState: WakeVoiceState;
  wakeMode: WakeMode;
  wakeWordEnabled: boolean;
  primaryWakePhrase: string;
  secondaryWakePhrase: string;
  sessionTimeoutSeconds: number;
  requireReverification: boolean;
  session: WakeSessionInfo;
  secondsRemaining: number | null;
  /** Set to true when the session expires and must be re-activated. */
  sessionExpired: boolean;
  /** Set to true when expiry requires re-verification before re-use. */
  reverificationRequired: boolean;
  /** Security mode reported by backend ("disabled" | "strict" | …). */
  securityMode: string;

  loading: boolean;
  error: string | null;

  /** Last voice command response – used by ChatPage to append to message thread. */
  lastCommandResponse: VoiceCommandResponse | null;

  /** Last TTS text spoken by the assistant – used for the replay feature. */
  lastTtsText: string | null;
  /** True while session is unlocked – shows the "say a follow-up" hint in the UI. */
  followUpHint: boolean;

  // ── STT recording state ────────────────────────────────────────────────────
  /** Fine-grained state of the push-to-talk recording pipeline. */
  sttState: SttRecordingState;
  /** Last successfully received transcript text. */
  transcript: string | null;
  /** Human-readable error for the last failed STT round-trip. */
  sttError: string | null;

  // ── Actions ────────────────────────────────────────────────────────────────
  fetchStatus: () => Promise<void>;
  activate: (phraseHeard?: string, modeOverride?: WakeMode) => Promise<void>;
  verifyAndUnlock: (audioBase64?: string, bypass?: boolean) => Promise<void>;
  lock: () => Promise<void>;
  saveSettings: (settings: Partial<WakeSettings>) => Promise<void>;
  /** Submit a text command through the active voice session. */
  processCommand: (command: string, ttsResponse?: boolean) => Promise<VoiceCommandResponse | null>;
  /**
   * Full STT round-trip: upload audio blob → get transcript → pass transcript
   * into the existing voice session command flow.
   *
   * Manages sttState transitions internally so the UI can react to each step.
   */
  transcribeAndCommand: (audioBlob: Blob, language?: string) => Promise<VoiceCommandResponse | null>;
  /**
   * Stop any currently playing TTS audio and return the session to unlocked
   * state. Also sends an interrupt command if the session is active.
   */
  stopSpeaking: () => void;
  /**
   * Replay the last assistant TTS response (fetches from backend if not cached).
   */
  replayLast: (autoPlay: (text: string) => Promise<void>) => Promise<void>;
  /** Manually clear the conversational context. */
  clearContext: () => Promise<void>;

  // ── Internal ───────────────────────────────────────────────────────────────
  _applyStatus: (status: WakeStatus) => void;
  _startCountdown: () => void;
  _countdownTimer: ReturnType<typeof setInterval> | null;
  /** Polling interval that re-fetches status every 30s while session is active. */
  _pollTimer: ReturnType<typeof setInterval> | null;
  _stopPoll: () => void;
  _startPoll: () => void;
}

export const useWakeStore = create<WakeStore>((set, get) => ({
  voiceState: "idle",
  wakeMode: "manual",
  wakeWordEnabled: false,
  primaryWakePhrase: "Lani",
  secondaryWakePhrase: "Hey Lani",
  sessionTimeoutSeconds: 120,
  requireReverification: false,
  session: {
    unlocked: false,
    unlocked_at: null,
    expires_at: null,
    seconds_remaining: null,
    session_id: null,
  },
  secondsRemaining: null,
  sessionExpired: false,
  reverificationRequired: false,
  securityMode: "disabled",
  loading: false,
  error: null,
  lastCommandResponse: null,
  lastTtsText: null,
  followUpHint: false,
  sttState: "idle" as SttRecordingState,
  transcript: null,
  sttError: null,
  _countdownTimer: null,
  _pollTimer: null,

  _applyStatus(status: WakeStatus) {
    set({
      voiceState: status.voice_state,
      wakeMode: status.wake_mode,
      wakeWordEnabled: status.wake_word_enabled,
      primaryWakePhrase: status.primary_wake_phrase,
      secondaryWakePhrase: status.secondary_wake_phrase,
      sessionTimeoutSeconds: status.voice_session_timeout_seconds,
      requireReverification: status.require_reverification_after_timeout,
      session: status.session,
      secondsRemaining: status.session.seconds_remaining,
      securityMode: status.security_mode ?? "disabled",
    });
    // Clear expired flags when backend confirms session is live
    if (status.session.unlocked) {
      set({ sessionExpired: false, reverificationRequired: false });
    }
    get()._startCountdown();
  },

  _stopPoll() {
    const t = get()._pollTimer;
    if (t) clearInterval(t);
    set({ _pollTimer: null });
  },

  _startPoll() {
    get()._stopPoll();
    const timer = setInterval(() => {
      get().fetchStatus();
    }, 30_000);
    set({ _pollTimer: timer });
  },

  _startCountdown() {
    const existing = get()._countdownTimer;
    if (existing) clearInterval(existing);

    if (!get().session.unlocked || !get().session.expires_at) {
      set({ _countdownTimer: null, secondsRemaining: null });
      get()._stopPoll();
      return;
    }

    // Start 30s polling so backend expiry is picked up even if countdown misses
    get()._startPoll();

    const timer = setInterval(() => {
      const expiresAt = get().session.expires_at;
      if (!expiresAt) {
        clearInterval(timer);
        set({ secondsRemaining: null, _countdownTimer: null });
        return;
      }
      const remaining = Math.max(
        0,
        Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)
      );
      set({ secondsRemaining: remaining });
      if (remaining <= 0) {
        clearInterval(timer);
        get()._stopPoll();
        // Sync with backend to get authoritative lock state
        get().fetchStatus();
        set({
          voiceState: "timeout",
          sessionExpired: true,
          secondsRemaining: null,
          _countdownTimer: null,
          session: {
            ...get().session,
            unlocked: false,
            expires_at: null,
            seconds_remaining: null,
            session_id: null,
          },
        });
      }
    }, 1000);
    set({ _countdownTimer: timer });
  },

  async fetchStatus() {
    set({ loading: true, error: null });
    try {
      const status = await getWakeStatus();
      get()._applyStatus(status);
    } catch (e: any) {
      set({ error: e.message ?? "Failed to fetch wake status" });
    } finally {
      set({ loading: false });
    }
  },

  async activate(phraseHeard?: string, modeOverride?: WakeMode) {
    set({ loading: true, error: null });
    try {
      const resp = await activateWake({
        phrase_heard: phraseHeard,
        mode_override: modeOverride,
      });
      set({
        voiceState: resp.voice_state,
        session: resp.session,
        secondsRemaining: resp.session.seconds_remaining,
        error: resp.ok ? null : resp.blocked_reason ?? resp.message,
      });
      if (resp.ok) {
        set({ sessionExpired: false, reverificationRequired: false });
        get()._startCountdown();
      }
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  async verifyAndUnlock(audioBase64?: string, bypass?: boolean) {
    set({ loading: true, error: null });
    try {
      const resp = await verifyAndUnlock({ audio_base64: audioBase64, bypass });
      set({
        voiceState: resp.voice_state,
        session: resp.session,
        secondsRemaining: resp.session.seconds_remaining,
        error: resp.ok ? null : resp.blocked_reason ?? resp.message,
      });
      if (resp.ok) {
        set({ sessionExpired: false, reverificationRequired: false });
        get()._startCountdown();
      }
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  async lock() {
    set({ loading: true, error: null });
    try {
      const resp = await lockWakeSession();
      const existing = get()._countdownTimer;
      if (existing) clearInterval(existing);
      get()._stopPoll();
      set({
        voiceState: resp.voice_state,
        session: resp.session,
        secondsRemaining: null,
        sessionExpired: false,
        reverificationRequired: false,
        followUpHint: false,
        lastTtsText: null,
        _countdownTimer: null,
      });
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  async saveSettings(settings: Partial<WakeSettings>) {
    set({ loading: true, error: null });
    try {
      await updateWakeSettings(settings);
      await get().fetchStatus();
    } catch (e: any) {
      set({ error: e.message });
    } finally {
      set({ loading: false });
    }
  },

  async processCommand(command: string, ttsResponse = false) {
    set({ loading: true, error: null, lastCommandResponse: null });
    try {
      const resp = await sendVoiceCommand({
        command,
        tts_response: ttsResponse,
        include_context: true,
      });
      const isExpired =
        resp.blocked_reason === "session_expired" ||
        resp.blocked_reason === "reverification_required";
      set({
        voiceState: resp.voice_state,
        session: resp.session,
        secondsRemaining: resp.session.seconds_remaining,
        lastCommandResponse: resp,
        error: resp.ok ? null : resp.blocked_reason ?? resp.message,
        sessionExpired: isExpired ? true : get().sessionExpired,
        reverificationRequired: resp.blocked_reason === "reverification_required"
          ? true
          : get().reverificationRequired,
        // Cache the TTS text for replay
        lastTtsText: resp.tts_text ?? get().lastTtsText,
        // Show follow-up hint whenever session stays unlocked
        followUpHint: resp.ok && resp.session.unlocked,
      });
      if (resp.ok && resp.session.unlocked) get()._startCountdown();
      return resp;
    } catch (e: any) {
      set({ error: e.message });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  async transcribeAndCommand(audioBlob: Blob, language = "en") {
    // ── Step 1: upload + transcribe ────────────────────────────────────────
    set({ sttState: "uploading", sttError: null, transcript: null });
    let transcript: string;
    try {
      set({ sttState: "transcribing" });
      const sttResp = await transcribeAudio(audioBlob, language);

      if (sttResp.status === "provider_not_configured") {
        // Not an error the user made – show a clear message
        set({
          sttState: "error",
          sttError:
            "Speech-to-text provider not configured. " +
            "Set VOICE_PROVIDER in the backend .env file, or type your command instead.",
        });
        return null;
      }

      if (sttResp.status === "error") {
        set({
          sttState: "error",
          sttError: sttResp.message ?? "Transcription failed.",
        });
        return null;
      }

      transcript = sttResp.transcript.trim();
      if (!transcript) {
        set({
          sttState: "error",
          sttError: "Nothing was heard. Please speak clearly and try again.",
        });
        return null;
      }

      set({ transcript, sttState: "processing" });
    } catch (e: any) {
      set({
        sttState: "error",
        sttError:
          e?.message?.includes("413")
            ? "Recording is too long. Please keep it under the configured limit."
            : e?.message?.includes("422")
            ? "Audio upload failed – speech-to-text may be disabled."
            : `Audio upload failed: ${e?.message ?? "unknown error"}`,
      });
      return null;
    }

    // ── Step 2: pass transcript into the voice session command flow ─────────
    try {
      const cmdResp = await get().processCommand(transcript, /* ttsResponse */ true);
      set({ sttState: cmdResp ? "done" : "error" });
      return cmdResp;
    } catch (e: any) {
      set({ sttState: "error", sttError: e?.message ?? "Command failed." });
      return null;
    }
  },

  stopSpeaking() {
    useVoiceStore.getState().stopPlayback();
    // If we were in the speaking state, go back to unlocked so follow-ups work.
    const current = get().voiceState;
    if (current === "speaking" || current === "responding") {
      set({ voiceState: "unlocked" });
    }
  },

  async replayLast(autoPlay: (text: string) => Promise<void>) {
    // Try cached text first
    const cached = get().lastTtsText;
    if (cached) {
      await autoPlay(cached);
      return;
    }
    // Fall back to backend context endpoint
    try {
      const ctx = await getVoiceContext();
      if (ctx.turns.length > 0) {
        // Find last assistant turn
        const lastAssistant = [...ctx.turns].reverse().find((t) => t.role === "assistant");
        if (lastAssistant) {
          set({ lastTtsText: lastAssistant.text });
          await autoPlay(lastAssistant.text);
        }
      }
    } catch {
      // Silently ignore – replay is best-effort
    }
  },

  async clearContext() {
    try {
      await clearVoiceContext();
    } catch {
      // Ignore errors – context clearing is best-effort
    }
  },
}));
