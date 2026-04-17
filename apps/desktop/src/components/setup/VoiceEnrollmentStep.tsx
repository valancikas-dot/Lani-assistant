import React, { useState } from "react";
import * as api from "../../lib/api";
import { useI18n } from "../../i18n/useI18n";

const VoiceEnrollmentStep: React.FC<any> = ({ profileId, startEnrollment, onNext, onBack }) => {
  const [localProfileId, setLocalProfileId] = useState<number | null>(profileId ?? null);
  const [samples, setSamples] = useState<File[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const { t } = useI18n();

  const handleStart = async () => {
    const res = await startEnrollment("Primary");
    if (res && res.profile_id) setLocalProfileId(res.profile_id);
    setMessage(t("setup", "voice_enroll_started"));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) setSamples(Array.from(e.target.files));
  };

  const uploadSamples = async () => {
    if (!localProfileId) return setMessage(t("setup", "voice_enroll_no_profile"));
    try {
      for (const f of samples) {
        await api.enrollSample(f, localProfileId);
      }
      const finish = await api.enrollFinish(localProfileId);
      setMessage(`Enrollment finished: ${finish.enrollment_status}`);
    } catch (err: any) {
      setMessage(String(err));
    }
  };

  return (
    <div>
      <h2>{t("setup", "voice_enroll_title")}</h2>
      <p>{t("setup", "voice_enroll_body")}</p>
      {!localProfileId && (
        <button className="btn btn--primary" onClick={() => void handleStart()}>
          {t("setup", "voice_enroll_start")}
        </button>
      )}
      <div style={{ marginTop: 8 }}>
        <input type="file" accept="audio/*" multiple onChange={handleFileChange} />
      </div>
      <div style={{ marginTop: 8 }}>
        <button className="btn" onClick={onBack}>
          {t("common", "back")}
        </button>
        <button className="btn btn--primary" style={{ marginLeft: 8 }} onClick={() => void uploadSamples()}>
          {t("setup", "voice_enroll_upload")}
        </button>
      </div>
      {message && <p className="setup-message">{message}</p>}
    </div>
  );
};

export default VoiceEnrollmentStep;
