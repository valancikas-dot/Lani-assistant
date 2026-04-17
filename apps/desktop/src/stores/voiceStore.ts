/**
 * voiceStore – manages push-to-talk state, MediaRecorder lifecycle,
 * and TTS playback.
 *
 * State machine
 * ─────────────
 *   idle  ──[startListening]──▶  listening  ──[stopListening]──▶  processing
 *                                                                      │
 *                                                          API /voice/transcribe
 *                                                                      │
 *                                                              ◀── idle
 *
 * Transcript is exposed so ChatInput can auto-fill the text box.
 *
 * TTS playback
 * ────────────
 *   Call playResponse(text) to synthesize and play the assistant reply.
 *   The current HTMLAudioElement is tracked so the user can stop playback.
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type { VoiceState } from "../lib/types";
import { useChatStore } from "./chatStore";

interface VoiceStoreState {
  /** Current microphone state. */
  voiceState: VoiceState;
  /** True while TTS audio is playing. */
  isPlaying: boolean;
  /** True while a TTS synthesis request is in-flight. */
  isTtsLoading: boolean;
  /** Most recent transcript returned by the STT endpoint. */
  transcript: string;
  /** Last error message (STT or TTS failure). */
  lastError: string | null;
  /** Last TTS-specific error (separate from general lastError). */
  ttsError: string | null;
  /** True if the browser microphone permission has been granted at least once. */
  micPermissionGranted: boolean;

  /** Begin recording from the microphone. */
  startListening: (language?: string) => Promise<void>;
  /** Stop recording and send the audio to the transcription endpoint. */
  stopListening: () => Promise<void>;
  /** Synthesize *text* and play it through the browser audio API. */
  playResponse: (text: string, voice?: string, language?: string) => Promise<void>;
  /**
   * Auto-play TTS: synthesize *text* and play it.
   * Convenience wrapper around playResponse that also manages isTtsLoading / ttsError.
   */
  autoPlayTts: (text: string, voice?: string, language?: string) => Promise<void>;
  /** Stop any currently playing TTS audio. */
  stopPlayback: () => void;
  /** Clear the last transcript (e.g. after it has been consumed by ChatInput). */
  clearTranscript: () => void;
  /** Clear the last error. */
  clearError: () => void;
  /** Clear the TTS-specific error. */
  clearTtsError: () => void;
}

// ── Internal MediaRecorder state (not part of Zustand – avoids serialisation) ──
let _mediaRecorder: MediaRecorder | null = null;
let _audioChunks: Blob[] = [];
let _currentAudio: HTMLAudioElement | null = null;

export const useVoiceStore = create<VoiceStoreState>((set, get) => ({
  voiceState: "idle",
  isPlaying: false,
  isTtsLoading: false,
  transcript: "",
  lastError: null,
  ttsError: null,
  micPermissionGranted: false,

  // ── startListening ─────────────────────────────────────────────────────────
  startListening: async (language = "en") => {
    const { voiceState } = get();
    if (voiceState !== "idle") return; // prevent double-start

    try {
      // navigator.mediaDevices may be undefined in Tauri http:// context — use legacy fallback
      let stream: MediaStream;
      if (navigator.mediaDevices?.getUserMedia) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } else {
        const legacy =
          (navigator as any).getUserMedia ||
          (navigator as any).webkitGetUserMedia ||
          (navigator as any).mozGetUserMedia;
        if (!legacy) throw new Error("Microphone API not available. Please grant microphone permission in System Settings → Privacy & Security → Microphone.");
        stream = await new Promise<MediaStream>((resolve, reject) =>
          legacy.call(navigator, { audio: true }, resolve, reject)
        );
      }
      set({ micPermissionGranted: true, voiceState: "listening", lastError: null });

      _audioChunks = [];

      // Prefer webm/opus (Chrome); fall back to whatever the browser supports.
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";

      _mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});

      _mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) _audioChunks.push(e.data);
      };

      _mediaRecorder.onstop = async () => {
        // Stop all mic tracks to turn off the browser mic indicator.
        stream.getTracks().forEach((t) => t.stop());

        if (_audioChunks.length === 0) {
          set({ voiceState: "idle" });
          return;
        }

        set({ voiceState: "processing" });

        const blob = new Blob(_audioChunks, {
          type: _mediaRecorder?.mimeType ?? "audio/webm",
        });
        _audioChunks = [];

        try {
          const result = await api.transcribeAudio(blob, language);

          if (result.status === "success" && result.transcript) {
            const cleaned = result.transcript.trim();

            // ── Whisper hallucination filter ──────────────────────────────
            const letterCount = (cleaned.match(/\p{L}/gu) ?? []).length;
            const wordCount = cleaned.trim().split(/\s+/).filter(w => w.length > 1).length;

            // Known hallucination symbols
            const knownBad = ["🎵","♪","♫","🎶","[BLANK_AUDIO]","[blank_audio]","...","…","♩","🎼"].includes(cleaned);
            // URL only (no real spoken command)
            const isUrlOnly = /^(https?:\/\/|www\.)\S+$/.test(cleaned);
            // Looks like a domain (word.tld with no spaces)
            const isDomainOnly = /^[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(\/\S*)?$/.test(cleaned) && wordCount <= 1;
            // Too short or no real letters
            const tooShort = cleaned.length < 3 || letterCount === 0;
            // Single word that looks like a website/brand (ends in .lt .com .net etc)
            const isBrandDomain = wordCount === 1 && /\.(lt|com|net|org|eu|io|tv|fm)$/i.test(cleaned);

            const isHallucination = knownBad || isUrlOnly || isDomainOnly || tooShort || isBrandDomain;

            if (isHallucination) {
              console.debug("[voiceStore] dropped hallucination:", JSON.stringify(cleaned));
              set({ voiceState: "idle" });
              return;
            }

            // Auto-send to chat — no need to press Send manually
            set({ transcript: cleaned, voiceState: "idle" });
            try {
              await useChatStore.getState().sendCommandWithPlan(cleaned);
            } catch (_e) {
              // sendCommandWithPlan handles its own errors; just ignore here
            }
          } else if (result.status === "provider_not_configured") {
            set({
              voiceState: "idle",
              lastError: result.message ?? "Voice provider not configured.",
            });
          } else {
            set({
              voiceState: "idle",
              lastError: result.message ?? "Transcription failed.",
            });
          }
        } catch (err) {
          set({
            voiceState: "idle",
            lastError: err instanceof Error ? err.message : "Transcription request failed.",
          });
        }
      };

      _mediaRecorder.start(250); // collect chunks every 250 ms
    } catch (err) {
      set({
        voiceState: "idle",
        lastError:
          err instanceof Error
            ? err.message
            : "Microphone access denied. Grant permission in browser settings.",
      });
    }
  },

  // ── stopListening ──────────────────────────────────────────────────────────
  stopListening: async () => {
    if (_mediaRecorder && _mediaRecorder.state !== "inactive") {
      _mediaRecorder.stop(); // triggers onstop → processes audio
    }
  },

  // ── playResponse ───────────────────────────────────────────────────────────
  playResponse: async (text, voice = "default", language = "en") => {
    get().stopPlayback(); // stop any previous playback

    try {
      const result = await api.synthesizeSpeech(text, voice, language);

      if (result.status === "success" && result.audio_base64) {
        const binary = atob(result.audio_base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        const blob = new Blob([bytes], { type: result.mime_type });
        const url = URL.createObjectURL(blob);

        _currentAudio = new Audio(url);
        set({ isPlaying: true, ttsError: null });

        _currentAudio.onended = () => {
          URL.revokeObjectURL(url);
          _currentAudio = null;
          set({ isPlaying: false });
        };
        _currentAudio.onerror = () => {
          URL.revokeObjectURL(url);
          _currentAudio = null;
          set({ isPlaying: false, ttsError: "Audio playback failed.", lastError: "Audio playback failed." });
        };

        await _currentAudio.play();
      } else if (result.status === "provider_not_configured") {
        set({
          ttsError: result.message ?? "TTS provider not configured.",
          lastError: result.message ?? "TTS provider not configured.",
        });
      } else {
        set({
          ttsError: result.message ?? "Speech synthesis failed.",
          lastError: result.message ?? "Speech synthesis failed.",
        });
      }
    } catch (err) {
      set({
        isPlaying: false,
        ttsError: err instanceof Error ? err.message : "Synthesis request failed.",
        lastError: err instanceof Error ? err.message : "Synthesis request failed.",
      });
    }
  },

  // ── stopPlayback ───────────────────────────────────────────────────────────
  stopPlayback: () => {
    if (_currentAudio) {
      _currentAudio.pause();
      _currentAudio = null;
    }
    set({ isPlaying: false });
  },

  clearTranscript: () => set({ transcript: "" }),
  clearError: () => set({ lastError: null }),
  clearTtsError: () => set({ ttsError: null }),

  // ── autoPlayTts ────────────────────────────────────────────────────────────
  autoPlayTts: async (text, voice = "default", language = "en") => {
    if (!text.trim()) return;
    set({ isTtsLoading: true, ttsError: null });
    try {
      await get().playResponse(text, voice, language);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "TTS playback failed.";
      set({ isTtsLoading: false, ttsError: msg });
      return;
    }
    set({ isTtsLoading: false });
  },
}));
