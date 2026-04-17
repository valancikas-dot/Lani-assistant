import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  getChains: vi.fn(),
  getChainDetail: vi.fn(),
  getChainCheckpoints: vi.fn(),
}));

import * as api from "../lib/api";
import { useMissionControlStore } from "./missionControlStore";

const mockedApi = api as unknown as {
  getChains: ReturnType<typeof vi.fn>;
  getChainDetail: ReturnType<typeof vi.fn>;
  getChainCheckpoints: ReturnType<typeof vi.fn>;
};

describe("missionControlStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useMissionControlStore.setState({
      chains: [],
      isLoading: false,
      error: null,
      selectedChainId: null,
      chainDetail: null,
      checkpoints: null,
      isLoadingDetail: false,
      detailError: null,
    });
  });

  it("fetchChains stores chain summaries", async () => {
    mockedApi.getChains.mockResolvedValueOnce([
      {
        chain_id: "c1",
        command: "open calendar",
        tool_name: "calendar_tool",
        outcome: "executed_verified",
        execution_status: "executed",
        risk_level: "low",
        risk_color: "green",
        policy_verdict: "allow",
        approval_id: null,
        approval_status: "n/a",
        eval_status: "success",
        session_id: "sess-1",
        timestamp: "2026-04-14T10:00:00Z",
        changed_fields: [],
        state_after_summary: "ok",
      },
    ]);

    await useMissionControlStore.getState().fetchChains(20);

    const state = useMissionControlStore.getState();
    expect(mockedApi.getChains).toHaveBeenCalledWith(20);
    expect(state.chains).toHaveLength(1);
    expect(state.chains[0].chain_id).toBe("c1");
  });

  it("selectChain loads detail and checkpoints", async () => {
    mockedApi.getChainDetail.mockResolvedValueOnce({
      chain_id: "c2",
      command: "send email",
      tool_name: "email_tool",
      outcome: "approval_required",
      execution_status: "approval_required",
      risk_level: "high",
      risk_color: "red",
      policy_verdict: "allow",
      approval_id: 5,
      approval_status: "pending",
      eval_status: null,
      session_id: "sess-2",
      timestamp: "2026-04-14T10:01:00Z",
      changed_fields: [],
      state_after_summary: "",
      capability: null,
      policy_reason: "requires approval",
      state_before_summary: "",
      replay_steps: [],
      replay_final_status: null,
      replay_timeline_text: "",
    });

    mockedApi.getChainCheckpoints.mockResolvedValueOnce({
      chain_id: "c2",
      tool_name: "email_tool",
      command: "send email",
      total_checkpoints: 0,
      checkpoints: [],
    });

    await useMissionControlStore.getState().selectChain("c2");

    const state = useMissionControlStore.getState();
    expect(state.selectedChainId).toBe("c2");
    expect(state.chainDetail?.chain_id).toBe("c2");
    expect(state.checkpoints?.chain_id).toBe("c2");
  });

  it("selectChain(null) clears selection", async () => {
    await useMissionControlStore.getState().selectChain(null);
    const state = useMissionControlStore.getState();
    expect(state.selectedChainId).toBeNull();
    expect(state.chainDetail).toBeNull();
    expect(state.checkpoints).toBeNull();
  });
});
