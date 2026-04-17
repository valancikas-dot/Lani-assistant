/**
 * missionControlStore – state management for the Mission Control page.
 *
 * Polls /api/v1/chains at configurable intervals and stores the detail
 * for a selected chain (lazy-loaded on selection).
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type { ChainSummary, ChainDetail, CheckpointsResponse } from "../lib/types";

interface MissionControlState {
  chains: ChainSummary[];
  isLoading: boolean;
  error: string | null;

  selectedChainId: string | null;
  chainDetail: ChainDetail | null;
  checkpoints: CheckpointsResponse | null;
  isLoadingDetail: boolean;
  detailError: string | null;

  // Actions
  fetchChains: (limit?: number) => Promise<void>;
  selectChain: (chainId: string | null) => Promise<void>;
  refreshDetail: () => Promise<void>;
  clearSelection: () => void;
}

export const useMissionControlStore = create<MissionControlState>((set, get) => ({
  chains: [],
  isLoading: false,
  error: null,

  selectedChainId: null,
  chainDetail: null,
  checkpoints: null,
  isLoadingDetail: false,
  detailError: null,

  fetchChains: async (limit = 40) => {
    set({ isLoading: true, error: null });
    try {
      const chains = await api.getChains(limit);
      set({ chains, isLoading: false });
    } catch (err) {
      set({ error: String(err), isLoading: false });
    }
  },

  selectChain: async (chainId: string | null) => {
    if (chainId === null) {
      set({ selectedChainId: null, chainDetail: null, checkpoints: null, detailError: null });
      return;
    }
    set({ selectedChainId: chainId, isLoadingDetail: true, detailError: null });
    try {
      const [detail, checkpoints] = await Promise.all([
        api.getChainDetail(chainId),
        api.getChainCheckpoints(chainId),
      ]);
      set({ chainDetail: detail, checkpoints, isLoadingDetail: false });
    } catch (err) {
      set({ detailError: String(err), isLoadingDetail: false });
    }
  },

  refreshDetail: async () => {
    const { selectedChainId } = get();
    if (!selectedChainId) return;
    await get().selectChain(selectedChainId);
  },

  clearSelection: () => {
    set({ selectedChainId: null, chainDetail: null, checkpoints: null, detailError: null });
  },
}));
