/**
 * useWakeWordListener – always-on background keyword detection.
 *
 * Uses the Web Speech API (webkitSpeechRecognition / SpeechRecognition) which
 * is available in Tauri's WKWebView on macOS. The hook continuously listens for
 * the configured wake phrase (default "lani") in the background.
 *
 * When the phrase is detected it calls `onWakeDetected(transcript)` so the
 * caller can activate the voice session and start a PTT recording.
 *
 * Lifecycle:
 *  - Starts only when `enabled === true` AND the browser supports SpeechRecognition.
 *  - Automatically restarts after each recognition result (continuous listening).
 *  - Stops cleanly on unmount or when `enabled` becomes false.
 *  - Does NOT start a new recognition session while the voice session is already
 *    unlocked (avoids double-triggering during PTT recording).
 *
 * Notes:
 *  - macOS Tauri WebView uses WKWebView which exposes `window.SpeechRecognition`
 *    or `window.webkitSpeechRecognition`.
 *  - The microphone permission popup is triggered on first use; after that it is
 *    remembered by the OS.
 *  - Language should match the user's spoken language (e.g. "lt-LT" for Lithuanian
 *    or "en-US" for English). The wake word "lani" is language-agnostic.
 */

import { useEffect, useRef, useCallback, useState } from "react";

// Minimal interface so TypeScript doesn't complain about webkitSpeechRecognition.
interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

interface SpeechRecognitionEvent {
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionResultList {
  readonly length: number;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionAlternative {
  readonly transcript: string;
  readonly confidence: number;
}

interface SpeechRecognitionErrorEvent {
  error: string;
  message?: string;
}

function getSpeechRecognitionClass():
  | (new () => SpeechRecognitionInstance)
  | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isWakeWordSupported(): boolean {
  return getSpeechRecognitionClass() !== null;
}

export interface UseWakeWordListenerOptions {
  /** Primary wake phrase – matched as a substring (case-insensitive). Default "lani". */
  wakePhrase: string;
  /** Secondary / alternative phrase. Default "hey lani". */
  secondaryPhrase?: string;
  /** BCP-47 language tag for the recogniser (e.g. "lt-LT", "en-US"). Default "lt-LT". */
  language?: string;
  /** Called with the raw transcript when a wake phrase is detected. */
  onWakeDetected: (transcript: string) => void;
  /** Whether the listener is active. Set to false to pause without unmounting. */
  enabled: boolean;
  /** Whether the voice session is currently unlocked (recording in progress). */
  sessionUnlocked: boolean;
}

export function useWakeWordListener({
  wakePhrase,
  secondaryPhrase = "hey lani",
  language = "lt-LT",
  onWakeDetected,
  enabled,
  sessionUnlocked,
}: UseWakeWordListenerOptions): {
  isListening: boolean;
  isSupported: boolean;
  lastError: string | null;
} {
  const recogRef = useRef<SpeechRecognitionInstance | null>(null);
  const isListeningRef = useRef(false);
  const [isListeningState, setIsListeningState] = useState(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const enabledRef = useRef(enabled);
  const sessionUnlockedRef = useRef(sessionUnlocked);
  const onWakeDetectedRef = useRef(onWakeDetected);

  // Use refs so the recognition callbacks always see latest values without
  // needing to recreate the recognition instance on every render.
  enabledRef.current = enabled;
  sessionUnlockedRef.current = sessionUnlocked;
  onWakeDetectedRef.current = onWakeDetected;

  const startListening = useCallback(() => {
    const SpeechRecognitionClass = getSpeechRecognitionClass();
    if (!SpeechRecognitionClass) return;
    if (isListeningRef.current) return;
    if (!enabledRef.current) return;
    if (sessionUnlockedRef.current) return; // don't listen during active recording

    const recog = new SpeechRecognitionClass();
    recog.lang = language;
    recog.continuous = false;    // one utterance at a time
    recog.interimResults = false; // only final results
    recog.maxAlternatives = 3;

    recog.onstart = () => {
      isListeningRef.current = true;
      setIsListeningState(true);
    };

    recog.onresult = (event: SpeechRecognitionEvent) => {
      // Collect all alternatives from all results
      const allTexts: string[] = [];
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        for (let j = 0; j < result.length; j++) {
          allTexts.push(result[j].transcript.toLowerCase().trim());
        }
      }

      const primary = wakePhrase.toLowerCase().trim();
      const secondary = secondaryPhrase.toLowerCase().trim();

      const matchedText = allTexts.find(
        (txt) => txt.includes(primary) || txt.includes(secondary)
      );

      if (matchedText) {
        onWakeDetectedRef.current(matchedText);
        // Don't restart immediately – the caller will activate the session,
        // which sets sessionUnlocked=true and blocks restart automatically.
        return;
      }
      // No wake word – recognition will end and onend will restart it.
    };

    recog.onerror = (event: SpeechRecognitionErrorEvent) => {
      isListeningRef.current = false;
      setIsListeningState(false);
      // "not-allowed" = leidimas dar nesuteiktas arba atimtas – bandome po 3s
      if (event.error === "aborted") return;
      if (event.error === "not-allowed") {
        if (enabledRef.current && !sessionUnlockedRef.current) {
          restartTimerRef.current = setTimeout(() => startListening(), 3000);
        }
        return;
      }
      // Back-off restart on other errors
      if (enabledRef.current && !sessionUnlockedRef.current) {
        restartTimerRef.current = setTimeout(() => startListening(), 2000);
      }
    };

    recog.onend = () => {
      isListeningRef.current = false;
      setIsListeningState(false);
      // Automatically restart if still enabled and session is not locked
      if (enabledRef.current && !sessionUnlockedRef.current) {
        restartTimerRef.current = setTimeout(() => startListening(), 300);
      }
    };

    recogRef.current = recog;
    try {
      recog.start();
    } catch {
      isListeningRef.current = false;
    }
  }, [language, wakePhrase, secondaryPhrase]); // stable – only recreated when config changes

  const stopListening = useCallback(() => {
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
    const recog = recogRef.current;
    if (recog) {
      try {
        recog.abort();
      } catch {
        /* ignore */
      }
      recogRef.current = null;
    }
    isListeningRef.current = false;
  }, []);

  // Start / stop based on enabled + sessionUnlocked
  useEffect(() => {
    if (enabled && !sessionUnlocked) {
      // Small delay so React can finish the render cycle before grabbing mic
      const t = setTimeout(() => startListening(), 200);
      return () => clearTimeout(t);
    } else {
      stopListening();
    }
  }, [enabled, sessionUnlocked, startListening, stopListening]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopListening();
    };
  }, [stopListening]);

  return {
    isListening: isListeningState,
    isSupported: getSpeechRecognitionClass() !== null,
    lastError: null,
  };
}
