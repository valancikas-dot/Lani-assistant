/**
 * SettingsPage – view and edit user preferences.
 *
 * Sections
 * ────────
 *   1. Allowed Directories   – file-system sandbox
 *   2. Voice                 – master toggle, language, voice selector
 *   3. Text-to-Speech        – legacy tts_enabled / tts_voice fields
 *   4. Language              – preferred_language
 */

import React, { useEffect, useMemo, useState } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { useWakeStore } from "../stores/wakeStore";
import { getSupportedLanguages, getVoiceProviders, getApiKeys, saveApiKeys } from "../lib/api";
import type { WakeMode, VoiceProviderInfo } from "../lib/types";
import type { ApiKeyEntry } from "../lib/api";
import { useI18n } from "../i18n/useI18n";
import { useI18nStore, SUPPORTED_UI_LANGUAGES } from "../i18n/index";
import { VoiceEnrollmentPanel } from "../components/settings/VoiceEnrollmentPanel";

interface SupportedLanguageOption {
  code: string;
  display_name: string;
  native_name?: string;
}

const FALLBACK_LANGUAGE_OPTIONS: SupportedLanguageOption[] = [
  { code: "en", display_name: "English", native_name: "English" },
  { code: "lt", display_name: "Lithuanian", native_name: "Lietuvių" },
  { code: "de", display_name: "German", native_name: "Deutsch" },
  { code: "fr", display_name: "French", native_name: "Français" },
  { code: "es", display_name: "Spanish", native_name: "Español" },
  { code: "it", display_name: "Italian", native_name: "Italiano" },
  { code: "pt", display_name: "Portuguese", native_name: "Português" },
  { code: "nl", display_name: "Dutch", native_name: "Nederlands" },
  { code: "ja", display_name: "Japanese", native_name: "日本語" },
  { code: "zh", display_name: "Chinese", native_name: "中文" },
  { code: "ko", display_name: "Korean", native_name: "한국어" },
];

// Common voice names per provider (shown as hints only; free text is also accepted)
const VOICE_PRESETS = [
  { value: "default", label: "default" },
  // OpenAI TTS voices
  { value: "alloy", label: "alloy (OpenAI)" },
  { value: "echo", label: "echo (OpenAI)" },
  { value: "fable", label: "fable (OpenAI)" },
  { value: "nova", label: "nova (OpenAI)" },
  { value: "onyx", label: "onyx (OpenAI)" },
  { value: "shimmer", label: "shimmer (OpenAI)" },
];

export const SettingsPage: React.FC = () => {
  const { settings, isLoading, isSaving, fetchSettings, saveSettings } =
    useSettingsStore();
  const { fetchStatus: fetchWakeStatus, saveSettings: saveWakeSettings,
          wakeWordEnabled, wakeMode, primaryWakePhrase, secondaryWakePhrase,
          sessionTimeoutSeconds, requireReverification } = useWakeStore();
  const { t } = useI18n();
  const setI18nLanguage = useI18nStore((s) => s.setLanguage);

  // ── Allowed directories ────────────────────────────────────────────────────
  const [dirInput, setDirInput] = useState("");

  // ── Voice ──────────────────────────────────────────────────────────────────
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState("en");
  const [selectedVoice, setSelectedVoice] = useState("default");
  const [uiLanguage, setUiLanguage] = useState("en");
  const [assistantLanguage, setAssistantLanguage] = useState("en");

  // ── Wake-word ─────────────────────────────────────────────────────────────
  const [localWakeEnabled, setLocalWakeEnabled] = useState(false);
  const [localWakeMode, setLocalWakeMode] = useState<WakeMode>("manual");
  const [localPrimaryPhrase, setLocalPrimaryPhrase] = useState("Lani");
  const [localSecondaryPhrase, setLocalSecondaryPhrase] = useState("Hey Lani");
  const [localSessionTimeout, setLocalSessionTimeout] = useState(120);
  const [localReverify, setLocalReverify] = useState(false);

  // ── TTS ───────────────────────────────────────────────────────────────────
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [ttsVoice, setTtsVoice] = useState("default");
  const [ttsProvider, setTtsProvider] = useState("");

  // ── Language ──────────────────────────────────────────────────────────────
  const [language, setLanguage] = useState("en");

  // ── STT ───────────────────────────────────────────────────────────────────
  const [sttEnabled, setSttEnabled] = useState(true);
  const [maxUploadSeconds, setMaxUploadSeconds] = useState(120);
  const [maxUploadMb, setMaxUploadMb] = useState(25);
  const [voiceProviders, setVoiceProviders] = useState<VoiceProviderInfo[]>([]);

  // ── API Keys ───────────────────────────────────────────────────────────────
  const [apiKeys, setApiKeys] = useState<ApiKeyEntry[]>([]);
  const [apiKeyDrafts, setApiKeyDrafts] = useState<Record<string, string>>({});
  const [apiKeyVisible, setApiKeyVisible] = useState<Record<string, boolean>>({});
  const [apiKeysSaving, setApiKeysSaving] = useState(false);
  const [apiKeysSaved, setApiKeysSaved] = useState(false);
  const [supportedLanguages, setSupportedLanguages] = useState<SupportedLanguageOption[]>(FALLBACK_LANGUAGE_OPTIONS);
  const [micStatus, setMicStatus] = useState<"unknown" | "granted" | "denied" | "prompt">("unknown");

  const languageOptions = useMemo(
    () => supportedLanguages.map((lang) => ({
      value: lang.code,
      label: `${lang.native_name || lang.display_name} (${lang.code})`,
    })),
    [supportedLanguages],
  );

  useEffect(() => {
    void fetchSettings();
    void fetchWakeStatus();
    // Load voice providers
    void getVoiceProviders().then(setVoiceProviders).catch(() => {});
    void getSupportedLanguages()
      .then((langs) => {
        if (Array.isArray(langs) && langs.length > 0) {
          setSupportedLanguages(langs);
        }
      })
      .catch(() => {});
    // Load API keys (masked)
    void getApiKeys()
      .then((data) => setApiKeys(data.keys))
      .catch(() => {});
    // Check microphone permission if supported
    if (navigator?.permissions?.query) {
      navigator.permissions
        .query({ name: "microphone" as PermissionName })
        .then((s) => setMicStatus(s.state as any))
        .catch(() => setMicStatus("unknown"));
    }
  }, [fetchSettings, fetchWakeStatus]);

  useEffect(() => {
    if (settings) {
      setDirInput(settings.allowed_directories.join("\n"));
      setLanguage(settings.preferred_language);
      setTtsEnabled(settings.tts_enabled);
      setTtsVoice(settings.tts_voice);
      setTtsProvider(settings.tts_provider ?? "");
      setVoiceEnabled(settings.voice_enabled);
      setSelectedLanguage(settings.speech_recognition_language ?? "en");
      setSelectedVoice(settings.tts_voice ?? "default");
      setUiLanguage(settings.ui_language ?? "en");
      setAssistantLanguage(settings.assistant_language ?? "en");
      // Wake settings come from wakeStore
      setLocalWakeEnabled(wakeWordEnabled);
      setLocalWakeMode(wakeMode);
      setLocalPrimaryPhrase(primaryWakePhrase);
      setLocalSecondaryPhrase(secondaryWakePhrase);
      setLocalSessionTimeout(sessionTimeoutSeconds);
      setLocalReverify(requireReverification);
      // STT settings
      setSttEnabled(settings.stt_enabled ?? true);
      setMaxUploadSeconds(settings.max_audio_upload_seconds ?? 120);
      setMaxUploadMb(settings.max_audio_upload_mb ?? 25);
    }
  }, [settings, wakeWordEnabled, wakeMode, primaryWakePhrase, secondaryWakePhrase, sessionTimeoutSeconds, requireReverification]);

  const handleSaveApiKeys = async () => {
    const updates: Record<string, string> = {};
    for (const [envVar, val] of Object.entries(apiKeyDrafts)) {
      if (val.trim() !== "") updates[envVar] = val.trim();
    }
    if (Object.keys(updates).length === 0) return;
    setApiKeysSaving(true);
    try {
      const data = await saveApiKeys(updates);
      setApiKeys(data.keys);
      setApiKeyDrafts({});
      setApiKeysSaved(true);
      setTimeout(() => setApiKeysSaved(false), 3000);
    } catch {
      /* ignore */
    } finally {
      setApiKeysSaving(false);
    }
  };

  const handleSave = async () => {
    const dirs = dirInput
      .split("\n")
      .map((d) => d.trim())
      .filter(Boolean);
    await saveSettings({
      allowed_directories: dirs,
      preferred_language: language,
      tts_enabled: ttsEnabled,
      tts_voice: ttsVoice,
      tts_provider: ttsProvider,
      voice_enabled: voiceEnabled,
      speech_recognition_language: selectedLanguage,
      speech_output_language: selectedLanguage,
      ui_language: uiLanguage,
      assistant_language: assistantLanguage,
      stt_enabled: sttEnabled,
      max_audio_upload_seconds: maxUploadSeconds,
      max_audio_upload_mb: maxUploadMb,
    });
    await saveWakeSettings({
      wake_word_enabled: localWakeEnabled,
      wake_mode: localWakeMode,
      primary_wake_phrase: localPrimaryPhrase,
      secondary_wake_phrase: localSecondaryPhrase,
      voice_session_timeout_seconds: localSessionTimeout,
      require_reverification_after_timeout: localReverify,
    });
  };

  if (isLoading) return <p className="page__loading">{t("common", "loading")}</p>;

  return (
    <div className="page settings-page">
      <div className="page__header">
        <h1>{t("settings", "title")}</h1>
      </div>

      {/* ── Allowed Directories ───────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>{t("settings", "allowed_dirs_title")}</h2>
        <p className="settings-section__hint">
          {t("settings", "allowed_dirs_hint")}
        </p>
        <textarea
          className="settings-input__textarea"
          rows={6}
          value={dirInput}
          onChange={(e) => setDirInput(e.target.value)}
          placeholder={t("settings", "allowed_dirs_placeholder")}
        />
      </section>

      {/* ── Voice ─────────────────────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>
          {t("settings", "voice_title")}{" "}
          {!voiceEnabled && (
            <span className="badge badge--warning">{t("common", "disabled")}</span>
          )}
        </h2>

        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={voiceEnabled}
            onChange={(e) => setVoiceEnabled(e.target.checked)}
          />
          {t("settings", "voice_enable")}
        </label>

        <p className="settings-section__hint">
          {t("settings", "voice_hint")}
        </p>

        <label className="settings-label" htmlFor="voice-language">
          {t("settings", "voice_language_label")}
        </label>
        <select
          id="voice-language"
          className="settings-input settings-select"
          value={selectedLanguage}
          disabled={!voiceEnabled}
          onChange={(e) => setSelectedLanguage(e.target.value)}
        >
          {languageOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <label className="settings-label" htmlFor="voice-voice">
          {t("settings", "voice_voice_label")}
        </label>
        <div className="settings-row">
          <select
            id="voice-voice"
            className="settings-input settings-select"
            value={VOICE_PRESETS.some((p) => p.value === selectedVoice) ? selectedVoice : "custom"}
            disabled={!voiceEnabled}
            onChange={(e) => {
              if (e.target.value !== "custom") setSelectedVoice(e.target.value);
            }}
          >
            {VOICE_PRESETS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
            <option value="custom">custom…</option>
          </select>
          <input
            type="text"
            className="settings-input"
            value={selectedVoice}
            disabled={!voiceEnabled}
            onChange={(e) => setSelectedVoice(e.target.value)}
            placeholder="Voice ID"
            aria-label="Custom voice ID"
          />
        </div>

        <p className="settings-section__hint">
          {t("settings", "voice_no_provider_hint")}
        </p>
      </section>

      {/* ── STT (Speech-to-Text) status ─────────────────────────────────── */}
      <section className="settings-section">
        <h2>{t("settings", "stt_title")}</h2>

        {/* Mic permission status */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
          <span style={{ fontSize: "12px", color: "#9ca3af" }}>{t("settings", "mic_label")}</span>
          {micStatus === "granted" && (
            <span className="badge badge--success">{t("settings", "mic_granted")}</span>
          )}
          {micStatus === "denied" && (
            <span className="badge badge--error">{t("settings", "mic_denied")}</span>
          )}
          {(micStatus === "prompt" || micStatus === "unknown") && (
            <span className="badge badge--warning">{t("settings", "mic_not_requested")}</span>
          )}
          {micStatus === "denied" && (
            <p className="settings-section__hint" style={{ marginTop: 0 }}>
              {t("settings", "mic_denied_hint")}
            </p>
          )}
        </div>

        {/* STT provider status */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
          <span style={{ fontSize: "12px", color: "#9ca3af" }}>{t("settings", "stt_provider_label")}</span>
          {voiceProviders.length === 0 ? (
            <span className="badge badge--warning">{t("common", "loading")}</span>
          ) : (
            voiceProviders.map((p) => (
              <span
                key={p.name}
                className={`badge ${p.active && p.configured ? "badge--success" : "badge--warning"}`}
              >
                {p.name}
                {p.active ? ` (${t("common", "active")})` : ""}
                {p.configured ? ` ✓ ${t("common", "configured")}` : ` — ${t("common", "not_configured")}`}
              </span>
            ))
          )}
        </div>

        {/* Master STT switch */}
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={sttEnabled}
            onChange={(e) => setSttEnabled(e.target.checked)}
          />
          {t("settings", "stt_enable")}
        </label>

        <p className="settings-section__hint">
          {t("settings", "stt_disabled_hint")}
        </p>

        <label className="settings-label" htmlFor="max-upload-seconds">
          {t("settings", "max_recording_label")}
        </label>
        <input
          id="max-upload-seconds"
          type="number"
          className="settings-input"
          value={maxUploadSeconds}
          min={5}
          max={600}
          disabled={!sttEnabled}
          onChange={(e) => setMaxUploadSeconds(Number(e.target.value))}
        />

        <label className="settings-label" htmlFor="max-upload-mb">
          {t("settings", "max_upload_label")}
        </label>
        <input
          id="max-upload-mb"
          type="number"
          className="settings-input"
          value={maxUploadMb}
          min={1}
          max={100}
          disabled={!sttEnabled}
          onChange={(e) => setMaxUploadMb(Number(e.target.value))}
        />

        <p className="settings-section__hint">
          {t("settings", "stt_provider_hint")}
        </p>
      </section>

      {/* ── UI Language ───────────────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>{t("settings", "ui_language_title")}</h2>
        <p className="settings-section__hint">
          {t("settings", "ui_language_hint")}
        </p>
        <select
          className="settings-input settings-select"
          value={uiLanguage}
          onChange={(e) => {
            setUiLanguage(e.target.value);
            // Live-update the UI immediately so the page re-renders in the new language
            setI18nLanguage(e.target.value);
          }}
        >
          {SUPPORTED_UI_LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.native} — {l.label}
            </option>
          ))}
        </select>
      </section>

      {/* ── Assistant Language ────────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>{t("settings", "assistant_language_title")}</h2>
        <p className="settings-section__hint">
          {t("settings", "assistant_language_hint")}
        </p>
        <select
          className="settings-input settings-select"
          value={assistantLanguage}
          onChange={(e) => setAssistantLanguage(e.target.value)}
        >
          {languageOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </section>

      {/* ── Language (preferred for AI) ─────────────────────────────────── */}
      <section className="settings-section">
        <h2>{t("settings", "language_title")}</h2>
        <p className="settings-section__hint">
          {t("settings", "language_hint")}
        </p>
        <input
          type="text"
          className="settings-input"
          value={language}
          maxLength={10}
          onChange={(e) => setLanguage(e.target.value)}
          placeholder="en"
        />
      </section>

      {/* ── Text-to-Speech (TTS) ────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>
          {t("settings", "tts_title")}{" "}
          {!ttsEnabled && <span className="badge badge--warning">{t("common", "disabled")}</span>}
        </h2>

        {/* TTS provider status */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
          <span style={{ fontSize: "12px", color: "#9ca3af" }}>{t("settings", "tts_provider_label")}</span>
          {voiceProviders.length === 0 ? (
            <span className="badge badge--warning">{t("common", "loading")}</span>
          ) : (
            voiceProviders.map((p) => (
              <span
                key={p.name}
                className={`badge ${p.active && p.configured ? "badge--success" : "badge--warning"}`}
              >
                {p.name}
                {p.active ? ` (${t("common", "active")})` : ""}
                {p.configured ? ` ✓ ${t("common", "configured")}` : ` — ${t("common", "not_configured")}`}
              </span>
            ))
          )}
        </div>

        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={ttsEnabled}
            onChange={(e) => setTtsEnabled(e.target.checked)}
          />
          {t("settings", "tts_enable")}
        </label>

        <p className="settings-section__hint">
          {t("settings", "tts_hint")}
        </p>

        <label className="settings-label" htmlFor="tts-voice">
          {t("settings", "tts_voice_label")}
        </label>
        <div className="settings-row">
          <select
            id="tts-voice"
            className="settings-input settings-select"
            value={VOICE_PRESETS.some((p) => p.value === ttsVoice) ? ttsVoice : "custom"}
            disabled={!ttsEnabled}
            onChange={(e) => {
              if (e.target.value !== "custom") setTtsVoice(e.target.value);
            }}
          >
            {VOICE_PRESETS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
            <option value="custom">custom…</option>
          </select>
          <input
            type="text"
            className="settings-input"
            value={ttsVoice}
            disabled={!ttsEnabled}
            onChange={(e) => setTtsVoice(e.target.value)}
            placeholder="Voice ID (e.g. alloy, nova)"
            aria-label="Custom TTS voice ID"
          />
        </div>

        <label className="settings-label" htmlFor="tts-provider">
          {t("settings", "tts_provider_override_label")}
        </label>
        <input
          id="tts-provider"
          type="text"
          className="settings-input"
          value={ttsProvider}
          disabled={!ttsEnabled}
          onChange={(e) => setTtsProvider(e.target.value)}
          placeholder={t("settings", "tts_provider_override_placeholder")}
        />
        <p className="settings-section__hint">
          {t("settings", "tts_provider_override_hint")}
        </p>
      </section>

      {/* ── Wake Word ─────────────────────────────────────────────────────── */}
      <section className="settings-section">
        <h2>
          {t("settings", "wake_title")}{" "}
          <span className="badge badge--warning">{t("settings", "wake_placeholder_badge")}</span>
        </h2>
        <p className="settings-section__hint">
          {t("settings", "wake_hint")}
        </p>

        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={localWakeEnabled}
            onChange={(e) => setLocalWakeEnabled(e.target.checked)}
          />
          {t("settings", "wake_enable")}
        </label>

        <label className="settings-label" htmlFor="wake-mode">{t("settings", "wake_mode_label")}</label>
        <select
          id="wake-mode"
          className="settings-input settings-select"
          value={localWakeMode}
          disabled={!localWakeEnabled}
          onChange={(e) => setLocalWakeMode(e.target.value as WakeMode)}
        >
          <option value="manual">{t("settings", "wake_mode_manual")}</option>
          <option value="push_to_talk">{t("settings", "wake_mode_ptt")}</option>
          <option value="wake_phrase_placeholder">{t("settings", "wake_mode_phrase")}</option>
          <option value="keyword_live">{t("settings", "wake_mode_keyword_live")}</option>
          <option value="provider_ready" disabled>{t("settings", "wake_mode_provider")}</option>
        </select>

        <label className="settings-label" htmlFor="primary-phrase">
          {t("settings", "wake_primary_phrase_label")}
        </label>
        <input
          id="primary-phrase"
          type="text"
          className="settings-input"
          value={localPrimaryPhrase}
          disabled={!localWakeEnabled}
          onChange={(e) => setLocalPrimaryPhrase(e.target.value)}
          placeholder="Lani"
        />

        <label className="settings-label" htmlFor="secondary-phrase">
          {t("settings", "wake_secondary_phrase_label")}
        </label>
        <input
          id="secondary-phrase"
          type="text"
          className="settings-input"
          value={localSecondaryPhrase}
          disabled={!localWakeEnabled}
          onChange={(e) => setLocalSecondaryPhrase(e.target.value)}
          placeholder="Hey Lani"
        />

        <label className="settings-label" htmlFor="session-timeout">
          {t("settings", "wake_session_timeout_label")} (0 = niekada nepasibaiga)
        </label>
        <input
          id="session-timeout"
          type="number"
          className="settings-input"
          value={localSessionTimeout}
          min={0}
          max={86400}
          disabled={!localWakeEnabled}
          onChange={(e) => setLocalSessionTimeout(Number(e.target.value))}
        />

        <label className="settings-toggle" style={{ marginTop: "8px" }}>
          <input
            type="checkbox"
            checked={localReverify}
            disabled={!localWakeEnabled}
            onChange={(e) => setLocalReverify(e.target.checked)}
          />
          {t("settings", "wake_reverify_label")}
        </label>
      </section>

      <button
        className="btn btn--primary"
        onClick={() => void handleSave()}
        disabled={isSaving}
      >
        {isSaving ? t("common", "saving") : t("common", "save")}
      </button>

      {/* ── Balso profilis (Speaker Verification) ──────────────────────── */}
      <section className="settings-section" style={{ marginTop: "24px" }}>
        <VoiceEnrollmentPanel />
      </section>

      {/* ── API Keys ─────────────────────────────────────────────────────── */}
      <section className="settings-section" style={{ marginTop: "24px" }}>
        <h2>🔑 API Keys</h2>
        <p className="settings-section__hint">
          Įveskite savo API raktus. Dabartinės reikšmės rodomos užmaskuotos.
          Palikite lauką tuščią, jei nenorite keisti.
        </p>

        {apiKeys.length === 0 && (
          <p className="settings-section__hint" style={{ color: "#9ca3af" }}>
            Kraunama…
          </p>
        )}

        {apiKeys.map((entry) => (
          <div key={entry.env_var} style={{ marginBottom: "16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
              <label className="settings-label" style={{ margin: 0 }}>
                {entry.label}
              </label>
              {entry.is_set ? (
                <span className="badge badge--success">✓ sukonfigūruota</span>
              ) : (
                <span className="badge badge--warning">⚠ nenurodytas</span>
              )}
            </div>
            <p style={{ fontSize: "11px", color: "#6b7280", margin: "0 0 6px 0" }}>
              {entry.hint}
              {entry.masked_value && (
                <span style={{ marginLeft: "8px", fontFamily: "monospace", color: "#9ca3af" }}>
                  ({entry.masked_value})
                </span>
              )}
            </p>
            <div className="settings-row">
              <input
                type={apiKeyVisible[entry.env_var] ? "text" : "password"}
                className="settings-input"
                style={{ flex: 1, fontFamily: "monospace" }}
                value={apiKeyDrafts[entry.env_var] ?? ""}
                onChange={(e) =>
                  setApiKeyDrafts((prev) => ({
                    ...prev,
                    [entry.env_var]: e.target.value,
                  }))
                }
                placeholder={entry.is_set ? "Palikite tuščią, jei nekeičiate" : "Įveskite raktą…"}
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                className="btn btn--secondary"
                style={{ padding: "0 10px", fontSize: "14px" }}
                onClick={() =>
                  setApiKeyVisible((prev) => ({
                    ...prev,
                    [entry.env_var]: !prev[entry.env_var],
                  }))
                }
                title={apiKeyVisible[entry.env_var] ? "Slėpti" : "Rodyti"}
              >
                {apiKeyVisible[entry.env_var] ? "🙈" : "👁"}
              </button>
            </div>
          </div>
        ))}

        {apiKeys.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "8px" }}>
            <button
              className="btn btn--primary"
              onClick={() => void handleSaveApiKeys()}
              disabled={apiKeysSaving || Object.values(apiKeyDrafts).every((v) => !v.trim())}
            >
              {apiKeysSaving ? "Saugoma…" : "Išsaugoti API raktus"}
            </button>
            {apiKeysSaved && (
              <span style={{ color: "#22c55e", fontSize: "13px" }}>✓ Išsaugota!</span>
            )}
          </div>
        )}
      </section>
    </div>
  );
};
