import React, { useState } from "react";
import { useI18n } from "../../i18n/useI18n";

const SecurityStep: React.FC<any> = ({ settings, onNext, onBack, onSave }) => {
  const [mode, setMode] = useState(settings?.security_mode ?? "disabled");
  const [pin, setPin] = useState("");
  const [passphraseHint, setPassphraseHint] = useState(settings?.fallback_passphrase_hint ?? "");
  const { t } = useI18n();

  const commit = async () => {
    // For now we only persist flags; PIN hashing/storage is handled in Settings page
    await onSave({ security_mode: mode, fallback_passphrase_enabled: !!passphraseHint });
    onNext();
  };

  return (
    <div>
      <h2>{t("setup", "security_title")}</h2>
      <p>{t("setup", "security_body")}</p>
      <select value={mode} onChange={(e) => setMode(e.target.value)}>
        <option value="disabled">{t("setup", "security_mode_disabled")}</option>
        <option value="soft">{t("setup", "security_mode_soft")}</option>
        <option value="strict">{t("setup", "security_mode_strict")}</option>
        <option value="sensitive">{t("setup", "security_mode_sensitive")}</option>
      </select>

      <div style={{ marginTop: 12 }}>
        <label className="settings-label">{t("setup", "security_passphrase_hint")}</label>
        <input value={passphraseHint} onChange={(e) => setPassphraseHint(e.target.value)} />
      </div>

      <div style={{ marginTop: 12 }}>
        <button className="btn" onClick={onBack}>
          {t("common", "back")}
        </button>
        <button className="btn btn--primary" style={{ marginLeft: 8 }} onClick={commit}>
          {t("common", "continue")}
        </button>
      </div>
    </div>
  );
};

export default SecurityStep;
