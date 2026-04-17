import React from "react";
import { useI18n } from "../../i18n/useI18n";

const WelcomeStep: React.FC<{ onNext: () => void }> = ({ onNext }) => {
  const { t } = useI18n();
  return (
    <div className="setup-welcome">
      <div className="setup-welcome__orb">✦</div>
      <h1 className="setup-welcome__title">{t("setup", "welcome_title")}</h1>
      <p className="setup-welcome__body">{t("setup", "welcome_body")}</p>
      <button className="setup-welcome__btn" onClick={onNext}>
        {t("setup", "get_started")} →
      </button>
    </div>
  );
};

export default WelcomeStep;
