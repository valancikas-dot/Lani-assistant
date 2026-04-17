/**
 * English (en) translations — source of truth for all translation keys.
 *
 * Structure mirrors the UI sections. Add new keys here first, then copy to
 * other locale files. Missing keys in other locales fall back to this file.
 */

export const en = {
  // ── Common ──────────────────────────────────────────────────────────────
  common: {
    save: "Save Settings",
    saving: "Saving…",
    loading: "Loading…",
    back: "Back",
    continue: "Continue",
    close: "Close",
    yes: "Yes",
    no: "No",
    unknown: "Unknown",
    active: "active",
    configured: "configured",
    not_configured: "not configured",
    enabled: "Enabled",
    disabled: "Disabled",
    cancel: "Cancel",
    create: "Create",
    edit: "Edit",
    confirm: "Confirm",
  },

  // ── Navigation / Sidebar ────────────────────────────────────────────────
  nav: {
    home: "Home",
    chat: "Chat",
    approvals: "Approvals",
    memory: "Memory",
    logs: "Logs",
    settings: "Settings",
    backend_online: "Backend online",
    backend_offline: "Backend offline",
    backend_connecting: "Connecting…",
    builder: "Builder",
    connectors: "Connectors",
    operator: "Operator",
    security: "Security",
    diagnostics: "Diagnostics",
    capabilities: "Capabilities",
    policies: "Policies",
    state: "World State",
    evals: "Evaluations",
    missions: "Missions",
    skill_proposals: "Skill Proposals",
    skill_drafts: "Skill Drafts",
    autonomous_missions: "Autonomous Missions",
    installed_skills: "Installed Skills",
    profiles: "Profiles",
    modes: "Modes",
  },

  // ── SetupWizard ─────────────────────────────────────────────────────────
  setup: {
    welcome_title: "Welcome to Lani",
    welcome_body:
      "Lani is a local-first personal AI assistant. This short setup will help you configure languages, voice and security preferences.",
    get_started: "Get started",
    choose_ui_language: "Choose UI language",
    choose_assistant_language: "Choose assistant language",
    speech_recognition_language: "Speech recognition language",
    speech_output_language: "Speech output language",
    language_hint: "Select your preferred language (you can change this later).",
    voice_step_title: "Voice & microphone",
    voice_step_body:
      "Voice features allow you to speak to Lani. You can enable or disable them here. Voice security can be configured in the next steps.",
    voice_enable_label: "Enable voice features",
    voice_enroll_title: "Voice enrollment",
    voice_enroll_body:
      "Record or upload 3–5 short voice samples (2–5 seconds each). These are stored locally. Speaker verification is currently in placeholder mode.",
    voice_enroll_start: "Start enrollment",
    voice_enroll_started: "Enrollment started. Upload 3–5 short samples.",
    voice_enroll_no_profile: "Start enrollment first.",
    voice_enroll_upload: "Upload samples & finish",
    security_title: "Security",
    security_body: "Select how strictly voice verification should be enforced.",
    security_passphrase_hint: "Optional passphrase (hint)",
    security_mode_disabled: "Disabled",
    security_mode_soft: "Soft verification (warn)",
    security_mode_strict: "Strict verification (block)",
    security_mode_sensitive: "Sensitive-only verification",
    allowed_folders_title: "Allowed folders",
    allowed_folders_body:
      "Specify folders Lani is allowed to access (one per line). You can change this later.",
    finish_title: "You're all set",
    finish_body: "Setup is complete. You can change these settings anytime from Settings.",
    finish_btn: "Finish and open Lani",
    finish_voice_enrolled: "enrolled (id={id})",
    finish_voice_not_enrolled: "not enrolled",
    finish_voice_profile: "Voice profile:",
  },

  // ── ChatPage ────────────────────────────────────────────────────────────
  chat: {
    title: "Chat",
    subtitle: "Type a command and Lani will get it done.",
    empty_greeting: "👋 Hello! I'm Lani, your personal AI assistant.",
    empty_try: "Try commands like:",
    input_placeholder: "Ask Lani to do something…",
    send: "Send",
    command_examples: [
      "create folder ~/Desktop/Projects",
      "summarize ~/Documents/report.pdf",
      "sort downloads in ~/Downloads",
      'create presentation "Q1 Review" with outline Sales, Engineering, Marketing',
    ],
  },

  // ── ApprovalsPage ───────────────────────────────────────────────────────
  approvals: {
    title: "Pending Approvals",
    subtitle: "The following actions require your confirmation before executing.",
    no_pending: "✅ No pending approvals.",
    command_label: "Command:",
    parameters: "Parameters",
    approve: "✅ Approve",
    deny: "❌ Deny",
    voice_approval_allowed: "Voice approval allowed for this risk level.",
  },

  // ── LogsPage ────────────────────────────────────────────────────────────
  logs: {
    title: "Action Logs",
    refresh: "↻ Refresh",
    no_logs: "No actions logged yet.",
    col_id: "#",
    col_time: "Time",
    col_tool: "Tool",
    col_status: "Status",
    col_command: "Command",
    col_summary: "Summary",
  },

  // ── MemoryPage ──────────────────────────────────────────────────────────
  memory: {
    title: "Memory",
    add_entry: "+ Add",
    no_entries: "No memory entries yet.",
    suggestions_title: "💡 Suggestions",
    confidence: "confidence",
    accept: "✔ Accept",
    dismiss: "✖ Dismiss",
    pin: "Pin",
    key: "Key",
    value: "Value",
    source: "Source",
    actions: "Actions",
    edit: "Edit",
    delete: "Delete",
    add_form_title: "Add Memory Entry",
    category_label: "Category",
    key_label: "Key",
    value_label: "Value",
    add_btn: "Add",
    category_user_preferences: "👤 User Preferences",
    category_workflow_preferences: "⚙️ Workflow Preferences",
    category_task_history: "📋 Task History",
    category_suggestions: "💡 Suggestions",
    source_user_explicit: "User",
    source_inferred: "Inferred",
    source_settings_sync: "Settings",
    source_executor_outcome: "Executor",
  },

  // ── SettingsPage ────────────────────────────────────────────────────────
  settings: {
    title: "Settings",
    // Allowed dirs
    allowed_dirs_title: "Allowed Directories",
    allowed_dirs_hint:
      "One absolute path per line. The assistant can only access files inside these directories.",
    allowed_dirs_placeholder: "/Users/you/Desktop\n/Users/you/Downloads",
    // Voice
    voice_title: "Voice",
    voice_enable: "Enable microphone & TTS playback",
    voice_hint:
      "When enabled a 🎙 button appears in the chat bar (push-to-talk). Audio is transcribed by the configured STT provider. Responses can be spoken back using the configured TTS provider.",
    voice_language_label: "Language",
    voice_voice_label: "Voice",
    voice_no_provider_hint:
      "No provider configured yet — responses will return status: provider_not_configured. Set VOICE_PROVIDER=openai (plus OPENAI_API_KEY) in services/orchestrator/.env to enable real STT/TTS.",
    // STT
    stt_title: "Speech-to-Text (STT)",
    mic_label: "Microphone:",
    mic_granted: "✓ Permission granted",
    mic_denied: "✗ Permission denied",
    mic_not_requested: "Permission not yet requested",
    mic_denied_hint:
      "Microphone access was denied. Please allow it in your OS/browser settings and reload the app.",
    stt_provider_label: "STT Provider:",
    stt_enable: "Enable speech-to-text (push-to-talk transcription)",
    stt_disabled_hint:
      "When disabled, the push-to-talk mic button will not upload audio. The assistant can still be used via typed commands.",
    max_recording_label: "Max recording length (seconds)",
    max_upload_label: "Max audio upload size (MB)",
    stt_provider_hint:
      "To enable a real STT provider set VOICE_PROVIDER=openai and OPENAI_API_KEY in services/orchestrator/.env, then restart the backend. See docs/voice-integration.md.",
    // TTS
    tts_title: "Text-to-Speech (TTS)",
    tts_provider_label: "TTS Provider:",
    tts_enable: "Enable text-to-speech (auto-play assistant replies)",
    tts_hint:
      "When enabled, assistant responses are automatically spoken after voice commands. You can also click the 🔊 button on any chat bubble to replay.",
    tts_voice_label: "Voice",
    tts_provider_override_label: "Provider override",
    tts_provider_override_hint:
      "Override the server-level TTS provider for this user. Leave empty to use the VOICE_PROVIDER env setting.",
    tts_provider_override_placeholder: "Leave empty to use server default",
    // Language
    language_title: "Preferred Language",
    language_hint: "Used for AI responses (separate from voice language above).",
    // UI Language
    ui_language_title: "UI Language",
    ui_language_hint: "Controls the language of this app's interface.",
    ui_language_label: "Interface language",
    // Assistant Language
    assistant_language_title: "Assistant Language",
    assistant_language_hint: "Default language the assistant uses for replies.",
    // Wake word
    wake_title: "Wake Word",
    wake_placeholder_badge: "Placeholder",
    wake_hint:
      "Activate Lani hands-free. Current implementation supports manual and keyword-match modes. True always-on wake-word detection requires a provider integration (not yet available).",
    wake_enable: "Enable wake-word / voice session",
    wake_mode_label: "Wake Mode",
    wake_mode_manual: "Manual (button press)",
    wake_mode_ptt: "Push-to-talk",
    wake_mode_phrase: "⚠️ Keyword match (not always-on)",
    wake_mode_keyword_live: "🎙 Always-on (say \"Lani\")",
    wake_mode_provider: "Always-on provider (coming soon)",
    wake_primary_phrase_label: "Primary Wake Phrase",
    wake_secondary_phrase_label: "Secondary Wake Phrase",
    wake_session_timeout_label: "Session Timeout (seconds)",
    wake_reverify_label: "Require re-verification after session timeout",
  },

  // ── WakeControls ────────────────────────────────────────────────────────
  wake: {
    disabled_hint: "Wake word is disabled. Enable it in Settings → Voice → Wake Word.",
    mode_manual: "Manual mode — press Activate to start a session.",
    mode_ptt: "Push-to-talk — hold the mic button while speaking.",
    mode_phrase: "⚠️ Keyword match — NOT always-on. Type the wake phrase to activate.",
    mode_keyword_live: "🎙 Always-on — say \"Lani\" to activate hands-free.",
    mode_provider: "Always-on wake-word provider (not yet integrated).",
    activate: "🎙 Activate Lani",
    activating: "Activating…",
    activate_ptt: "🎙 Activate (push-to-talk)",
    verify_unlock: "🔓 Verify & Unlock",
    verifying: "Verifying…",
    lock_session: "🔒 Lock Session",
    locking: "Locking…",
    send: "Send",
    sending: "…",
    command_placeholder: "Type a command…",
    phrase_placeholder: 'Say "{phrase}"',
    blocked_prefix: "🚫",
    timeout_msg: "⏰ Session timed out. Press Activate to start a new session.",
    reverification_required_msg:
      "🔐 Session expired. Re-verification is required to continue. Click Verify & Unlock or re-activate.",
    reverification_link_text: "Verify & Unlock",
    stt_not_configured:
      "Speech-to-text provider not configured. Set VOICE_PROVIDER in the backend .env file, or type your command instead.",
    stt_nothing_heard: "Nothing was heard. Please speak clearly and try again.",
    stt_too_long: "Recording is too long. Please keep it under the configured limit.",
    stt_disabled: "Audio upload failed – speech-to-text may be disabled.",
    stt_upload_failed: "Audio upload failed:",
    processing: "Processing command…",
  },

  // ── SessionIndicator ─────────────────────────────────────────────────────
  session: {
    active: "🔓 Session active",
    expires_in: "expires in",
    expired: "🔒 Session expired — re-activate",
    reverification_required: "🔐 Re-verification required",
  },

  // ── PushToTalkButton ─────────────────────────────────────────────────────
  ptt: {
    blocked: "🚫 Blocked",
    idle: "Hold to talk",
    requesting: "Requesting mic…",
    recording: "🎙 Recording…",
    uploading: "Uploading…",
    transcribing: "Transcribing…",
    processing: "Processing…",
    done: "Done ✓",
    error: "Error – tap to dismiss",
    tap_to_talk: "Tap to talk",
    release_to_send: "Release to send",
    permission_denied: "Microphone permission denied",
    permission_denied_detail:
      "Please allow microphone access in your system settings, then reload the app.",
    hold_instruction: "Hold to record · Release to send",
  },

  // ── Status badges ────────────────────────────────────────────────────────
  status: {
    success: "success",
    error: "error",
    blocked: "blocked",
    unlocked: "unlocked",
    locked: "locked",
    timeout: "session expired",
    processing: "processing",
    uploading: "uploading",
    recording: "recording",
    approval_required: "approval required",
    unrecognised: "unrecognised",
    completed: "completed",
    idle: "idle",
    verifying: "verifying",
    responding: "responding",
  },

  // ── Builder Mode ─────────────────────────────────────────────────────────
  builder: {
    title: "Builder",
    subtitle: "Describe a project and Lani will scaffold it for you.",
    describe_project: "Describe your project",
    goal_label: "What do you want to build?",
    goal_placeholder: "e.g. Create a React todo app with authentication",
    template_label: "Template",
    advanced: "Advanced options",
    project_name_label: "Project name (optional)",
    project_name_placeholder: "my-app",
    base_dir_label: "Output directory (optional)",
    base_dir_placeholder: "~/Desktop",
    features_label: "Features / pages to generate",
    features_placeholder: "e.g. UserProfile, Dashboard",
    build_btn: "🏗️ Build Project",
    building: "Building…",
    reset_btn: "Start over",
    steps_title: "Steps taken",
    files_title: "Files created",
    tree_title: "Project tree",
    tree_loading: "Loading tree…",
    commands_title: "Proposed commands",
    commands_note: "These commands are proposed, not executed. Copy and run them manually.",
    approval_required: "approval required",
  },

  // ── Account Connectors ────────────────────────────────────────────────────
  connectors: {
    title: "Connectors",
    subtitle: "Connect external accounts so Lani can access them on your behalf.",
    connected_accounts: "Connected accounts",
    available_providers: "Available providers",
    no_accounts: "No accounts connected yet.",
    connect_btn: "Connect",
    disconnect_btn: "Disconnect",
    reconnect_btn: "Reconnect",
    connecting: "Connecting…",
    disconnecting: "Disconnecting…",
    connected_as: "Connected as",
    last_used: "Last used",
    last_used_never: "Never",
    scopes_title: "Granted permissions",
    capabilities_title: "Capabilities",
    read_only: "Read-only",
    requires_approval: "Requires approval",
    error_state: "Last error",
    oauth_instructions:
      "Click Connect to open the provider's authorisation page. After approving, you will be redirected back.",
    disconnect_confirm: "Disconnect this account? All stored tokens will be deleted.",
    providers: {
      google_drive: "Google Drive",
      gmail: "Gmail",
      google_calendar: "Google Calendar",
    },
  },

  // ── Computer Operator ─────────────────────────────────────────────────────
  operator: {
    title: "Operator",
    subtitle: "Let Lani perform desktop actions on your behalf.",
    platform_label: "Platform",
    platform_unavailable: "Desktop automation is not yet supported on this platform.",
    capabilities_title: "Available actions",
    quick_actions_title: "Quick actions",
    windows_title: "Open windows",
    refresh_windows: "Refresh",
    recent_title: "Recent actions",
    clear_recent: "Clear",
    screenshot_btn: "Take screenshot",
    screenshot_saved: "Screenshot saved to",
    list_windows_btn: "List windows",
    open_app_btn: "Open app",
    open_app_placeholder: "App name (e.g. Safari)",
    open_app_submit: "Open",
    approval_required_badge: "Approval required",
    risk_low: "Low risk",
    risk_medium: "Medium risk",
    risk_high: "High risk",
    action_ok: "Done",
    action_failed: "Failed",
    action_approval_sent: "Awaiting approval",
    no_recent: "No recent actions.",
    executing: "Executing…",
    params_schema_title: "Parameters",
    supported_on: "Supported on",
  },

  // ── Security ─────────────────────────────────────────────────────────────
  security: {
    title: "Security",
    subtitle: "Security posture and access controls for Lani.",
    environment: "Environment & Keys",
    connector_encryption: "Connector Token Encryption",
    configured: "Configured",
    not_configured: "Not configured (dev key)",
    speaker_verification: "Speaker Verification",
    fallback_pin: "Fallback PIN",
    set_pin: "Set PIN",
    update_pin: "Update PIN",
    pin_placeholder: "Enter PIN",
    confirm_pin_placeholder: "Confirm PIN",
    pin_saved: "PIN saved successfully.",
    pin_mismatch: "PINs do not match.",
    approval_policy: "Approval Policy",
    recent_events: "Recent Security Events",
    no_events: "No recent security events.",
  },

  // ── Voice UX ─────────────────────────────────────────────────────────────
  voice_ux: {
    speaking: "Speaking…",
    waiting_for_confirmation: "Waiting for your confirmation",
    follow_up_hint: "Session active — say a follow-up command or press the mic",
    stop_speaking: "Stop speaking",
    replay_last: "Replay last response",
    interrupted: "Stopped.",
    clear_context: "Clear context",
    confirmation_banner: "Approval needed — confirm via the approvals panel",
    states: {
      idle: "Idle",
      wake_detected: "Wake detected",
      listening: "Listening…",
      verifying: "Verifying…",
      processing: "Processing…",
      responding: "Responding…",
      speaking: "Speaking…",
      waiting_for_confirmation: "Awaiting confirmation",
      unlocked: "Active",
      blocked: "Blocked",
      timeout: "Session expired",
    },
  },

  // ── Workflow ─────────────────────────────────────────────────────────────
  workflow: {
    goal: "Goal",
    steps: "Steps",
    artifacts: "Artifacts",
    summary: "Summary",
    step_completed: "Completed",
    step_failed: "Failed",
    step_pending: "Pending",
    step_approval: "Awaiting approval",
    status_completed: "Workflow complete",
    status_failed: "Workflow failed",
    status_partial: "Partially complete",
    status_approval_required: "Approval required",
    artifact_file: "File",
    artifact_email_draft: "Email Draft",
    artifact_presentation: "Presentation",
    artifact_url_list: "Sources",
    artifact_text_summary: "Summary",
    artifact_calendar_event: "Calendar Event",
    artifact_project_scaffold: "Project",
    artifact_comparison: "Comparison",
    artifact_drive_file: "Drive File",
    run_workflow: "Run Workflow",
    approval_needed: "One step requires your approval before continuing.",
    no_artifacts: "No artifacts produced.",
  },

  // ── Diagnostics / System Status ──────────────────────────────────────────
  diagnostics: {
    title: "System Status",
    subtitle: "Live readiness report for all Lani subsystems.",
    refresh: "↻ Refresh",
    overall_ready: "All systems ready",
    overall_not_ready: "Some systems need attention",
    status_ok: "OK",
    status_warning: "Warning",
    status_error: "Error",
    // Component labels
    environment: "Environment",
    database: "Database",
    encryption: "Token Encryption",
    openai_key: "OpenAI API Key",
    secret_key: "Secret Key",
    voice_provider: "Voice Provider",
    stt: "Speech-to-Text",
    tts: "Text-to-Speech",
    voice_profile: "Voice Profile",
    connected_accounts: "Connected Accounts",
    platform: "Platform",
    // Frontend-only checks
    microphone: "Microphone",
    mic_granted: "Permission granted",
    mic_denied: "Permission denied — allow in system settings",
    mic_not_requested: "Permission not yet requested",
    backend_connection: "Backend Connection",
    backend_online: "Online",
    backend_offline: "Offline — start the backend with ./scripts/start-backend.sh",
    backend_connecting: "Connecting…",
    // App metadata
    app_version: "App Version",
    python_version: "Python Version",
    app_env: "App Environment",
    // Hints
    hint_no_openai: "Set OPENAI_API_KEY in services/orchestrator/.env to enable AI features.",
    hint_no_voice: "Set VOICE_PROVIDER=openai in .env and OPENAI_API_KEY to enable voice.",
    hint_no_encryption: "Set CONNECTOR_ENCRYPTION_KEY in .env before connecting real accounts.",
    hint_no_profile: "Enroll a voice profile in Settings → Security.",
    hint_dev_mode: "Running in development mode. Some features use placeholder implementations.",
  },

  // ── Mission Control ──────────────────────────────────────────────────────
  mission_control: {
    title: "Mission Control",
    subtitle: "Observe, replay and audit every execution chain.",
    no_chains: "No execution chains recorded yet.",
    refresh: "Refresh",
    auto_refresh: "Auto-refresh",
    loading_detail: "Loading chain detail…",
    loading_checkpoints: "Loading checkpoints…",
    error_load: "Failed to load chains.",
    error_detail: "Failed to load chain detail.",
    pending_approvals: "pending approval",
    pending_approvals_plural: "pending approvals",
    go_to_approvals: "Review approvals",
    // Chain detail labels
    command: "Command",
    tool: "Tool",
    risk: "Risk",
    outcome: "Outcome",
    policy_verdict: "Policy",
    policy_reason: "Policy reason",
    eval_status: "Eval status",
    approval_status: "Approval",
    session: "Session",
    timestamp: "Time",
    changed_fields: "Changed fields",
    state_before: "State before",
    state_after: "State after",
    replay_timeline: "Replay timeline",
    replay_steps: "Replay steps",
    checkpoints: "Checkpoints",
    simulate: "Dry-run simulate",
    simulate_running: "Simulating…",
    simulate_result: "Simulation result",
    no_replay: "No replay data available.",
    no_checkpoints: "No checkpoints recorded.",
    proof_panel: "Browser proofs",
    no_proofs: "No browser proofs for this chain.",
    // Outcome labels
    outcome_blocked: "Blocked",
    outcome_approval_required: "Awaiting approval",
    outcome_executed_unverified: "Executed (unverified)",
    outcome_executed_verified: "Executed ✓",
    outcome_failed_retryable: "Failed (retryable)",
    outcome_failed_nonretryable: "Failed",
    outcome_rolled_back: "Rolled back",
    outcome_rollback_failed: "Rollback failed",
    outcome_unknown: "Unknown",
    // Risk labels
    risk_low: "Low",
    risk_medium: "Medium",
    risk_high: "High",
    risk_critical: "Critical",
    risk_unknown: "Unknown",
    // Simulated step outcome labels
    sim_would_succeed: "Would succeed",
    sim_would_require_approval: "Would require approval",
    sim_would_be_blocked: "Would be blocked",
    sim_unknown: "Unknown",
    // Step fields
    step_action: "Action",
    step_inputs: "Inputs",
    step_result: "Result",
    step_verification: "Verification",
    step_failure: "Failure reason",
    step_delta: "State delta",
    step_notes: "Notes",
  },

  // ── Errors ───────────────────────────────────────────────────────────────
  errors: {
    mic_permission_denied: "Microphone permission denied.",
    stt_not_configured:
      "Speech-to-text provider is not configured. Please set VOICE_PROVIDER in the backend .env.",
    tts_not_configured:
      "Text-to-speech provider is not configured. Please set VOICE_PROVIDER in the backend .env.",
    session_expired: "Voice session has expired. Please re-activate.",
    reverification_required: "Voice session expired. Please verify again.",
    session_locked: "Voice session is locked. Activate Lani first.",
    fetch_failed: "Failed to fetch data.",
    save_failed: "Failed to save settings.",
    unknown_error: "An unexpected error occurred.",
  },

  // ── Profiles (Phase 10) ─────────────────────────────────────────────────
  profiles: {
    title: "Profiles",
    subtitle: "Manage isolated workspaces for different contexts",
    new_profile: "New Profile",
    no_profiles: "No profiles yet. Create one to get started.",
    name: "Name",
    type: "Type",
    type_personal: "Personal",
    type_work: "Work",
    type_team: "Team",
    description: "Description",
    security_mode: "Security mode",
    security_standard: "Standard",
    security_strict: "Strict",
    security_permissive: "Permissive",
    activate_on_create: "Activate immediately",
    active: "active",
    activate: "Activate",
    archive: "Archive",
    stat_missions: "Missions",
    stat_skills: "Skills",
    stat_proposals: "Proposals",
  },

  // ── Onboarding (Phase 11) ────────────────────────────────────────────────
  onboarding: {
    title: "Welcome to Lani",
    subtitle: "Your personal AI assistant",
    step_welcome: "Welcome",
    step_modes: "Choose Modes",
    step_ready: "You're Ready",
    get_started: "Get Started",
    skip: "Skip",
    select_modes_title: "What do you use Lani for?",
    select_modes_subtitle: "Choose one or more modes to personalise your experience. You can change this later.",
    finish: "Start Using Lani",
    welcome_body: "Lani adapts to how you work. Select a mode to tailor AI suggestions, tool priorities, and context.",
    ready_title: "You're all set!",
    ready_body: "Lani is ready. You can change your active modes anytime from the Modes page.",
  },

  // ── Modes (Phase 11) ─────────────────────────────────────────────────────
  modes: {
    title: "Modes",
    subtitle: "Manage active operational contexts",
    active_label: "Active",
    activate: "Activate",
    deactivate: "Deactivate",
    custom_label: "Custom",
    no_active: "No modes active. Activate a mode to tailor Lani to your context.",
    suggestions_title: "Suggested for you",
    category_productivity: "Productivity",
    category_development: "Development",
    category_research: "Research",
    category_creative: "Creative",
    category_communication: "Communication",
    category_personal: "Personal",
    category_custom: "Custom",
    create_custom: "Create custom mode",
    archive_confirm: "Archive this mode? It will no longer appear in suggestions.",
    builtin_badge: "Built-in",
    new_mode_name: "Mode name",
    new_mode_description: "Description",
    new_mode_tagline: "Short tagline",
    new_mode_hint: "System prompt hint (optional)",
    save: "Save",
  },
} as const;

/** Literal-typed shape (the `as const` object). Used internally by the i18n engine. */
export type Translations = typeof en;

/** Key names at the top namespace level. */
export type TranslationKey = keyof Translations;

// ── Utility types ──────────────────────────────────────────────────────────

/** Recursively replaces all leaf values with `string`.  Used so that locale
 *  files can declare their own strings without being constrained to the exact
 *  English literals produced by `as const`. */
type DeepString<T> = {
  [K in keyof T]: T[K] extends readonly string[]
    ? readonly string[]
    : T[K] extends object
    ? DeepString<T[K]>
    : string;
};

/** Recursively makes every property optional. */
type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends readonly string[]
    ? readonly string[] | string[]
    : T[K] extends object
    ? DeepPartial<T[K]>
    : T[K];
};

/** The shape that all non-English locale files must satisfy.
 *  Every key is optional (missing keys fall back to English at runtime). */
export type LocaleDefinition = DeepPartial<DeepString<Translations>>;
