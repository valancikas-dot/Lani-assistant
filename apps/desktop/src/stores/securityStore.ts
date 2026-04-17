/**
 * Zustand store for the Security dashboard.
 *
 * Holds the server-side SecurityStatus snapshot, PIN-form state,
 * and async actions for fetching / setting the PIN.
 */

import { create } from "zustand";
import type { SecurityStatus, SetPinRequest } from "../lib/types";
import { getSecurityStatus, setPin as apiSetPin } from "../lib/api";

interface SecurityStore {
  // Remote state
  status: SecurityStatus | null;
  isLoading: boolean;
  error: string | null;

  // PIN form
  pinValue: string;
  confirmPinValue: string;
  pinSaving: boolean;
  pinMessage: string | null;
  pinError: string | null;

  // Actions
  fetchStatus: () => Promise<void>;
  setPinValue: (v: string) => void;
  setConfirmPinValue: (v: string) => void;
  savePin: () => Promise<void>;
  clearPinForm: () => void;
}

export const useSecurityStore = create<SecurityStore>((set, get) => ({
  status: null,
  isLoading: false,
  error: null,

  pinValue: "",
  confirmPinValue: "",
  pinSaving: false,
  pinMessage: null,
  pinError: null,

  fetchStatus: async () => {
    set({ isLoading: true, error: null });
    try {
      const data = await getSecurityStatus();
      set({ status: data, isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  setPinValue: (v) => set({ pinValue: v }),
  setConfirmPinValue: (v) => set({ confirmPinValue: v }),

  savePin: async () => {
    const { pinValue, confirmPinValue } = get();
    if (pinValue !== confirmPinValue) {
      set({ pinError: "PINs do not match." });
      return;
    }
    if (pinValue.length < 4) {
      set({ pinError: "PIN must be at least 4 characters." });
      return;
    }
    set({ pinSaving: true, pinError: null, pinMessage: null });
    try {
      const payload: SetPinRequest = { pin: pinValue };
      const res = await apiSetPin(payload);
      set({
        pinSaving: false,
        pinMessage: res.message,
        pinValue: "",
        confirmPinValue: "",
      });
      // Refresh security status so fallback_pin_enabled updates
      await get().fetchStatus();
    } catch (e) {
      set({ pinSaving: false, pinError: String(e) });
    }
  },

  clearPinForm: () =>
    set({ pinValue: "", confirmPinValue: "", pinMessage: null, pinError: null }),
}));
