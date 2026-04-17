/**
 * Memory store – manages memory entries and suggestions in the UI.
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type {
  MemoryEntry,
  MemoryEntryCreate,
  MemoryEntryUpdate,
  SuggestionCard,
} from "../lib/types";

interface MemoryState {
  entries: MemoryEntry[];
  suggestions: SuggestionCard[];
  isLoading: boolean;
  error: string | null;

  fetchEntries: (category?: string) => Promise<void>;
  fetchSuggestions: () => Promise<void>;
  createEntry: (payload: MemoryEntryCreate) => Promise<MemoryEntry | null>;
  updateEntry: (id: number, patch: MemoryEntryUpdate) => Promise<MemoryEntry | null>;
  deleteEntry: (id: number) => Promise<void>;
  acceptSuggestion: (entryId: number) => Promise<void>;
  dismissSuggestion: (entryId: number) => Promise<void>;
  pinEntry: (id: number, pinned: boolean) => Promise<void>;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  entries: [],
  suggestions: [],
  isLoading: false,
  error: null,

  fetchEntries: async (category?: string) => {
    set({ isLoading: true, error: null });
    try {
      const entries = await api.listMemory(category, "active");
      set({ entries, isLoading: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Failed to load memory.",
        isLoading: false,
      });
    }
  },

  fetchSuggestions: async () => {
    try {
      const suggestions = await api.getMemorySuggestions();
      set({ suggestions });
    } catch {
      // silently fail – suggestions are non-critical
    }
  },

  createEntry: async (payload: MemoryEntryCreate) => {
    try {
      const entry = await api.createMemoryEntry(payload);
      set((state) => ({ entries: [entry, ...state.entries] }));
      return entry;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to create entry." });
      return null;
    }
  },

  updateEntry: async (id: number, patch: MemoryEntryUpdate) => {
    try {
      const updated = await api.updateMemoryEntry(id, patch);
      set((state) => ({
        entries: state.entries.map((e) => (e.id === id ? updated : e)),
      }));
      return updated;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to update entry." });
      return null;
    }
  },

  deleteEntry: async (id: number) => {
    try {
      await api.deleteMemoryEntry(id);
      set((state) => ({
        entries: state.entries.filter((e) => e.id !== id),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to delete entry." });
    }
  },

  acceptSuggestion: async (entryId: number) => {
    try {
      const updated = await api.updateMemoryEntry(entryId, {
        status: "active",
        confidence: 1.0,
      });
      // Move from suggestions list to entries list
      set((state) => ({
        suggestions: state.suggestions.filter((s) => s.entry_id !== entryId),
        entries: [updated, ...state.entries.filter((e) => e.id !== entryId)],
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to accept suggestion." });
    }
  },

  dismissSuggestion: async (entryId: number) => {
    try {
      await api.updateMemoryEntry(entryId, { status: "dismissed" });
      set((state) => ({
        suggestions: state.suggestions.filter((s) => s.entry_id !== entryId),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to dismiss suggestion." });
    }
  },

  pinEntry: async (id: number, pinned: boolean) => {
    const updated = await get().updateEntry(id, { pinned });
    if (updated) {
      // Re-sort: pinned entries first
      set((state) => ({
        entries: [...state.entries].sort((a, b) => {
          if (a.pinned === b.pinned) return 0;
          return a.pinned ? -1 : 1;
        }),
      }));
    }
  },
}));
