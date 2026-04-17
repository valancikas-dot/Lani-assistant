/**
 * Auth store – JWT token, user info, login/logout/register.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

const API_BASE = "http://localhost:8000";

export interface AuthUser {
  user_id: number;
  email: string;
  is_admin: boolean;
  token_balance: number;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isLoading: boolean;
  error: string | null;

  login: (email: string, password: string) => Promise<boolean>;
  register: (email: string, password: string) => Promise<boolean>;
  logout: () => void;
  fetchMe: () => Promise<void>;
  clearError: () => void;
}

async function authRequest(path: string, body: object) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail ?? "Request failed");
  return data;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      isLoading: false,
      error: null,

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const data = await authRequest("/api/v1/auth/login", { email, password });
          set({ token: data.access_token, isLoading: false });
          await get().fetchMe();
          return true;
        } catch (e: unknown) {
          set({ error: (e as Error).message, isLoading: false });
          return false;
        }
      },

      register: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const data = await authRequest("/api/v1/auth/register", { email, password });
          set({ token: data.access_token, isLoading: false });
          await get().fetchMe();
          return true;
        } catch (e: unknown) {
          set({ error: (e as Error).message, isLoading: false });
          return false;
        }
      },

      logout: () => {
        set({ token: null, user: null, error: null });
      },

      fetchMe: async () => {
        const { token } = get();
        if (!token) return;
        try {
          const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (!res.ok) {
            set({ token: null, user: null });
            return;
          }
          const data = await res.json();
          set({
            user: {
              user_id: data.user_id,
              email: data.email,
              is_admin: data.is_admin,
              token_balance: data.token_balance,
            },
          });
        } catch {
          /* ignore network errors */
        }
      },

      clearError: () => set({ error: null }),
    }),
    {
      name: "lani-auth",
      partialize: (s) => ({ token: s.token, user: s.user }),
    }
  )
);
