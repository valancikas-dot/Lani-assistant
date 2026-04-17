/**
 * ChatMessage – renders a single message bubble with optional tool result,
 * execution plan view, and TTS playback button.
 */

import React from "react";
import type { ChatMessage as ChatMessageType } from "../../lib/types";
import { AudioPlayer } from "./AudioPlayer";
import { ExecutionPlanView } from "./ExecutionPlanView";
import { WorkflowCard } from "./WorkflowCard";
import { ResearchResultView } from "../research/ResearchResultView";
import { PipelineResultCard, type PipelineResultData } from "../pipeline/PipelineResultCard";
import { useSettingsStore } from "../../stores/settingsStore";
import { useChatStore } from "../../stores/chatStore";

interface Props {
  message: ChatMessageType;
}

const STATUS_COLORS: Record<string, string> = {
  success: "#22c55e",
  error: "#ef4444",
  approval_required: "#f59e0b",
};

export const ChatMessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === "user";
  const { settings } = useSettingsStore();
  const { sendCommandWithPlan } = useChatStore();
  const isVoiceRendered = message.render_mode === "voice";
  const showAudio = !isUser && !isVoiceRendered && (settings?.tts_enabled ?? false) && (settings?.voice_enabled ?? false);

  // Show animated working indicator while streaming and content is still empty
  const isWorking = !isUser && message.isStreaming && message.content === "";

  const showResultCard =
    message.result &&
    message.result.tool_name !== "chat" &&
    !(message.plan_response?.plan.is_multi_step);

  // Detect pipeline result payload
  const pipelineData: PipelineResultData | null =
    message.result?.data != null &&
    typeof message.result.data === "object" &&
    "pipeline" in (message.result.data as object)
      ? (message.result.data as PipelineResultData)
      : null;

  return (
    <div className={`message message--${message.role}`}>
      <div className="message__avatar">{isUser ? "👤" : "🤖"}</div>

      <div className="message__body">
        {/* Animated working indicator shown while no tokens have arrived yet */}
        {isWorking && (
          <div className="message__working">
            <span className="message__working-icon">🔧</span>
            <span className="message__working-text">Dirbu</span>
            <span className="message__working-dots">
              <span>.</span><span>.</span><span>.</span>
            </span>
          </div>
        )}

        {!isVoiceRendered && !isWorking && <p className="message__text">{message.content}</p>}
        {!isVoiceRendered && message.isStreaming && message.content !== "" && (
          <p className="message__text">{message.content}<span className="message__cursor" /></p>
        )}

        {/* Attached file badge (user messages) */}
        {isUser && message.attachedFileName && (
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              marginTop: "4px",
              padding: "2px 8px",
              borderRadius: "6px",
              background: "rgba(99,102,241,0.12)",
              border: "1px solid rgba(99,102,241,0.25)",
              color: "#a5b4fc",
              fontSize: "11px",
              fontWeight: 600,
            }}
          >
            <span>📎</span>
            <span>{message.attachedFileName}</span>
          </div>
        )}

        {isVoiceRendered && (
          <div className="message__voice-summary" aria-label="Voice response delivered aloud">
            <span className="message__voice-summary-icon">🔊</span>
            <span className="message__voice-summary-text">Atsakyta balsu</span>
          </div>
        )}

        {/* ── Workflow result card (cross-tool automation) ── */}
        {message.workflow_result && (
          <WorkflowCard result={message.workflow_result} />
        )}

        {/* ── Multi-step plan view ── */}
        {!message.workflow_result && message.plan_response?.plan.is_multi_step && (
          <ExecutionPlanView
            response={message.plan_response}
            onRetry={(cmd) => sendCommandWithPlan(cmd)}
          />
        )}
        {!isVoiceRendered && message.plan_response?.memory_hints && message.plan_response.memory_hints.length > 0 && (
          <ul className="message__memory-hints">
            {message.plan_response.memory_hints.map((hint, i) => (
              <li key={i} className="message__memory-hint">
                🧠 {hint}
              </li>
            ))}
          </ul>
        )}

        {/* ── Research results ── */}
        {message.research_result && (
          <ResearchResultView data={message.research_result} />
        )}

        {/* ── Pipeline execution result ── */}
        {pipelineData && (
          <PipelineResultCard
            data={pipelineData}
            onNextAction={(action) => sendCommandWithPlan(action)}
          />
        )}

        {/* ── Single-tool result card ── */}
        {showResultCard && !pipelineData && (
          <div
            className="message__result"
            style={{ borderLeftColor: STATUS_COLORS[message.result!.status] }}
          >
            <span className="message__result-tool">{message.result!.tool_name}</span>
            <span
              className="message__result-status"
              style={{ color: STATUS_COLORS[message.result!.status] }}
            >
              {message.result!.status}
            </span>
            {message.result!.data != null && (
              <pre className="message__result-data">
                {JSON.stringify(message.result!.data, null, 2)}
              </pre>
            )}
          </div>
        )}

        <div className="message__footer">
          <time className="message__time">
            {new Date(message.timestamp).toLocaleTimeString()}
          </time>
          {showAudio && (
            <AudioPlayer text={message.content} />
          )}
        </div>
      </div>
    </div>
  );
};

