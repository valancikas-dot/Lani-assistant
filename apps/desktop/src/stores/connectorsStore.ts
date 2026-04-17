/**
 * Connectors store – manages OAuth-connected accounts and their capabilities.
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type {
  ConnectorAccount,
  ConnectorManifest,
  ConnectorProvider,
  OAuthCallbackRequest,
} from "../lib/types";

interface ConnectorsState {
  accounts: ConnectorAccount[];
  manifests: ConnectorManifest[];
  isLoading: boolean;
  isConnecting: boolean;
  error: string | null;

  /** Fetch current connected accounts from the backend. */
  fetchAccounts: () => Promise<void>;

  /** Fetch all provider capability manifests. */
  fetchManifests: () => Promise<void>;

  /**
   * Initiate OAuth flow for the given provider.
   * Returns the auth URL so the caller can open it in a browser / webview.
   */
  startOAuth: (provider: ConnectorProvider) => Promise<string | null>;

  /**
   * Exchange the OAuth callback code+state for tokens and persist the account.
   * Call this after the user completes the consent screen and you have extracted
   * `code` and `state` from the redirect URL.
   */
  completeOAuth: (req: OAuthCallbackRequest) => Promise<boolean>;

  /** Disconnect an account and remove it from the list. */
  disconnect: (accountId: number) => Promise<boolean>;

  /** Clear any error banner. */
  clearError: () => void;
}

export const useConnectorsStore = create<ConnectorsState>((set, get) => ({
  accounts: [],
  manifests: [],
  isLoading: false,
  isConnecting: false,
  error: null,

  fetchAccounts: async () => {
    set({ isLoading: true, error: null });
    try {
      const accounts = await api.getConnectors();
      set({ accounts, isLoading: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to load connected accounts.",
        isLoading: false,
      });
    }
  },

  fetchManifests: async () => {
    try {
      const manifests = await api.getConnectorCapabilities();
      set({ manifests });
    } catch {
      // Non-critical; manifests are mostly static
    }
  },

  startOAuth: async (provider: ConnectorProvider) => {
    set({ error: null });
    try {
      const res = await api.initOAuth(provider);
      if (res.ok) return res.auth_url;
      set({ error: res.message });
      return null;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to start OAuth." });
      return null;
    }
  },

  completeOAuth: async (req: OAuthCallbackRequest) => {
    set({ isConnecting: true, error: null });
    try {
      const res = await api.completeOAuth(req);
      if (res.ok) {
        // Reload the account list so the new account appears
        await get().fetchAccounts();
        set({ isConnecting: false });
        return true;
      }
      set({ error: res.message, isConnecting: false });
      return false;
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to complete OAuth.",
        isConnecting: false,
      });
      return false;
    }
  },

  disconnect: async (accountId: number) => {
    set({ error: null });
    try {
      const res = await api.disconnectConnector(accountId);
      if (res.ok) {
        set((state) => ({
          accounts: state.accounts.filter((a) => a.id !== accountId),
        }));
        return true;
      }
      set({ error: res.message });
      return false;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to disconnect account." });
      return false;
    }
  },

  clearError: () => set({ error: null }),
}));
