import React, { useEffect, useState } from "react";
import * as api from "../../lib/api";
import { useI18nStore } from "../../i18n/index";

const FLAG_MAP: Record<string, string> = {
  en: "🇬🇧", lt: "🇱🇹", de: "🇩🇪", fr: "🇫🇷", es: "🇪🇸",
  it: "🇮🇹", pl: "🇵🇱", ru: "🇷🇺", uk: "🇺🇦", ja: "🇯🇵",
  ko: "🇰🇷", zh: "🇨🇳", pt: "🇵🇹", nl: "🇳🇱", sv: "🇸🇪",
  fi: "🇫🇮", no: "🇳🇴", da: "🇩🇰", cs: "🇨🇿", sk: "🇸🇰",
  ro: "🇷🇴", hu: "🇭🇺", tr: "🇹🇷", ar: "🇸🇦", hi: "🇮🇳",
};

const FALLBACK_LANGUAGES = [
  { code: "en", display_name: "English", native_name: "English" },
  { code: "lt", display_name: "Lithuanian", native_name: "Lietuvių" },
  { code: "de", display_name: "German", native_name: "Deutsch" },
  { code: "fr", display_name: "French", native_name: "Français" },
  { code: "es", display_name: "Spanish", native_name: "Español" },
  { code: "it", display_name: "Italian", native_name: "Italiano" },
  { code: "pl", display_name: "Polish", native_name: "Polski" },
  { code: "ru", display_name: "Russian", native_name: "Русский" },
  { code: "uk", display_name: "Ukrainian", native_name: "Українська" },
  { code: "ja", display_name: "Japanese", native_name: "日本語" },
  { code: "zh", display_name: "Chinese", native_name: "中文" },
  { code: "ko", display_name: "Korean", native_name: "한국어" },
];

interface LangOption { code: string; display_name: string; native_name?: string }

interface Props {
  settings: any;
  onNext: () => void;
  onBack: () => void;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
}

const LanguageStep: React.FC<Props> = ({ settings, onNext, onBack, onSave }) => {
  const [languages, setLanguages] = useState<LangOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const browserLang = navigator.language?.split("-")[0] ?? "en";
  const [uiLang, setUiLang] = useState<string>(settings?.ui_language ?? browserLang);
  const [assistantLang, setAssistantLang] = useState<string>(settings?.assistant_language ?? browserLang);

  const setI18nLanguage = useI18nStore((s) => s.setLanguage);

  useEffect(() => {
    void (async () => {
      try {
        const langs = await api.getSupportedLanguages();
        setLanguages(langs && langs.length > 0 ? langs : FALLBACK_LANGUAGES);
      } catch {
        setLanguages(FALLBACK_LANGUAGES);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (settings?.ui_language) setUiLang(settings.ui_language);
    if (settings?.assistant_language) setAssistantLang(settings.assistant_language);
  }, [settings]);

  const commit = async () => {
    setSaving(true);
    try {
      await onSave({
        ui_language: uiLang,
        assistant_language: assistantLang,
        speech_recognition_language: assistantLang,
        speech_output_language: assistantLang,
      });
      setI18nLanguage(uiLang);
      onNext();
    } finally {
      setSaving(false);
    }
  };

  const LangGrid = ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string;
    onChange: (code: string) => void;
  }) => (
    <div className="lang-section">
      <p className="lang-section__label">{label}</p>
      {loading ? (
        <div className="lang-loading"><div className="lang-spinner" /></div>
      ) : (
        <div className="lang-grid">
          {languages.map((l) => (
            <button
              key={l.code}
              type="button"
              className={"lang-card" + (value === l.code ? " lang-card--selected" : "")}
              onClick={() => onChange(l.code)}
            >
              <span className="lang-card__flag">{FLAG_MAP[l.code] ?? "🌐"}</span>
              <span className="lang-card__name">
                {l.native_name && l.native_name !== l.display_name ? l.native_name : l.display_name}
              </span>
              {value === l.code && <span className="lang-card__check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="setup-language">
      <h2 className="setup-step__title">Choose your languages</h2>
      <p className="setup-step__subtitle">
        Select the interface and assistant language. You can change these later in Settings.
      </p>

      <LangGrid label="Interface language" value={uiLang} onChange={setUiLang} />
      <LangGrid label="Assistant language" value={assistantLang} onChange={setAssistantLang} />

      <div className="setup-nav">
        <button className="setup-btn-back" onClick={onBack}>← Back</button>
        <button
          className="setup-btn-primary"
          onClick={() => void commit()}
          disabled={loading || saving}
        >
          {saving ? "Saving…" : "Continue →"}
        </button>
      </div>
    </div>
  );
};

export default LanguageStep;
