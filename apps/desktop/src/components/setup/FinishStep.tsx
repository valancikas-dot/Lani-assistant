import React, { useState } from "react";

interface Props {
  settings: any;
  onBack: () => void;
  onComplete: () => Promise<void>;
}

const FinishStep: React.FC<Props> = ({ settings, onBack, onComplete }) => {
  const [loading, setLoading] = useState(false);

  const handleFinish = async () => {
    setLoading(true);
    try {
      await onComplete();
    } finally {
      setLoading(false);
    }
  };

  const uiLang = settings?.ui_language ?? "en";
  const assistantLang = settings?.assistant_language ?? "en";

  return (
    <div className="setup-finish">
      <div className="setup-finish__icon">🎉</div>
      <h2 className="setup-finish__title">You're all set!</h2>
      <p className="setup-finish__body">
        Setup is complete. You can change all settings anytime from the Settings page.
      </p>

      <div className="setup-finish__summary">
        <div className="setup-finish__row">
          <span className="setup-finish__row-label">Interface language</span>
          <span className="setup-finish__row-value">{uiLang.toUpperCase()}</span>
        </div>
        <div className="setup-finish__row">
          <span className="setup-finish__row-label">Assistant language</span>
          <span className="setup-finish__row-value">{assistantLang.toUpperCase()}</span>
        </div>
      </div>

      <div className="setup-nav">
        <button className="setup-btn-back" onClick={onBack} disabled={loading}>
          ← Back
        </button>
        <button
          className="setup-btn-primary"
          onClick={() => void handleFinish()}
          disabled={loading}
        >
          {loading ? "Starting…" : "Open Lani →"}
        </button>
      </div>
    </div>
  );
};

export default FinishStep;
