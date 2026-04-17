/**
 * Approvals store – polls and manages the pending approval queue.
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type { ApprovalRequest } from "../lib/types";

interface ApprovalsState {
  approvals: ApprovalRequest[];
  isLoading: boolean;
  fetchApprovals: () => Promise<void>;
  decide: (id: number, decision: "approved" | "denied") => Promise<void>;
}

export const useApprovalsStore = create<ApprovalsState>((set) => ({
  approvals: [],
  isLoading: false,

  fetchApprovals: async () => {
    set({ isLoading: true });
    try {
      const data = await api.getPendingApprovals();
      set({ approvals: data, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  decide: async (id: number, decision: "approved" | "denied") => {
    await api.decideApproval(id, { decision });
    // Refresh the list after deciding
    const data = await api.getPendingApprovals();
    set({ approvals: data });
  },
}));
