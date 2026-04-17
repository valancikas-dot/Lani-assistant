/**
 * LaniCore v1 — Luminous Sphere with Ethereal Feminine Presence
 *
 * Visual architecture (bottom → top):
 *   1. Ambient glow backdrop  — blurred radial <div>, state-coloured
 *   2. Canvas sphere          — rings, orbiting particles, core gradient,
 *                               specular highlight, face-center light source
 *   3. SVG face overlay       — iris glow, eye almonds, nose hint, lips
 *                               Everything is blurred + low opacity.
 *                               Face contours emerge from light, never hard-edged.
 *   4. Think-sweep bands      — two SVG gradient bands that drift across the face
 *                               during the "thinking" state via <animateTransform>
 *   5. Scan-line decoration   — single-pixel HUD sweep
 *   6. State label
 *
 * DESIGN RULES enforced in code:
 *   – No hard edges on face features (all use feGaussianBlur filter)
 *   – Face opacity is 0.08–0.15 at idle; rises gracefully per-state
 *   – Lips animate shape (lower lip drops) only with live audioLevel > 0
 *   – Colour palette: violet → blue sphere, warm rose/gold lips, cyan/silver eyes
 *   – State transitions driven by CSS `transition: opacity` — never abrupt
 */

import React, { useEffect, useRef, useCallback } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type CoreState = "idle" | "listening" | "speaking" | "thinking" | "error" | "locked";

export interface LaniCoreProps {
  state?: CoreState;
  /** 0..1 amplitude from mic or TTS playback */
  audioLevel?: number;
  size?: number;
}

// ─── Colour palettes ──────────────────────────────────────────────────────────

const PAL: Record<CoreState, { core: string; glow: string; ring: string; accent: string; iris: string }> = {
  idle:      { core: "#7c6fff", glow: "#7c6fff55", ring: "#7c6fff38", accent: "#b8a5ff", iris: "#9c8fff" },
  listening: { core: "#38bdf8", glow: "#38bdf866", ring: "#38bdf840", accent: "#7dd3fc", iris: "#38d8ff" },
  speaking:  { core: "#a78bfa", glow: "#a78bfa99", ring: "#a78bfa55", accent: "#c4b5fd", iris: "#c4b5fd" },
  thinking:  { core: "#818cf8", glow: "#818cf877", ring: "#818cf844", accent: "#c7d2fe", iris: "#a5b4fc" },
  error:     { core: "#ef4444", glow: "#ef444455", ring: "#ef444438", accent: "#fca5a5", iris: "#f87171" },
  locked:    { core: "#475569", glow: "#47556930", ring: "#47556920", accent: "#94a3b8", iris: "#64748b" },
};

// Face feature opacity per state — deliberately understated at idle
const FOPT: Record<CoreState, { eyes: number; nose: number; lips: number; iris: number }> = {
  idle:      { eyes: 0.11, nose: 0.04, lips: 0.09,  iris: 0.16 },
  listening: { eyes: 0.44, nose: 0.13, lips: 0.24,  iris: 0.58 },
  speaking:  { eyes: 0.36, nose: 0.11, lips: 0.40,  iris: 0.50 },
  thinking:  { eyes: 0.30, nose: 0.09, lips: 0.18,  iris: 0.40 },
  error:     { eyes: 0.22, nose: 0.07, lips: 0.14,  iris: 0.28 },
  locked:    { eyes: 0.05, nose: 0.02, lips: 0.04,  iris: 0.07 },
};

const STATE_LABELS: Record<CoreState, string> = {
  idle:      "STANDBY",
  listening: "LISTENING",
  speaking:  "SPEAKING",
  thinking:  "PROCESSING",
  error:     "ERROR",
  locked:    "LOCKED",
};

// ─── Canvas particles ─────────────────────────────────────────────────────────

const TWO_PI = Math.PI * 2;
const PARTICLE_COUNT = 54;

interface Particle {
  angle: number;
  speed: number;
  size: number;
  opacity: number;
  layer: number; // 0=inner 1=mid 2=outer
}

function makeParticles(): Particle[] {
  return Array.from({ length: PARTICLE_COUNT }, (_, i) => ({
    angle:   (i / PARTICLE_COUNT) * TWO_PI + Math.random() * 0.6,
    speed:   (0.0025 + Math.random() * 0.0055) * (Math.random() > 0.5 ? 1 : -1),
    size:    0.8 + Math.random() * 2.4,
    opacity: 0.22 + Math.random() * 0.68,
    layer:   i % 3,
  }));
}

// ─── Component ────────────────────────────────────────────────────────────────

export const LaniCore: React.FC<LaniCoreProps> = ({
  state      = "idle",
  audioLevel = 0,
  size       = 220,
}) => {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>(makeParticles());
  const frameRef     = useRef<number>(0);
  const timeRef      = useRef<number>(0);
  const stateRef     = useRef<CoreState>(state);
  const levelRef     = useRef<number>(audioLevel);
  const lowerLipRef  = useRef<SVGPathElement | null>(null);

  // Keep hot refs in sync — no re-render needed for animation
  stateRef.current = state;
  levelRef.current = audioLevel;

  // ── Canvas animation loop ─────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const baseR = W * 0.282;

    const st  = stateRef.current;
    const lv  = levelRef.current;
    const pal = PAL[st];
    const t   = (timeRef.current += 0.016);

    ctx.clearRect(0, 0, W, H);

    // ── 1. Outer ambient haze ──────────────────────────────────────────
    const hazeR = baseR * (1.75 + lv * 0.45);
    const haze  = ctx.createRadialGradient(cx, cy, baseR * 0.25, cx, cy, hazeR);
    haze.addColorStop(0, pal.core + "14");
    haze.addColorStop(1, "transparent");
    ctx.fillStyle = haze;
    ctx.fillRect(0, 0, W, H);

    // ── 2. Breathing pulse calculation ────────────────────────────────
    const breathPulse =
      st === "idle"      ? Math.sin(t * 1.12) * 0.055 :
      st === "speaking"  ? Math.sin(t * 5.8)  * 0.10 * (0.5 + lv) :
      st === "listening" ? Math.sin(t * 3.6)  * 0.072 * (0.55 + lv * 0.85) :
      st === "thinking"  ? Math.sin(t * 2.6)  * 0.085 : 0;

    // ── 3. Outer halo ring ─────────────────────────────────────────────
    const ringR = baseR * (1.30 + breathPulse + lv * 0.17);
    ctx.beginPath();
    ctx.arc(cx, cy, ringR, 0, TWO_PI);
    ctx.strokeStyle = pal.ring;
    ctx.lineWidth = 1.0;
    ctx.stroke();

    // Dashed outer ring — slow rotation, faster when thinking
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * (st === "thinking" ? 1.55 : 0.32));
    ctx.setLineDash([4, 15]);
    ctx.beginPath();
    ctx.arc(0, 0, ringR * 1.17, 0, TWO_PI);
    ctx.strokeStyle = pal.ring.slice(0, 7) + "20";
    ctx.lineWidth = 0.75;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    // ── 4. Orbiting particles ──────────────────────────────────────────
    const speedMul =
      st === "speaking"  ? 2.3 + lv * 2.8 :
      st === "listening" ? 1.65 + lv * 1.9 :
      st === "thinking"  ? 2.7 : 1.0;

    for (const p of particlesRef.current) {
      p.angle += p.speed * speedMul;
      const lr    = baseR * (p.layer === 0 ? 0.81 : p.layer === 1 ? 1.03 : 1.20);
      const px    = cx + Math.cos(p.angle) * lr * (1 + lv * 0.13);
      const py    = cy + Math.sin(p.angle) * lr * (0.56 + lv * 0.09); // flatten Y → sphere illusion
      const depth = (Math.cos(p.angle) + 1) / 2; // 0=back 1=front
      const alpha = p.opacity * (0.20 + depth * 0.80) * (st === "locked" ? 0.28 : 1);
      const ps    = p.size * (0.42 + depth * 0.88);

      ctx.beginPath();
      ctx.arc(px, py, ps, 0, TWO_PI);
      ctx.fillStyle = pal.core + Math.round(alpha * 255).toString(16).padStart(2, "0");
      ctx.fill();
    }

    // ── 5. Core sphere ─────────────────────────────────────────────────
    const coreR = baseR * (0.74 + breathPulse * 0.38 + lv * 0.13);

    // Deep violet-to-blue volumetric gradient
    const coreGrad = ctx.createRadialGradient(
      cx - coreR * 0.20, cy - coreR * 0.20, coreR * 0.03,
      cx, cy, coreR,
    );
    coreGrad.addColorStop(0.00, "#ffffff22");
    coreGrad.addColorStop(0.25, pal.core + "ee");
    coreGrad.addColorStop(0.65, pal.core + "88");
    coreGrad.addColorStop(1.00, pal.glow  + "00");
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, TWO_PI);
    ctx.fillStyle = coreGrad;
    ctx.fill();

    // ── 6. Specular highlight — upper-left lens flare ─────────────────
    const hl = ctx.createRadialGradient(
      cx - coreR * 0.28, cy - coreR * 0.30, 0,
      cx - coreR * 0.28, cy - coreR * 0.30, coreR * 0.50,
    );
    hl.addColorStop(0, "rgba(255,255,255,0.28)");
    hl.addColorStop(1, "transparent");
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, TWO_PI);
    ctx.fillStyle = hl;
    ctx.fill();

    // ── 7. Face-centre light source ───────────────────────────────────
    // Soft luminous patch at face-centre — makes the sphere feel inhabited.
    // Opacity scales with face visibility: barely present at idle.
    const faceAlpha = FOPT[st].iris * 0.55 + lv * 0.08;
    const faceLight = ctx.createRadialGradient(
      cx, cy - coreR * 0.04, 0,
      cx, cy - coreR * 0.04, coreR * 0.78,
    );
    faceLight.addColorStop(0, pal.accent + Math.round(Math.min(faceAlpha, 1) * 220).toString(16).padStart(2, "0"));
    faceLight.addColorStop(1, "transparent");
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, TWO_PI);
    ctx.fillStyle = faceLight;
    ctx.fill();

    // ── 8. Waveform ring when speaking / listening ─────────────────────
    if ((st === "speaking" || st === "listening") && lv > 0.015) {
      const wpts = 60;
      ctx.beginPath();
      for (let i = 0; i <= wpts; i++) {
        const ang  = (i / wpts) * TWO_PI - Math.PI / 2;
        const wamp = (st === "speaking" ? 0.085 : 0.048) * lv;
        const n    = Math.sin(ang * 7 + t * 9.5) * wamp + Math.sin(ang * 13 - t * 5.5) * wamp * 0.45;
        const r    = baseR * (1.0 + n);
        const wx   = cx + Math.cos(ang) * r;
        const wy   = cy + Math.sin(ang) * r * 0.60;
        if (i === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy);
      }
      ctx.closePath();
      ctx.strokeStyle = pal.core + "77";
      ctx.lineWidth   = 1.1;
      ctx.stroke();
    }

    // ── 9. Thinking orbit dots ─────────────────────────────────────────
    if (st === "thinking") {
      for (let i = 0; i < 3; i++) {
        const sa = t * (2.1 + i * 0.65) + (i * TWO_PI) / 3;
        const sx = cx + Math.cos(sa) * baseR * 1.33;
        const sy = cy + Math.sin(sa) * baseR * 0.73;
        ctx.beginPath();
        ctx.arc(sx, sy, 3.0, 0, TWO_PI);
        ctx.fillStyle = pal.core + "cc";
        ctx.fill();
      }
    }

    // ── 10. Update lower lip via direct DOM — driven by audioLevel ────
    if (lowerLipRef.current) {
      if (st === "speaking" && lv > 0.02) {
        const drop   = Math.min(lv * 0.7, 0.7); // max 0.7 SVG units
        const baseY  = 59.5;
        const dropY  = baseY + drop * 5.5;
        const ctrlY  = baseY + 3.2 + drop * 5.5;
        lowerLipRef.current.setAttribute(
          "d",
          `M 43,${baseY.toFixed(1)} C 45,${ctrlY.toFixed(1)} 55,${ctrlY.toFixed(1)} 57,${baseY.toFixed(1)}`,
        );
      } else {
        lowerLipRef.current.setAttribute("d", "M 43,59.5 C 45,63.2 55,63.2 57,59.5");
      }
    }

    frameRef.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    frameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameRef.current);
  }, [draw]);

  // ── Derived render values ─────────────────────────────────────────────────
  const pal   = PAL[state];
  const fopt  = FOPT[state];
  const isThinking = state === "thinking";

  // Transition timing — face features crossfade over 0.9s
  const faceTrans = "opacity 0.9s ease";

  return (
    <div
      style={{
        position:      "relative",
        width:         size,
        height:        size + 38,
        display:       "flex",
        flexDirection: "column",
        alignItems:    "center",
        userSelect:    "none",
      }}
    >
      {/* ── Layer 1: Ambient glow backdrop ─────────────────────────────── */}
      <div
        style={{
          position:     "absolute",
          width:        size * 0.74,
          height:       size * 0.74,
          borderRadius: "50%",
          background:   pal.glow,
          filter:       "blur(38px)",
          opacity:      0.38 + audioLevel * 0.48,
          pointerEvents:"none",
          top:          size * 0.13,
          left:         "50%",
          transform:    "translateX(-50%)",
          transition:   "opacity 0.22s, background 0.5s",
        }}
      />

      {/* ── Layer 2: Canvas sphere ──────────────────────────────────────── */}
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        style={{ position: "relative", zIndex: 1 }}
      />

      {/* ── Layer 3: SVG face overlay ───────────────────────────────────── */}
      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        style={{
          position:     "absolute",
          top:          0,
          left:         "50%",
          transform:    "translateX(-50%)",
          zIndex:       2,
          pointerEvents:"none",
          overflow:     "visible",
        }}
      >
        <defs>
          {/* ── Iris radial glow — left ─────────────────────────── */}
          <radialGradient id="lc-iris-l" cx="50%" cy="45%" r="55%">
            <stop offset="0%"   stopColor={pal.iris} stopOpacity="1.0" />
            <stop offset="55%"  stopColor={pal.iris} stopOpacity="0.45" />
            <stop offset="100%" stopColor={pal.iris} stopOpacity="0" />
          </radialGradient>

          {/* ── Iris radial glow — right ────────────────────────── */}
          <radialGradient id="lc-iris-r" cx="50%" cy="45%" r="55%">
            <stop offset="0%"   stopColor={pal.iris} stopOpacity="1.0" />
            <stop offset="55%"  stopColor={pal.iris} stopOpacity="0.45" />
            <stop offset="100%" stopColor={pal.iris} stopOpacity="0" />
          </radialGradient>

          {/* ── Lip warm gradient ───────────────────────────────── */}
          <linearGradient id="lc-lip-grad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#e8c0dd" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#d4b48a" stopOpacity="0.80" />
          </linearGradient>

          {/* ── Thinking sweep gradient band ────────────────────── */}
          <linearGradient id="lc-sweep-a" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor={pal.accent} stopOpacity="0" />
            <stop offset="35%"  stopColor={pal.accent} stopOpacity="0.55" />
            <stop offset="65%"  stopColor={pal.accent} stopOpacity="0.55" />
            <stop offset="100%" stopColor={pal.accent} stopOpacity="0" />
          </linearGradient>
          <linearGradient id="lc-sweep-b" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#c7d2fe"    stopOpacity="0" />
            <stop offset="40%"  stopColor="#c7d2fe"    stopOpacity="0.35" />
            <stop offset="60%"  stopColor="#c7d2fe"    stopOpacity="0.35" />
            <stop offset="100%" stopColor="#c7d2fe"    stopOpacity="0" />
          </linearGradient>

          {/* ── Clip to sphere circle so sweeps stay inside ─────── */}
          <clipPath id="lc-sphere-clip">
            <circle cx="50" cy="50" r="30" />
          </clipPath>

          {/* ── Soft blur for face lines ─────────────────────────── */}
          <filter id="lc-soft" x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="0.75" />
          </filter>

          {/* ── Softer blur for iris glow ────────────────────────── */}
          <filter id="lc-iris-blur" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.4" />
          </filter>

          {/* ── Very soft blur for think sweeps ─────────────────── */}
          <filter id="lc-sweep-blur" x="-10%" y="-30%" width="120%" height="160%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.8" />
          </filter>
        </defs>

        {/* ═══════════════════════════════════════════════════════════════
            IRIS GLOW CIRCLES — sit behind eye paths, provide luminosity
        ════════════════════════════════════════════════════════════════ */}
        <circle
          cx="36" cy="43" r="5.8"
          fill="url(#lc-iris-l)"
          filter="url(#lc-iris-blur)"
          style={{ opacity: fopt.iris, transition: faceTrans }}
        />
        <circle
          cx="64" cy="43" r="5.8"
          fill="url(#lc-iris-r)"
          filter="url(#lc-iris-blur)"
          style={{ opacity: fopt.iris, transition: faceTrans }}
        />

        {/* ═══════════════════════════════════════════════════════════════
            EYE ALMOND SHAPES — thin stroke paths, feGaussianBlur blurred
            Deliberately asymmetric-free: perfect bilateral symmetry.
            No thick lines, no lash detail, no brows — just the outline
            of closed-almond eyes made of light.
        ════════════════════════════════════════════════════════════════ */}
        <g filter="url(#lc-soft)" style={{ opacity: fopt.eyes, transition: faceTrans }}>
          {/* Left eye almond */}
          <path
            d="M 30,43 C 32,39.5 35,38 36,38 C 37,38 40,39.5 42,43
               C 40,46.5 37,48 36,48 C 35,48 32,46.5 30,43 Z"
            fill="none"
            stroke={pal.accent}
            strokeWidth="0.65"
            strokeOpacity="0.88"
          />
          {/* Left pupil — soft dot */}
          <circle cx="36" cy="43" r="1.15" fill={pal.accent} fillOpacity="0.72" />
          {/* Left catchlight spark */}
          <circle cx="34.6" cy="41.6" r="0.50" fill="white" fillOpacity="0.92" />

          {/* Right eye almond */}
          <path
            d="M 58,43 C 60,39.5 63,38 64,38 C 65,38 68,39.5 70,43
               C 68,46.5 65,48 64,48 C 63,48 60,46.5 58,43 Z"
            fill="none"
            stroke={pal.accent}
            strokeWidth="0.65"
            strokeOpacity="0.88"
          />
          {/* Right pupil */}
          <circle cx="64" cy="43" r="1.15" fill={pal.accent} fillOpacity="0.72" />
          {/* Right catchlight spark */}
          <circle cx="62.6" cy="41.6" r="0.50" fill="white" fillOpacity="0.92" />
        </g>

        {/* ═══════════════════════════════════════════════════════════════
            NOSE BRIDGE — nearly invisible at all times.
            Just enough to imply the central axis of a face.
        ════════════════════════════════════════════════════════════════ */}
        <g filter="url(#lc-soft)" style={{ opacity: fopt.nose, transition: faceTrans }}>
          {/* Bridge line */}
          <line
            x1="50" y1="47.5" x2="50" y2="53.8"
            stroke="#8899bb"
            strokeWidth="0.45"
            strokeLinecap="round"
            strokeOpacity="0.9"
          />
          {/* Subtle nostril wing hint */}
          <path
            d="M 46.5,54 C 47.5,52.8 49.2,53.3 50,54 C 50.8,53.3 52.5,52.8 53.5,54"
            fill="none"
            stroke="#8899bb"
            strokeWidth="0.45"
            strokeLinecap="round"
            strokeOpacity="0.9"
          />
        </g>

        {/* ═══════════════════════════════════════════════════════════════
            LIPS — cupid's bow upper + rounded lower arc.
            Lower lip ref is updated imperatively in canvas loop for jaw.
            Lip fill uses warm rose-to-gold gradient at very low opacity.
        ════════════════════════════════════════════════════════════════ */}
        <g filter="url(#lc-soft)" style={{ opacity: fopt.lips, transition: "opacity 0.6s ease" }}>
          {/* Subtle inner fill — warmth, barely visible */}
          <path
            d="M 43,59.5 C 45,56.5 47.5,55.8 50,56.2
               C 52.5,55.8 55,56.5 57,59.5
               C 55,63.2 45,63.2 43,59.5 Z"
            fill="url(#lc-lip-grad)"
            fillOpacity="0.14"
          />
          {/* Upper lip — cupid's bow shape */}
          <path
            d="M 43,59.5 C 45,56.5 47.5,55.8 50,56.2 C 52.5,55.8 55,56.5 57,59.5"
            fill="none"
            stroke="url(#lc-lip-grad)"
            strokeWidth="0.85"
            strokeLinecap="round"
          />
          {/* Lower lip — updated by canvas loop ref to animate speaking */}
          <path
            ref={lowerLipRef}
            d="M 43,59.5 C 45,63.2 55,63.2 57,59.5"
            fill="none"
            stroke="url(#lc-lip-grad)"
            strokeWidth="0.85"
            strokeLinecap="round"
          />
        </g>

        {/* ═══════════════════════════════════════════════════════════════
            THINKING LIGHT SWEEPS — two gradient bands that drift across
            the face area during the "thinking" state.
            Clipped to sphere so they fade naturally at the orb edge.
        ════════════════════════════════════════════════════════════════ */}
        {isThinking && (
          <g clipPath="url(#lc-sphere-clip)" filter="url(#lc-sweep-blur)" opacity="0.20">
            {/* Sweep A — slightly diagonal, 2.4s period */}
            <rect x="-25" y="30" width="22" height="42" fill="url(#lc-sweep-a)">
              <animateTransform
                attributeName="transform"
                type="translate"
                from="-25 2"
                to="130 -4"
                dur="2.4s"
                repeatCount="indefinite"
              />
            </rect>
            {/* Sweep B — opposite tilt, 3.1s period, delayed */}
            <rect x="-25" y="24" width="14" height="55" fill="url(#lc-sweep-b)">
              <animateTransform
                attributeName="transform"
                type="translate"
                from="-25 -3"
                to="130 5"
                dur="3.1s"
                begin="1.0s"
                repeatCount="indefinite"
              />
            </rect>
          </g>
        )}
      </svg>

      {/* ── Layer 4: Scan line ────────────────────────────────────────────── */}
      <div
        style={{
          position:     "absolute",
          top:          0,
          left:         "50%",
          transform:    "translateX(-50%)",
          width:        size,
          height:       1.5,
          zIndex:       3,
          pointerEvents:"none",
          background:   `linear-gradient(90deg, transparent, ${pal.accent}38, transparent)`,
          animation:    `lc-scan ${isThinking ? "2.2s" : "5.5s"} linear infinite`,
        }}
      />
      <style>{`@keyframes lc-scan { from { top: 0px } to { top: ${size}px } }`}</style>

      {/* ── Layer 5: State label ──────────────────────────────────────────── */}
      <div
        style={{
          fontFamily:  "'JetBrains Mono', 'Courier New', monospace",
          fontSize:    "9px",
          fontWeight:  700,
          letterSpacing: "0.24em",
          color:       pal.accent,
          opacity:     0.78,
          textShadow:  `0 0 9px ${pal.glow}`,
          marginTop:   "3px",
          position:    "relative",
          zIndex:      4,
          transition:  "color 0.5s",
        }}
      >
        {STATE_LABELS[state]}
      </div>

      {/* HUD rule below label */}
      <div
        style={{
          marginTop:  "5px",
          width:      size * 0.44,
          height:     1,
          background: `linear-gradient(90deg, transparent, ${pal.accent}55, transparent)`,
        }}
      />
    </div>
  );
};

export default LaniCore;
