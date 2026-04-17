/**
 * useVolumeAnalyser – returns a normalised RMS volume (0–1) for a MediaStream.
 *
 * Attaches a Web Audio AnalyserNode to the given stream and drives a
 * requestAnimationFrame loop that samples the FFT byte array and computes
 * the root-mean-square amplitude. Returns 0 whenever the stream is null
 * (session not recording).
 *
 * Usage
 * ─────
 *  const volume = useVolumeAnalyser(activeStream, true);
 *  // pass `volume` to <VoiceOrb volume={volume} />
 */

import { useEffect, useRef, useState } from "react";

export function useVolumeAnalyser(stream: MediaStream | null, enabled = true): number {
  const [volume, setVolume] = useState(0);

  // Hold refs so we can clean up correctly even if the effect re-runs
  const contextRef = useRef<AudioContext | null>(null);
  const sourceRef  = useRef<MediaStreamAudioSourceNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef     = useRef<number | null>(null);
  const dataRef    = useRef<Uint8Array<ArrayBuffer> | null>(null);

  useEffect(() => {
    if (!enabled || !stream) {
      // Clean up and reset to 0 when stream disappears
      cleanup();
      setVolume(0);
      return;
    }

    // Lazily create (or reuse) an AudioContext
    const AudioContextCtor =
      window.AudioContext ?? (window as any).webkitAudioContext as typeof AudioContext | undefined;
    if (!AudioContextCtor) return;

    const ctx = new AudioContextCtor();
    contextRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;

    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.8;
    analyserRef.current = analyser;
    source.connect(analyser);

    const bufferLength = analyser.frequencyBinCount; // 128
    const data = new Uint8Array(new ArrayBuffer(bufferLength));
    dataRef.current = data;

    const tick = () => {
      if (!analyserRef.current || !dataRef.current) return;
      analyserRef.current.getByteFrequencyData(dataRef.current);

      // RMS of the frequency magnitudes (each byte is 0-255)
      let sum = 0;
      for (let i = 0; i < dataRef.current.length; i++) {
        const v = dataRef.current[i] / 255;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / dataRef.current.length);

      setVolume(Math.min(rms * 2.5, 1)); // scale up slightly so subtle speech registers
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return cleanup;

    function cleanup() {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      sourceRef.current?.disconnect();
      sourceRef.current = null;
      analyserRef.current?.disconnect();
      analyserRef.current = null;
      dataRef.current = null;
      // close() is async; ignore the promise – just fire and forget
      void contextRef.current?.close();
      contextRef.current = null;
    }
  }, [stream, enabled]);

  return volume;
}
