/**
 * BackendOfflineBanner
 *
 * Shown as a full-screen overlay when the backend cannot be reached on app
 * startup.  After the first successful health-check it disappears and never
 * re-shows (the sidebar footer already shows the live connection dot).
 *
 * Three states:
 *   connecting  – first poll is in-flight (isOnline === null)
 *   offline     – poll returned false (isOnline === false)
 *   dismissed   – backend came online at least once; banner removed
 */

import React, { useEffect, useState } from "react";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import { useI18n } from "../../i18n/useI18n";

export const BackendOfflineBanner: React.FC = () => {
  const { isOnline } = useBackendHealth(8_000);
  const { t } = useI18n();

  // Once online, permanently dismiss
  const [everOnline, setEverOnline] = useState(false);

  useEffect(() => {
    if (isOnline === true) setEverOnline(true);
  }, [isOnline]);

  // Don't render once the backend has been reached at least once
  if (everOnline) return null;

  // Still waiting for the first poll
  if (isOnline === null) {
    return (
      <div className="startup-banner startup-banner--connecting" aria-live="polite">
        <span className="startup-banner__icon">⚪</span>
        <span className="startup-banner__text">{t("nav", "backend_connecting")}</span>
        <span className="startup-banner__spinner" />
      </div>
    );
  }

  // Definitively offline
  return (
    <div className="startup-banner startup-banner--offline" role="alert">
      <div className="startup-banner__body">
        <span className="startup-banner__icon">🔴</span>
        <div>
          <strong className="startup-banner__title">Lani backend is not running</strong>
          <p className="startup-banner__detail">
            Start the backend with:
          </p>
          <code className="startup-banner__code">
            ./scripts/start-backend.sh
          </code>
          <p className="startup-banner__detail" style={{ marginTop: "6px" }}>
            The app will reconnect automatically once the service is up.
          </p>
        </div>
      </div>
    </div>
  );
};
