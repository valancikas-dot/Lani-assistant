/**
 * useAudioLevel – streams real-time microphone amplitude (0..1) via Web Audio API.
 *
 * Returns 0 when the mic is not active or permission is denied.
 * Call with `active = true` only while the user is in a voice session.
 */
import { useEffect, useRef, useState } from "react";

export function useAudioLevel(active: boolean): number {
  const [level, setLevel] = useState(0);
  const rafRef  = useRef<number>(0);
  const ctxRef  = useRef<AudioContext | null>(null);
  const srcRef  = useRef<MediaStreamAudioSourceNode | null>(null);
  const anaRef  = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!active) {
      setLevel(0);
      return;
    }

    let cancelled = false;

    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }

        streamRef.current = stream;

        const ctx = new AudioContext();
        ctxRef.current = ctx;

        const src = ctx.createMediaStreamSource(stream);
        srcRef.current = src;

        const ana = ctx.createAnalyser();
        ana.fftSize = 256;
        ana.smoothingTimeConstant = 0.8;
        anaRef.current = ana;

        src.connect(ana);

        const buf = new Uint8Array(ana.frequencyBinCount);

        function tick() {
          if (cancelled) return;
          ana.getByteTimeDomainData(buf);

          // RMS amplitude
          let sumSq = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sumSq += v * v;
          }
          const rms = Math.sqrt(sumSq / buf.length);
          // Scale 0..0.5 → 0..1, clamp
          setLevel(Math.min(1, rms * 2));

          rafRef.current = requestAnimationFrame(tick);
        }
        tick();
      } catch {
        // Mic permission denied or unavailable — stay at 0
      }
    }

    start();

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);

      srcRef.current?.disconnect();
      ctxRef.current?.close();
      streamRef.current?.getTracks().forEach((t) => t.stop());

      srcRef.current  = null;
      ctxRef.current  = null;
      anaRef.current  = null;
      streamRef.current = null;

      setLevel(0);
    };
  }, [active]);

  return level;
}
