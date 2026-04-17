/**
 * HTTP client for the FastAPI orchestrator backend.
 *
 * All requests go through this module so base URL and error handling
 * are centralised in one place.
 */

import type {
  AppSettings,
  ApprovalDecision,
  ApprovalRequest,
  AuditLog,
  BuilderTaskRequest,
  BuilderTaskResponse,
  CommandRequest,
  CommandResponse,
  ConnectResponse,
  ConnectorAccount,
  ConnectorActionRequest,
  ConnectorActionResponse,
  ConnectorManifest,
  ConnectorProvider,
  DisconnectResponse,
  OAuthCallbackRequest,
  OAuthCallbackResponse,
  CreateFileRequest,
  CreateFileResponse,
  FeatureFilesRequest,
  FeatureFilesResponse,
  MemoryContext,
  MemoryEntry,
  MemoryEntryCreate,
  MemoryEntryUpdate,
  PlanExecutionResponse,
  ProposeCommandsRequest,
  ProposeCommandsResponse,
  ProjectTreeResponse,
  ReadmeRequest,
  ReadmeResponse,
  ScaffoldRequest,
  ScaffoldResponse,
  SettingsUpdate,
  SuggestionCard,
  SynthesizeResponse,
  ToolMeta,
  TranscribeResponse,
  VoiceProviderInfo,
  WakeStatus,
  WakeSettings,
  WakeSettingsUpdate,
  WakeActivateRequest,
  WakeVerifyRequest,
  WakeResponse,
  VoiceCommandRequest,
  VoiceCommandResponse,
  ContextResponse,
  OperatorManifest,
  OperatorWindowsResponse,
  OperatorActionRequest,
  OperatorActionResponse,
  SecurityStatus,
  SetPinRequest,
  SetPinResponse,
  UnlockRequest,
  UnlockResponse,
  WorkflowRequest,
  WorkflowResult,
  SystemStatusResponse,
  CapabilityMeta,
  PolicyDecision,
  PolicyRule,
  WorldState,
  EvalEntry,
  EvalStats,
  VoiceConfirmation,
  ImprovementProposal,
  ChainSummary,
  SkillProposal,
  SkillProposalsResponse,
  SkillProposalScanResponse,
  // Phase 7: Skill Drafts
  SkillDraft,
  SkillDraftsResponse,
  GenerateDraftResponse,
  TestDraftResponse,
  DraftActionResponse,
  ChainDetail,
  CheckpointsResponse,
  SimulateRequest,
  SimulateResponse,
  // Phase 8: Autonomous Missions
  Mission,
  MissionCheckpoint,
  MissionsResponse,
  MissionCheckpointsResponse,
  // Phase 9: Installed Skills Registry
  InstalledSkillsResponse,
  InstalledSkillResponse,
  InstalledSkillVersionsResponse,
  InstalledCapabilitiesResponse,
  FinalizeInstallResponse,
  // Phase 10: Profiles
  ProfilesResponse,
  ProfileResponse,
  CreateProfileRequest,
  UpdateProfileRequest,
  // Phase 11: Modes
  ModesResponse,
  ModeResponse,
  SelectModesRequest,
  ModeSuggestionsResponse,
  CreateModeRequest,
} from "./types";

// import.meta.env typing can be missing in some environments; use any cast to avoid TS error
const BASE_URL = ((import.meta as any).env?.VITE_API_BASE_URL as string) ?? "http://127.0.0.1:8000";

export function getApiBaseUrl(): string {
  return BASE_URL;
}

// ─── Generic fetch wrapper ────────────────────────────────────────────────────

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }

  return response.json() as Promise<T>;
}

// ─── Health ───────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ status: string }> {
  return request("/api/v1/health");
}

// ─── Commands ─────────────────────────────────────────────────────────────────

export async function submitCommand(
  payload: CommandRequest
): Promise<CommandResponse> {
  return request("/api/v1/commands", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAvailableTools(): Promise<ToolMeta[]> {
  return request("/api/v1/tools");
}

// ─── Approvals ────────────────────────────────────────────────────────────────

export async function getPendingApprovals(): Promise<ApprovalRequest[]> {
  return request("/api/v1/approvals");
}

export async function decideApproval(
  approvalId: number,
  decision: ApprovalDecision
): Promise<ApprovalRequest> {
  return request(`/api/v1/approvals/${approvalId}`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

// ─── Settings ─────────────────────────────────────────────────────────────────

export async function getSettings(): Promise<AppSettings> {
  return request("/api/v1/settings");
}

export async function updateSettings(
  payload: SettingsUpdate
): Promise<AppSettings> {
  return request("/api/v1/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// ─── Audit Logs ───────────────────────────────────────────────────────────────

export async function getAuditLogs(limit = 100): Promise<AuditLog[]> {
  return request(`/api/v1/logs?limit=${limit}`);
}

// ─── Voice ────────────────────────────────────────────────────────────────────

/**
 * Transcribe an audio Blob captured from the microphone.
 *
 * Sends multipart/form-data so we must NOT set Content-Type manually
 * (the browser fills in the correct boundary automatically).
 */
export async function transcribeAudio(
  audio: Blob,
  language = "en"
): Promise<TranscribeResponse> {
  const form = new FormData();
  form.append("audio", audio, "recording.webm");
  form.append("language", language);

  const url = `${BASE_URL}/api/v1/voice/transcribe`;
  const response = await fetch(url, { method: "POST", body: form });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Transcribe error ${response.status}: ${detail}`);
  }
  return response.json() as Promise<TranscribeResponse>;
}

/**
 * Request speech synthesis for *text*.
 *
 * Returns a TranscribeResponse-like object.  When the provider is not
 * configured, ``audio_base64`` will be null and ``status`` will be
 * ``"provider_not_configured"``.
 */
export async function synthesizeSpeech(
  text: string,
  voice = "default",
  language = "en"
): Promise<SynthesizeResponse> {
  return request("/api/v1/voice/synthesize", {
    method: "POST",
    body: JSON.stringify({ text, voice, language }),
  });
}

/** Fetch the list of registered voice providers and their configuration status. */
export async function getVoiceProviders(): Promise<VoiceProviderInfo[]> {
  return request("/api/v1/voice/providers");
}

// ─── Setup / Languages
export async function getSupportedLanguages(): Promise<any[]> {
  return request("/api/v1/settings/languages");
}

// ─── Voice enrollment / verification (placeholder-backed)
export async function enrollStart(profileName = "Primary") {
  const res = await fetch(`${BASE_URL}/api/v1/voice/enroll/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_name: profileName }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function enrollSample(audio: Blob, profileId: number) {
  const form = new FormData();
  form.append("audio", audio, "sample.webm");
  form.append("profile_id", String(profileId));
  const url = `${BASE_URL}/api/v1/voice/enroll/sample`;
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function enrollFinish(profileId: number) {
  const form = new FormData();
  form.append("profile_id", String(profileId));
  const url = `${BASE_URL}/api/v1/voice/enroll/finish`;
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getVoiceProfile() {
  return request("/api/v1/voice/profile");
}

export async function deleteVoiceProfile() {
  const url = `${BASE_URL}/api/v1/voice/profile`;
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function verifySpeaker(audio: Blob) {
  const form = new FormData();
  form.append("audio", audio, "verify.webm");
  const url = `${BASE_URL}/api/v1/voice/verify`;
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Security (fallback unlock)
export async function unlockWithPin(payload: UnlockRequest): Promise<UnlockResponse> {
  return request("/api/v1/security/unlock", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function unlockWithPassphrase(phrase: string): Promise<UnlockResponse> {
  return request("/api/v1/security/unlock", {
    method: "POST",
    body: JSON.stringify({ method: "passphrase", value: phrase }),
  });
}

// ─── Plans ────────────────────────────────────────────────────────────────────

/**
 * Submit a command to the task planner.
 *
 * The backend will create an ExecutionPlan (1-step or multi-step) and run it
 * immediately, returning per-step results and an overall_status.
 */
export async function submitPlan(
  payload: CommandRequest
): Promise<PlanExecutionResponse> {
  return request("/api/v1/plans", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Resume a paused plan after the user approves the pending step.
 *
 * Re-sends the original command so the planner can reconstruct the plan and
 * continue from the approved step.
 */
export async function resumePlan(
  approvalId: number,
  payload: CommandRequest
): Promise<PlanExecutionResponse> {
  return request(`/api/v1/plans/resume/${approvalId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** List all tools registered on the backend (name, description, requires_approval). */
export async function getPlanTools(): Promise<ToolMeta[]> {
  return request("/api/v1/plans/tools");
}

// ─── Memory ───────────────────────────────────────────────────────────────────

export async function listMemory(
  category?: string,
  status?: string
): Promise<MemoryEntry[]> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (status) params.set("status", status);
  const qs = params.toString();
  return request(`/api/v1/memory${qs ? `?${qs}` : ""}`);
}

export async function createMemoryEntry(
  payload: MemoryEntryCreate
): Promise<MemoryEntry> {
  return request("/api/v1/memory", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateMemoryEntry(
  id: number,
  patch: MemoryEntryUpdate
): Promise<MemoryEntry> {
  return request(`/api/v1/memory/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteMemoryEntry(id: number): Promise<void> {
  const url = `${BASE_URL}/api/v1/memory/${id}`;
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API error ${response.status}: ${detail}`);
  }
}

export async function getMemorySuggestions(): Promise<SuggestionCard[]> {
  return request("/api/v1/memory/suggestions");
}

export async function getMemoryContext(
  command: string
): Promise<MemoryContext> {
  return request("/api/v1/memory/context", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

// ══════════════════════════════════════════════
// Research / Browser Operator
// ══════════════════════════════════════════════

import type {
  WebSearchResponse,
  SummarizeResponse,
  CompareResponse,
  ResearchBrief,
  ResearchRequest,
} from "./types";

export async function webSearch(
  query: string,
  max_results = 8
): Promise<WebSearchResponse> {
  return request("/api/v1/research/search", {
    method: "POST",
    body: JSON.stringify({ query, max_results }),
  });
}

export async function summarizeUrls(
  query: string,
  urls: string[],
  max_sources = 5
): Promise<SummarizeResponse> {
  return request("/api/v1/research/summarize", {
    method: "POST",
    body: JSON.stringify({ query, urls, max_sources }),
  });
}

export async function compareUrls(
  topic: string,
  urls: string[],
  max_sources = 6
): Promise<CompareResponse> {
  return request("/api/v1/research/compare", {
    method: "POST",
    body: JSON.stringify({ topic, urls, max_sources }),
  });
}

export async function researchBrief(
  payload: ResearchRequest
): Promise<ResearchBrief> {
  return request("/api/v1/research/brief", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Wake Word / Voice Session ────────────────────────────────────────────────

export async function getWakeStatus(): Promise<WakeStatus> {
  return request("/api/v1/wake/status");
}

export async function updateWakeSettings(payload: WakeSettingsUpdate): Promise<WakeSettings> {
  return request("/api/v1/wake/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function activateWake(payload: WakeActivateRequest = {}): Promise<WakeResponse> {
  return request("/api/v1/wake/activate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function verifyAndUnlock(payload: WakeVerifyRequest = {}): Promise<WakeResponse> {
  return request("/api/v1/wake/verify-and-unlock", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function lockWakeSession(): Promise<WakeResponse> {
  return request("/api/v1/wake/lock", { method: "POST", body: "{}" });
}

export async function sendVoiceCommand(
  payload: VoiceCommandRequest
): Promise<VoiceCommandResponse> {
  return request("/api/v1/voice/command", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getVoiceContext(): Promise<ContextResponse> {
  return request("/api/v1/voice/context", { method: "GET" });
}

export async function clearVoiceContext(): Promise<{ ok: boolean }> {
  return request("/api/v1/voice/context", { method: "DELETE" });
}

// ─── Builder Mode ─────────────────────────────────────────────────────────────

export async function scaffoldProject(payload: ScaffoldRequest): Promise<ScaffoldResponse> {
  return request("/api/v1/builder/scaffold", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createBuilderFile(payload: CreateFileRequest): Promise<CreateFileResponse> {
  return request("/api/v1/builder/file", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createReadme(payload: ReadmeRequest): Promise<ReadmeResponse> {
  return request("/api/v1/builder/readme", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateFeatureFiles(
  payload: FeatureFilesRequest
): Promise<FeatureFilesResponse> {
  return request("/api/v1/builder/feature", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getProjectTree(
  projectPath: string,
  maxDepth = 4
): Promise<ProjectTreeResponse> {
  const params = new URLSearchParams({
    project_path: projectPath,
    max_depth: String(maxDepth),
  });
  return request(`/api/v1/builder/tree?${params.toString()}`);
}

export async function proposeCommands(
  payload: ProposeCommandsRequest
): Promise<ProposeCommandsResponse> {
  return request("/api/v1/builder/commands", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runBuilderTask(payload: BuilderTaskRequest): Promise<BuilderTaskResponse> {
  return request("/api/v1/builder/task", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Account Connectors ──────────────────────────────────────────────────────

export async function getConnectors(): Promise<ConnectorAccount[]> {
  return request("/api/v1/connectors");
}

export async function getConnectorCapabilities(): Promise<ConnectorManifest[]> {
  return request("/api/v1/connectors/capabilities");
}

export async function initOAuth(
  provider: ConnectorProvider,
  redirectUri?: string
): Promise<ConnectResponse> {
  const params = new URLSearchParams({ provider });
  if (redirectUri) params.set("redirect_uri", redirectUri);
  return request(`/api/v1/connectors/oauth/init?${params.toString()}`);
}

export async function completeOAuth(
  payload: OAuthCallbackRequest
): Promise<OAuthCallbackResponse> {
  return request("/api/v1/connectors/oauth/callback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function disconnectConnector(
  accountId: number
): Promise<DisconnectResponse> {
  return request(`/api/v1/connectors/${accountId}`, { method: "DELETE" });
}

export async function runConnectorAction(
  accountId: number,
  payload: ConnectorActionRequest
): Promise<ConnectorActionResponse> {
  return request(`/api/v1/connectors/${accountId}/action`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Computer Operator ────────────────────────────────────────────────────────

export async function getOperatorCapabilities(): Promise<OperatorManifest> {
  return request("/api/v1/operator/capabilities");
}

export async function getOpenWindows(): Promise<OperatorWindowsResponse> {
  return request("/api/v1/operator/windows");
}

export async function runOperatorAction(
  payload: OperatorActionRequest
): Promise<OperatorActionResponse> {
  return request("/api/v1/operator/action", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Security ─────────────────────────────────────────────────────────────────

export async function getSecurityStatus(): Promise<SecurityStatus> {
  return request("/api/v1/security/status");
}

export async function setPin(payload: SetPinRequest): Promise<SetPinResponse> {
  return request("/api/v1/security/set_pin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Workflow ─────────────────────────────────────────────────────────────────

export async function runWorkflow(payload: WorkflowRequest): Promise<WorkflowResult> {
  return request("/api/v1/workflow/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getWorkflowStatus(workflowId: string): Promise<WorkflowResult> {
  return request(`/api/v1/workflow/status/${workflowId}`);
}

// ─── System Diagnostics ───────────────────────────────────────────────────────

export async function getSystemStatus(): Promise<SystemStatusResponse> {
  return request("/api/v1/system/status");
}

// ─── Capability Registry ──────────────────────────────────────────────────────

export async function getCapabilities(params?: { category?: string; risk_level?: string }): Promise<{
  capabilities: CapabilityMeta[];
  total: number;
}> {
  const q = new URLSearchParams();
  if (params?.category) q.set("category", params.category);
  if (params?.risk_level) q.set("risk_level", params.risk_level);
  const qs = q.toString() ? `?${q.toString()}` : "";
  return request(`/api/v1/capabilities${qs}`);
}

export async function getCapability(name: string): Promise<CapabilityMeta> {
  return request(`/api/v1/capabilities/${encodeURIComponent(name)}`);
}

export async function refreshCapabilities(): Promise<{ ok: boolean; total: number }> {
  return request("/api/v1/capabilities/refresh", { method: "POST" });
}

// ─── Policy Engine ────────────────────────────────────────────────────────────

export async function evaluatePolicy(action: string, params: Record<string, unknown>, commandText?: string): Promise<PolicyDecision> {
  return request("/api/v1/policy/evaluate", {
    method: "POST",
    body: JSON.stringify({ action, params, command_text: commandText ?? "" }),
  });
}

export async function getPolicyRules(): Promise<{ rules: PolicyRule[] }> {
  return request("/api/v1/policy/rules");
}

// ─── World State ──────────────────────────────────────────────────────────────

export async function getWorldState(): Promise<WorldState> {
  return request("/api/v1/state");
}

// ─── Evaluation System ────────────────────────────────────────────────────────

export async function getEvals(params?: { limit?: number; tool?: string }): Promise<{
  evals: EvalEntry[];
  total: number;
}> {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.tool) q.set("tool", params.tool);
  const qs = q.toString() ? `?${q.toString()}` : "";
  return request(`/api/v1/evals${qs}`);
}

export async function getEvalStats(sinceDays?: number, tool?: string): Promise<EvalStats> {
  const q = new URLSearchParams();
  if (sinceDays) q.set("since_days", String(sinceDays));
  if (tool) q.set("tool", tool);
  const qs = q.toString() ? `?${q.toString()}` : "";
  return request(`/api/v1/evals/stats${qs}`);
}

export async function rateEval(evalId: number, rating: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/evals/rate/${evalId}`, {
    method: "POST",
    body: JSON.stringify({ rating }),
  });
}

// ─── Voice Confirmation ───────────────────────────────────────────────────────

export async function listVoiceConfirmations(): Promise<{ confirmations: VoiceConfirmation[]; total: number }> {
  return request("/api/v1/voice/confirmations");
}

export async function respondToConfirmation(cid: string, responseText: string): Promise<{ ok: boolean; status: string }> {
  return request(`/api/v1/voice/confirmation/${cid}/respond`, {
    method: "POST",
    body: JSON.stringify({ response_text: responseText }),
  });
}

// ─── Self-Improvement ─────────────────────────────────────────────────────────

export async function getImprovementProposals(): Promise<{ proposals: ImprovementProposal[]; total: number }> {
  return request("/api/v1/self-improvement/proposals");
}

export async function triggerImprovementCycle(): Promise<{ ok: boolean; proposals_created: number }> {
  return request("/api/v1/self-improvement/cycle", { method: "POST" });
}

export async function approveImprovementProposal(proposalId: string): Promise<{ ok: boolean; message: string }> {
  return request(`/api/v1/self-improvement/proposals/${proposalId}/approve`, { method: "POST" });
}

export async function rejectImprovementProposal(proposalId: string): Promise<{ ok: boolean }> {
  return request(`/api/v1/self-improvement/proposals/${proposalId}/reject`, { method: "POST" });
}

// ─── Mission Control – Chains API (Phase 5) ───────────────────────────────────

/** List recent execution chains from the audit ring buffer. */
export async function getChains(limit = 30): Promise<ChainSummary[]> {
  return request(`/api/v1/chains?limit=${limit}`);
}

/** Get full detail for one execution chain (with replay steps). */
export async function getChainDetail(chainId: string): Promise<ChainDetail> {
  return request(`/api/v1/chains/${encodeURIComponent(chainId)}`);
}

/** Get checkpoint list for one execution chain. */
export async function getChainCheckpoints(chainId: string): Promise<CheckpointsResponse> {
  return request(`/api/v1/chains/${encodeURIComponent(chainId)}/checkpoints`);
}

/** Get the text timeline for a chain. */
export async function getChainTimeline(chainId: string): Promise<{ chain_id: string; timeline: string }> {
  return request(`/api/v1/replay/${encodeURIComponent(chainId)}/timeline`);
}

/** Dry-run simulate a list of planned steps. */
export async function simulateSteps(payload: SimulateRequest): Promise<SimulateResponse> {
  return request("/api/v1/replay/simulate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ─── Skill Proposals (Phase 6) ────────────────────────────────────────────────


/** List skill proposals, optionally filtered by status. */
export async function getSkillProposals(
  status?: "proposed" | "approved" | "rejected",
  limit = 50,
  includeDismissed = false,
): Promise<SkillProposalsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  if (includeDismissed) params.set("include_dismissed", "true");
  return request(`/api/v1/skill-proposals?${params.toString()}`);
}

/** Trigger a fresh pattern-detection scan. */
export async function scanSkillProposals(
  minFrequency = 3,
  minConfidence = 0,
): Promise<SkillProposalScanResponse> {
  const params = new URLSearchParams({
    min_frequency: String(minFrequency),
    min_confidence: String(minConfidence),
  });
  return request(`/api/v1/skill-proposals/scan?${params.toString()}`, {
    method: "POST",
  });
}

/** Approve a skill proposal (marks as accepted; installs nothing). */
export async function approveSkillProposal(
  proposalId: number,
): Promise<{ ok: boolean; message: string; proposal: SkillProposal }> {
  return request(`/api/v1/skill-proposals/${proposalId}/approve`, {
    method: "POST",
  });
}

/** Reject a skill proposal. */
export async function rejectSkillProposal(
  proposalId: number,
): Promise<{ ok: boolean; message: string; proposal: SkillProposal }> {
  return request(`/api/v1/skill-proposals/${proposalId}/reject`, {
    method: "POST",
  });
}

/** Record a feedback signal (useful / not_useful / ignored) on a proposal. */
export async function feedbackSkillProposal(
  proposalId: number,
  signal: "useful" | "not_useful" | "ignored",
): Promise<{ ok: boolean; message: string; proposal: SkillProposal }> {
  return request(`/api/v1/skill-proposals/${proposalId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signal }),
  });
}

/** Soft-hide (dismiss) a proposal so it is excluded from default list views. */
export async function dismissSkillProposal(
  proposalId: number,
): Promise<{ ok: boolean; message: string; proposal: SkillProposal }> {
  return request(`/api/v1/skill-proposals/${proposalId}/dismiss`, {
    method: "POST",
  });
}

// ─── Skill Drafts (Phase 7) ───────────────────────────────────────────────────

/**
 * Convert an approved SkillProposal into a SkillDraft.
 * The draft starts with status="draft" and must be tested before install.
 */
export async function generateSkillDraft(
  proposalId: number,
): Promise<GenerateDraftResponse> {
  return request(`/api/v1/skill-proposals/${proposalId}/generate`, {
    method: "POST",
  });
}

/** List all skill drafts, optionally filtered by proposalId. */
export async function listSkillDrafts(
  proposalId?: number,
  limit = 50,
  offset = 0,
): Promise<SkillDraftsResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (proposalId !== undefined) params.set("proposal_id", String(proposalId));
  return request(`/api/v1/skill-drafts?${params.toString()}`);
}

/** Get a single skill draft by ID. */
export async function getSkillDraft(draftId: number): Promise<{ draft: SkillDraft }> {
  return request(`/api/v1/skill-drafts/${draftId}`);
}

/**
 * Run sandbox validation on a draft's scaffold.
 * Safe – nothing in the scaffold is executed.
 */
export async function testSkillDraft(draftId: number): Promise<TestDraftResponse> {
  return request(`/api/v1/skill-drafts/${draftId}/test`, { method: "POST" });
}

/**
 * Approve a tested draft (requires passing sandbox test).
 * Does not install anything.
 */
export async function approveSkillDraft(draftId: number): Promise<DraftActionResponse> {
  return request(`/api/v1/skill-drafts/${draftId}/approve`, { method: "POST" });
}

/**
 * Request installation of an approved draft.
 * Creates an ApprovalRequest; nothing is executed automatically.
 */
export async function installSkillDraft(draftId: number): Promise<DraftActionResponse> {
  return request(`/api/v1/skill-drafts/${draftId}/install`, { method: "POST" });
}

/** Discard a skill draft (keeps record for audit; sets status=discarded). */
export async function discardSkillDraft(draftId: number): Promise<DraftActionResponse> {
  return request(`/api/v1/skill-drafts/${draftId}/discard`, { method: "POST" });
}

// ─── Phase 8: Autonomous Missions ────────────────────────────────────────────

/** Create a new mission in *planned* status. */
export async function createMission(body: {
  title: string;
  goal: string;
  total_steps?: number;
  budget_tokens?: number | null;
  budget_time_ms?: number | null;
  checkpoint_policy?: string;
  session_id?: string | null;
}): Promise<Mission> {
  return request("/api/v1/missions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** List missions, optionally filtered by status. */
export async function listMissions(
  status?: string,
  limit = 50,
): Promise<MissionsResponse> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return request(`/api/v1/missions?${params.toString()}`);
}

/** Get a single mission by ID. */
export async function getMission(missionId: number): Promise<Mission> {
  return request(`/api/v1/missions/${missionId}`);
}

/** Start a planned mission. */
export async function startMission(missionId: number): Promise<Mission> {
  return request(`/api/v1/missions/${missionId}/start`, { method: "POST" });
}

/** Pause a running mission. */
export async function pauseMission(
  missionId: number,
  reason = "",
): Promise<Mission> {
  return request(`/api/v1/missions/${missionId}/pause`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

/** Resume a paused mission. */
export async function resumeMission(missionId: number): Promise<Mission> {
  return request(`/api/v1/missions/${missionId}/resume`, { method: "POST" });
}

/** Cancel an active mission. */
export async function cancelMission(missionId: number): Promise<Mission> {
  return request(`/api/v1/missions/${missionId}/cancel`, { method: "POST" });
}

/** List checkpoints for a mission. */
export async function getMissionCheckpoints(
  missionId: number,
): Promise<MissionCheckpointsResponse> {
  return request(`/api/v1/missions/${missionId}/checkpoints`);
}

/** Resolve (approve or deny) a pending checkpoint. */
export async function resolveCheckpoint(
  missionId: number,
  checkpointId: number,
  approved: boolean,
): Promise<MissionCheckpoint> {
  return request(
    `/api/v1/missions/${missionId}/checkpoints/${checkpointId}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    },
  );
}

// ─── Phase 9: Installed Skills Registry ──────────────────────────────────────

/** List installed skills, optionally filtered by status. */
export async function listInstalledSkills(
  statusFilter?: string,
  limit = 100,
): Promise<InstalledSkillsResponse> {
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  params.set("limit", String(limit));
  return request(`/api/v1/installed-skills?${params}`);
}

/** Get a single installed skill by id. */
export async function getInstalledSkill(id: number): Promise<InstalledSkillResponse> {
  return request(`/api/v1/installed-skills/${id}`);
}

/** Get version history for a skill. */
export async function getInstalledSkillVersions(
  id: number,
): Promise<InstalledSkillVersionsResponse> {
  return request(`/api/v1/installed-skills/${id}/versions`);
}

/** Enable a disabled skill. */
export async function enableInstalledSkill(id: number): Promise<InstalledSkillResponse> {
  return request(`/api/v1/installed-skills/${id}/enable`, { method: "POST" });
}

/** Temporarily disable a skill. */
export async function disableInstalledSkill(id: number): Promise<InstalledSkillResponse> {
  return request(`/api/v1/installed-skills/${id}/disable`, { method: "POST" });
}

/** Roll back a skill to its previous version. */
export async function rollbackInstalledSkill(id: number): Promise<InstalledSkillResponse> {
  return request(`/api/v1/installed-skills/${id}/rollback`, { method: "POST" });
}

/** Permanently revoke a skill. */
export async function revokeInstalledSkill(
  id: number,
  reason?: string,
): Promise<InstalledSkillResponse> {
  return request(`/api/v1/installed-skills/${id}/revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason ?? "" }),
  });
}

/** Return enabled installed skills formatted as capability metadata. */
export async function getInstalledCapabilities(): Promise<InstalledCapabilitiesResponse> {
  return request(`/api/v1/installed-skills/capabilities`);
}

/** Finalize the installation of an approved skill draft. */
export async function finalizeSkillInstall(draftId: number): Promise<FinalizeInstallResponse> {
  return request(`/api/v1/skill-drafts/${draftId}/finalize`, { method: "POST" });
}

// ─── Phase 10: Profiles ───────────────────────────────────────────────────────

/** List all profiles, optionally filtered by status. */
export async function listProfiles(statusFilter?: string): Promise<ProfilesResponse> {
  const params = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return request(`/api/v1/profiles${params}`);
}

/** Fetch a single profile with stats. */
export async function getProfile(profileId: number): Promise<ProfileResponse> {
  return request(`/api/v1/profiles/${profileId}`);
}

/** Get the currently active profile. */
export async function getActiveProfile(): Promise<ProfileResponse> {
  return request(`/api/v1/profiles/active`);
}

/** Create a new profile. */
export async function createProfile(data: CreateProfileRequest): Promise<ProfileResponse> {
  return request(`/api/v1/profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Update name / description / security mode / meta. */
export async function updateProfile(
  profileId: number,
  data: UpdateProfileRequest,
): Promise<ProfileResponse> {
  return request(`/api/v1/profiles/${profileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Make this profile the active one. */
export async function activateProfile(profileId: number): Promise<ProfileResponse> {
  return request(`/api/v1/profiles/${profileId}/activate`, { method: "POST" });
}

/** Archive (soft-delete) a profile. */
export async function archiveProfile(profileId: number): Promise<ProfileResponse> {
  return request(`/api/v1/profiles/${profileId}/archive`, { method: "POST" });
}

// ─── Phase 11: Modes ─────────────────────────────────────────────────────────

/** List all modes, optionally filtered by category and/or status. */
export async function listModes(params?: {
  category?: string;
  status?: string;
  profile_id?: number;
}): Promise<ModesResponse> {
  const qs = params ? "?" + new URLSearchParams(
    Object.fromEntries(
      Object.entries(params)
        .filter(([, v]) => v != null)
        .map(([k, v]) => [k, String(v)])
    )
  ) : "";
  return request(`/api/v1/modes${qs}`);
}

/** Get all currently active modes for a profile. */
export async function getActiveModes(profileId?: number): Promise<ModesResponse> {
  const qs = profileId != null ? `?profile_id=${profileId}` : "";
  return request(`/api/v1/modes/active${qs}`);
}

/** Get mode suggestions based on usage history. */
export async function getModeSuggestions(
  profileId?: number,
  topK = 3
): Promise<ModeSuggestionsResponse> {
  const params = new URLSearchParams({ top_k: String(topK) });
  if (profileId != null) params.set("profile_id", String(profileId));
  return request(`/api/v1/modes/suggestions?${params}`);
}

/** Bulk-replace the active mode set for a profile (onboarding + settings). */
export async function selectModes(data: SelectModesRequest): Promise<ModesResponse> {
  return request(`/api/v1/modes/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Activate a single mode for a profile. */
export async function activateMode(
  modeId: number,
  profileId?: number
): Promise<ModeResponse> {
  const qs = profileId != null ? `?profile_id=${profileId}` : "";
  return request(`/api/v1/modes/${modeId}/activate${qs}`, { method: "POST" });
}

/** Deactivate a single mode for a profile. */
export async function deactivateMode(
  modeId: number,
  profileId?: number
): Promise<ModeResponse> {
  const qs = profileId != null ? `?profile_id=${profileId}` : "";
  return request(`/api/v1/modes/${modeId}/deactivate${qs}`, { method: "POST" });
}

/** Create a custom mode. */
export async function createMode(data: CreateModeRequest): Promise<ModeResponse> {
  return request(`/api/v1/modes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Archive (soft-delete) a custom mode. */
export async function archiveMode(modeId: number): Promise<ModeResponse> {
  return request(`/api/v1/modes/${modeId}/archive`, { method: "POST" });
}

// ── API Keys ──────────────────────────────────────────────────────────────────

export interface ApiKeyEntry {
  env_var: string;
  label: string;
  hint: string;
  is_set: boolean;
  masked_value: string;
}

export interface ApiKeysOut {
  keys: ApiKeyEntry[];
}

/** Fetch all API key statuses (masked values only). */
export async function getApiKeys(): Promise<ApiKeysOut> {
  return request("/api/v1/api-keys");
}

/** Save one or more API keys. Pass empty string to clear a key. */
export async function saveApiKeys(
  updates: Record<string, string>
): Promise<ApiKeysOut> {
  return request("/api/v1/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates }),
  });
}

// ── Payments / Token packages ─────────────────────────────────────────────────

export interface TokenPackage {
  id: string;
  name: string;
  price_eur: number;
  tokens: number;
  description: string;
  highlight: boolean;
}

export interface TokenBalance {
  user_id: number;
  email: string;
  balance: number;
  lifetime_purchased: number;
  lifetime_used: number;
  is_admin: boolean;
}

export interface TokenTransaction {
  id: number;
  amount: number;
  tx_type: string;
  description: string;
  balance_after: number;
  created_at: string;
}

/** Fetch all available token packages (no auth required). */
export async function getTokenPackages(): Promise<TokenPackage[]> {
  return request("/api/v1/payments/packages");
}

/** Create a Stripe checkout session and return the redirect URL. */
export async function createCheckoutSession(
  packageId: string
): Promise<{ checkout_url: string }> {
  return request("/api/v1/payments/create-checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package_id: packageId }),
  });
}

/** Fetch current user's token balance. */
export async function fetchTokenBalance(): Promise<TokenBalance> {
  return request("/api/v1/tokens/balance");
}

/** Fetch token transaction history. */
export async function fetchTokenHistory(): Promise<{ transactions: TokenTransaction[] }> {
  return request("/api/v1/tokens/history");
}
