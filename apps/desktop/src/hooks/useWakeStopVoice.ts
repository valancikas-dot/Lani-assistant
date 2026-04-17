/**
 * useWakeStopVoice v4 – greitas, patikimas wake word aptikimas.
 *
 * Pagrindiniai patobulinimai:
 *  • muteRef – kol Lani kalba (TTS), Whisper nekviečiamas (nereaguoja į savo balsą)
 *  • WINDOW_MS=5000 – ilgesnis langas, visada pagauna pilną frazę
 *  • POLL_MS=800 – greitesnis polling
 *  • "Lani" be komandos → papildomas poll'as su didesniu langu
 *  • Švaresnis cooldown valdymas
 */

import { useEffect, useRef, useState } from "react";
import * as api from "../lib/api";

// ── Konstantos ─────────────────────────────────────────────────────────────────
const WAKE_WORD          = "lani";
const SAMPLE_RATE        = 16000;
const POLL_MS            = 800;    // polling dažnis
const WINDOW_MS          = 5000;   // kiek garso istorijos imame (5s – visada pilna frazė)
const EXTENDED_WINDOW_MS = 7000;   // jei girdi "Lani" be komandos – platesnis langas
const BUFFER_MAX_SAMPLES = SAMPLE_RATE * 20;
const COOLDOWN_MS        = 3500;   // po komandos tiek ms neklausoma
const TTS_EXTRA_COOLDOWN_MS = 2500; // papildomas laikas po TTS pabaigos (garso „uodega")
const MIN_RMS            = 0.012;  // tylos slenkstis – tik ryškus kalbos garsas
const MIN_LETTERS        = 3;

// ── Haliucinacijų filtras ──────────────────────────────────────────────────────
const HALLUCINATION_RE = [
  /^https?:\/\//i,
  /^www\./i,
  /\bwww\./i,
  /\.(lt|com|net|org|io|eu)\b/i,   // bet koks domenas
  /ziniuradijas|lrt\.lt|delfi|15min|bernardinai/i,
  /subtitl|copyright|pabaiga/i,
  /^\s*[🎵🎶📷👏✨🌟💫🔊🎤📣🔔]+\s*$/u,
  /[🎵🎶📷👏✨🌟💫🔊🎤]{2,}/u,   // keli emoji iš eilės
];

function isHallucination(text: string): boolean {
  const t = text.trim();
  if (t.length < MIN_LETTERS) return true;
  const letters = (t.match(/\p{L}/gu) ?? []).length;
  if (letters < MIN_LETTERS) return true;
  for (const re of HALLUCINATION_RE) if (re.test(t)) return true;
  // jei >60% žodžiai atrodo kaip domenai
  const words = t.split(/\s+/);
  const domainLike = words.filter(w => /^[a-z0-9-]+\.[a-z]{2,4}$/i.test(w));
  if (domainLike.length > 0 && domainLike.length >= words.length * 0.5) return true;
  return false;
}

export type WakeStopStatus = "off" | "idle" | "processing";

export interface UseWakeStopVoiceOptions {
  language?: string;
  onCommand: (transcript: string) => Promise<unknown>;
  onWakeDetected?: () => void;
  /** Perduodame true kai TTS groja – tada nutildo mikrofoną */
  isTtsPlaying?: boolean;
}

// WAV encoder
function float32ToWav(samples: Float32Array, sampleRate: number): Blob {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const s4 = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  s4(0, "RIFF"); v.setUint32(4, 36 + n * 2, true);
  s4(8, "WAVE"); s4(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  s4(36, "data"); v.setUint32(40, n * 2, true);
  let off = 44;
  for (let i = 0; i < n; i++, off += 2) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(off, x < 0 ? x * 0x8000 : x * 0x7FFF, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

function hasWakeWord(t: string): boolean {
  return /\blan[iy]e?\b/i.test(t);
}

function extractCommand(text: string): string {
  return text
    .replace(/^\s*lan[iy]e?\s*[,.]?\s*/i, "")
    .replace(/\bpabaiga\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function useWakeStopVoice({
  language = "lt-LT",
  onCommand,
  onWakeDetected,
  isTtsPlaying = false,
}: UseWakeStopVoiceOptions) {
  const [status, setStatus]                 = useState<WakeStopStatus>("off");
  const [isActive, setIsActive]             = useState(false);
  const [lastTranscript, setLastTranscript] = useState<string | null>(null);
  const [error, setError]                   = useState<string | null>(null);

  const activeRef         = useRef(false);
  const onCommandRef      = useRef(onCommand);
  const onWakeDetectedRef = useRef(onWakeDetected);
  const langRef           = useRef(language);
  const transcribingRef   = useRef(false);
  const lastCommandAtRef  = useRef(0);
  const isTtsPlayingRef   = useRef(isTtsPlaying);
  const ttsEndedAtRef     = useRef(0); // kada TTS baigėsi – papildomas cooldown

  // PCM ring buffer
  const audioCtxRef  = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef    = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef    = useRef<MediaStream | null>(null);
  const pcmRingRef   = useRef<Float32Array>(new Float32Array(BUFFER_MAX_SAMPLES));
  const pcmWriteRef  = useRef(0);
  const pcmCountRef  = useRef(0);

  // Sinchronizuojame refs
  onCommandRef.current      = onCommand;
  onWakeDetectedRef.current = onWakeDetected;
  langRef.current           = language;
  // Kai TTS baigiasi – fiksuojame laiką (papildomas cooldown prieš klausymą)
  if (isTtsPlayingRef.current && !isTtsPlaying) {
    ttsEndedAtRef.current = Date.now();
    pcmCountRef.current = 0; // išvalome bufferį – neliks TTS garso
  }
  isTtsPlayingRef.current = isTtsPlaying;

  // ── AudioContext ──────────────────────────────────────────────────────────
  async function startAudio(): Promise<boolean> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });
      streamRef.current = stream;

      let ctx: AudioContext;
      try { ctx = new AudioContext({ sampleRate: SAMPLE_RATE }); }
      catch { ctx = new AudioContext(); }
      if (ctx.state === "suspended") await ctx.resume();
      audioCtxRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      sourceRef.current = source;

      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      pcmRingRef.current  = new Float32Array(BUFFER_MAX_SAMPLES);
      pcmWriteRef.current = 0;
      pcmCountRef.current = 0;

      processor.onaudioprocess = (e) => {
        if (!activeRef.current) return;
        // Kol TTS groja – rašome bufferį bet neįskaičiuojame į count
        // (taip valosi senas turinys, bet naujas TTS garsas nebus siunčiamas)
        const data = e.inputBuffer.getChannelData(0);
        const ring = pcmRingRef.current;
        let w = pcmWriteRef.current;
        for (let i = 0; i < data.length; i++) {
          ring[w] = data[i];
          w = (w + 1) % BUFFER_MAX_SAMPLES;
        }
        pcmWriteRef.current = w;
        // Kai TTS groja – nustatome count į 0 kad getWindowWav grąžintų null
        if (!isTtsPlayingRef.current) {
          pcmCountRef.current = Math.min(pcmCountRef.current + data.length, BUFFER_MAX_SAMPLES);
        } else {
          pcmCountRef.current = 0; // reset – nesiuntinėjame TTS garso
        }
      };

      source.connect(processor);
      processor.connect(ctx.destination);
      return true;
    } catch (err) {
      console.error("[wake] AudioContext klaida:", err);
      setError("Mikrofonas neprieinamas. Patikrinkite leidimus sistemos nustatymuose.");
      return false;
    }
  }

  function stopAudio() {
    try { processorRef.current?.disconnect(); } catch { /* */ }
    try { sourceRef.current?.disconnect(); } catch { /* */ }
    try { audioCtxRef.current?.close(); } catch { /* */ }
    streamRef.current?.getTracks().forEach(t => t.stop());
    processorRef.current = null;
    sourceRef.current = null;
    audioCtxRef.current = null;
    streamRef.current = null;
    pcmCountRef.current = 0;
    pcmWriteRef.current = 0;
  }

  function getWindowWav(windowMs = WINDOW_MS): Blob | null {
    const sampleRate = audioCtxRef.current?.sampleRate ?? SAMPLE_RATE;
    const wantSamples = Math.floor(sampleRate * (windowMs / 1000));
    const available = Math.min(pcmCountRef.current, BUFFER_MAX_SAMPLES);
    if (available < sampleRate * 0.8) return null; // < 0.8s – per mažai

    const n = Math.min(wantSamples, available);
    const out = new Float32Array(n);
    const ring = pcmRingRef.current;
    const w = pcmWriteRef.current;
    for (let i = 0; i < n; i++) {
      out[i] = ring[(w - n + i + BUFFER_MAX_SAMPLES) % BUFFER_MAX_SAMPLES];
    }

    // RMS tylos filtras – tik garsas viršijantis kalbos lygį
    let sumSq = 0;
    for (let i = 0; i < n; i++) sumSq += out[i] * out[i];
    if (Math.sqrt(sumSq / n) < MIN_RMS) return null;

    return float32ToWav(out, sampleRate);
  }

  async function transcribeNow(windowMs = WINDOW_MS): Promise<string | null> {
    if (transcribingRef.current) return null;
    const wavBlob = getWindowWav(windowMs);
    if (!wavBlob) return null;

    transcribingRef.current = true;
    try {
      const result = await api.transcribeAudio(wavBlob, langRef.current);
      if (result.status === "success" && result.transcript?.trim()) {
        return result.transcript.trim();
      }
    } catch { /* tinklo klaida */ }
    finally { transcribingRef.current = false; }
    return null;
  }

  // ── Pagrindinis polling ciklas ────────────────────────────────────────────
  async function runLoop() {
    const ok = await startAudio();
    if (!ok) return;

    setStatus("idle");
    console.debug("[wake v4] pradėtas, poll=%dms, window=%dms, RMS>%.3f",
      POLL_MS, WINDOW_MS, MIN_RMS);

    while (activeRef.current) {
      await new Promise(r => setTimeout(r, POLL_MS));
      if (!activeRef.current) break;

      // Kol TTS groja – laukiame + cooldown'as po TTS
      if (isTtsPlayingRef.current) continue;
      // Po TTS pabaigos – papildomas cooldown (garso „uodega" bufferyje)
      if (Date.now() - ttsEndedAtRef.current < TTS_EXTRA_COOLDOWN_MS) continue;
      if (Date.now() - lastCommandAtRef.current < COOLDOWN_MS) continue;
      if (transcribingRef.current) continue;

      const wavBlob = getWindowWav(WINDOW_MS);
      if (!wavBlob) continue;

      transcribingRef.current = true;
      let text: string | null = null;
      try {
        const result = await api.transcribeAudio(wavBlob, langRef.current);
        if (result.status === "success" && result.transcript?.trim()) {
          text = result.transcript.trim();
        }
      } catch { /* */ }
      finally { transcribingRef.current = false; }

      if (!text || isHallucination(text)) continue;

      console.debug("[wake] poll →", JSON.stringify(text));

      if (!hasWakeWord(text)) continue;

      // Cooldown race condition apsauga
      if (Date.now() - lastCommandAtRef.current < COOLDOWN_MS) continue;

      let command = extractCommand(text);

      // Jei frazėje yra tik "Lani" be komandos – palaukiame vieno papildomo ciklo
      if (command.length < 2) {
        console.debug("[wake] Tik 'Lani' – laukiame papildomų", POLL_MS * 2, "ms...");
        await new Promise(r => setTimeout(r, POLL_MS * 2));
        if (!activeRef.current) break;
        if (Date.now() - lastCommandAtRef.current < COOLDOWN_MS) continue;

        // Bandome dar kartą su platesniu langu
        const text2 = await transcribeNow(EXTENDED_WINDOW_MS);
        if (text2 && !isHallucination(text2) && hasWakeWord(text2)) {
          command = extractCommand(text2);
          console.debug("[wake] papildomas poll →", JSON.stringify(text2));
        }
        if (command.length < 2) continue; // vis tiek be komandos
      }

      console.debug("[wake] ✓ KOMANDA:", JSON.stringify(command));
      lastCommandAtRef.current = Date.now();

      setStatus("processing");
      setLastTranscript(command);
      onWakeDetectedRef.current?.();

      try {
        await onCommandRef.current(command);
      } catch (e) {
        console.error("[wake] onCommand klaida:", e);
      }

      setStatus("idle");
    }

    stopAudio();
    setStatus("off");
    console.debug("[wake] sustojo");
  }

  const activate = () => {
    if (activeRef.current) return;
    activeRef.current = true;
    setIsActive(true);
    setError(null);
    void runLoop();
  };

  const deactivate = () => {
    activeRef.current = false;
    setIsActive(false);
    setStatus("off");
    stopAudio();
  };

  const stopRecordingAndSend = () => { /* suderinamumui */ };

  useEffect(() => {
    return () => { activeRef.current = false; stopAudio(); };
  }, []);

  return { status, isActive, lastTranscript, error, activate, deactivate, stopRecordingAndSend };
}
