/**
 * TypeScript type contracts shared between frontend components.
 * Mirror of the Python Pydantic schemas in services/orchestrator/app/schemas/.
 */

// ─── Commands ───────────────────────────────────────────────────────────────

export interface CommandRequest {
  command: string;
  context?: Record<string, unknown>;
}

export type ToolStatus = "success" | "error" | "approval_required";

export interface ToolResult {
  tool_name: string;
  status: ToolStatus;
  data?: unknown;
  message?: string;
}

export interface CommandResponse {
  command: string;
  result: ToolResult;
  approval_id?: number;
}

// ─── Approvals ──────────────────────────────────────────────────────────────

export type ApprovalStatus = "pending" | "approved" | "denied";

export interface ApprovalRequest {
  id: number;
  created_at: string;
  tool_name: string;
  command: string;
  params: Record<string, unknown>;
  status: ApprovalStatus;
}

export interface ApprovalDecision {
  decision: "approved" | "denied";
}

// ─── Settings ───────────────────────────────────────────────────────────────

export interface AppSettings {
  allowed_directories: string[];
  preferred_language: string;
  tts_enabled: boolean;
  tts_voice: string;
  tts_provider: string;
  ui_language: string;
  assistant_language: string;
  speech_recognition_language: string;
  speech_output_language: string;
  multilingual_enabled: boolean;
  // Voice layer
  voice_enabled: boolean;
  speaker_verification_enabled: boolean;
  voice_lock_enabled: boolean;
  security_mode: string;
  fallback_pin_enabled: boolean;
  fallback_passphrase_enabled: boolean;
  allow_text_access_without_voice_verification: boolean;
  require_verification_for_sensitive_actions_only: boolean;
  max_failed_voice_attempts: number;
  lock_on_failed_verification: boolean;
  first_run_complete: boolean;
  failed_voice_attempts: number;
  // Wake-word
  wake_word_enabled: boolean;
  primary_wake_phrase: string;
  secondary_wake_phrase: string;
  voice_session_timeout_seconds: number;
  require_reverification_after_timeout: boolean;
  wake_mode: WakeMode;
  // STT
  stt_enabled: boolean;
  stt_provider: string;
  max_audio_upload_seconds: number;
  max_audio_upload_mb: number;
}

export interface SettingsUpdate {
  allowed_directories?: string[];
  preferred_language?: string;
  tts_enabled?: boolean;
  tts_voice?: string;
  tts_provider?: string;
  ui_language?: string;
  assistant_language?: string;
  speech_recognition_language?: string;
  speech_output_language?: string;
  multilingual_enabled?: boolean;
  // Voice / security
  voice_enabled?: boolean;
  speaker_verification_enabled?: boolean;
  voice_lock_enabled?: boolean;
  security_mode?: string;
  fallback_pin_enabled?: boolean;
  fallback_passphrase_enabled?: boolean;
  allow_text_access_without_voice_verification?: boolean;
  require_verification_for_sensitive_actions_only?: boolean;
  max_failed_voice_attempts?: number;
  lock_on_failed_verification?: boolean;
  first_run_complete?: boolean;
  failed_voice_attempts?: number;
  // Wake-word
  wake_word_enabled?: boolean;
  primary_wake_phrase?: string;
  secondary_wake_phrase?: string;
  voice_session_timeout_seconds?: number;
  require_reverification_after_timeout?: boolean;
  wake_mode?: WakeMode;
  // STT
  stt_enabled?: boolean;
  stt_provider?: string;
  max_audio_upload_seconds?: number;
  max_audio_upload_mb?: number;
}

// ─── Voice ───────────────────────────────────────────────────────────────────

/** UI state of the microphone button. */
export type VoiceState = "idle" | "listening" | "processing";

/** Possible outcomes from the backend voice endpoints. */
export type VoiceStatus = "success" | "error" | "provider_not_configured";

/**
 * Fine-grained state machine for the push-to-talk recording flow.
 *
 *  idle          → user has not started recording
 *  requesting    → asking for mic permission
 *  recording     → MediaRecorder is capturing audio
 *  uploading     → audio blob being POSTed to /voice/transcribe
 *  transcribing  → waiting for backend STT response
 *  processing    → transcript received, sending to /voice/command
 *  done          → full round-trip complete
 *  error         → any step failed; sttError contains the message
 */
export type SttRecordingState =
  | "idle"
  | "requesting"
  | "recording"
  | "uploading"
  | "transcribing"
  | "processing"
  | "done"
  | "error";

/**
 * State machine for TTS audio playback.
 *
 *  idle     → no audio loaded / not playing
 *  loading  → synthesis request in-flight
 *  playing  → HTMLAudioElement.play() running
 *  paused   → paused mid-playback
 *  error    → synthesis or playback failed
 */
export type TtsPlaybackState = "idle" | "loading" | "playing" | "paused" | "error";

export interface TranscribeResponse {
  transcript: string;
  confidence: number | null;
  provider: string;
  status: VoiceStatus;
  message?: string;
  /** BCP-47 language code detected by the provider, if available. */
  detected_language?: string | null;
  /** Duration of the submitted audio in milliseconds, if available. */
  duration_ms?: number | null;
  /** 'configured' | 'not_configured' | 'error' */
  provider_status?: string;
}

export interface SynthesizeResponse {
  audio_base64: string | null;
  mime_type: string;
  provider: string;
  status: VoiceStatus;
  message?: string;
  /** Duration of the generated audio in milliseconds, if available. */
  duration_ms?: number | null;
  /** 'configured' | 'not_configured' | 'error' */
  provider_status?: string;
}

export interface VoiceProviderInfo {
  name: string;
  active: boolean;
  configured: boolean;
}

// ─── Audit Logs ─────────────────────────────────────────────────────────────

export interface AuditLog {
  id: number;
  timestamp: string;
  command: string;
  tool_name: string;
  status: string;
  result_summary?: string;
  error_message?: string;
}

// ─── Tool Metadata ───────────────────────────────────────────────────────────

export interface ToolMeta {
  name: string;
  description: string;
  requires_approval: boolean;
}

// ─── Chat UI ─────────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  input_mode?: "text" | "voice";
  render_mode?: "text" | "voice";
  result?: ToolResult;
  approval_id?: number;
  plan_response?: PlanExecutionResponse;
  /** Set when the plan contains research steps – convenience field for rendering */
  research_result?: ResearchStepData;
  /** Set when the response is a cross-tool WorkflowResult */
  workflow_result?: WorkflowResult;
  /** Filename of an attached file (user messages only) */
  attachedFileName?: string;
  /** True while the assistant is still streaming tokens */
  isStreaming?: boolean;
}

/** Aggregated research data extracted from step_results for easy rendering. */
export interface ResearchStepData {
  search?: WebSearchResponse;
  summary?: SummarizeResponse;
  comparison?: CompareResponse;
  brief?: ResearchBrief;
}

// ─── Task Planner ────────────────────────────────────────────────────────────

export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "approval_required"
  | "skipped";

export interface PlanStep {
  index: number;
  tool: string;
  description: string;
  args: Record<string, unknown>;
  requires_approval: boolean;
  status: StepStatus;
}

export interface ExecutionPlan {
  goal: string;
  steps: PlanStep[];
  is_multi_step: boolean;
}

export interface StepResult {
  step_index: number;
  tool: string;
  status: StepStatus;
  message?: string;
  data?: unknown;
  approval_id?: number;
}

export interface PlanExecutionResponse {
  command: string;
  plan: ExecutionPlan;
  step_results: StepResult[];
  overall_status: StepStatus;
  message?: string;
  tts_text?: string;
  memory_hints: string[];
}

// ─── Workflow ─────────────────────────────────────────────────────────────────

export type WorkflowArtifactType =
  | "file"
  | "email_draft"
  | "presentation"
  | "url_list"
  | "text_summary"
  | "calendar_event"
  | "project_scaffold"
  | "comparison"
  | "drive_file";

export interface WorkflowArtifact {
  type: WorkflowArtifactType;
  name: string;
  step_index: number;
  path?: string;
  url?: string;
  content?: string;
  metadata: Record<string, unknown>;
}

export interface WorkflowStepSummary {
  index: number;
  tool: string;
  description: string;
  status: StepStatus;
  message?: string;
  artifact?: WorkflowArtifact;
}

export type WorkflowStatus = "completed" | "failed" | "approval_required" | "partial";

export interface WorkflowResult {
  workflow_id: string;
  goal: string;
  overall_status: WorkflowStatus;
  steps: WorkflowStepSummary[];
  artifacts: WorkflowArtifact[];
  message: string;
  tts_text?: string;
  memory_hints: string[];
  requires_approval: boolean;
  approval_id?: number;
  created_at: string;
}

export interface WorkflowRequest {
  goal: string;
  context?: Record<string, unknown>;
  tts_response?: boolean;
  include_context?: boolean;
}

// ─── Memory ───────────────────────────────────────────────────────────────────

export type MemoryCategory =
  | "user_preferences"
  | "workflow_preferences"
  | "task_history"
  | "suggestions";

export type MemorySource =
  | "user_explicit"
  | "inferred_from_repeated_actions"
  | "settings_sync"
  | "executor_outcome";

export interface MemoryEntry {
  id: number;
  category: MemoryCategory;
  key: string;
  value: Record<string, unknown>;
  source: MemorySource;
  confidence: number;
  pinned: boolean;
  status: "active" | "dismissed";
  created_at: string;
  updated_at: string;
}

export interface MemoryEntryCreate {
  category: MemoryCategory;
  key: string;
  value: Record<string, unknown>;
  source?: MemorySource;
  confidence?: number;
  pinned?: boolean;
}

export interface MemoryEntryUpdate {
  value?: Record<string, unknown>;
  confidence?: number;
  pinned?: boolean;
  status?: "active" | "dismissed";
}

export interface SuggestionCard {
  entry_id: number;
  category: string;
  key: string;
  value: Record<string, unknown>;
  confidence: number;
  explanation: string;
}

export interface MemoryContext {
  entries: MemoryEntry[];
  hints: string[];
}

// ══════════════════════════════════════════════
// Research / Browser Operator types
// ══════════════════════════════════════════════

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  source_domain: string;
}

export interface WebSearchResponse {
  query: string;
  results: SearchResult[];
  total_results: number;
  error?: string;
}

export interface SourceSummary {
  url: string;
  title: string;
  snippet: string;
  fetched: boolean;
}

export interface SummarizeResponse {
  query: string;
  overall_summary: string;
  key_points: string[];
  sources: SourceSummary[];
  sources_attempted: number;
  sources_succeeded: number;
  error?: string;
}

export interface ComparedItem {
  name: string;
  url: string;
  scores: Record<string, number>;
  summary: string;
}

export interface CompareResponse {
  topic: string;
  criteria: string[];
  compared_items: ComparedItem[];
  conclusion: string;
  sources: string[];
  error?: string;
}

export interface ResearchBrief {
  query: string;
  summary: string;
  key_points: string[];
  top_sources: SearchResult[];
  comparison?: CompareResponse;
  raw_search?: WebSearchResponse;
  error?: string;
}

export interface ResearchRequest {
  query: string;
  max_sources?: number;
  include_comparison?: boolean;
}

// ─── Wake Word / Voice Session ────────────────────────────────────────────────

export type WakeVoiceState =
  | "idle"
  | "wake_detected"
  | "listening"
  | "verifying"
  | "unlocked"
  | "processing"
  | "responding"
  | "speaking"
  | "waiting_for_confirmation"
  | "blocked"
  | "timeout";

export type WakeMode =
  | "manual"
  | "push_to_talk"
  | "wake_phrase_placeholder"
  | "keyword_live"
  | "provider_ready";

export interface WakeSessionInfo {
  unlocked: boolean;
  unlocked_at: string | null;
  expires_at: string | null;
  seconds_remaining: number | null;
  session_id: string | null;
  last_activity_at?: string | null;
}

export interface WakeStatus {
  voice_state: WakeVoiceState;
  wake_mode: WakeMode;
  wake_word_enabled: boolean;
  primary_wake_phrase: string;
  secondary_wake_phrase: string;
  voice_session_timeout_seconds: number;
  require_reverification_after_timeout: boolean;
  session: WakeSessionInfo;
  security_mode: string;
}

export interface WakeSettings {
  wake_word_enabled: boolean;
  primary_wake_phrase: string;
  secondary_wake_phrase: string;
  voice_session_timeout_seconds: number;
  require_reverification_after_timeout: boolean;
  wake_mode: WakeMode;
}

export interface WakeSettingsUpdate {
  wake_word_enabled?: boolean;
  primary_wake_phrase?: string;
  secondary_wake_phrase?: string;
  voice_session_timeout_seconds?: number;
  require_reverification_after_timeout?: boolean;
  wake_mode?: WakeMode;
}

export interface WakeActivateRequest {
  phrase_heard?: string;
  mode_override?: WakeMode;
}

export interface WakeVerifyRequest {
  audio_base64?: string;
  bypass?: boolean;
}

export interface WakeResponse {
  ok: boolean;
  voice_state: WakeVoiceState;
  session: WakeSessionInfo;
  message: string;
  blocked_reason: string | null;
}

// ─── Voice Command (session-gated) ───────────────────────────────────────────

export interface VoiceCommandRequest {
  command: string;
  tts_response?: boolean;
  include_context?: boolean;
}

export interface VoiceStepResult {
  step_index: number;
  tool: string;
  status: string;
  message?: string;
}

export interface VoiceCommandResponse {
  ok: boolean;
  voice_state: WakeVoiceState;
  session: WakeSessionInfo;
  command: string;
  overall_status: string;
  message: string;
  step_results: VoiceStepResult[];
  tts_text: string | null;
  blocked_reason: string | null;
  was_interrupt: boolean;
  confirmation_prompt: string | null;
  context_turns: Array<{ role: string; text: string }>;
}

export interface ContextResponse {
  turns: Array<{ role: string; text: string }>;
  summary: string;
  session_id: string | null;
}

// ─── Builder Mode ────────────────────────────────────────────────────────────

export type ProjectTemplate =
  | "react"
  | "react-ts"
  | "nextjs"
  | "vite-react"
  | "fastapi"
  | "python-script"
  | "node-express"
  | "static-html"
  | "mobile-expo"
  | "generic";

export type CommandRisk = "safe" | "moderate" | "destructive";

export interface ProposedCommand {
  command: string;
  description: string;
  risk: CommandRisk;
  requires_approval: boolean;
  cwd?: string | null;
}

export interface GeneratedFile {
  path: string;
  content: string;
  is_new: boolean;
}

export interface ScaffoldRequest {
  name: string;
  template: ProjectTemplate;
  base_dir: string;
  description?: string;
  features?: string[];
}

export interface ScaffoldResponse {
  ok: boolean;
  project_path: string;
  files_created: string[];
  proposed_commands: ProposedCommand[];
  message: string;
  requires_approval?: boolean;
}

export interface CreateFileRequest {
  project_path: string;
  relative_path: string;
  content: string;
  overwrite?: boolean;
}

export interface CreateFileResponse {
  ok: boolean;
  absolute_path: string;
  message: string;
  requires_approval: boolean;
}

export interface ReadmeRequest {
  project_path: string;
  project_name: string;
  description?: string;
  template?: ProjectTemplate;
  features?: string[];
}

export interface ReadmeResponse {
  ok: boolean;
  absolute_path: string;
  content: string;
  message: string;
}

export interface FeatureFilesRequest {
  project_path: string;
  feature_description: string;
  template?: ProjectTemplate;
  output_dir?: string;
}

export interface FeatureFilesResponse {
  ok: boolean;
  files: GeneratedFile[];
  message: string;
}

export interface ProjectTreeNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: ProjectTreeNode[];
}

export interface ProjectTreeResponse {
  ok: boolean;
  root: ProjectTreeNode | null;
  message: string;
}

export interface ProposeCommandsRequest {
  project_path: string;
  template: ProjectTemplate;
  goal?: string;
}

export interface ProposeCommandsResponse {
  ok: boolean;
  commands: ProposedCommand[];
  message: string;
}

export interface BuilderTaskRequest {
  goal: string;
  template?: ProjectTemplate;
  project_name?: string;
  base_dir?: string;
  features?: string[];
}

export interface BuilderTaskResponse {
  ok: boolean;
  project_path: string | null;
  files_created: string[];
  files_updated: string[];
  proposed_commands: ProposedCommand[];
  summary: string;
  steps_taken: string[];
  requires_approval?: boolean;
}

// ─── Account Connectors ──────────────────────────────────────────────────────

export type ConnectorProvider = "google_drive" | "gmail" | "google_calendar";

export interface ConnectorCapability {
  name: string;
  description: string;
  requires_approval: boolean;
  required_scopes: string[];
  read_only: boolean;
}

export interface ConnectorManifest {
  provider: ConnectorProvider;
  display_name: string;
  icon: string;
  capabilities: ConnectorCapability[];
  auth_scopes: string[];
}

export interface ConnectorAccount {
  id: number;
  provider: ConnectorProvider;
  account_email: string;
  display_name: string;
  scopes_granted: string[];
  is_active: boolean;
  connected_at: string;
  last_used_at: string | null;
  last_error: string;
}

export interface ConnectResponse {
  ok: boolean;
  provider: ConnectorProvider;
  auth_url: string;
  state: string;
  message: string;
}

export interface OAuthCallbackRequest {
  provider: ConnectorProvider;
  code: string;
  state: string;
  redirect_uri: string;
}

export interface OAuthCallbackResponse {
  ok: boolean;
  account_id: number;
  provider: ConnectorProvider;
  account_email: string;
  scopes_granted: string[];
  message: string;
}

export interface DisconnectResponse {
  ok: boolean;
  message: string;
}

export interface ConnectorActionRequest {
  account_id: number;
  action: string;
  params: Record<string, unknown>;
}

export interface ConnectorActionResponse {
  ok: boolean;
  action: string;
  data: unknown;
  message: string;
  requires_approval: boolean;
  approval_id: number | null;
}

// ─── Computer Operator ──────────────────────────────────────────────────────

export type OperatorActionName =
  | "list_open_windows"
  | "open_app"
  | "focus_window"
  | "minimize_window"
  | "close_window"
  | "open_path"
  | "reveal_file"
  | "copy_to_clipboard"
  | "paste_clipboard"
  | "type_text"
  | "press_shortcut"
  | "take_screenshot";

export type OperatorRiskLevel = "low" | "medium" | "high";
export type OperatorPlatform = "macos" | "windows" | "linux" | "unknown";

export interface OperatorCapability {
  name: OperatorActionName;
  description: string;
  requires_approval: boolean;
  risk_level: OperatorRiskLevel;
  params_schema: Record<string, string>;
  supported_on: OperatorPlatform[];
}

export interface OperatorManifest {
  platform: OperatorPlatform;
  platform_available: boolean;
  capabilities: OperatorCapability[];
}

export interface WindowInfo {
  title: string;
  app: string;
  is_minimized: boolean;
  is_focused: boolean;
}

export interface OperatorWindowsResponse {
  ok: boolean;
  windows: WindowInfo[];
  message: string;
  platform: OperatorPlatform;
}

export interface OperatorActionRequest {
  action: OperatorActionName;
  params: Record<string, unknown>;
}

export interface OperatorActionResponse {
  ok: boolean;
  action: OperatorActionName;
  message: string;
  data: unknown;
  requires_approval: boolean;
  approval_id: number | null;
  platform: OperatorPlatform;
}

export interface RecentOperatorAction {
  action: OperatorActionName;
  params: Record<string, unknown>;
  response: OperatorActionResponse;
  timestamp: string;
}

// ─── Security ───────────────────────────────────────────────────────────────

export type ApprovalLevel =
  | "read_safe"
  | "write_requires_approval"
  | "destructive_requires_approval"
  | "security_sensitive_requires_approval";

export interface SecurityStatus {
  app_env: string;
  connector_encryption_configured: boolean;
  connector_encryption_uses_dev_key: boolean;
  secret_key_configured: boolean;
  speaker_verification_enabled: boolean;
  fallback_pin_enabled: boolean;
  fallback_pin_scheme: "argon2" | "sha256_legacy" | "none" | "unknown";
  fallback_passphrase_enabled: boolean;
  approval_policy_summary: Record<ApprovalLevel, number>;
  recent_security_events: SecurityEvent[];
}

export interface SecurityEvent {
  id: number;
  command: string;
  status: string;
  timestamp: string | null;
  error_message: string | null;
}

export interface SetPinRequest {
  pin: string;
}

export interface SetPinResponse {
  ok: boolean;
  message: string;
}

export interface UnlockRequest {
  method: "pin" | "passphrase";
  value: string;
}

export interface UnlockResponse {
  status: string;
  method: string;
  upgraded: boolean;
}

// ─── System Diagnostics ─────────────────────────────────────────────────────

export interface ComponentStatus {
  ok: boolean;
  label: string;
  detail?: string | null;
}

export interface SystemStatusResponse {
  ready: boolean;
  environment: ComponentStatus;
  database: ComponentStatus;
  encryption: ComponentStatus;
  openai_key: ComponentStatus;
  secret_key: ComponentStatus;
  voice_provider: ComponentStatus;
  stt: ComponentStatus;
  tts: ComponentStatus;
  voice_profile: ComponentStatus;
  connected_accounts: ComponentStatus;
  platform: ComponentStatus;
  app_env: string;
  app_version: string;
  python_version: string;
}

// ─── Capability Registry ─────────────────────────────────────────────────────

export interface RetryPolicy {
  max_retries: number;
  backoff_seconds: number;
}

export interface CapabilityMeta {
  name: string;
  description: string;
  risk_level: "low" | "medium" | "high" | "critical";
  requires_approval: boolean;
  allowed_accounts: string[];
  side_effects: string[];
  retry_policy: RetryPolicy;
  input_schema: Record<string, unknown>;
  category: string;
}

// ─── Policy Engine ────────────────────────────────────────────────────────────

export interface PolicyDecision {
  action: string;
  verdict: "allow" | "deny" | "require_approval";
  reason: string;
  risk_level: string;
}

export interface PolicyRule {
  priority: number;
  condition: string;
  verdict: string;
  description: string;
}

// ─── World State ──────────────────────────────────────────────────────────────

export interface AppInfo {
  name: string;
  pid?: number;
  is_frontmost: boolean;
}

export interface WindowInfo {
  app_name: string;
  title: string;
  window_id?: string;
  is_minimized: boolean;
}

export interface BrowserTab {
  url: string;
  title: string;
  active: boolean;
  added_at: string;
}

export interface RecentFile {
  path: string;
  tool: string;
  timestamp: string;
  operation: string;
}

export interface ActionRecord {
  tool: string;
  status: string;
  summary: string;
  timestamp: string;
  duration_ms?: number;
}

export interface PendingTask {
  task_id: string;
  description: string;
  tool: string;
  params: Record<string, unknown>;
  created_at: string;
  scheduled_at?: string;
}

export interface WorldState {
  updated_at: string;
  open_apps: AppInfo[];
  active_windows: WindowInfo[];
  recent_files: RecentFile[];
  browser_tabs: BrowserTab[];
  last_actions: ActionRecord[];
  pending_tasks: PendingTask[];
  clipboard_preview?: string;
  last_screenshot?: string;
}

// ─── Evaluation System ────────────────────────────────────────────────────────

export interface EvalEntry {
  id: number;
  timestamp: string;
  command: string;
  tool_name: string;
  status: string;
  duration_ms?: number;
  retries: number;
  required_approval: boolean;
  approval_granted?: boolean;
  risk_level?: string;
  policy_verdict?: string;
  quality_score?: number;
  error_message?: string;
  plan_id?: string;
}

export interface TopFailingTool {
  tool: string;
  errors: number;
  total: number;
  error_rate: number;
}

export interface EvalStats {
  period_days: number;
  total_tasks: number;
  success_count: number;
  failure_count: number;
  approval_count: number;
  retry_count: number;
  task_success_rate: number;
  task_failure_rate: number;
  approval_frequency: number;
  retry_rate: number;
  avg_execution_time_ms: number;
  avg_quality_score?: number;
  top_failing_tools: TopFailingTool[];
  daily_timeline: Record<string, { success: number; error: number; total: number }>;
}

// ─── Voice Confirmation ───────────────────────────────────────────────────────

export interface VoiceConfirmation {
  confirmation_id: string;
  prompt: string;
  approval_id?: number;
  action: string;
  risk_level: string;
  status: "pending" | "approved" | "denied" | "expired" | "modify";
  response_text?: string;
  created_at: string;
  expires_at: string;
  has_audio: boolean;
}

// ─── Self-Improvement ─────────────────────────────────────────────────────────

export interface ImprovementPattern {
  tool_name: string;
  failure_count: number;
  total_count: number;
  failure_rate: number;
  common_errors: string[];
  avg_duration_ms?: number;
}

export interface ImprovementProposal {
  proposal_id: string;
  pattern: ImprovementPattern;
  description: string;
  generated_code: string;
  test_code: string;
  status: "pending" | "sandbox_ok" | "sandbox_failed" | "approved" | "rejected" | "deployed";
  sandbox_output: string;
  test_output: string;
  sandbox_passed: boolean;
  tests_passed: boolean;
  approval_id?: number;
  created_at: string;
  plugin_path?: string;
}

// ─── Mission Control (Phase 5) ────────────────────────────────────────────────

/** Execution outcome enum mirroring backend OUTCOME_* constants. */
export type ChainOutcome =
  | "blocked"
  | "approval_required"
  | "executed_unverified"
  | "executed_verified"
  | "failed_retryable"
  | "failed_nonretryable"
  | "rolled_back"
  | "rollback_failed"
  | "unknown";

/** Risk color indicator for UI badges. */
export type RiskColor = "green" | "amber" | "red" | "grey";

/** Compact chain summary returned by GET /api/v1/chains. */
export interface ChainSummary {
  chain_id: string;
  command: string;
  tool_name: string;
  outcome: ChainOutcome;
  execution_status: string;
  risk_level: string;
  risk_color: RiskColor;
  policy_verdict: string;
  approval_id: number | null;
  approval_status: string;
  eval_status: string | null;
  session_id: string | null;
  timestamp: string;
  changed_fields: string[];
  state_after_summary: string;
}

/** One step extracted from replay data — used in chain detail drawer. */
export interface ReplayStep {
  step_number: number;
  action: string;
  inputs: Record<string, unknown>;
  result_status: string;
  result_summary: string;
  verification_verdict: string | null;
  state_delta_summary: string;
  failure_reason: string | null;
  timestamp: string;
  notes: string;
}

/** Full chain detail returned by GET /api/v1/chains/{chain_id}. */
export interface ChainDetail extends ChainSummary {
  capability: Record<string, unknown> | null;
  policy_reason: string;
  state_before_summary: string;
  // Replay enrichments
  replay_steps: ReplayStep[];
  replay_final_status: string | null;
  replay_timeline_text: string;
}

/** One simulated step from POST /api/v1/replay/simulate. */
export interface SimulatedStep {
  step_number: number;
  action: string;
  inputs: Record<string, unknown>;
  simulated_outcome: "would_succeed" | "would_require_approval" | "would_be_blocked" | "unknown";
  risk_level: string;
  approval_required: boolean;
  notes: string;
}

/** Checkpoint item from GET /api/v1/chains/{chain_id}/checkpoints. */
export interface ChainCheckpoint {
  step_number: number;
  action: string;
  result_status: string;
  result_summary: string;
  verification_verdict: string | null;
  failure_reason: string | null;
  state_delta_summary: string;
  timestamp: string;
  notes: string;
}

/** Response from GET /api/v1/chains/{chain_id}/checkpoints. */
export interface CheckpointsResponse {
  chain_id: string;
  tool_name: string;
  command: string;
  total_checkpoints: number;
  checkpoints: ChainCheckpoint[];
}

/** Request body for POST /api/v1/replay/simulate. */
export interface SimulateRequest {
  steps: Array<{ action: string; inputs: Record<string, unknown> }>;
}

/** Response from POST /api/v1/replay/simulate. */
export interface SimulateResponse {
  total_steps: number;
  steps: SimulatedStep[];
}


// ─── Skill Proposals (Phase 6 / 6.5) ─────────────────────────────────────────

/** One step in a skill proposal (mirrors PatternStep on the backend). */
export interface SkillProposalStep {
  tool_name: string;
  command_template: string;
}

/** Status of a skill proposal. */
export type SkillProposalStatus = "proposed" | "approved" | "rejected";

/** Phase 6.5 feedback signal type. */
export type SkillProposalFeedback = "useful" | "not_useful" | "ignored";

/** Risk level string shared with chains. */
export type RiskLevel = "low" | "medium" | "high" | "critical";

/** A detected recurring behaviour proposed as a skill shortcut. */
export interface SkillProposal {
  id: number;
  pattern_id: string;
  title: string;
  description: string;
  steps: SkillProposalStep[];
  estimated_time_saved: string | null;
  risk_level: RiskLevel;
  status: SkillProposalStatus;
  chain_ids: string[];
  frequency: number;
  confidence: number | null;
  created_at: string | null;
  // Phase 6.5 fields
  why_suggested: string | null;
  dismissed: boolean;
  feedback_score: number;
  feedback_count: number;
  last_feedback_at: string | null;
  relevance_score: number;
  suppressed_by: string | null;
}

/** Response from GET /api/v1/skill-proposals. */
export interface SkillProposalsResponse {
  proposals: SkillProposal[];
  total: number;
}

/** Response from POST /api/v1/skill-proposals/scan. */
export interface SkillProposalScanResponse {
  ok: boolean;
  proposals_created: number;
  proposals: SkillProposal[];
}

// ─── Phase 7: Skill Draft (Scaffold Generator) ────────────────────────────────

/** A single step inside a SkillSpec. */
export interface SkillSpecStep {
  step_index: number;
  tool_name: string;
  command_template: string;
  description: string;
  is_required: boolean;
}

/** Structured representation of what the skill does (before scaffolding). */
export interface SkillSpec {
  skill_id: string;
  name: string;
  description: string;
  steps: SkillSpecStep[];
  required_tools: string[];
  risk_level: RiskLevel;
  expected_inputs: string[];
  expected_outputs: string[];
  rationale: string;
  source_proposal_id: number;
  source_pattern_id: string;
  estimated_time_saved: string | null;
}

/** Lifecycle status of a SkillDraft. */
export type SkillDraftStatus =
  | "draft"
  | "tested"
  | "approved"
  | "install_requested"
  | "installed"
  | "discarded";

/** A single issue reported by the sandbox validator. */
export interface SandboxIssue {
  severity: "error" | "warning" | "info";
  location: string;
  message: string;
  suggestion?: string | null;
}

/** Full sandbox validation report attached to a SkillDraft after /test. */
export interface SandboxTestReport {
  passed: boolean;
  summary: string;
  error_count: number;
  warning_count: number;
  info_count: number;
  issues: SandboxIssue[];
}

/** A generated, inspectable automation draft derived from a SkillProposal. */
export interface SkillDraft {
  id: number;
  proposal_id: number;
  name: string;
  description: string;
  spec_json: SkillSpec;
  scaffold_json: Record<string, unknown>;
  scaffold_type: string;
  risk_level: RiskLevel;
  status: SkillDraftStatus;
  test_report: SandboxTestReport | null;
  tested_at: string | null;
  approval_request_id: number | null;
  installed_at: string | null;
  reviewed: boolean;
  created_at: string | null;
}

/** Response from POST /api/v1/skill-proposals/{id}/generate. */
export interface GenerateDraftResponse {
  ok: boolean;
  draft: SkillDraft;
}

/** Response from GET /api/v1/skill-drafts. */
export interface SkillDraftsResponse {
  drafts: SkillDraft[];
  total: number;
  limit: number;
  offset: number;
}

/** Response from POST /api/v1/skill-drafts/{id}/test. */
export interface TestDraftResponse {
  ok: boolean;
  draft: SkillDraft;
  report: SandboxTestReport;
}

/** Generic draft action response (approve / install / discard). */
export interface DraftActionResponse {
  ok: boolean;
  draft: SkillDraft;
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 8 – Autonomous Missions
// ─────────────────────────────────────────────────────────────────────────────

/** Lifecycle status of a Mission. */
export type MissionStatus =
  | "planned"
  | "running"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

/** How the mission generates human-approval checkpoints. */
export type CheckpointPolicy = "risky" | "always" | "never";

/** Lifecycle status of a MissionCheckpoint. */
export type CheckpointStatus = "pending" | "approved" | "denied" | "skipped";

/** A single autonomous mission. */
export interface Mission {
  id: number;
  title: string;
  goal: string;
  status: MissionStatus;
  current_step: number;
  total_steps: number;
  progress_percent: number;
  budget_tokens: number | null;
  budget_time_ms: number | null;
  tokens_used: number;
  elapsed_time_ms: number;
  checkpoint_policy: CheckpointPolicy;
  chain_ids: string[];
  session_id: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

/** A human-approval gate within a mission. */
export interface MissionCheckpoint {
  id: number;
  mission_id: number;
  step_index: number;
  reason: string;
  approval_required: boolean;
  status: CheckpointStatus;
  chain_id: string | null;
  summary: string | null;
  approval_request_id: number | null;
  created_at: string;
  resolved_at: string | null;
}

/** Response from GET /missions */
export interface MissionsResponse {
  total: number;
  missions: Mission[];
}

/** Response from GET /missions/{id}/checkpoints */
export interface MissionCheckpointsResponse {
  total: number;
  checkpoints: MissionCheckpoint[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 9 – Installed Skills Registry + Versioning
// ─────────────────────────────────────────────────────────────────────────────

/** Lifecycle status of an InstalledSkill. */
export type InstalledSkillStatus =
  | "installed"
  | "disabled"
  | "superseded"
  | "revoked";

/** A versioned registry entry for a fully-installed generated skill. */
export interface InstalledSkill {
  id: number;
  name: string;
  description: string;
  source_draft_id: number;
  source_proposal_id: number | null;
  current_version: string;
  rollback_version: string | null;
  status: InstalledSkillStatus;
  enabled: boolean;
  risk_level: string;
  spec_json: Record<string, unknown>;
  scaffold_json: Record<string, unknown>;
  last_used_at: string | null;
  use_count: number;
  installed_at: string | null;
  revoke_reason: string | null;
  created_at: string;
  updated_at: string | null;
}

/** An immutable version-history record for an InstalledSkill. */
export interface InstalledSkillVersion {
  id: number;
  skill_id: number;
  skill_name: string;
  version: string;
  /** install | upgrade | rollback | disable | enable | revoke */
  action: string;
  source_draft_id: number;
  spec_json: Record<string, unknown>;
  scaffold_json: Record<string, unknown>;
  risk_level: string;
  note: string | null;
  created_at: string;
}

/** Response from GET /installed-skills */
export interface InstalledSkillsResponse {
  ok: boolean;
  total: number;
  skills: InstalledSkill[];
}

/** Response from GET /installed-skills/{id}/versions */
export interface InstalledSkillVersionsResponse {
  ok: boolean;
  skill_id: number;
  versions: InstalledSkillVersion[];
}

/** Response from GET /installed-skills/{id} */
export interface InstalledSkillResponse {
  ok: boolean;
  skill: InstalledSkill;
}

/** Response from POST /skill-drafts/{id}/finalize */
export interface FinalizeInstallResponse {
  ok: boolean;
  draft: SkillDraft;
  skill: InstalledSkill;
}

/** Installed skill formatted as a capability metadata entry. */
export interface InstalledCapability {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  risk_level: string;
  version: string;
  source: "installed";
  enabled: boolean;
  installed_at: string | null;
}

/** Response from GET /installed-skills/capabilities */
export interface InstalledCapabilitiesResponse {
  ok: boolean;
  total: number;
  capabilities: InstalledCapability[];
}

// ─── Phase 10: Profiles ───────────────────────────────────────────────────────

export type ProfileType = "personal" | "work" | "team";
export type ProfileStatus = "active" | "inactive" | "archived";
export type SecurityMode = "standard" | "strict" | "permissive";

export interface ProfileStats {
  missions: number;
  skill_proposals: number;
  skill_drafts: number;
  installed_skills: number;
  approvals: number;
}

export interface Profile {
  id: number;
  name: string;
  slug: string;
  profile_type: ProfileType;
  status: ProfileStatus;
  is_active: boolean;
  description: string;
  default_security_mode: SecurityMode;
  meta_json: Record<string, unknown>;
  stats?: ProfileStats;
  created_at: string;
  updated_at: string | null;
}

export interface ProfilesResponse {
  ok: boolean;
  total: number;
  profiles: Profile[];
}

export interface ProfileResponse {
  ok: boolean;
  profile: Profile | null;
}

export interface CreateProfileRequest {
  name: string;
  profile_type?: ProfileType;
  description?: string;
  default_security_mode?: SecurityMode;
  meta_json?: Record<string, unknown>;
  activate?: boolean;
}

export interface UpdateProfileRequest {
  name?: string;
  description?: string;
  default_security_mode?: SecurityMode;
  meta_json?: Record<string, unknown>;
}

// ─── Phase 11: Modes ─────────────────────────────────────────────────────────

export type ModeCategory =
  | "productivity"
  | "development"
  | "research"
  | "creative"
  | "communication"
  | "personal"
  | "custom";

export type ModeStatus = "active" | "inactive" | "archived";

export interface Mode {
  id: number;
  slug: string;
  name: string;
  category: ModeCategory;
  icon: string;
  tagline: string;
  description: string;
  is_builtin: boolean;
  status: ModeStatus;
  system_prompt_hint: string;
  preferred_tools: string[];
  capability_tags: string[];
  meta_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ModesResponse {
  ok: boolean;
  total: number;
  modes: Mode[];
}

export interface ModeResponse {
  ok: boolean;
  mode: Mode;
}

export interface SelectModesRequest {
  mode_ids: number[];
  profile_id?: number;
}

export interface ModeSuggestion {
  mode: Mode;
  score: number;
  reason: string;
}

export interface ModeSuggestionsResponse {
  ok: boolean;
  suggestions: ModeSuggestion[];
}

export interface CreateModeRequest {
  name: string;
  description?: string;
  icon?: string;
  tagline?: string;
  system_prompt_hint?: string;
  preferred_tools?: string[];
  capability_tags?: string[];
  category?: ModeCategory;
  meta_json?: Record<string, unknown>;
}
