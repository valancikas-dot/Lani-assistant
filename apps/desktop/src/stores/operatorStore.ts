/**
 * Zustand store for the Computer Operator feature.
 */

import { create } from "zustand";
import {
  OperatorActionName,
  OperatorActionResponse,
  OperatorCapability,
  OperatorManifest,
  OperatorPlatform,
  RecentOperatorAction,
  WindowInfo,
} from "../lib/types";
import {
  getOperatorCapabilities,
  getOpenWindows,
  runOperatorAction,
} from "../lib/api";

interface OperatorState {
  // ── Data ─────────────────────────────────────────────────────────────────
  manifest: OperatorManifest | null;
  capabilities: OperatorCapability[];
  platform: OperatorPlatform;
  platformAvailable: boolean;
  windows: WindowInfo[];
  recentActions: RecentOperatorAction[];

  // ── UI state ─────────────────────────────────────────────────────────────
  isLoadingCapabilities: boolean;
  isLoadingWindows: boolean;
  isExecuting: boolean;
  error: string | null;
  lastScreenshotPath: string | null;

  // ── Actions ───────────────────────────────────────────────────────────────
  fetchCapabilities: () => Promise<void>;
  fetchWindows: () => Promise<void>;
  execute: (
    action: OperatorActionName,
    params?: Record<string, unknown>
  ) => Promise<OperatorActionResponse>;
  clearError: () => void;
  clearRecent: () => void;
}

export const useOperatorStore = create<OperatorState>((set, get) => ({
  manifest: null,
  capabilities: [],
  platform: "unknown",
  platformAvailable: false,
  windows: [],
  recentActions: [],
  isLoadingCapabilities: false,
  isLoadingWindows: false,
  isExecuting: false,
  error: null,
  lastScreenshotPath: null,

  fetchCapabilities: async () => {
    set({ isLoadingCapabilities: true, error: null });
    try {
      const manifest = await getOperatorCapabilities();
      set({
        manifest,
        capabilities: manifest.capabilities,
        platform: manifest.platform,
        platformAvailable: manifest.platform_available,
        isLoadingCapabilities: false,
      });
    } catch (e: unknown) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch capabilities",
        isLoadingCapabilities: false,
      });
    }
  },

  fetchWindows: async () => {
    set({ isLoadingWindows: true, error: null });
    try {
      const res = await getOpenWindows();
      set({ windows: res.windows, isLoadingWindows: false });
    } catch (e: unknown) {
      set({
        error: e instanceof Error ? e.message : "Failed to fetch windows",
        isLoadingWindows: false,
      });
    }
  },

  execute: async (action, params = {}) => {
    set({ isExecuting: true, error: null });
    try {
      const response = await runOperatorAction({ action, params });
      const entry: RecentOperatorAction = {
        action,
        params,
        response,
        timestamp: new Date().toISOString(),
      };
      // Track screenshot path for preview
      if (
        action === "take_screenshot" &&
        response.ok &&
        response.data &&
        typeof response.data === "object" &&
        "path" in (response.data as object)
      ) {
        set({
          lastScreenshotPath: (response.data as { path: string }).path,
        });
      }
      set((state) => ({
        recentActions: [entry, ...state.recentActions].slice(0, 20),
        isExecuting: false,
      }));
      return response;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Action failed";
      set({ error: msg, isExecuting: false });
      const errResponse: OperatorActionResponse = {
        ok: false,
        action,
        message: msg,
        data: null,
        requires_approval: false,
        approval_id: null,
        platform: get().platform,
      };
      return errResponse;
    }
  },

  clearError: () => set({ error: null }),
  clearRecent: () => set({ recentActions: [] }),
}));
