/**
 * DiagnosticsPage – System Status & Release Readiness
 *
 * Shows a grid of component health tiles pulled from:
 *   1. GET /api/v1/system/status  (backend checks)
 *   2. Browser APIs                (microphone permission)
 *   3. useBackendHealth hook       (live backend connectivity)
 *
 * The page is intentionally read-only and makes no state changes.
 */

import React, { useEffect, useState, useCallback } from "react";
import { getSystemStatus } from "../lib/api";
import type { SystemStatusResponse, ComponentStatus } from "../lib/types";
import { useBackendHealth } from "../hooks/useBackendHealth";
import { useI18n } from "../i18n/useI18n";

// ─── Status tile ─────────────────────────────────────────────────────────────

interface TileProps {
  icon: string;
  label: string;
  status: ComponentStatus | null;
  /** Override the label shown in the badge (instead of status.label) */
  badgeOverride?: string;
  /** Whether to mark as ok/warning without a ComponentStatus */
  forcedOk?: boolean;
  forcedDetail?: string;
}

const Tile: React.FC<TileProps> = ({ icon, label, status, forcedOk, forcedDetail }) => {
  const isOk = status ? status.ok : (forcedOk ?? false);
  const badgeLabel = status?.label ?? (isOk ? "OK" : "—");
  const detail = status?.detail ?? forcedDetail ?? null;

  return (
    <div
      className={`diag-tile diag-tile--${isOk ? "ok" : "warn"}`}
      title={detail ?? undefined}
    >
      <div className="diag-tile__header">
        <span className="diag-tile__icon">{icon}</span>
        <span className="diag-tile__label">{label}</span>
      </div>
      <div className={`diag-tile__badge badge ${isOk ? "badge--success" : "badge--warning"}`}>
        {badgeLabel}
      </div>
      {detail && <p className="diag-tile__detail">{detail}</p>}
    </div>
  );
};

// ─── Page ────────────────────────────────────────────────────────────────────

export const DiagnosticsPage: React.FC = () => {
  const { t } = useI18n();
  const { isOnline } = useBackendHealth(15_000);

  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [micStatus, setMicStatus] = useState<"granted" | "denied" | "prompt" | "unknown">("unknown");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSystemStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  // Check microphone permission from the browser
  useEffect(() => {
    if (navigator?.permissions?.query) {
      navigator.permissions
        .query({ name: "microphone" as PermissionName })
        .then((s) => setMicStatus(s.state as "granted" | "denied" | "prompt"))
        .catch(() => setMicStatus("unknown"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // ── Backend connection tile (frontend-only) ─────────────────────────────
  const backendTile: ComponentStatus | null = isOnline === null
    ? null
    : {
        ok: isOnline,
        label: isOnline
          ? t("diagnostics", "backend_online")
          : t("diagnostics", "backend_offline"),
        detail: isOnline
          ? null
          : "Run: cd services/orchestrator && ./../../scripts/start-backend.sh",
      };

  // ── Microphone tile (browser permission) ───────────────────────────────
  const micTile: ComponentStatus = {
    ok: micStatus === "granted",
    label:
      micStatus === "granted"
        ? t("diagnostics", "mic_granted")
        : micStatus === "denied"
        ? t("diagnostics", "mic_denied")
        : t("diagnostics", "mic_not_requested"),
    detail:
      micStatus === "denied"
        ? "Allow microphone access in System Settings → Privacy & Security → Microphone."
        : null,
  };

  // ── Overall readiness ──────────────────────────────────────────────────
  const allReady = isOnline === true && (status?.ready ?? false);

  return (
    <div className="page diagnostics-page">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="page__header">
        <div>
          <h1>{t("diagnostics", "title")}</h1>
          <p className="page__subtitle">{t("diagnostics", "subtitle")}</p>
        </div>
        <button
          className="btn btn--secondary"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? t("common", "loading") : t("diagnostics", "refresh")}
        </button>
      </div>

      {/* ── Overall banner ──────────────────────────────────────────────── */}
      <div className={`diag-banner ${allReady ? "diag-banner--ok" : "diag-banner--warn"}`}>
        <span className="diag-banner__icon">{allReady ? "✅" : "⚠️"}</span>
        <span>
          {allReady
            ? t("diagnostics", "overall_ready")
            : t("diagnostics", "overall_not_ready")}
        </span>
      </div>

      {/* ── Error fetching status ────────────────────────────────────────── */}
      {error && (
        <div className="diag-error">
          <strong>Could not reach backend:</strong> {error}
          <br />
          <span style={{ fontSize: "12px", color: "#9ca3af" }}>
            Make sure the orchestrator service is running on port 8000.
          </span>
        </div>
      )}

      {/* ── App metadata row ─────────────────────────────────────────────── */}
      {status && (
        <div className="diag-meta">
          <span>
            <strong>{t("diagnostics", "app_version")}</strong> {status.app_version}
          </span>
          <span>
            <strong>{t("diagnostics", "python_version")}</strong> {status.python_version}
          </span>
          <span>
            <strong>{t("diagnostics", "app_env")}</strong>{" "}
            <span
              className={`badge ${
                status.app_env === "production" ? "badge--error" : "badge--info"
              }`}
            >
              {status.app_env}
            </span>
          </span>
        </div>
      )}

      {/* ── Tile grid ────────────────────────────────────────────────────── */}
      <div className="diag-grid">
        {/* Frontend-driven */}
        <Tile
          icon="🔌"
          label={t("diagnostics", "backend_connection")}
          status={backendTile}
          forcedOk={isOnline === null ? undefined : isOnline}
          forcedDetail={
            isOnline === null ? t("diagnostics", "backend_connecting") : undefined
          }
        />
        <Tile
          icon="🎙"
          label={t("diagnostics", "microphone")}
          status={micTile}
        />

        {/* Backend-driven — shown as loading until data arrives */}
        <Tile
          icon="🖥️"
          label={t("diagnostics", "platform")}
          status={status?.platform ?? null}
        />
        <Tile
          icon="🗄️"
          label={t("diagnostics", "database")}
          status={status?.database ?? null}
        />
        <Tile
          icon="🔐"
          label={t("diagnostics", "encryption")}
          status={status?.encryption ?? null}
        />
        <Tile
          icon="🤖"
          label={t("diagnostics", "openai_key")}
          status={status?.openai_key ?? null}
        />
        <Tile
          icon="🔑"
          label={t("diagnostics", "secret_key")}
          status={status?.secret_key ?? null}
        />
        <Tile
          icon="🎤"
          label={t("diagnostics", "voice_provider")}
          status={status?.voice_provider ?? null}
        />
        <Tile
          icon="📝"
          label={t("diagnostics", "stt")}
          status={status?.stt ?? null}
        />
        <Tile
          icon="🔊"
          label={t("diagnostics", "tts")}
          status={status?.tts ?? null}
        />
        <Tile
          icon="👤"
          label={t("diagnostics", "voice_profile")}
          status={status?.voice_profile ?? null}
        />
        <Tile
          icon="🔌"
          label={t("diagnostics", "connected_accounts")}
          status={status?.connected_accounts ?? null}
        />
      </div>

      {/* ── Setup hints ──────────────────────────────────────────────────── */}
      {status && (
        <div className="diag-hints">
          <h2 style={{ fontSize: "13px", color: "#9ca3af", marginBottom: "8px" }}>
            Setup hints
          </h2>
          <ul className="diag-hints__list">
            {status.app_env !== "production" && (
              <li className="diag-hints__item diag-hints__item--info">
                💡 {t("diagnostics", "hint_dev_mode")}
              </li>
            )}
            {!status.openai_key.ok && (
              <li className="diag-hints__item diag-hints__item--warn">
                ⚙️ {t("diagnostics", "hint_no_openai")}
              </li>
            )}
            {!status.voice_provider.ok && (
              <li className="diag-hints__item diag-hints__item--warn">
                🎙 {t("diagnostics", "hint_no_voice")}
              </li>
            )}
            {!status.encryption.ok && (
              <li className="diag-hints__item diag-hints__item--warn">
                🔐 {t("diagnostics", "hint_no_encryption")}
              </li>
            )}
            {!status.voice_profile.ok && (
              <li className="diag-hints__item diag-hints__item--info">
                👤 {t("diagnostics", "hint_no_profile")}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
};
