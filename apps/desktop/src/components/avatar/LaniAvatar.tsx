/**
 * LaniAvatar v7 — Holographic Particle Face
 *
 * 120 000 glowing particles sampled from a dense feminine face point-cloud.
 * Each particle position is driven by a custom GLSL vertex shader with:
 *   – idle breathing drift
 *   – speaking jaw morph (audioLevel)
 *   – thinking swirl
 *   – blink / eye-close
 *
 * No separate meshes. No ugly geometries. Pure particle system.
 *
 * Technique:
 *   1. Generate a dense set of 3D face landmark positions analytically
 *      (forehead, eyes, nose, lips, jaw, cheeks, neck) into a Float32Array.
 *   2. Upload as THREE.BufferGeometry + THREE.Points.
 *   3. Drive every vertex in the vertex shader via uniforms.
 *   4. Use THREE.AdditiveBlending + small sprite size for glow.
 */
import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import type { OrbState } from "./LaniOrb";

interface Props { state?: OrbState; audioLevel?: number; size?: number }

// ─── Colour palette per state ────────────────────────────────────────────────
const PAL: Record<OrbState, { r: number; g: number; b: number; label: string }> = {
  idle:      { r: 0.48, g: 0.44, b: 1.00, label: "STANDBY"  },
  listening: { r: 0.00, g: 0.90, b: 1.00, label: "LISTENING" },
  speaking:  { r: 0.75, g: 0.09, b: 0.82, label: "SPEAKING"  },
  thinking:  { r: 0.98, g: 0.62, b: 0.00, label: "THINKING"  },
  error:     { r: 0.94, g: 0.27, b: 0.27, label: "ERROR"     },
  locked:    { r: 0.20, g: 0.25, b: 0.32, label: "LOCKED"    },
};

// ─── Face point-cloud generator ──────────────────────────────────────────────
//
// We sample points on a set of analytically-defined surface patches
// (ellipsoids, bezier patches, parametric curves) that together form a
// feminine face. Every region returns {x,y,z} in a [-1,1] cube.

const rng = (() => {
  let seed = 42;
  return () => { seed = (seed * 1664525 + 1013904223) & 0xffffffff; return (seed >>> 0) / 0xffffffff; };
})();

function gaussian() {
  // Box-Muller
  const u = rng() + 1e-10, v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Sample a point on the surface of an axis-aligned ellipsoid */
function ellipsoidSurface(cx:number,cy:number,cz:number, rx:number,ry:number,rz:number, noise=0.0): [number,number,number] {
  // uniform sphere → scale
  const u = rng()*2-1, v = rng()*2-1, w = rng()*2-1;
  const len = Math.sqrt(u*u+v*v+w*w)+1e-9;
  const x = cx + (u/len)*rx + gaussian()*noise;
  const y = cy + (v/len)*ry + gaussian()*noise;
  const z = cz + (w/len)*rz + gaussian()*noise;
  return [x,y,z];
}

/** Sample inside a thin disc (for eyebrow / lip curves) */
function discSample(cx:number,cy:number,cz:number,
                    nx:number,ny:number,nz:number,  // normal
                    r:number, thickness:number): [number,number,number] {
  const angle = rng()*Math.PI*2;
  const rad   = Math.sqrt(rng())*r;
  // two tangent vectors perpendicular to normal
  const tx = ny, ty = -nx, tz = 0; // simplified, works for near-Z normals
  const bx = ny*nz - nz*ty, by = nz*tx - nx*nz, bz = nx*ty - ny*tx;
  const tlen = Math.sqrt(tx*tx+ty*ty+tz*tz)+1e-9;
  const blen = Math.sqrt(bx*bx+by*by+bz*bz)+1e-9;
  return [
    cx + (tx/tlen)*Math.cos(angle)*rad + (bx/blen)*Math.sin(angle)*rad + nx*(rng()-0.5)*thickness,
    cy + (ty/tlen)*Math.cos(angle)*rad + (by/blen)*Math.sin(angle)*rad + ny*(rng()-0.5)*thickness,
    cz + (tz/tlen)*Math.cos(angle)*rad + (bz/blen)*Math.sin(angle)*rad + nz*(rng()-0.5)*thickness,
  ];
}

/** Bezier curve in 3D, sampled n points with cross-section radius r */
function bezierTube(
  pts: [number,number,number][],
  n: number, r: number
): [number,number,number][] {
  const result: [number,number,number][] = [];
  for (let i = 0; i < n; i++) {
    const t = rng();
    // Catmull-Rom eval between pts[0..3]
    const p0=pts[0],p1=pts[1],p2=pts[2],p3=pts.length>3?pts[3]:pts[2];
    const t2=t*t,t3=t2*t;
    const bx=0.5*((-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2+(-p0[0]+p2[0])*t+2*p1[0]);
    const by=0.5*((-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3+(2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2+(-p0[1]+p2[1])*t+2*p1[1]);
    const bz=0.5*((-p0[2]+3*p1[2]-3*p2[2]+p3[2])*t3+(2*p0[2]-5*p1[2]+4*p2[2]-p3[2])*t2+(-p0[2]+p2[2])*t+2*p1[2]);
    // add radial jitter
    const jx=gaussian()*r, jy=gaussian()*r, jz=gaussian()*r*0.3;
    result.push([bx+jx, by+jy, bz+jz]);
  }
  return result;
}

// ── Store morphTarget info per particle: [jaw influence, eye-close influence, swirl influence]
// We pack these into a Float32Array attribute.

interface FaceParticles {
  positions: Float32Array;  // x,y,z
  morphJaw:  Float32Array;  // 0..1  jaw drop influence
  morphBlink:Float32Array;  // 0..1  eye-close influence
  morphSwirl:Float32Array;  // swirl phase offset
  sizes:     Float32Array;  // per-particle size scale
  brightness:Float32Array;  // per-particle brightness
  count:     number;
}

function generateFaceParticles(target: number): FaceParticles {
  type P = [number,number,number];
  const pts: P[]    = [];
  const jaw: number[]   = [];
  const blink: number[] = [];
  const swirl: number[] = [];
  const sizes: number[] = [];
  const bright: number[] = [];

  const add = (p: P, j=0, bl=0, sw=0, sz=1, br=1) => {
    pts.push(p); jaw.push(j); blink.push(bl); swirl.push(sw);
    sizes.push(sz); bright.push(br);
  };

  const addMany = (arr: P[], j=0,bl=0,sw=0,sz=1,br=1) =>
    arr.forEach(p => add(p,j,bl,sw,sz,br));

  // ── HEAD SHELL (skull outline) ─────────────────────────────────────────
  // Large slightly-egg-shaped skull: narrower at jaw
  const headN = Math.floor(target * 0.12);
  for (let i=0;i<headN;i++) {
    const u=rng()*2*Math.PI, v=rng()*Math.PI;
    const su=Math.sin(u),cu=Math.cos(u),sv=Math.sin(v),cv=Math.cos(v);
    // y-scale varies: narrower at bottom (jaw)
    const ypos = cv * 1.05;
    const jawFactor = ypos < -0.1 ? Math.pow(Math.max(0, (-ypos-0.1)/0.95), 1.4)*0.38 : 0;
    const rx=0.72-jawFactor*0.38, rz=0.68-jawFactor*0.18;
    const x=su*sv*rx, y=ypos, z=cu*sv*rz;
    // Only front/sides (z > -0.3)
    if (z < -0.35) continue;
    // Surface only: thin shell
    const r2 = x*x+y*y+z*z;
    if (r2 < 0.48 || r2 > 0.90) continue;
    add([x,y,z], jawFactor*0.4, 0, rng()*Math.PI*2, 0.5+rng()*0.5, 0.3+rng()*0.4);
  }

  // ── FOREHEAD ──────────────────────────────────────────────────────────
  for(let i=0;i<Math.floor(target*0.04);i++){
    const x=(rng()-0.5)*0.9, y=0.55+rng()*0.35, z=0.38+rng()*0.25;
    if(x*x/(0.45*0.45)+((y-0.72)*(y-0.72))/(0.25*0.25) > 1.1) continue;
    add([x,y,z],0,0,rng()*Math.PI*2,0.6+rng()*0.6,0.4+rng()*0.35);
  }

  // ── CHEEKBONES ────────────────────────────────────────────────────────
  for(const side of [-1,1]){
    for(let i=0;i<Math.floor(target*0.035);i++){
      const p = ellipsoidSurface(side*0.48, 0.04, 0.52, 0.20,0.14,0.12, 0.015);
      add(p,0,0,rng()*Math.PI*2,0.7+rng()*0.6,0.5+rng()*0.3);
    }
  }

  // ── EYES ──────────────────────────────────────────────────────────────
  for(const side of [-1,1]){
    const ex=side*0.30, ey=0.175, ez=0.60;
    // Iris ring
    for(let i=0;i<Math.floor(target*0.025);i++){
      const a=rng()*Math.PI*2, r=0.06+rng()*0.025;
      const x=ex+Math.cos(a)*r, y=ey+Math.sin(a)*r*0.75, z=ez+rng()*0.012;
      add([x,y,z], 0, 1, rng()*Math.PI*2, 1.2+rng(), 1.0);
    }
    // Pupil (dense)
    for(let i=0;i<Math.floor(target*0.012);i++){
      const a=rng()*Math.PI*2, r=rng()*0.028;
      add([ex+Math.cos(a)*r, ey+Math.sin(a)*r*0.75, ez+0.005],
        0,1,rng()*Math.PI*2,1.5,1.0);
    }
    // Highlight spark
    for(let i=0;i<Math.floor(target*0.004);i++){
      add([ex+0.022*side*-1+gaussian()*0.008, ey+0.030+gaussian()*0.006, ez+0.016],
        0,1,0,2.5,2.5);
    }
    // Upper eyelid arc
    const lidPts: P[] = [
      [ex-0.095,ey+0.015,ez-0.02],[ex-0.04,ey+0.060,ez+0.01],
      [ex+0.04,ey+0.060,ez+0.01],[ex+0.095,ey+0.015,ez-0.02]
    ];
    addMany(bezierTube(lidPts, Math.floor(target*0.018), 0.006), 0, 1, rng()*Math.PI*2, 0.8, 0.9);
    // Lower lash line
    const lashPts: P[] = [
      [ex-0.088,ey-0.010,ez-0.01],[ex,ey-0.040,ez+0.005],[ex+0.088,ey-0.010,ez-0.01]
    ];
    addMany(bezierTube(lashPts, Math.floor(target*0.012), 0.005), 0, 0, rng()*Math.PI*2, 0.7, 0.8);
  }

  // ── EYEBROWS ──────────────────────────────────────────────────────────
  for(const side of [-1,1]){
    const bx=side*0.30, by=0.305, bz=0.595;
    const browPts: P[] = [
      [bx-side*0.12,by-0.008,bz],[bx-side*0.04,by+0.022,bz+0.01],
      [bx+side*0.04,by+0.018,bz+0.005],[bx+side*0.11,by+0.002,bz]
    ];
    addMany(bezierTube(browPts, Math.floor(target*0.022), 0.008),
      0, 0, rng()*Math.PI*2, 1.0, 1.1);
  }

  // ── NOSE ──────────────────────────────────────────────────────────────
  // Bridge
  for(let i=0;i<Math.floor(target*0.018);i++){
    const y=0.16+rng()*0.22, x=(rng()-0.5)*0.055*(1-((y-0.16)/0.30));
    add([x,y,0.70+rng()*0.02],0,0,rng()*Math.PI*2,0.6+rng()*0.5,0.6+rng()*0.3);
  }
  // Tip bulge
  for(let i=0;i<Math.floor(target*0.018);i++){
    const p=ellipsoidSurface(0,-0.085,0.735,0.058,0.045,0.040,0.006);
    add(p,0,0,rng()*Math.PI*2,0.8+rng()*0.5,0.65+rng()*0.3);
  }
  // Nostrils
  for(const side of [-1,1]){
    for(let i=0;i<Math.floor(target*0.012);i++){
      const p=ellipsoidSurface(side*0.060,-0.110,0.718,0.030,0.022,0.024,0.005);
      add(p,0,0,rng()*Math.PI*2,0.7,0.6+rng()*0.3);
    }
  }

  // ── UPPER LIP ─────────────────────────────────────────────────────────
  // Cupid's bow curve
  const ulPts: P[] = [
    [-0.185,-0.195,0.688],[-0.095,-0.175,0.702],[-0.045,-0.188,0.706],
    [0.000,-0.183,0.708],[0.045,-0.188,0.706],[0.095,-0.175,0.702],[0.185,-0.195,0.688]
  ];
  for(let i=0;i<Math.floor(target*0.030);i++){
    const t=rng(), seg=Math.min(5,Math.floor(t*6));
    const lt=t*6-seg;
    const p0=ulPts[seg],p1=ulPts[Math.min(seg+1,6)];
    const x=p0[0]+(p1[0]-p0[0])*lt + gaussian()*0.008;
    const y=p0[1]+(p1[1]-p0[1])*lt + gaussian()*0.004 + rng()*-0.016;
    const z=p0[2]+(p1[2]-p0[2])*lt + gaussian()*0.004;
    add([x,y,z], 0.3, 0, rng()*Math.PI*2, 1.0+rng()*0.5, 0.95);
  }

  // ── LOWER LIP ─────────────────────────────────────────────────────────
  const llPts: P[] = [
    [-0.178,-0.215,0.690],[-0.080,-0.240,0.706],[0.000,-0.248,0.710],
    [0.080,-0.240,0.706],[0.178,-0.215,0.690]
  ];
  for(let i=0;i<Math.floor(target*0.032);i++){
    const t=rng(), seg=Math.min(3,Math.floor(t*4));
    const lt=t*4-seg;
    const p0=llPts[seg],p1=llPts[Math.min(seg+1,4)];
    const x=p0[0]+(p1[0]-p0[0])*lt + gaussian()*0.008;
    const y=p0[1]+(p1[1]-p0[1])*lt + gaussian()*0.004 + rng()*0.018;
    const z=p0[2]+(p1[2]-p0[2])*lt + gaussian()*0.004;
    add([x,y,z], 0.85, 0, rng()*Math.PI*2, 1.0+rng()*0.5, 0.95);
  }

  // ── LIP CORNERS ───────────────────────────────────────────────────────
  for(const side of [-1,1]){
    for(let i=0;i<Math.floor(target*0.010);i++){
      const p=ellipsoidSurface(side*0.185,-0.205,0.692,0.014,0.018,0.010,0.004);
      add(p,0.5,0,rng()*Math.PI*2,1.1,1.0);
    }
  }

  // ── PHILTRUM (vertical groove above lip) ──────────────────────────────
  for(let i=0;i<Math.floor(target*0.010);i++){
    const y=-0.10-rng()*0.08, x=(rng()-0.5)*0.045;
    add([x,y,0.718+rng()*0.008],0,0,rng()*Math.PI*2,0.6,0.6+rng()*0.3);
  }

  // ── JAW LINE ──────────────────────────────────────────────────────────
  for(let i=0;i<Math.floor(target*0.040);i++){
    const t=rng(), angle=(-0.7+t*1.4)*Math.PI*0.5;
    const x=Math.sin(angle)*0.52, y=-0.40-Math.abs(Math.sin(angle))*0.15, z=Math.cos(angle)*0.42;
    if(z<0) continue;
    add([x,y,z],0.15,0,rng()*Math.PI*2,0.5+rng()*0.4,0.35+rng()*0.3);
  }
  // Chin
  for(let i=0;i<Math.floor(target*0.020);i++){
    const p=ellipsoidSurface(0,-0.50,0.45,0.095,0.065,0.075,0.010);
    add(p,0.1,0,rng()*Math.PI*2,0.6,0.4+rng()*0.35);
  }

  // ── NECK ──────────────────────────────────────────────────────────────
  for(let i=0;i<Math.floor(target*0.025);i++){
    const a=rng()*Math.PI*2, y=-0.60-rng()*0.35;
    const r=0.18+rng()*0.04;
    if(Math.cos(a)<-0.2) continue; // only front half
    add([Math.sin(a)*r, y, Math.cos(a)*r+0.08],
      0.05,0,rng()*Math.PI*2,0.4+rng()*0.3,0.2+rng()*0.25);
  }

  // ── INNER MOUTH CAVITY (visible when open) ────────────────────────────
  for(let i=0;i<Math.floor(target*0.015);i++){
    const x=(rng()-0.5)*0.26, y=-0.205-rng()*0.035, z=0.660+rng()*0.02;
    add([x,y,z],1.0,0,rng()*Math.PI*2,0.5,0.3);
  }
  // Teeth hint
  for(let i=0;i<Math.floor(target*0.012);i++){
    const x=(rng()-0.5)*0.22, y=-0.200+rng()*0.016;
    add([x,y,0.682+rng()*0.008],0.9,0,0,1.2,1.8);
  }

  // ── SCATTERED AMBIENT PARTICLES (depth / atmosphere) ──────────────────
  for(let i=0;i<Math.floor(target*0.050);i++){
    const r=0.85+rng()*0.55;
    const u=rng()*Math.PI*2, v=rng()*Math.PI;
    const x=Math.sin(v)*Math.sin(u)*r;
    const y=Math.sin(v)*Math.cos(u)*r;
    const z=Math.cos(v)*r*0.7-0.1;
    if(z<-0.5) continue;
    add([x,y,z],0,0,rng()*Math.PI*2,0.3+rng()*0.3,0.12+rng()*0.18);
  }

  const count = pts.length;
  const positions  = new Float32Array(count*3);
  const morphJaw   = new Float32Array(count);
  const morphBlink = new Float32Array(count);
  const morphSwirl = new Float32Array(count);
  const sizesArr   = new Float32Array(count);
  const brightArr  = new Float32Array(count);
  for(let i=0;i<count;i++){
    positions[i*3]   = pts[i][0];
    positions[i*3+1] = pts[i][1];
    positions[i*3+2] = pts[i][2];
    morphJaw[i]   = jaw[i];
    morphBlink[i] = blink[i];
    morphSwirl[i] = swirl[i];
    sizesArr[i]   = sizes[i];
    brightArr[i]  = bright[i];
  }
  return { positions, morphJaw, morphBlink, morphSwirl, sizes:sizesArr, brightness:brightArr, count };
}

// ─── GLSL Shaders ────────────────────────────────────────────────────────────

const VERT = /* glsl */`
  attribute float morphJaw;
  attribute float morphBlink;
  attribute float morphSwirl;
  attribute float pSize;
  attribute float brightness;

  uniform float uTime;
  uniform float uJaw;        // 0..1 mouth open
  uniform float uBlink;      // 0..1 eye close
  uniform float uSwirl;      // 0..1 swirl amount
  uniform float uBreath;     // 0..1 breathing
  uniform vec3  uColor;
  uniform float uBaseSize;

  varying vec3  vColor;
  varying float vAlpha;

  // Simple noise helper
  float hash(float n){ return fract(sin(n)*43758.5453123); }
  float noise(float x){ float i=floor(x); float f=fract(x); return mix(hash(i),hash(i+1.),smoothstep(0.,1.,f)); }

  void main(){
    vec3 pos = position;

    // ── Breathing: gentle Y bob + Z pulse ──────────────────────────────
    float breath = sin(uTime*1.15) * 0.012 * uBreath;
    pos.y += breath;
    pos.z += sin(uTime*1.15) * 0.004 * uBreath;

    // ── Idle drift: per-particle noise displacement ─────────────────────
    float phase = morphSwirl;
    float driftAmt = 0.008 + brightness * 0.004;
    pos.x += sin(uTime*0.8 + phase) * driftAmt;
    pos.y += cos(uTime*0.65 + phase*1.3) * driftAmt * 0.7;
    pos.z += sin(uTime*0.55 + phase*0.7) * driftAmt * 0.4;

    // ── Thinking swirl: spiral around Y axis ───────────────────────────
    if(uSwirl > 0.01){
      float angle = uTime * 1.8 + phase;
      float r = length(pos.xz);
      float swirlAngle = uSwirl * sin(uTime*1.4 + phase) * 0.28;
      float cosA = cos(swirlAngle), sinA = sin(swirlAngle);
      float nx = pos.x*cosA - pos.z*sinA;
      float nz = pos.x*sinA + pos.z*cosA;
      pos.x = mix(pos.x, nx, uSwirl);
      pos.z = mix(pos.z, nz, uSwirl);
      // Also float outward slightly
      pos.x += sin(uTime*2.2 + phase) * uSwirl * 0.03;
      pos.y += cos(uTime*1.7 + phase*1.5) * uSwirl * 0.025;
    }

    // ── Jaw open: lower lip/jaw particles drop ──────────────────────────
    if(morphJaw > 0.0 && uJaw > 0.0){
      pos.y -= morphJaw * uJaw * 0.12;
      pos.z -= morphJaw * uJaw * 0.015;
      // Inner mouth opens outward
      pos.x += morphJaw * uJaw * pos.x * 0.08;
    }

    // ── Eye blink: eyelid particles descend ─────────────────────────────
    if(morphBlink > 0.0 && uBlink > 0.0){
      pos.y -= morphBlink * uBlink * 0.065;
    }

    // ── Speaking micro-wobble on face ───────────────────────────────────
    float speakWobble = (1.0 - morphJaw) * uJaw * sin(uTime*8.5 + phase) * 0.003;
    pos.x += speakWobble;
    pos.y += speakWobble * 0.6;

    vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mvPos;

    // ── Size: closer particles are bigger + brightness scale ───────────
    float dist = -mvPos.z;
    float sizeScale = (300.0 / dist) * uBaseSize * pSize;
    gl_PointSize = clamp(sizeScale, 0.5, 8.0);

    // ── Colour: base + slight depth fade ───────────────────────────────
    float depthFade = clamp(1.0 - (pos.z - (-0.8)) / 1.6, 0.35, 1.0);
    float brightMod = brightness * depthFade;
    vColor = uColor * brightMod;

    // Alpha: brighter for key feature particles
    vAlpha = clamp(brightness * 0.85 * depthFade, 0.0, 1.0);
  }
`;

const FRAG = /* glsl */`
  varying vec3  vColor;
  varying float vAlpha;

  void main(){
    // Soft circular particle
    vec2  uv   = gl_PointCoord - vec2(0.5);
    float dist = length(uv);
    if(dist > 0.5) discard;

    // Glow falloff: bright core, soft halo
    float core = smoothstep(0.5, 0.0, dist);
    float halo = pow(core, 1.8);

    gl_FragColor = vec4(vColor + vColor * halo * 0.6, vAlpha * halo);
  }
`;

// ─── Component ───────────────────────────────────────────────────────────────
export const LaniAvatar: React.FC<Props> = ({
  state = "idle", audioLevel = 0, size = 320,
}) => {
  const mountRef  = useRef<HTMLDivElement>(null);
  const rafRef    = useRef<number>(0);
  const stateRef  = useRef(state);
  const lvRef     = useRef(audioLevel);
  stateRef.current = state;
  lvRef.current    = audioLevel;

  useEffect(() => {
    if (!mountRef.current) return;
    const el = mountRef.current;

    // ── Renderer ─────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(size, size);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    // ── Scene / Camera ───────────────────────────────────────────────
    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 20);
    camera.position.set(0, 0.0, 2.5);
    camera.lookAt(0, -0.02, 0);

    // ── Generate particles ───────────────────────────────────────────
    const PARTICLE_COUNT = 90_000;
    const fp = generateFaceParticles(PARTICLE_COUNT);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position",    new THREE.BufferAttribute(fp.positions,  3));
    geo.setAttribute("morphJaw",    new THREE.BufferAttribute(fp.morphJaw,   1));
    geo.setAttribute("morphBlink",  new THREE.BufferAttribute(fp.morphBlink, 1));
    geo.setAttribute("morphSwirl",  new THREE.BufferAttribute(fp.morphSwirl, 1));
    geo.setAttribute("pSize",       new THREE.BufferAttribute(fp.sizes,      1));
    geo.setAttribute("brightness",  new THREE.BufferAttribute(fp.brightness, 1));

    // ── Shader uniforms ──────────────────────────────────────────────
    const uniforms = {
      uTime:     { value: 0 },
      uJaw:      { value: 0 },
      uBlink:    { value: 0 },
      uSwirl:    { value: 0 },
      uBreath:   { value: 1 },
      uColor:    { value: new THREE.Color(0x7c6fff) },
      uBaseSize: { value: 1.0 },
    };

    const mat = new THREE.ShaderMaterial({
      vertexShader:   VERT,
      fragmentShader: FRAG,
      uniforms,
      transparent:    true,
      depthWrite:     false,
      blending:       THREE.AdditiveBlending,
    });

    const points = new THREE.Points(geo, mat);
    scene.add(points);

    // ── Clock + anim state ───────────────────────────────────────────
    const clock  = new THREE.Clock();
    let jawSmooth   = 0;
    let blinkSmooth = 0;
    let swirlSmooth = 0;
    let blinkTimer  = 3.5 + Math.random() * 2;
    let blinkActive = false;
    let blinkPhase  = 0;

    const animate = () => {
      rafRef.current = requestAnimationFrame(animate);
      const t  = clock.getElapsedTime();
      const st = stateRef.current;
      const lv = lvRef.current;
      const pal = PAL[st];

      // ── Colour ──────────────────────────────────────────────────────
      uniforms.uColor.value.setRGB(pal.r, pal.g, pal.b);

      // ── Jaw (lip sync) ──────────────────────────────────────────────
      const jawTarget = (st === "speaking" && lv > 0.02) ? Math.min(lv * 2.2, 1.0) : 0;
      jawSmooth += (jawTarget - jawSmooth) * 0.22;
      uniforms.uJaw.value = jawSmooth;

      // ── Swirl (thinking) ────────────────────────────────────────────
      const swirlTarget = st === "thinking" ? 0.75 : 0;
      swirlSmooth += (swirlTarget - swirlSmooth) * 0.04;
      uniforms.uSwirl.value = swirlSmooth;

      // ── Blink ────────────────────────────────────────────────────────
      if (!blinkActive && t > blinkTimer) {
        blinkActive = true;
        blinkPhase  = 0;
      }
      if (blinkActive) {
        blinkPhase  += 0.085;
        blinkSmooth  = Math.max(0, Math.sin(blinkPhase < Math.PI ? blinkPhase : 0));
        if (blinkPhase >= Math.PI) {
          blinkActive = false;
          blinkSmooth = 0;
          blinkTimer  = t + 3.0 + Math.random() * 3.5;
        }
      }
      uniforms.uBlink.value = blinkSmooth;

      // ── Breath ───────────────────────────────────────────────────────
      uniforms.uBreath.value = st === "locked" ? 0.3 : 1.0;

      // ── Head gentle sway ─────────────────────────────────────────────
      points.rotation.y = Math.sin(t * 0.55) * 0.030;
      points.rotation.x = Math.sin(t * 0.38) * 0.016
        + (st === "thinking" ? Math.sin(t * 0.22) * 0.04 : 0);

      // ── Time ─────────────────────────────────────────────────────────
      uniforms.uTime.value = t;

      // ── Size pulse for listening ─────────────────────────────────────
      const sizePulse = st === "listening"
        ? 1.0 + Math.sin(t * 2.5) * 0.12
        : st === "speaking"
        ? 1.0 + lv * 0.4
        : 1.0;
      uniforms.uBaseSize.value = sizePulse;

      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(rafRef.current);
      geo.dispose();
      mat.dispose();
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, [size]);

  const pal = PAL[state];
  const toHex = (r:number,g:number,b:number) =>
    "#" + [r,g,b].map(v => Math.round(v*255).toString(16).padStart(2,"0")).join("");
  const hP = toHex(pal.r, pal.g, pal.b);
  // accent: brighter / shifted hue
  const hA = toHex(Math.min(1,pal.r*0.5+0.5), Math.min(1,pal.g*0.5+0.8), Math.min(1,pal.b*0.5+0.9));

  return (
    <div style={{
      position: "relative", width: size, height: size,
      borderRadius: "20px", overflow: "hidden",
      background: `radial-gradient(ellipse at 50% 45%, ${hP}14 0%, #02010a 72%)`,
      boxShadow: `0 0 80px ${hP}38, 0 0 160px ${hP}14, inset 0 0 50px rgba(0,0,0,.92)`,
      border: `1px solid ${hP}38`,
      userSelect: "none",
      transition: "box-shadow .6s ease, border-color .6s ease",
    }}>
      {/* glass sheen */}
      <div style={{
        position:"absolute",inset:0,borderRadius:"20px",pointerEvents:"none",zIndex:10,
        background:"linear-gradient(135deg,rgba(255,255,255,.055) 0%,transparent 44%,rgba(255,255,255,.010) 100%)",
      }}/>
      {/* HUD corners */}
      {(["tl","tr","bl","br"] as const).map(pos => {
        const s=size*.054, m=size*.026;
        return (
          <svg key={pos} style={{
            position:"absolute",
            [pos.includes("r")?"right":"left"]:m,
            [pos.includes("b")?"bottom":"top"]:m,
            zIndex:11,pointerEvents:"none",opacity:.36,
          }} width={s} height={s}>
            <polyline
              points={pos.includes("r")?`${s},0 0,0 0,${s}`:`0,0 ${s},0 ${s},${s}`}
              fill="none" stroke={hP} strokeWidth="1.4"
            />
          </svg>
        );
      })}
      {/* state label */}
      <div style={{
        position:"absolute",bottom:10,left:0,right:0,textAlign:"center",
        fontFamily:"'JetBrains Mono','SF Mono',monospace",
        fontSize:Math.round(size*.032),fontWeight:700,
        color:hA,opacity:.68,textShadow:`0 0 10px ${hA}`,
        zIndex:11,letterSpacing:"0.15em",pointerEvents:"none",
      }}>{pal.label}</div>
      {/* scan line */}
      <div style={{
        position:"absolute",left:0,right:0,height:2,zIndex:12,pointerEvents:"none",
        background:`linear-gradient(90deg,transparent,${hA}50,transparent)`,
        animation:"scanline 4s linear infinite",
      }}/>
      <style>{`@keyframes scanline{from{top:0}to{top:${size}px}}`}</style>
      {/* canvas */}
      <div ref={mountRef} style={{width:size,height:size}}/>
    </div>
  );
};

export default LaniAvatar;
