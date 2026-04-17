/**
 * LaniOrb – Lani's animated holographic avatar.
 *
 * A pure CSS + Canvas orb that reacts to:
 *  - voiceState: idle | listening | speaking | thinking | error
 *  - audioLevel: 0..1 – live microphone or TTS amplitude (Web Audio API)
 *
 * No external 3D library required – runs on CSS animations + requestAnimationFrame.
 */

import React, { useEffect, useRef, useCallback } from "react";

export type OrbState = "idle" | "listening" | "speaking" | "thinking" | "error" | "locked";

interface LaniOrbProps {
  state?: OrbState;
  /** 0..1 amplitude from mic or TTS playback */
  audioLevel?: number;
  size?: number;
}

// ── Colour palette per state ──────────────────────────────────────────────────
const STATE_COLORS: Record<OrbState, { core: string; glow: string; ring: string }> = {
  idle:      { core: "#6c63ff", glow: "#6c63ff66", ring: "#6c63ff44" },
  listening: { core: "#00e5ff", glow: "#00e5ff88", ring: "#00e5ff55" },
  speaking:  { core: "#a78bfa", glow: "#a78bfaaa", ring: "#a78bfa66" },
  thinking:  { core: "#f59e0b", glow: "#f59e0b88", ring: "#f59e0b44" },
  error:     { core: "#ef4444", glow: "#ef444488", ring: "#ef444444" },
  locked:    { core: "#475569", glow: "#47556944", ring: "#47556922" },
};

const PARTICLE_COUNT = 48;
const TWO_PI = Math.PI * 2;

interface Particle {
  angle: number;
  radius: number;
  speed: number;
  size: number;
  opacity: number;
  layer: number; // 0=inner, 1=mid, 2=outer
}

function makeParticles(): Particle[] {
  return Array.from({ length: PARTICLE_COUNT }, (_, i) => ({
    angle: (i / PARTICLE_COUNT) * TWO_PI + Math.random() * 0.5,
    radius: 0.35 + Math.random() * 0.5,
    speed: (0.003 + Math.random() * 0.006) * (Math.random() > 0.5 ? 1 : -1),
    size: 1 + Math.random() * 2.5,
    opacity: 0.3 + Math.random() * 0.7,
    layer: i % 3,
  }));
}

export const LaniOrb: React.FC<LaniOrbProps> = ({
  state = "idle",
  audioLevel = 0,
  size = 220,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>(makeParticles());
  const frameRef = useRef<number>(0);
  const timeRef = useRef<number>(0);
  const stateRef = useRef<OrbState>(state);
  const levelRef = useRef<number>(audioLevel);

  // Keep refs in sync with props
  stateRef.current = state;
  levelRef.current = audioLevel;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const baseR = W * 0.28;

    const st = stateRef.current;
    const lv = levelRef.current;
    const colors = STATE_COLORS[st];
    const t = (timeRef.current += 0.016);

    // Clear
    ctx.clearRect(0, 0, W, H);

    // ── Outer ambient glow ──────────────────────────────────────────────
    const glowR = baseR * (1.6 + lv * 0.6);
    const ambientGrad = ctx.createRadialGradient(cx, cy, baseR * 0.4, cx, cy, glowR);
    ambientGrad.addColorStop(0, colors.ring.replace("44", "22"));
    ambientGrad.addColorStop(1, "transparent");
    ctx.fillStyle = ambientGrad;
    ctx.fillRect(0, 0, W, H);

    // ── Breathing pulse ring ────────────────────────────────────────────
    const pulse = st === "idle"
      ? Math.sin(t * 1.2) * 0.06
      : st === "speaking"
      ? Math.sin(t * 6) * 0.12 * (0.5 + lv)
      : st === "listening"
      ? Math.sin(t * 4) * 0.08 * (0.5 + lv * 0.8)
      : st === "thinking"
      ? Math.sin(t * 3) * 0.1
      : 0;

    const ringR = baseR * (1.28 + pulse + lv * 0.2);
    ctx.beginPath();
    ctx.arc(cx, cy, ringR, 0, TWO_PI);
    ctx.strokeStyle = colors.ring;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Second outer ring (dashed/rotating)
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * (st === "thinking" ? 1.5 : 0.4));
    ctx.setLineDash([6, 14]);
    ctx.beginPath();
    ctx.arc(0, 0, ringR * 1.18, 0, TWO_PI);
    ctx.strokeStyle = colors.ring.replace("44", "28");
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // ── Particles orbiting the sphere ────────────────────────────────────
    const particles = particlesRef.current;
    const speedMultiplier =
      st === "speaking" ? 2.5 + lv * 3 :
      st === "listening" ? 1.8 + lv * 2 :
      st === "thinking" ? 3.0 :
      1.0;

    for (const p of particles) {
      p.angle += p.speed * speedMultiplier;
      const layerR = baseR * (p.layer === 0 ? 0.82 : p.layer === 1 ? 1.05 : 1.22);
      const px = cx + Math.cos(p.angle) * layerR * (1 + lv * 0.15);
      const py = cy + Math.sin(p.angle) * layerR * (0.55 + lv * 0.1); // flatten Y for sphere illusion

      const depthFactor = (Math.cos(p.angle) + 1) / 2; // 0=back, 1=front
      const alpha = p.opacity * (0.25 + depthFactor * 0.75) * (st === "locked" ? 0.3 : 1);
      const ps = p.size * (0.5 + depthFactor * 0.8);

      ctx.beginPath();
      ctx.arc(px, py, ps, 0, TWO_PI);
      ctx.fillStyle = colors.core + Math.round(alpha * 255).toString(16).padStart(2, "0");
      ctx.fill();
    }

    // ── Core sphere ──────────────────────────────────────────────────────
    const coreR = baseR * (0.72 + pulse * 0.5 + lv * 0.15);
    const coreGrad = ctx.createRadialGradient(
      cx - coreR * 0.25, cy - coreR * 0.25, coreR * 0.05,
      cx, cy, coreR,
    );
    coreGrad.addColorStop(0, "#ffffff33");
    coreGrad.addColorStop(0.3, colors.core + "dd");
    coreGrad.addColorStop(0.75, colors.core + "88");
    coreGrad.addColorStop(1, colors.glow + "00");

    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, TWO_PI);
    ctx.fillStyle = coreGrad;
    ctx.fill();

    // ── Specular highlight ───────────────────────────────────────────────
    const hlGrad = ctx.createRadialGradient(
      cx - coreR * 0.3, cy - coreR * 0.35, 0,
      cx - coreR * 0.3, cy - coreR * 0.35, coreR * 0.55,
    );
    hlGrad.addColorStop(0, "rgba(255,255,255,0.35)");
    hlGrad.addColorStop(1, "transparent");
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, TWO_PI);
    ctx.fillStyle = hlGrad;
    ctx.fill();

    // ── Waveform ring when speaking/listening ────────────────────────────
    if (st === "speaking" || st === "listening") {
      const wavePoints = 64;
      ctx.beginPath();
      for (let i = 0; i <= wavePoints; i++) {
        const ang = (i / wavePoints) * TWO_PI - Math.PI / 2;
        const waveAmp = (st === "speaking" ? 0.08 : 0.05) * lv;
        const noise = Math.sin(ang * 6 + t * 8) * waveAmp
                    + Math.sin(ang * 11 - t * 5) * waveAmp * 0.5;
        const r = baseR * (1.0 + noise);
        const wx = cx + Math.cos(ang) * r;
        const wy = cy + Math.sin(ang) * r * 0.58;
        if (i === 0) ctx.moveTo(wx, wy);
        else ctx.lineTo(wx, wy);
      }
      ctx.closePath();
      ctx.strokeStyle = colors.core + "99";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // ── Thinking spinner ─────────────────────────────────────────────────
    if (st === "thinking") {
      for (let i = 0; i < 3; i++) {
        const spinAngle = t * (2 + i * 0.7) + (i * TWO_PI) / 3;
        const sx = cx + Math.cos(spinAngle) * baseR * 1.35;
        const sy = cy + Math.sin(spinAngle) * baseR * 0.75;
        ctx.beginPath();
        ctx.arc(sx, sy, 3.5, 0, TWO_PI);
        ctx.fillStyle = colors.core + "cc";
        ctx.fill();
      }
    }

    frameRef.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    frameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameRef.current);
  }, [draw]);

  // ── State label ───────────────────────────────────────────────────────────
  const labels: Record<OrbState, string> = {
    idle:      "STANDBY",
    listening: "LISTENING",
    speaking:  "SPEAKING",
    thinking:  "PROCESSING",
    error:     "ERROR",
    locked:    "LOCKED",
  };

  const colors = STATE_COLORS[state];

  return (
    <div
      className="lani-orb"
      style={{
        width: size,
        height: size + 36,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        userSelect: "none",
      }}
    >
      {/* Glow backdrop */}
      <div
        style={{
          position: "absolute",
          width: size * 0.7,
          height: size * 0.7,
          borderRadius: "50%",
          background: colors.glow,
          filter: "blur(32px)",
          opacity: 0.45 + audioLevel * 0.4,
          pointerEvents: "none",
          marginTop: size * 0.15,
          transition: "opacity 0.2s, background 0.4s",
        }}
      />

      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        style={{ position: "relative", zIndex: 1 }}
      />

      {/* State label */}
      <div
        style={{
          fontFamily: "'JetBrains Mono', 'Courier New', monospace",
          fontSize: "10px",
          fontWeight: 700,
          letterSpacing: "0.22em",
          color: colors.core,
          opacity: 0.85,
          textShadow: `0 0 8px ${colors.glow}`,
          marginTop: "-4px",
          position: "relative",
          zIndex: 2,
        }}
      >
        {labels[state]}
      </div>

      {/* Scan line decoration */}
      <div
        style={{
          marginTop: "6px",
          width: size * 0.45,
          height: 1,
          background: `linear-gradient(90deg, transparent, ${colors.core}88, transparent)`,
        }}
      />
    </div>
  );
};
