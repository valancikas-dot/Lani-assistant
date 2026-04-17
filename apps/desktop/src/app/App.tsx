/**
 * App – root component with router and sidebar layout.
 */

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";
import { BackendOfflineBanner } from "../components/layout/BackendOfflineBanner";
import { ChatPage } from "../pages/ChatPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { LogsPage } from "../pages/LogsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { MemoryPage } from "../pages/MemoryPage";
import { BuilderPage } from "../pages/BuilderPage";
import { ConnectorsPage } from "../pages/ConnectorsPage";
import { OperatorPage } from "../pages/OperatorPage";
import { SecurityPage } from "../pages/SecurityPage";
import { DiagnosticsPage } from "../pages/DiagnosticsPage";
import { CapabilitiesPage } from "../pages/CapabilitiesPage";
import { PoliciesPage } from "../pages/PoliciesPage";
import { StateViewerPage } from "../pages/StateViewerPage";
import { EvalsPage } from "../pages/EvalsPage";
import { MissionControlPage } from "../pages/MissionControlPage";
import { SkillProposalsPage } from "../pages/SkillProposalsPage";
import { SkillDraftPage } from "../pages/SkillDraftPage";
import { MissionsPage } from "../pages/MissionsPage";
import { InstalledSkillsPage } from "../pages/InstalledSkillsPage";
import { ProfilesPage } from "../pages/ProfilesPage";
import { ModesPage } from "../pages/ModesPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { HomePage } from "../pages/HomePage";
import SetupWizard from "../pages/SetupWizard";
import { TokenPackagesPage } from "../pages/TokenPackagesPage";
import { useSettingsStore } from "../stores/settingsStore";
import { useI18nStore } from "../i18n/index";
import { useAuthStore } from "../stores/authStore";
import { LoginPage } from "../pages/LoginPage";

export const App: React.FC = () => {
  const { settings, fetchSettings, isLoading } = useSettingsStore();
  const setLanguage = useI18nStore((s) => s.setLanguage);
  const { token, user, fetchMe } = useAuthStore();

  // Phase 11: track whether mode-onboarding has been shown this install
  const [modesOnboardingDone, setModesOnboardingDone] = React.useState<boolean>(
    () => localStorage.getItem("lani_modes_onboarding") === "1"
  );

  React.useEffect(() => {
    void fetchSettings();
  }, [fetchSettings]);

  // Refresh user info on every load (balance may have changed)
  React.useEffect(() => {
    if (token) void fetchMe();
  }, [token, fetchMe]);

  // Sync UI language from persisted settings whenever it changes.
  React.useEffect(() => {
    if (settings?.ui_language) {
      setLanguage(settings.ui_language);
    }
  }, [settings?.ui_language, setLanguage]);

  if (settings && settings.first_run_complete === false) {
    return <SetupWizard />;
  }

  // ── Auth gate ──────────────────────────────────────────────────────────────
  if (!token || !user) {
    return <LoginPage />;
  }

  // Phase 11 – Mode onboarding gate: shown once after initial setup is complete
  if (settings && settings.first_run_complete === true && !modesOnboardingDone) {
    return (
      <OnboardingPage
        onComplete={() => {
          localStorage.setItem("lani_modes_onboarding", "1");
          setModesOnboardingDone(true);
        }}
      />
    );
  }

  // Show a minimal splash while settings are loading for the first time
  if (isLoading && !settings) {
    return (
      <div className="app-splash">
        <div className="app-splash__logo">✦</div>
        <div className="app-splash__name">LANI</div>
        <div className="app-splash__hint">INITIALIZING SYSTEMS_</div>
      </div>
    );
  }

  // Backend not reachable yet — keep showing splash and retry
  if (!settings) {
    return (
      <div className="app-splash">
        <div className="app-splash__logo">◈</div>
        <div className="app-splash__name">LANI</div>
        <div className="app-splash__hint">CONNECTING TO CORE_</div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <BackendOfflineBanner />
      <div className="layout">
        <Sidebar />
        <main className="layout__main">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/builder" element={<BuilderPage />} />
            <Route path="/connectors" element={<ConnectorsPage />} />
            <Route path="/operator" element={<OperatorPage />} />
            <Route path="/security" element={<SecurityPage />} />
            <Route path="/diagnostics" element={<DiagnosticsPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/capabilities" element={<CapabilitiesPage />} />
            <Route path="/policies" element={<PoliciesPage />} />
            <Route path="/state" element={<StateViewerPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/mission" element={<MissionControlPage />} />
            <Route path="/skill-proposals" element={<SkillProposalsPage />} />
            <Route path="/skill-drafts" element={<SkillDraftPage />} />
            <Route path="/missions" element={<MissionsPage />} />
            <Route path="/installed-skills" element={<InstalledSkillsPage />} />
            <Route path="/profiles" element={<ProfilesPage />} />
            <Route path="/modes" element={<ModesPage />} />
            <Route path="/tokens" element={<TokenPackagesPage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
};
