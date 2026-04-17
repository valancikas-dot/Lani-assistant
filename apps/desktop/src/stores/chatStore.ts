/**
 * Chat store – manages conversation history and command submission state.
 */

import { create } from "zustand";
import { v4 as uuidv4 } from "uuid";
import * as api from "../lib/api";
import { getApiBaseUrl } from "../lib/api";
import type {
  ChatMessage,
  CommandResponse,
  PlanExecutionResponse,
  ResearchStepData,
  WebSearchResponse,
  SummarizeResponse,
  CompareResponse,
  ResearchBrief,
  WorkflowResult,
} from "../lib/types";

/** Extract structured research output from plan step_results for rendering. */
function extractResearchData(response: PlanExecutionResponse): ResearchStepData | undefined {
  const stepMap: ResearchStepData = {};
  let hasResearch = false;

  for (const sr of response.step_results) {
    if (!sr.data) continue;
    if (sr.tool === "web_search") {
      stepMap.search = sr.data as WebSearchResponse;
      hasResearch = true;
    } else if (sr.tool === "summarize_web_results") {
      stepMap.summary = sr.data as SummarizeResponse;
      hasResearch = true;
    } else if (sr.tool === "compare_research_results") {
      stepMap.comparison = sr.data as CompareResponse;
      hasResearch = true;
    } else if (sr.tool === "research_and_prepare_brief") {
      stepMap.brief = sr.data as ResearchBrief;
      hasResearch = true;
    }
  }
  return hasResearch ? stepMap : undefined;
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  /** Submit via the original /commands endpoint (single-tool, backward compat). */
  sendCommand: (command: string) => Promise<CommandResponse | null>;
  /** Submit via the /plans endpoint (planner + executor, supports multi-step). */
  sendCommandWithPlan: (command: string) => Promise<PlanExecutionResponse | null>;
  /** Submit via /workflow/run (cross-tool automation with artifact piping). */
  sendWorkflow: (goal: string) => Promise<WorkflowResult | null>;
  /**
   * Stream LLM chat response token-by-token via SSE.
   * First token appears in ~300-500 ms — no waiting for the full reply.
   * Optional fileContent/fileName are sent to the backend for file-aware replies.
   */
  sendChatStream: (command: string, fileContent?: string, fileName?: string) => Promise<void>;
  /** Directly append a message (used by voice session flow). */
  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,

  sendCommand: async (command: string) => {
    const userMsg: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: command,
      timestamp: new Date().toISOString(),
    };

    set((state) => ({
      messages: [...state.messages, userMsg],
      isLoading: true,
      error: null,
    }));

    try {
      const response = await api.submitCommand({ command });

      const assistantMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content: response.result.message ?? `Tool: ${response.result.tool_name}`,
        timestamp: new Date().toISOString(),
        result: response.result,
        approval_id: response.approval_id,
      };

      set((state) => ({
        messages: [...state.messages, assistantMsg],
        isLoading: false,
      }));

      return response;
    } catch (err) {
      const errorText = err instanceof Error ? err.message : "Unknown error";

      const errorMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content: `Error: ${errorText}`,
        timestamp: new Date().toISOString(),
        result: { tool_name: "error", status: "error", message: errorText },
      };

      set((state) => ({
        messages: [...state.messages, errorMsg],
        isLoading: false,
        error: errorText,
      }));

      return null;
    }
  },

  sendCommandWithPlan: async (command: string) => {
    const userMsg: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: command,
      timestamp: new Date().toISOString(),
    };

    set((state) => ({
      messages: [...state.messages, userMsg],
      isLoading: true,
      error: null,
    }));

    try {
      const response = await api.submitPlan({ command });

      // Use tts_text (localised by backend) when available, otherwise
      // build a summary from step results.
      const stepCount = response.plan.steps.length;
      const doneCount = response.step_results.filter(
        (r) => r.status === "completed"
      ).length;

      // Prefer the backend-localised tts_text as display content
      let content: string;
      const isChatTool =
        !response.plan.is_multi_step &&
        response.plan.steps[0]?.tool === "chat";

      if (isChatTool) {
        // Pure conversational response — show directly without icons
        content =
          response.tts_text ||
          response.step_results[0]?.message ||
          response.message ||
          "…";
      } else if (response.tts_text) {
        // Add a status icon prefix
        const icon =
          response.overall_status === "completed" ? "✔" :
          response.overall_status === "approval_required" ? "⏳" :
          response.overall_status === "failed" ? "✖" : "⟳";
        content = `${icon} ${response.tts_text}`;
      } else if (response.overall_status === "approval_required") {
        content = `⏸ Plan paused – approval required. ${doneCount}/${stepCount} steps done.`;
      } else if (response.overall_status === "completed") {
        content =
          stepCount === 1
            ? (response.step_results[0]?.message ?? "Done.")
            : `✔ All ${stepCount} steps completed.`;
      } else if (response.overall_status === "failed") {
        const failedStep = response.step_results.find((r) => r.status === "failed");
        content = `✖ Plan failed at step ${(failedStep?.step_index ?? 0) + 1}: ${failedStep?.message ?? "Unknown error."}`;
      } else {
        content = response.message ?? "Plan running…";
      }

      const assistantMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content,
        timestamp: new Date().toISOString(),
        plan_response: response,
        research_result: extractResearchData(response),
        // For single-step plans preserve backward-compat fields too
        result: response.plan.is_multi_step
          ? undefined
          : {
              tool_name: response.plan.steps[0]?.tool ?? "unknown",
              status:
                response.overall_status === "completed"
                  ? "success"
                  : response.overall_status === "approval_required"
                  ? "approval_required"
                  : "error",
              message: response.message,
              data: response.step_results[0]?.data,
            },
        approval_id: response.step_results.find((r) => r.approval_id !== undefined)
          ?.approval_id,
      };

      set((state) => ({
        messages: [...state.messages, assistantMsg],
        isLoading: false,
      }));

      return response;
    } catch (err) {
      const errorText = err instanceof Error ? err.message : "Unknown error";

      const errorMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content: `Error: ${errorText}`,
        timestamp: new Date().toISOString(),
        result: { tool_name: "error", status: "error", message: errorText },
      };

      set((state) => ({
        messages: [...state.messages, errorMsg],
        isLoading: false,
        error: errorText,
      }));

      return null;
    }
  },

  clearMessages: () => set({ messages: [], error: null }),

  sendChatStream: async (command: string, fileContent?: string, fileName?: string) => {
    const BASE_URL = getApiBaseUrl();

    // 1. Push user message immediately
    const userMsg: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: command,
      timestamp: new Date().toISOString(),
      ...(fileName ? { attachedFileName: fileName } : {}),
    };

    // 2. Reserve a placeholder assistant message (will be filled token-by-token)
    const placeholderId = uuidv4();
    const placeholder: ChatMessage = {
      id: placeholderId,
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
      isStreaming: true,
    };

    set((state) => ({
      messages: [...state.messages, userMsg, placeholder],
      isLoading: true,
      error: null,
    }));

    try {
      const res = await fetch(`${BASE_URL}/api/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: command,
          ...(fileContent ? { file_content: fileContent, file_name: fileName } : {}),
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Stream request failed: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6)) as {
              type: string;
              text?: string;
              full?: string;
              message?: string;
            };

            if (evt.type === "token" && evt.text) {
              // Append token to the placeholder message
              set((state) => ({
                messages: state.messages.map((m) =>
                  m.id === placeholderId
                    ? { ...m, content: m.content + evt.text! }
                    : m
                ),
              }));
            } else if (evt.type === "done") {
              // Replace with final authoritative text, clear streaming flag
              const finalText = evt.full ?? get().messages.find((m) => m.id === placeholderId)?.content ?? "";
              set((state) => ({
                messages: state.messages.map((m) =>
                  m.id === placeholderId ? { ...m, content: finalText, isStreaming: false } : m
                ),
                isLoading: false,
              }));
            } else if (evt.type === "error") {
              throw new Error(evt.message ?? "Stream error");
            }
          } catch {
            // skip malformed JSON lines
          }
        }
      }

      set({ isLoading: false });
    } catch (err) {
      const errorText = err instanceof Error ? err.message : "Unknown error";
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === placeholderId
            ? { ...m, content: `Error: ${errorText}`, isStreaming: false }
            : m
        ),
        isLoading: false,
        error: errorText,
      }));
    }
  },

  sendWorkflow: async (goal: string) => {
    const userMsg: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: goal,
      timestamp: new Date().toISOString(),
    };

    set((state) => ({
      messages: [...state.messages, userMsg],
      isLoading: true,
      error: null,
    }));

    try {
      const result = await api.runWorkflow({ goal });

      const statusIcon =
        result.overall_status === "completed"   ? "✔" :
        result.overall_status === "partial"     ? "⚠" :
        result.overall_status === "approval_required" ? "⏸" : "✖";

      const content = `${statusIcon} ${result.message.split("\n")[0]}`;

      const assistantMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content,
        timestamp: new Date().toISOString(),
        workflow_result: result,
      };

      set((state) => ({
        messages: [...state.messages, assistantMsg],
        isLoading: false,
      }));

      return result;
    } catch (err) {
      const errorText = err instanceof Error ? err.message : "Unknown error";

      const errorMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content: `Error: ${errorText}`,
        timestamp: new Date().toISOString(),
        result: { tool_name: "error", status: "error", message: errorText },
      };

      set((state) => ({
        messages: [...state.messages, errorMsg],
        isLoading: false,
        error: errorText,
      }));

      return null;
    }
  },

  addMessage: (msg: ChatMessage) =>
    set((state) => ({ messages: [...state.messages, msg] })),
}));

