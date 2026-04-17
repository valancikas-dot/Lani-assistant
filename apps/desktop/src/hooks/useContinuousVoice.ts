/**
 * useContinuousVoice – "always-on" voice conversation mode.
 *
 * Flow
 * ────
 *   1.  Wake word detected ("hey Lani" / "Lani") or user clicks the mic
 *       → continuous mode activates, green indicator shown.
 *   2.  MediaRecorder records a short utterance (silence-detection via
 *       AudioContext analyser).
 *   3.  Audio sent to /voice/transcribe → transcript.
 *       • If transcript contains "Lani off" / "Lani stop" / "Lani baigti"
 *         → continuous mode deactivates.
 *       • Otherwise → sendCommandWithPlan(transcript).
 *   4.  After the response is received (and TTS finishes playing) the
 *       recorder restarts for the next utterance.
 *
 * Silence detection
 * ─────────────────
 *   We use a Web Audio AnalyserNode to watch RMS volume.
 *   Recording stops automatically after SILENCE_DURATION_MS of audio below
 *   SILENCE_THRESHOLD (0..255 scale). Min recording length: MIN_RECORD_MS.
 *
 * Stop phrases (case-insensitive, any language variant accepted):
 *   "lani off", "lani stop", "lani baigti", "lani išjungti", "lani sustabdyk"
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../lib/api";

// ── Tunable constants ──────────────────────────────────────────────────────────
const SILENCE_THRESHOLD = 18;        // RMS below this → silence (0-255). Pakeltas kad fono triukšmas neskaičiuotų kaip kalba.
const VOICE_THRESHOLD = 28;          // RMS above this → voice detected (turi būti > SILENCE_THRESHOLD)
const SILENCE_DURATION_MS = 1_800;   // stop after 1.8 s of silence (po kalbos)
const MIN_RECORD_MS = 1_200;         // never stop before 1.2 s (avoids cutting off speech)
const MAX_RECORD_MS = 25_000;        // hard cap 25 s per utterance
const RESTART_DELAY_MS = 400;        // wait after TTS finishes before re-listening
const VOICE_START_MIN_MS = 400;      // how long voice must be above threshold to count as "real speech" started
const MAX_WAIT_FOR_VOICE_MS = 8_000; // jei per 8s niekas nekalba — restartam (negyvai neuždegame)

const STOP_PHRASES = [
  "lani off",
  "lani stop",
  "lani baigti",
  "lani išjungti",
  "lani sustabdyk",
  "lani nutilk",
];

/**
 * Whisper hallucinations — returned when it hears silence or background noise.
 * These should be silently dropped instead of being sent as commands.
 */
const WHISPER_HALLUCINATIONS = new Set([
  "🎵", "♪", "♫", "🎶", "♩", "🎼",
  ".", "..", "...", "…",
  "[BLANK_AUDIO]", "[blank_audio]",
  "(silence)", "[silence]",
  "[ Silence ]", "[ silence ]",
  "음악", // Korean: "music"
  "Музыка", // Russian: "music"
]);

function isHallucination(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.length < 3) return true;

  // Known symbols / markers
  if (WHISPER_HALLUCINATIONS.has(trimmed)) return true;

  // No real letter characters
  const letterCount = (trimmed.match(/\p{L}/gu) ?? []).length;
  if (letterCount === 0 && trimmed.length < 20) return true;

  // URL only
  if (/^(https?:\/\/|www\.)\S+$/.test(trimmed)) return true;

  // Plain domain / website name (e.g. "ziniuradijas.lt", "www.ziniuradijas.lt")
  const wordCount = trimmed.split(/\s+/).filter(w => w.length > 1).length;
  if (/^[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(\/\S*)?$/.test(trimmed) && wordCount <= 1) return true;

  // Single word ending in a TLD — likely a domain hallucination
  if (wordCount === 1 && /\.(lt|com|net|org|eu|io|tv|fm|lrt|delfi)$/i.test(trimmed)) return true;

  return false;
}

function isStopPhrase(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return STOP_PHRASES.some((p) => lower.includes(p));
}

export type ContinuousVoiceStatus =
  | "off"           // not active
  | "listening"     // recording + silence detection
  | "processing"    // sending to STT / waiting for LLM
  | "speaking";     // TTS playing back

export interface UseContinuousVoiceOptions {
  /** Language forwarded to STT endpoint. */
  language?: string;
  /** Called with the transcript text when a command is ready to send. */
  onCommand: (transcript: string) => Promise<unknown>;
  /** Called when continuous mode is deactivated (stop phrase heard). */
  onStop?: () => void;
}

export function useContinuousVoice({
  // Use BCP-47 tag to match backend and Web Speech API expectations
  language = "lt-LT",
  onCommand,
  onStop,
}: UseContinuousVoiceOptions) {
  const [status, setStatus] = useState<ContinuousVoiceStatus>("off");
  const [lastTranscript, setLastTranscript] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ── Internal refs (not state — avoids stale closure issues) ───────────────
  const activeRef = useRef(false);           // is continuous mode on?
  const recordingRef = useRef(false);        // currently recording?
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startTimeRef = useRef<number>(0);
  const onCommandRef = useRef(onCommand);
  const onStopRef = useRef(onStop);
  const languageRef = useRef(language);
  // VAD: sekame ar jau pradėta kalbėti
  const voiceDetectedRef = useRef(false);    // true kai žmogus pradėjo kalbėti
  const voiceStartTimeRef = useRef<number>(0); // kada pirmą kartą išgirdo balsą

  onCommandRef.current = onCommand;
  onStopRef.current = onStop;
  languageRef.current = language;

  // ── Helpers ───────────────────────────────────────────────────────────────

  const clearTimers = useCallback(() => {
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
    if (maxTimerRef.current) { clearTimeout(maxTimerRef.current); maxTimerRef.current = null; }
  }, []);

  const teardownRecorder = useCallback(() => {
    clearTimers();
    if (mediaRecorderRef.current) {
      try { mediaRecorderRef.current.stop(); } catch { /* ignore */ }
      mediaRecorderRef.current = null;
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch { /* ignore */ }
      audioContextRef.current = null;
      analyserRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    recordingRef.current = false;
    chunksRef.current = [];
  }, [clearTimers]);

  // ── Core: record one utterance, transcribe, dispatch ─────────────────────

  const recordUtterance = useCallback(async () => {
    if (!activeRef.current) return;
    if (recordingRef.current) return;
    recordingRef.current = true;
    chunksRef.current = [];
    setStatus("listening");
    setError(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError("Mikrofonas neprieinamas. Patikrinkite leidimus sistemos nustatymuose.");
      setStatus("off");
      activeRef.current = false;
      recordingRef.current = false;
      return;
    }
    streamRef.current = stream;

    // Set up AudioContext for silence detection
    const audioCtx = new AudioContext();
    audioContextRef.current = audioCtx;
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyserRef.current = analyser;

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    startTimeRef.current = Date.now();
    voiceDetectedRef.current = false;
    voiceStartTimeRef.current = 0;

    // VAD + Silence detection poll
    const checkSilence = () => {
      if (!activeRef.current || !recordingRef.current) return;
      analyser.getByteTimeDomainData(dataArray);
      // RMS
      let sum = 0;
      for (const v of dataArray) { const d = v - 128; sum += d * d; }
      const rms = Math.sqrt(sum / dataArray.length);

      const now = Date.now();
      const elapsed = now - startTimeRef.current;

      if (rms >= VOICE_THRESHOLD) {
        // Balsas girdimas — atšaukiame silence timer
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
        // Pažymime kad kalba prasidėjo
        if (!voiceDetectedRef.current) {
          if (voiceStartTimeRef.current === 0) {
            voiceStartTimeRef.current = now;
          } else if (now - voiceStartTimeRef.current >= VOICE_START_MIN_MS) {
            // Balsas tęsėsi pakankamai ilgai — laikome tikru kalbėjimu
            voiceDetectedRef.current = true;
          }
        }
      } else if (rms < SILENCE_THRESHOLD) {
        // Tylu — bet pradedame silence timer TIK jei kalba jau buvo aptikta
        if (voiceDetectedRef.current && !silenceTimerRef.current) {
          silenceTimerRef.current = setTimeout(() => {
            // Sustabdome tik jei minimum įrašymo laikas praėjo
            if (Date.now() - startTimeRef.current >= MIN_RECORD_MS) {
              if (mediaRecorderRef.current?.state === "recording") {
                mediaRecorderRef.current.stop();
              }
            }
          }, SILENCE_DURATION_MS);
        }
        // Jei balsas dar neprasidėjo, resetuojame voiceStartTime (trumpas spraktelėjimas)
        if (!voiceDetectedRef.current && rms < SILENCE_THRESHOLD) {
          // Nulinti tik jei labai ilgai laukiame (> 500ms)
          if (voiceStartTimeRef.current > 0 && now - voiceStartTimeRef.current > 500) {
            voiceStartTimeRef.current = 0;
          }
        }
      } else {
        // Tarpinė zona (SILENCE_THRESHOLD <= rms < VOICE_THRESHOLD) — ignoruojame
        // tai gali būti fono triukšmas — ne kalba, ne visiška tyla
        if (silenceTimerRef.current && voiceDetectedRef.current) {
          // Jei jau kalbėjo ir dabar tarpinė zona — atšaukiame silence timer
          // (žmogus dar kalba, tik garsiau/tyliau)
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
      }

      if (activeRef.current && recordingRef.current) {
        requestAnimationFrame(checkSilence);
      }
    };

    // Preferred codec
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = async () => {
      clearTimers();
      clearTimeout(noVoiceTimer);
      // Tear down audio context + stream tracks
      try { audioCtx.close(); } catch { /* ignore */ }
      audioContextRef.current = null;
      analyserRef.current = null;
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recordingRef.current = false;

      if (!activeRef.current) return;

      // Jei balsas nebuvo aptiktas (tik fono triukšmas) — tiesiog pradedame iš naujo
      if (!voiceDetectedRef.current) {
        console.debug("[voice] nėra balso — paleidžiame iš naujo");
        setTimeout(() => { if (activeRef.current) void recordUtterance(); }, RESTART_DELAY_MS);
        return;
      }

      if (chunksRef.current.length === 0) {
        // Nothing recorded — restart immediately
        setTimeout(() => { if (activeRef.current) void recordUtterance(); }, RESTART_DELAY_MS);
        return;
      }

      setStatus("processing");
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      });
      chunksRef.current = [];

      try {
  // Ensure we send a BCP-47 tag to the backend (e.g. "lt-LT").
  // The backend will normalise to provider-specific form (e.g. "lt").
  const result = await api.transcribeAudio(blob, languageRef.current);
        if (result.status !== "success" || !result.transcript?.trim()) {
          // Nothing heard — restart loop silently
          if (activeRef.current) {
            setTimeout(() => void recordUtterance(), RESTART_DELAY_MS);
          }
          return;
        }

        const transcript = result.transcript.trim();

        // Drop Whisper hallucinations (🎵, silence, etc.) silently
        if (isHallucination(transcript)) {
          if (activeRef.current) {
            setTimeout(() => void recordUtterance(), RESTART_DELAY_MS);
          }
          return;
        }

        setLastTranscript(transcript);

        // Check for stop phrase
        if (isStopPhrase(transcript)) {
          activeRef.current = false;
          setStatus("off");
          onStopRef.current?.();
          return;
        }

        // Dispatch to chat
        await onCommandRef.current(transcript);

        // Wait a short moment for TTS to potentially start, then restart listening
        // (ChatPage/voiceStore handles TTS; we just wait a bit)
        setTimeout(() => {
          if (activeRef.current) void recordUtterance();
        }, RESTART_DELAY_MS);

      } catch (err) {
        // On error, still keep the loop going
        if (activeRef.current) {
          setTimeout(() => void recordUtterance(), 1_500);
        }
      }
    };

    // Max recording time guard
    maxTimerRef.current = setTimeout(() => {
      if (recorder.state === "recording") recorder.stop();
    }, MAX_RECORD_MS);

    // Jei per MAX_WAIT_FOR_VOICE_MS niekas neprasidėjo kalbėti — restartam be siuntimo
    const noVoiceTimer = setTimeout(() => {
      if (!voiceDetectedRef.current && recorder.state === "recording") {
        console.debug("[voice] per ilgai laukėme balso — restartam");
        recorder.stop();
      }
    }, MAX_WAIT_FOR_VOICE_MS);

    recorder.start(100);
    requestAnimationFrame(checkSilence);
  }, [clearTimers]);

  // ── Public API ─────────────────────────────────────────────────────────────

  /** Activate continuous voice mode. */
  const activate = useCallback(() => {
    if (activeRef.current) return;
    activeRef.current = true;
    void recordUtterance();
  }, [recordUtterance]);

  /** Deactivate continuous voice mode immediately. */
  const deactivate = useCallback(() => {
    activeRef.current = false;
    teardownRecorder();
    setStatus("off");
  }, [teardownRecorder]);

  // Stop on unmount
  useEffect(() => {
    return () => {
      activeRef.current = false;
      teardownRecorder();
    };
  }, [teardownRecorder]);

  return {
    status,
    lastTranscript,
    error,
    isActive: status !== "off",
    activate,
    deactivate,
  };
}
