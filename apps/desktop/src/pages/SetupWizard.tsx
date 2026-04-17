import React, { useEffect, useState } from "react";
import WelcomeStep from "../components/setup/WelcomeStep";
import LanguageStep from "../components/setup/LanguageStep";
import FinishStep from "../components/setup/FinishStep";
import { useSettingsStore } from "../stores/settingsStore";

// 3 simple steps: welcome → language → finish
const STEPS = ["welcome", "language", "finish"] as const;
type Step = (typeof STEPS)[number];

export const SetupWizard: React.FC = () => {
  const { settings, fetchSettings, saveSettings } = useSettingsStore();
  const [current, setCurrent] = useState<number>(0);

  useEffect(() => {
    void fetchSettings();
  }, [fetchSettings]);

  const next = () => setCurrent((c) => Math.min(c + 1, STEPS.length - 1));
  const back = () => setCurrent((c) => Math.max(c - 1, 0));

  const savePartial = async (patch: Record<string, unknown>) => {
    await saveSettings(patch as any);
  };

  const step: Step = STEPS[current];

  // Progress: 3 dots (one per step)
  const showProgress = current > 0;

  return (
    <div className="setup-wizard">
      <div className="setup-wizard__card">
        {/* Header */}
        <div className="setup-wizard__header">
          <div className="setup-wizard__logo">✦</div>
          <span className="setup-wizard__app-name">Lani</span>
        </div>

        {/* Progress dots (hidden on welcome) */}
        {showProgress && (
          <div className="setup-wizard__progress">
            {STEPS.slice(1).map((_, i) => (
              <div
                key={i}
                className={[
                  "setup-wizard__dot",
                  i < current - 1 ? "setup-wizard__dot--done" : "",
                  i === current - 1 ? "setup-wizard__dot--active" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              />
            ))}
          </div>
        )}

        {/* Step body */}
        <div className="setup-wizard__body">
          {step === "welcome" && <WelcomeStep onNext={next} />}

          {step === "language" && (
            <LanguageStep
              settings={settings}
              onNext={next}
              onBack={back}
              onSave={savePartial}
            />
          )}

          {step === "finish" && (
            <FinishStep
              settings={settings}
              onBack={back}
              onComplete={async () => {
                await savePartial({ first_run_complete: true });
                window.location.reload();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default SetupWizard;
