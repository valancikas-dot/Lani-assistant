/**
 * Settings store – loads and persists user application settings.
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type { AppSettings, SettingsUpdate } from "../lib/types";

interface SettingsState {
  settings: AppSettings | null;
  isLoading: boolean;
  isSaving: boolean;
  fetchSettings: () => Promise<void>;
  saveSettings: (update: SettingsUpdate) => Promise<void>;
}

const DEFAULT_SETTINGS: AppSettings = {
  allowed_directories: [],
  preferred_language: "en",
  tts_enabled: false,
  tts_voice: "default",
  tts_provider: "",
  ui_language: "en",
  assistant_language: "en",
  speech_recognition_language: "en",
  speech_output_language: "en",
  multilingual_enabled: false,
  // voice layer / security
  voice_enabled: false,
  speaker_verification_enabled: false,
  voice_lock_enabled: false,
  security_mode: "disabled",
  fallback_pin_enabled: false,
  fallback_passphrase_enabled: false,
  allow_text_access_without_voice_verification: true,
  require_verification_for_sensitive_actions_only: false,
  max_failed_voice_attempts: 5,
  lock_on_failed_verification: true,
  first_run_complete: false,
  failed_voice_attempts: 0,
  // wake word / session
  wake_word_enabled: false,
  primary_wake_phrase: "Lani",
  secondary_wake_phrase: "Hey Lani",
  voice_session_timeout_seconds: 120,
  require_reverification_after_timeout: false,
  wake_mode: "manual",
  // STT
  stt_enabled: true,
  stt_provider: "",
  max_audio_upload_seconds: 120,
  max_audio_upload_mb: 25,
};

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  isLoading: false,
  isSaving: false,

  fetchSettings: async () => {
    set({ isLoading: true });
    try {
      const data = await api.getSettings();
      set({ settings: data, isLoading: false });
    } catch {
      set({ settings: DEFAULT_SETTINGS, isLoading: false });
    }
  },

  saveSettings: async (update: SettingsUpdate) => {
    set({ isSaving: true });
    try {
      const data = await api.updateSettings(update);
      set({ settings: data, isSaving: false });
    } catch {
      set({ isSaving: false });
    }
  },
}));
