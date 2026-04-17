/**
 * `useI18n` — primary hook for accessing translations.
 *
 * Usage:
 *   const { t, ta, language, setLanguage } = useI18n();
 *
 *   t("nav", "chat")                      // → "Chat" | "Pokalbis" | …
 *   t("wake", "phrase_placeholder", { phrase: "Hey Lani" })  // interpolation
 *   ta("chat", "command_examples")        // → string[]  (array keys)
 */

import { useI18nStore, lookupT, lookupTArray } from "./index";
import type { Translations } from "./locales/en";

export function useI18n() {
  const { language, setLanguage } = useI18nStore();

  /**
   * Translate a string key.
   * @param namespace  Top-level namespace (e.g. "nav", "settings")
   * @param key        Key within that namespace
   * @param vars       Optional variable map for `{varName}` interpolation
   */
  function t<N extends keyof Translations, K extends keyof Translations[N]>(
    namespace: N,
    key: K,
    vars?: Record<string, string>,
  ): string {
    let result = lookupT(language, namespace, key);
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        result = result.replace(new RegExp(`\\{${k}\\}`, "g"), v);
      }
    }
    return result;
  }

  /**
   * Translate an array key (e.g. `chat.command_examples`).
   */
  function ta<N extends keyof Translations, K extends keyof Translations[N]>(
    namespace: N,
    key: K,
  ): string[] {
    return lookupTArray(language, namespace, key);
  }

  return { t, ta, language, setLanguage };
}
