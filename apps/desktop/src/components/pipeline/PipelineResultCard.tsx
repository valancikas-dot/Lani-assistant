/**
 * PipelineResultCard – renders a structured pipeline execution result
 * returned by the backend pipeline_service.
 */

import React, { useState } from "react";

// ── Types ──────────────────────────────────────────────────────────────────

export interface PipelineStepRecord {
  step_id: string;
  name: string;
  status: "completed" | "simulated" | "approval_required" | "blocked" | "failed";
  artifact?: string;
  approval_id?: number;
  simulation?: boolean;
}

export interface PipelineResultData {
  pipeline: string;
  pipeline_name: string;
  status: "completed" | "paused_for_approval" | "failed" | "partial";
  steps_completed: PipelineStepRecord[];
  artifacts: Record<string, unknown>;
  next_actions: string[];
  mission_id?: number;
  approval_id?: number;
  error?: string;
  simulation: boolean;
}

interface Props {
  data: PipelineResultData;
  onNextAction?: (action: string) => void;
}

// ── Domain icons ───────────────────────────────────────────────────────────

const DOMAIN_ICONS: Record<string, string> = {
  video: "🎬",
  music: "🎵",
  app: "🛠️",
  marketing: "📣",
  research: "🔬",
};

// ── Step status helpers ────────────────────────────────────────────────────

const STEP_ICONS: Record<string, string> = {
  completed: "✓",
  simulated: "⚠",
  approval_required: "⏳",
  blocked: "🚫",
  failed: "✗",
};

const STEP_COLORS: Record<string, string> = {
  completed: "#22c55e",
  simulated: "#f59e0b",
  approval_required: "#818cf8",
  blocked: "#6b7280",
  failed: "#ef4444",
};

const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  partial: "#f59e0b",
  paused_for_approval: "#818cf8",
  failed: "#ef4444",
};

// ── Artifact block ─────────────────────────────────────────────────────────

/** Detect media fields in an artifact dict and render them inline. */
const MediaPreview: React.FC<{ value: unknown }> = ({ value }) => {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;

  const videoPath = v.video_path as string | undefined;
  const videoUrl = v.video_url as string | undefined;
  const audioPaths = (v.audio_path ? [v.audio_path as string] : []);
  const imagePaths = (v.image_paths as string[] | undefined) ?? [];

  const hasMedia = videoUrl || audioPaths.length > 0 || imagePaths.length > 0;
  if (!hasMedia) return null;

  return (
    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Video */}
      {videoUrl && (
        <div>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>🎬 Video</div>
          <video
            src={videoUrl}
            controls
            style={{ width: "100%", borderRadius: 6, maxHeight: 220 }}
          />
        </div>
      )}
      {!videoUrl && videoPath && (
        <div style={{ fontSize: 11, color: "#a5b4fc" }}>
          🎬 Saved: <code style={{ fontSize: 10 }}>{videoPath}</code>
        </div>
      )}
      {/* Audio */}
      {audioPaths.map((p, i) => (
        <div key={i}>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>🔊 Audio</div>
          <audio controls src={`file://${p}`} style={{ width: "100%" }} />
          <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{p}</div>
        </div>
      ))}
      {/* Images */}
      {imagePaths.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>🖼 Images</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {imagePaths.map((p, i) => (
              <img
                key={i}
                src={`file://${p}`}
                alt={`Generated image ${i + 1}`}
                style={{ width: 90, height: 90, objectFit: "cover", borderRadius: 6, border: "1px solid rgba(99,102,241,0.2)" }}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const ArtifactBlock: React.FC<{ label: string; value: unknown }> = ({ label, value }) => {
  const [open, setOpen] = useState(false);
  const text =
    typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);

  const preview = text.length > 180 ? text.slice(0, 180) + "…" : text;

  return (
    <div
      style={{
        marginBottom: 6,
        borderRadius: 8,
        background: "rgba(99,102,241,0.06)",
        border: "1px solid rgba(99,102,241,0.15)",
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 10px",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "#a5b4fc",
          fontSize: 11,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        <span>📦 {label}</span>
        <span style={{ opacity: 0.5 }}>{open ? "▲" : "▼"}</span>
      </button>
      <div
        style={{
          padding: open ? "0 10px 8px" : "0 10px",
          maxHeight: open ? 600 : 0,
          overflow: "hidden",
          transition: "max-height 0.25s ease, padding 0.15s ease",
        }}
      >
        {/* Media previews (video / audio / images) */}
        <MediaPreview value={value} />
        <pre
          style={{
            margin: 0,
            fontSize: 11,
            color: "#cbd5e1",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}
        >
          {open ? text : preview}
        </pre>
      </div>
    </div>
  );
};

// ── Main component ─────────────────────────────────────────────────────────

export const PipelineResultCard: React.FC<Props> = ({ data, onNextAction }) => {
  const icon = DOMAIN_ICONS[data.pipeline] ?? "⚡";
  const statusColor = STATUS_COLORS[data.status] ?? "#94a3b8";
  const artifactEntries = Object.entries(data.artifacts ?? {});

  return (
    <div
      style={{
        marginTop: 8,
        borderRadius: 12,
        border: `1px solid ${statusColor}33`,
        background: "rgba(15,15,30,0.7)",
        backdropFilter: "blur(8px)",
        overflow: "hidden",
        fontSize: 13,
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 14px",
          borderBottom: "1px solid rgba(99,102,241,0.12)",
          background: "rgba(99,102,241,0.06)",
        }}
      >
        <span style={{ fontSize: 20 }}>{icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, color: "#e2e8f0", fontSize: 14 }}>
            {data.pipeline_name}
          </div>
          {data.mission_id && (
            <div style={{ fontSize: 10, color: "#64748b" }}>
              Mission #{data.mission_id}
            </div>
          )}
        </div>
        <span
          style={{
            padding: "3px 9px",
            borderRadius: 99,
            background: `${statusColor}22`,
            color: statusColor,
            fontWeight: 700,
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          {data.status.replace(/_/g, " ")}
        </span>
      </div>

      {/* ── Simulation warning ── */}
      {data.simulation && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "7px 14px",
            background: "rgba(245,158,11,0.08)",
            borderBottom: "1px solid rgba(245,158,11,0.15)",
            color: "#fbbf24",
            fontSize: 11,
          }}
        >
          <span>⚠️</span>
          <span>
            <strong>Simulation mode</strong> — some steps used placeholders. Connect API keys to enable full execution.
          </span>
        </div>
      )}

      {/* ── Error banner ── */}
      {data.error && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "7px 14px",
            background: "rgba(239,68,68,0.08)",
            borderBottom: "1px solid rgba(239,68,68,0.15)",
            color: "#f87171",
            fontSize: 11,
          }}
        >
          <span>❌</span>
          <span>{data.error}</span>
        </div>
      )}

      <div style={{ padding: "10px 14px" }}>
        {/* ── Steps ── */}
        {data.steps_completed.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#64748b",
                marginBottom: 5,
              }}
            >
              Steps
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {data.steps_completed.map((step) => (
                <div
                  key={step.step_id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "4px 8px",
                    borderRadius: 6,
                    background: "rgba(255,255,255,0.03)",
                  }}
                >
                  <span
                    style={{
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      background: `${STEP_COLORS[step.status] ?? "#94a3b8"}22`,
                      border: `1.5px solid ${STEP_COLORS[step.status] ?? "#94a3b8"}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 9,
                      color: STEP_COLORS[step.status] ?? "#94a3b8",
                      flexShrink: 0,
                      fontWeight: 700,
                    }}
                  >
                    {STEP_ICONS[step.status] ?? "·"}
                  </span>
                  <span style={{ color: "#cbd5e1", flex: 1 }}>{step.name}</span>
                  {step.simulation && (
                    <span style={{ fontSize: 10, color: "#f59e0b" }}>sim</span>
                  )}
                  {step.approval_id && (
                    <span style={{ fontSize: 10, color: "#818cf8" }}>
                      #{step.approval_id}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Artifacts ── */}
        {artifactEntries.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#64748b",
                marginBottom: 5,
              }}
            >
              Artifacts
            </div>
            {artifactEntries.map(([key, val]) => (
              <ArtifactBlock key={key} label={key} value={val} />
            ))}
          </div>
        )}

        {/* ── Approval CTA ── */}
        {data.status === "paused_for_approval" && data.approval_id && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 10px",
              borderRadius: 8,
              background: "rgba(129,140,248,0.08)",
              border: "1px solid rgba(129,140,248,0.25)",
              marginBottom: 10,
            }}
          >
            <span style={{ color: "#818cf8", fontSize: 16 }}>⏳</span>
            <span style={{ color: "#a5b4fc", flex: 1, fontSize: 12 }}>
              Awaiting your approval to continue (#{data.approval_id})
            </span>
            <a
              href="/approvals"
              style={{
                padding: "4px 12px",
                borderRadius: 6,
                background: "rgba(129,140,248,0.2)",
                color: "#818cf8",
                fontWeight: 700,
                fontSize: 11,
                textDecoration: "none",
                border: "1px solid rgba(129,140,248,0.35)",
              }}
            >
              Review
            </a>
          </div>
        )}

        {/* ── Next actions ── */}
        {data.next_actions.length > 0 && (
          <div>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#64748b",
                marginBottom: 5,
              }}
            >
              Continue with
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {data.next_actions.map((action, i) => (
                <button
                  key={i}
                  onClick={() => onNextAction?.(action)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 99,
                    background: "rgba(99,102,241,0.1)",
                    border: "1px solid rgba(99,102,241,0.25)",
                    color: "#a5b4fc",
                    cursor: "pointer",
                    fontSize: 11,
                    fontWeight: 500,
                    transition: "background 0.15s",
                  }}
                >
                  {action}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default PipelineResultCard;
