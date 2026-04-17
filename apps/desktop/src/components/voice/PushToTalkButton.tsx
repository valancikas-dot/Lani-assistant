/**
 * PushToTalkButton – real MediaRecorder-based push-to-talk component.
 *
 * State machine
 * ─────────────
 *  idle         → default; hold / press to start
 *  requesting   → asking browser for microphone permission
 *  recording    → MediaRecorder capturing audio; release/click to stop
 *  uploading    → audio blob being sent to /voice/transcribe
 *  transcribing → waiting for backend STT response
 *  processing   → transcript received; calling /voice/command
 *  done         → success; will reset to idle after brief delay
 *  error        → any step failed; tap to dismiss
 *
 * Props
 * ─────
 *  onResult(transcript, cmdResponse)  – called on successful full round-trip
 *  onError(msg)                       – called on any failure
 *  disabled                           – prevents activation
 *  blocked                            – shows blocked state (session locked etc.)
 *  language                           – BCP-47 tag forwarded to transcribe API
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWakeStore } from "../../stores/wakeStore";
import type { VoiceCommandResponse, SttRecordingState } from "../../lib/types";
import { useI18n } from "../../i18n/useI18n";

// Tauri WebView runs on http:// which blocks navigator.mediaDevices.
// This helper works around it by falling back to the legacy API.
async function getMicStream(): Promise<MediaStream> {
  // Modern API (works on https:// and tauri:// schemes)
  if (navigator.mediaDevices?.getUserMedia) {
    return navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  }
  // Legacy fallback (works in some WebViews on http://)
  const legacy =
    (navigator as any).getUserMedia ||
    (navigator as any).webkitGetUserMedia ||
    (navigator as any).mozGetUserMedia ||
    (navigator as any).msGetUserMedia;
  if (legacy) {
    return new Promise<MediaStream>((resolve, reject) => {
      legacy.call(navigator, { audio: true, video: false }, resolve, reject);
    });
  }
  throw new Error(
    "Microphone not available. If you see this error, please ensure the app has microphone permission in System Settings → Privacy & Security → Microphone."
  );
}

interface PushToTalkButtonProps {
  onResult?: (transcript: string, response: VoiceCommandResponse | null) => void;
  onError?: (message: string) => void;
  onStream?: (stream: MediaStream | null) => void;
  disabled?: boolean;
  blocked?: boolean;
  language?: string;
  /**
   * When set to true the button will automatically begin recording as soon as
   * it is in the idle state (used by the wake-word listener to start recording
   * right after the wake phrase is detected). The parent is responsible for
   * resetting this to false after recording starts.
   */
  autoStart?: boolean;
  onAutoStartConsumed?: () => void;
}

// ── Visual config per state ──────────────────────────────────────────────────

const STATE_STYLE: Record<
  SttRecordingState | "blocked",
  { color: string; bg: string; icon: string; pulse: boolean }
> = {
  blocked:      { color: "#ef4444", bg: "rgba(239,68,68,0.12)",  icon: "🚫", pulse: false },
  idle:         { color: "#6b7280", bg: "rgba(255,255,255,0.04)", icon: "🎙", pulse: false },
  requesting:   { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", icon: "🎙", pulse: true  },
  recording:    { color: "#10b981", bg: "rgba(16,185,129,0.15)", icon: "⏹", pulse: true  },
  uploading:    { color: "#3b82f6", bg: "rgba(59,130,246,0.12)", icon: "📤", pulse: false },
  transcribing: { color: "#8b5cf6", bg: "rgba(139,92,246,0.12)", icon: "✨", pulse: true  },
  processing:   { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", icon: "⚙️", pulse: true  },
  done:         { color: "#10b981", bg: "rgba(16,185,129,0.12)", icon: "✅", pulse: false },
  error:        { color: "#ef4444", bg: "rgba(239,68,68,0.10)", icon: "⚠️", pulse: false },
};

export const PushToTalkButton: React.FC<PushToTalkButtonProps> = ({
  onResult,
  onError,
  onStream,
  disabled = false,
  blocked = false,
  language = "en",
  autoStart = false,
  onAutoStartConsumed,
}) => {
  const { sttState, transcript, sttError, transcribeAndCommand } = useWakeStore();
  const { t } = useI18n();

  // Local recording state (MediaRecorder lives here, not in the store)
  const [localState, setLocalState] = useState<SttRecordingState>("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const doneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync localState from store transitions after transcribeAndCommand is called
  useEffect(() => {
    if (
      sttState === "uploading" ||
      sttState === "transcribing" ||
      sttState === "processing" ||
      sttState === "done" ||
      sttState === "error"
    ) {
      setLocalState(sttState);
    }
  }, [sttState]);

  // Auto-reset to idle after "done"
  useEffect(() => {
    if (localState === "done") {
      doneTimerRef.current = setTimeout(() => setLocalState("idle"), 1800);
    }
    return () => {
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
    };
  }, [localState]);

  // Report errors to parent via callback
  useEffect(() => {
    if (localState === "error" && sttError) {
      onError?.(sttError);
    }
  }, [localState, sttError, onError]);

  // Report success to parent
  useEffect(() => {
    if (
      localState === "done" &&
      transcript &&
      useWakeStore.getState().lastCommandResponse
    ) {
      onResult?.(transcript, useWakeStore.getState().lastCommandResponse);
    }
  }, [localState, transcript, onResult]);

  // Auto-start recording when wake word is detected (autoStart=true)
  useEffect(() => {
    if (autoStart && localState === "idle" && !disabled && !blocked) {
      onAutoStartConsumed?.(); // tell parent to reset the flag
      void startRecording();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  // ── Stop recording and submit ──────────────────────────────────────────────
  const stopAndSubmit = useCallback(() => {
    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") return;
    mr.stop(); // triggers ondataavailable + onstop
  }, []);

  // ── Start recording ────────────────────────────────────────────────────────
  const startRecording = useCallback(async () => {
    if (disabled || blocked || localState !== "idle") return;

    setLocalState("requesting");
    chunksRef.current = [];

    let stream: MediaStream;
    try {
      stream = await getMicStream();
    } catch (err: any) {
      const msg =
        err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError"
          ? "Microphone permission denied. Allow mic access in System Settings → Privacy & Security → Microphone."
          : err?.name === "NotFoundError"
          ? "No microphone found. Please connect a microphone and try again."
          : `Microphone error: ${err?.message ?? "unknown"}`;
      setLocalState("error");
      useWakeStore.setState({ sttError: msg });
      onError?.(msg);
      return;
    }

    streamRef.current = stream;
    setLocalState("recording");
    onStream?.(stream); // notify parent so it can feed the stream to useVolumeAnalyser

    // Pick a MIME type the browser supports
    const mimeType = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
    ].find((m) => MediaRecorder.isTypeSupported(m)) ?? "";

    const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    mediaRecorderRef.current = mr;

    mr.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    mr.onstop = async () => {
      // Release mic immediately
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      onStream?.(null); // notify parent that stream ended

      const blob = new Blob(chunksRef.current, {
        type: mimeType || "audio/webm",
      });
      chunksRef.current = [];

      if (blob.size === 0) {
        const msg = "No audio captured. Please try again.";
        setLocalState("error");
        useWakeStore.setState({ sttError: msg });
        onError?.(msg);
        return;
      }

      // Hand off to the store's full STT→command pipeline
      const cmdResp = await transcribeAndCommand(blob, language);
      if (cmdResp) {
        onResult?.(useWakeStore.getState().transcript ?? "", cmdResp);
      }
    };

    mr.start(250); // collect chunks every 250 ms
  }, [disabled, blocked, localState, language, transcribeAndCommand, onError, onResult, onStream]);

  // ── Toggle on click (mobile / keyboard friendly) ───────────────────────────
  const handleClick = useCallback(() => {
    if (disabled) return;
    if (blocked) return;
    if (localState === "idle") {
      void startRecording();
      return;
    }
    if (localState === "recording") {
      stopAndSubmit();
      return;
    }
    if (localState === "error") {
      setLocalState("idle");
      useWakeStore.setState({ sttError: null, sttState: "idle" });
    }
  }, [disabled, blocked, localState, startRecording, stopAndSubmit]);

  // Hold-to-talk: press = start, release = stop
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (localState === "idle") void startRecording();
    },
    [localState, startRecording]
  );

  const handleMouseUp = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (localState === "recording") stopAndSubmit();
    },
    [localState, stopAndSubmit]
  );

  const handleMouseLeave = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      if (localState === "recording") stopAndSubmit();
    },
    [localState, stopAndSubmit]
  );

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      e.preventDefault();
      if (localState === "idle") void startRecording();
    },
    [localState, startRecording]
  );

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      e.preventDefault();
      if (localState === "recording") stopAndSubmit();
    },
    [localState, stopAndSubmit]
  );

  // Cleanup on unmount
  useEffect(
    () => () => {
      mediaRecorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    },
    []
  );

  // ── Render ─────────────────────────────────────────────────────────────────
  const stateLabels: Record<SttRecordingState | "blocked", string> = {
    blocked:      t("ptt", "blocked"),
    idle:         t("ptt", "idle"),
    requesting:   t("ptt", "requesting"),
    recording:    t("ptt", "recording"),
    uploading:    t("ptt", "uploading"),
    transcribing: t("ptt", "transcribing"),
    processing:   t("ptt", "processing"),
    done:         t("ptt", "done"),
    error:        t("ptt", "error"),
  };
  const styleKey = blocked ? "blocked" : localState;
  const cfg = { ...STATE_STYLE[styleKey], label: stateLabels[styleKey] };
  const isActive = localState === "recording";
  const isBusy =
    localState === "uploading" ||
    localState === "transcribing" ||
    localState === "processing";

  const statusLine =
    localState === "error" && sttError
      ? sttError
      : localState === "done" && transcript
      ? `✓ "${transcript.length > 50 ? transcript.slice(0, 50) + "…" : transcript}"`
      : localState === "transcribing"
      ? t("ptt", "transcribing")
      : localState === "processing"
      ? `${t("ptt", "processing")}: "${transcript ?? ""}"`
      : null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "8px",
        userSelect: "none",
      }}
    >
      {/* ── Main button ───────────────────────────────────────────────────── */}
      <button
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        disabled={disabled || isBusy}
        style={{
          width: "64px",
          height: "64px",
          borderRadius: "50%",
          border: `2px solid ${cfg.color}`,
          background: cfg.bg,
          cursor: disabled || isBusy ? "not-allowed" : blocked ? "default" : "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "26px",
          transition: "all 0.15s",
          outline: "none",
          boxShadow: isActive
            ? `0 0 0 6px rgba(16,185,129,0.20), 0 0 0 3px rgba(16,185,129,0.30)`
            : "none",
          animation: cfg.pulse ? "pulse 1.2s infinite" : "none",
          opacity: disabled ? 0.45 : 1,
        }}
        title={cfg.label}
        aria-label={cfg.label}
        aria-pressed={isActive}
      >
        {cfg.icon}
      </button>

      {/* ── State label ───────────────────────────────────────────────────── */}
      <span
        style={{
          fontSize: "11px",
          fontWeight: isActive ? 600 : 400,
          color: cfg.color,
          textAlign: "center",
          maxWidth: "160px",
        }}
      >
        {cfg.label}
      </span>

      {/* ── Waveform placeholder while recording ──────────────────────────── */}
      {isActive && (
        <div
          aria-hidden
          style={{
            display: "flex",
            gap: "3px",
            alignItems: "flex-end",
            height: "18px",
          }}
        >
          {[4, 8, 14, 10, 6, 12, 8, 5, 11, 7].map((h, i) => (
            <span
              key={i}
              style={{
                width: "3px",
                height: `${h}px`,
                borderRadius: "2px",
                background: "#10b981",
                animation: `wave 0.8s ease-in-out ${i * 0.08}s infinite alternate`,
              }}
            />
          ))}
        </div>
      )}

      {/* ── Status / transcript preview line ──────────────────────────────── */}
      {statusLine && (
        <p
          style={{
            margin: 0,
            fontSize: "11px",
            color:
              localState === "error"
                ? "#ef4444"
                : localState === "done"
                ? "#10b981"
                : "#94a3b8",
            maxWidth: "220px",
            textAlign: "center",
            wordBreak: "break-word",
          }}
        >
          {statusLine}
        </p>
      )}

      {/* ── Hint when idle ────────────────────────────────────────────────── */}
      {localState === "idle" && !blocked && !disabled && (
        <p style={{ margin: 0, fontSize: "10px", color: "#4b5563" }}>
          {t("ptt", "hold_instruction")}
        </p>
      )}
    </div>
  );
};
