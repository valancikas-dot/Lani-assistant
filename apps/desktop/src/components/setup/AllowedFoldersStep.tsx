import React, { useState, useEffect } from "react";
import { useI18n } from "../../i18n/useI18n";

const AllowedFoldersStep: React.FC<any> = ({ settings, onNext, onBack, onSave }) => {
  const [dirs, setDirs] = useState<string>((settings?.allowed_directories || []).join("\n"));
  const { t } = useI18n();

  useEffect(() => {
    setDirs((settings?.allowed_directories || []).join("\n"));
  }, [settings]);

  const commit = async () => {
    const arr = dirs
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    await onSave({ allowed_directories: arr });
    onNext();
  };

  return (
    <div>
      <h2>{t("setup", "allowed_folders_title")}</h2>
      <p>{t("setup", "allowed_folders_body")}</p>
      <textarea value={dirs} onChange={(e) => setDirs(e.target.value)} rows={6} />
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

export default AllowedFoldersStep;
