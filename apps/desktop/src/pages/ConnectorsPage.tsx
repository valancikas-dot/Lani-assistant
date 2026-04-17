/**
 * ConnectorsPage – manage OAuth-connected accounts (Google Drive, Gmail, Google Calendar).
 *
 * Flow
 * ────
 * 1. Page loads → fetches current accounts + capability manifests
 * 2. User clicks "Connect" for a provider → backend returns an OAuth auth_url
 * 3. We open the URL in the system browser (Tauri shell.open or window.open in dev)
 * 4. User approves → Google redirects to localhost:8000/api/v1/connectors/oauth/callback
 *    (which is handled by the backend, *not* by the frontend)
 *    — OR in a Tauri deep-link scenario the frontend intercepts the redirect and
 *    POSTs the code+state to /connectors/oauth/callback.
 *
 * For the desktop Tauri app the simplest path is the backend-handles-callback
 * approach: after the user approves, they are redirected to the backend which
 * stores the tokens, and the frontend just polls / refreshes to see the new account.
 * A manual "I've finished connecting" button triggers a refresh.
 */

import React, { useEffect, useState } from "react";
import { useConnectorsStore } from "../stores/connectorsStore";
import { useI18n } from "../i18n/useI18n";
import type { ConnectorAccount, ConnectorManifest, ConnectorProvider } from "../lib/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function providerIcon(provider: ConnectorProvider): string {
  switch (provider) {
    case "google_drive":     return "📁";
    case "gmail":            return "✉️";
    case "google_calendar":  return "📅";
    default:                 return "🔌";
  }
}

// ── Connected account card ────────────────────────────────────────────────────

interface AccountCardProps {
  account: ConnectorAccount;
  manifest: ConnectorManifest | undefined;
  onDisconnect: (id: number) => void;
}

const AccountCard: React.FC<AccountCardProps> = ({ account, manifest, onDisconnect }) => {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);

  return (
    <div className={`connector-card ${account.is_active ? "connector-card--active" : "connector-card--inactive"}`}>
      <div className="connector-card__header">
        <span className="connector-card__icon">{providerIcon(account.provider)}</span>
        <div className="connector-card__title">
          <strong>{manifest?.display_name ?? account.provider}</strong>
          <span className="connector-card__email">{account.display_name || account.account_email}</span>
        </div>
        <span className={`connector-card__badge ${account.is_active ? "badge--green" : "badge--red"}`}>
          {account.is_active ? t("common", "active") : "inactive"}
        </span>
      </div>

      <dl className="connector-card__meta">
        <dt>{t("connectors", "connected_as")}</dt>
        <dd>{account.account_email}</dd>

        <dt>{t("connectors", "last_used")}</dt>
        <dd>{account.last_used_at ? formatDate(account.last_used_at) : t("connectors", "last_used_never")}</dd>

        {account.scopes_granted.length > 0 && (
          <>
            <dt>{t("connectors", "scopes_title")}</dt>
            <dd>
              <ul className="connector-card__scopes">
                {account.scopes_granted.map((s) => (
                  <li key={s} className="connector-card__scope">{s.split("/").pop() ?? s}</li>
                ))}
              </ul>
            </dd>
          </>
        )}

        {account.last_error && (
          <>
            <dt className="connector-card__error-label">{t("connectors", "error_state")}</dt>
            <dd className="connector-card__error">{account.last_error}</dd>
          </>
        )}
      </dl>

      {manifest && manifest.capabilities.length > 0 && (
        <div className="connector-card__capabilities">
          <h4>{t("connectors", "capabilities_title")}</h4>
          <ul>
            {manifest.capabilities.map((cap) => (
              <li key={cap.name} className="connector-cap">
                <span className="connector-cap__name">{cap.name}</span>
                <span className="connector-cap__desc">{cap.description}</span>
                <span className={`connector-cap__flag ${cap.requires_approval ? "flag--approval" : "flag--safe"}`}>
                  {cap.requires_approval
                    ? t("connectors", "requires_approval")
                    : t("connectors", "read_only")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="connector-card__actions">
        {confirming ? (
          <>
            <span className="connector-card__confirm-text">{t("connectors", "disconnect_confirm")}</span>
            <button className="btn btn--danger btn--sm" onClick={() => onDisconnect(account.id)}>
              {t("connectors", "disconnect_btn")}
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setConfirming(false)}>
              {t("common", "close")}
            </button>
          </>
        ) : (
          <button className="btn btn--outline btn--sm" onClick={() => setConfirming(true)}>
            {t("connectors", "disconnect_btn")}
          </button>
        )}
      </div>
    </div>
  );
};

// ── Provider connect card ─────────────────────────────────────────────────────

interface ProviderCardProps {
  manifest: ConnectorManifest;
  alreadyConnected: boolean;
  onConnect: (provider: ConnectorProvider) => void;
  connecting: boolean;
}

const ProviderCard: React.FC<ProviderCardProps> = ({
  manifest,
  alreadyConnected,
  onConnect,
  connecting,
}) => {
  const { t } = useI18n();

  return (
    <div className={`provider-card ${alreadyConnected ? "provider-card--connected" : ""}`}>
      <span className="provider-card__icon">{manifest.icon}</span>
      <div className="provider-card__info">
        <strong>{manifest.display_name}</strong>
        <span className="provider-card__count">
          {manifest.capabilities.length} capability
          {manifest.capabilities.length !== 1 ? "ies" : "y"}
        </span>
      </div>
      <button
        className={`btn btn--sm ${alreadyConnected ? "btn--outline" : "btn--primary"}`}
        onClick={() => onConnect(manifest.provider)}
        disabled={connecting}
      >
        {connecting
          ? t("connectors", "connecting")
          : alreadyConnected
          ? t("connectors", "reconnect_btn")
          : t("connectors", "connect_btn")}
      </button>
    </div>
  );
};

// ── Page ──────────────────────────────────────────────────────────────────────

export const ConnectorsPage: React.FC = () => {
  const {
    accounts,
    manifests,
    isLoading,
    isConnecting,
    error,
    fetchAccounts,
    fetchManifests,
    startOAuth,
    disconnect,
    clearError,
  } = useConnectorsStore();
  const { t } = useI18n();

  const [oauthPending, setOauthPending] = useState<ConnectorProvider | null>(null);

  useEffect(() => {
    void fetchAccounts();
    void fetchManifests();
  }, [fetchAccounts, fetchManifests]);

  const handleConnect = async (provider: ConnectorProvider) => {
    setOauthPending(provider);
    const authUrl = await startOAuth(provider);
    if (authUrl) {
      // Open in system browser.  In Tauri use the shell open API.
      // In browser dev mode window.open works fine.
      try {
        // @ts-ignore – Tauri shell API (optional)
        if (typeof window.__TAURI__ !== "undefined") {
          const { open } = await import("@tauri-apps/api/shell");
          await open(authUrl);
        } else {
          window.open(authUrl, "_blank", "noopener,noreferrer");
        }
      } catch {
        window.open(authUrl, "_blank", "noopener,noreferrer");
      }
    }
  };

  const handleRefresh = async () => {
    setOauthPending(null);
    await fetchAccounts();
  };

  const connectedProviders = new Set(accounts.filter((a) => a.is_active).map((a) => a.provider));

  const manifestByProvider = Object.fromEntries(manifests.map((m) => [m.provider, m]));

  return (
    <div className="page connectors-page">
      <div className="page__header">
        <h1>{t("connectors", "title")}</h1>
        <p className="page__subtitle">{t("connectors", "subtitle")}</p>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          <span>{error}</span>
          <button className="alert__close" onClick={clearError} aria-label="dismiss">×</button>
        </div>
      )}

      {oauthPending && (
        <div className="alert alert--info">
          <span>
            {t("connectors", "oauth_instructions")}
          </span>
          <button className="btn btn--sm btn--outline" onClick={handleRefresh}>
            Done – refresh accounts
          </button>
        </div>
      )}

      {/* ── Available providers ── */}
      <section className="connectors-page__section">
        <h2>{t("connectors", "available_providers")}</h2>
        <div className="provider-grid">
          {manifests.map((m) => (
            <ProviderCard
              key={m.provider}
              manifest={m}
              alreadyConnected={connectedProviders.has(m.provider)}
              onConnect={handleConnect}
              connecting={isConnecting && oauthPending === m.provider}
            />
          ))}
        </div>
      </section>

      {/* ── Connected accounts ── */}
      <section className="connectors-page__section">
        <div className="connectors-page__section-header">
          <h2>{t("connectors", "connected_accounts")}</h2>
          <button
            className="btn btn--ghost btn--sm"
            onClick={handleRefresh}
            disabled={isLoading}
          >
            {isLoading ? t("common", "loading") : "↻ Refresh"}
          </button>
        </div>

        {isLoading && accounts.length === 0 ? (
          <p className="page__loading">{t("common", "loading")}</p>
        ) : accounts.length === 0 ? (
          <div className="page__empty">
            <p>{t("connectors", "no_accounts")}</p>
          </div>
        ) : (
          <div className="connectors-page__list">
            {accounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                manifest={manifestByProvider[account.provider]}
                onDisconnect={disconnect}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
