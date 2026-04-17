/**
 * i18n engine.
 *
 * • `locales` — registry of all supported language packs.
 * • `lookupT`  — type-safe lookup with automatic English fallback.
 * • `useI18nStore` — Zustand store holding the active language code.
 * • `SUPPORTED_UI_LANGUAGES` — list shown in the language selector.
 */

import { create } from "zustand";
import { en, type Translations, type LocaleDefinition } from "./locales/en";
import { lt } from "./locales/lt";

// ── Locale registry ────────────────────────────────────────────────────────

const locales: Record<string, LocaleDefinition> = {
  en,
  lt,
};

// ── Core lookup ────────────────────────────────────────────────────────────

/**
 * Look up a translation key, falling back to English when:
 *  1. The requested language is not registered.
 *  2. The namespace or key is missing in the locale.
 *  3. The resolved value is not a string.
 */
export function lookupT<
  N extends keyof Translations,
  K extends keyof Translations[N],
>(lang: string, namespace: N, key: K): string {
  const locale = locales[lang] ?? locales["en"];

  // Try the requested locale first
  const ns = locale[namespace] as Record<string, unknown> | undefined;
  const val = ns?.[key as string];
  if (typeof val === "string") return val;

  // Fall back to English
  const enNs = (en as Record<string, Record<string, unknown>>)[namespace as string];
  const enVal = enNs?.[key as string];
  return typeof enVal === "string" ? enVal : String(key);
}

/**
 * Look up an array translation key (e.g. `chat.command_examples`).
 * Falls back to the English array if missing.
 */
export function lookupTArray<
  N extends keyof Translations,
  K extends keyof Translations[N],
>(lang: string, namespace: N, key: K): string[] {
  const locale = locales[lang] ?? locales["en"];

  const ns = locale[namespace] as Record<string, unknown> | undefined;
  const val = ns?.[key as string];
  if (Array.isArray(val)) return val as string[];

  // Fall back to English
  const enNs = (en as Record<string, Record<string, unknown>>)[namespace as string];
  const enVal = enNs?.[key as string];
  return Array.isArray(enVal) ? (enVal as string[]) : [];
}

// ── Zustand store ──────────────────────────────────────────────────────────

interface I18nState {
  language: string;
  setLanguage: (lang: string) => void;
}

export const useI18nStore = create<I18nState>((set) => ({
  language: "en",
  setLanguage: (lang) => set({ language: lang }),
}));

// ── Supported language list ────────────────────────────────────────────────

export interface UILanguage {
  code: string;
  /** English label */
  label: string;
  /** Native label */
  native: string;
}

export const SUPPORTED_UI_LANGUAGES: UILanguage[] = [
  { code: "en", label: "English",    native: "English"   },
  { code: "lt", label: "Lithuanian", native: "Lietuvių"  },
];
