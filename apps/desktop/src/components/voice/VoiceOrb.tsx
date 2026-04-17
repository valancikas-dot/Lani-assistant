/**
 * VoiceOrb – Canvas-based animated orb that visualises the current voice state.
 *
 * Props
 * ─────
 *  volume   – normalised RMS volume, 0–1 (from useVolumeAnalyser)
 *  state    – current voice/STT state string, drives colour and animation
 *  size     – canvas side length in px (default 220)
 */

import React, { useRef, useEffect } from "react";
import type { WakeVoiceState, VoiceState, SttRecordingState } from "../../lib/types";

export type OrbState = WakeVoiceState | VoiceState | SttRecordingState | "blocked";

// Colour palette per state group
const STATE_PALETTE: Record<string, [string, string]> = {
  // Active / listening
  listening:  ["#00d4ff", "#6c63ff"],
  recording:  ["#00d4ff", "#10b981"],
  // Busy
  processing:    ["#f59e0b", "#6c63ff"],
  transcribing:  ["#f59e0b", "#6c63ff"],
  uploading:     ["#3b82f6", "#6c63ff"],
  // Speaking / responding
  speaking:   ["#a78bfa", "#6c63ff"],
  responding: ["#a78bfa", "#6c63ff"],
  // Special
  verifying:  ["#8b5cf6", "#6c63ff"],
  wake_detected: ["#10b981", "#6c63ff"],
  waiting_for_confirmation: ["#f59e0b", "#ef4444"],
  blocked:    ["#ef4444", "#7f1d1d"],
  // Default / idle
  idle:       ["#6c63ff", "#4c1d95"],
};

function getPalette(state: string): [string, string] {
  return STATE_PALETTE[state] ?? STATE_PALETTE.idle;
}

interface VoiceOrbProps {
  volume?: number;
  state?: OrbState;
  size?: number;
}

export const VoiceOrb: React.FC<VoiceOrbProps> = ({
  volume = 0,
  state = "idle",
  size = 220,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    let animationId: number;
    let t = 0;

    const [colorInner, colorOuter] = getPalette(state as string);

    const render = () => {
      t += 0.03;
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const baseRadius = size * 0.28; // ~30% of canvas width
      const pulse = Math.sin(t * 2) * (size * 0.025);
      const audioBoost = volume * (size * 0.16);
      const radius = baseRadius + pulse + audioBoost;

      // Core radial gradient
      const gradient = ctx.createRadialGradient(cx, cy, radius * 0.3, cx, cy, radius);
      gradient.addColorStop(0, colorInner);
      gradient.addColorStop(0.5, colorOuter);
      gradient.addColorStop(1, colorOuter + "1a"); // ~10% opacity tail

      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = gradient;
      ctx.fill();

      // Outer glow ring
      ctx.beginPath();
      ctx.arc(cx, cy, radius + size * 0.045, 0, Math.PI * 2);
      ctx.strokeStyle = colorInner + "4d"; // ~30% opacity
      ctx.lineWidth = size * 0.018;
      ctx.stroke();

      // Waveform ring – 64 sample points
      const points = 64;
      const waveRadius = radius + size * 0.09;
      ctx.beginPath();
      for (let i = 0; i < points; i++) {
        const angle = (i / points) * Math.PI * 2;
        const waveAmp = size * 0.04 + volume * (size * 0.16);
        const wave = Math.sin(angle * 6 + t * 3) * waveAmp;
        const r = waveRadius + wave;
        const x = cx + Math.cos(angle) * r;
        const y = cy + Math.sin(angle) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = colorInner + "cc"; // ~80% opacity
      ctx.lineWidth = size * 0.009;
      ctx.stroke();

      animationId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [volume, state, size]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ display: "block", margin: "0 auto" }}
      aria-hidden
    />
  );
};

