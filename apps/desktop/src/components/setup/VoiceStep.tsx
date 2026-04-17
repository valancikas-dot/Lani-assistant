import React from "react";
import { useI18n } from "../../i18n/useI18n";

const VoiceStep: React.FC<any> = ({ settings, onNext, onBack, onSave }) => {
  const enabled = settings?.voice_enabled ?? false;
  const { t } = useI18n();

  return (
    <div>
      <h2>{t("setup", "voice_step_title")}</h2>
      <p>{t("setup", "voice_step_body")}</p>
      <label className="settings-toggle">
        <input
          type="checkbox"
          defaultChecked={enabled}
          onChange={(e) => onSave({ voice_enabled: e.target.checked })}
        />
        {t("setup", "voice_enable_label")}
      </label>

      <div style={{ marginTop: 12 }}>
        <button className="btn" onClick={onBack}>
          {t("common", "back")}
        </button>
        <button className="btn btn--primary" style={{ marginLeft: 8 }} onClick={onNext}>
          {t("common", "continue")}
        </button>
      </div>
    </div>
  );
};

export default VoiceStep;
