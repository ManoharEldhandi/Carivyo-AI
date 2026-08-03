export type Page = "jobs" | "applications" | "chat" | "profile";

export interface RuntimeModel {
  id: string;
  name: string;
  profile: "efficient" | "balanced" | "quality" | "local";
  recommended: boolean;
  detail?: string;
  reasoning_efforts?: ReasoningEffort[];
  use_cases?: string[];
}

export type ReasoningEffort = "none" | "low" | "medium" | "high";

export interface RuntimeProvider {
  id: string;
  name: string;
  kind: "cli" | "local_endpoint";
  available: boolean;
  authenticated?: boolean;
  supports_sessions: boolean;
  supports_usage: boolean;
  privacy: "local" | "provider" | "unknown";
  detail?: string;
  models: RuntimeModel[];
  selected_model?: string;
  selected_reasoning_effort?: string;
}

export interface RuntimeSelection {
  provider: string;
  model: string;
  reasoning_effort: ReasoningEffort;
  fully_local?: boolean;
}

export interface RuntimeExecution {
  fully_local: boolean;
  ready: boolean;
  boundary?: string;
}

export interface RuntimeState {
  providers: RuntimeProvider[];
  mode: string;
  selection: RuntimeSelection;
  execution?: RuntimeExecution;
}

export interface RuntimeSettingsResponse {
  providers: RuntimeProvider[];
  selection: RuntimeSelection;
  execution?: RuntimeExecution;
}

export interface OnboardingQuestion {
  id: string;
  prompt: string;
  reason: string;
  example?: string;
  skippable: boolean;
}

export interface OnboardingProfileReview {
  name: string;
  email?: string;
  phone?: string;
  links: string[];
  skills: string[];
  role_tracks: string[];
  highlights: string[];
}

export interface OnboardingState {
  session_id: string;
  status: string;
  summary: OnboardingProfileReview & {
    claim_count: number;
  };
  conflicts: Array<Record<string, unknown>>;
  question?: OnboardingQuestion;
  progress: { answered: number; total: number };
}

export interface MatchReason {
  code: string;
  text: string;
  evidence_ids: string[];
  job_span: string;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  description: string;
  location: string;
  work_mode?: string;
  employment_type?: string;
  salary?: {
    min?: number;
    max?: number;
    currency?: string;
    interval?: string;
    period?: string;
    text?: string;
  } | null;
  posted_at?: string;
  apply_url: string;
  source_url: string;
  source_family: string;
  live_state: string;
  freshness_class: string;
  verified_at: string;
  score: number;
  tier: "strong" | "good" | "possible" | "low";
  factors: Record<string, number>;
  reasons: MatchReason[];
  risks: string[];
  evidence_ids: string[];
  latest_feedback?: string;
}

export interface SearchContract {
  target_roles: string[];
  locations: string[];
  work_modes: string[];
  employment_types: string[];
  excluded_keywords: string[];
  excluded_locations: string[];
  freshness_hours: number;
  location_policy: "preference_order" | "strict" | string;
  role_policy: "expanded_early_career" | "strict" | string;
  freshness_policy?: "ranking" | "strict" | string;
  metadata_policy?: "include_unknown" | "strict" | string;
  seniority_policy?: "early_career" | "strict" | string;
  source_policy: "official_direct" | string;
  temporary_override?: {
    instruction: string;
    applied: Array<{ field: string; value: unknown }>;
    saved_preferences_changed: false;
  } | null;
}

export interface SearchCoverageSource {
  connector: string;
  status: "ok" | "failed" | string;
  count?: number;
  fetched?: number;
  eligible?: number;
  selected?: number;
  rejected?: number;
  rejected_by_reason?: Record<string, number>;
}

export interface SearchCoverage {
  sources?: SearchCoverageSource[];
  errors?: Array<Record<string, string>>;
  families?: Record<string, number>;
  freshness?: Record<string, number>;
  rejections?: Record<string, number>;
}

export interface LatestSearchRun {
  run_id?: string;
  status: SearchRun["status"] | "not_run";
  coverage: SearchCoverage;
  finished_at?: string | null;
}

export interface JobsPayload {
  jobs: Job[];
  count: number;
  freshness: Record<string, number>;
  locations: Record<string, number>;
  contract: SearchContract;
  latest_run: LatestSearchRun;
}

export interface Preference {
  id: string;
  key: string;
  value: unknown;
  kind: "hard" | "soft" | "negative";
  source: string;
  confidence: number;
}

export interface PreferenceSettings {
  target_roles: string[];
  preferred_locations: string[];
  preferred_industries: string[];
  preferred_companies: string[];
  excluded_companies: string[];
  priority_skills: string[];
  work_modes: Array<"remote" | "hybrid" | "onsite">;
  employment_types: Array<"full_time" | "part_time" | "contract" | "internship">;
  salary_min: number | null;
  salary_currency: string;
  salary_period: "hour" | "month" | "year";
  seniority_tolerance: string;
  excluded_keywords: string[];
  excluded_locations: string[];
  location_policy: "preference_order" | "strict";
  freshness_hours: number;
}

export interface PreferenceUpdateResponse {
  version: string;
  changed?: Array<Record<string, unknown>>;
  change?: Array<Record<string, unknown>>;
  search_plan: ProfilePayload["search_plan"] | Record<string, unknown>;
}

export interface ResumeIdentityValue {
  field: "name" | "email" | "phone" | "links";
  value: unknown;
}

export interface ResumeIdentityChange {
  field: "name" | "email" | "phone" | "links";
  before: unknown;
  after: unknown;
}

export interface ResumeListDiff {
  added: string[];
  removed: string[];
  changed: Array<{ before: string; after: string }>;
}

export interface ResumeProfileDiff {
  identity: {
    added: ResumeIdentityValue[];
    removed: ResumeIdentityValue[];
    changed: ResumeIdentityChange[];
  };
  skills: ResumeListDiff;
  role_tracks: ResumeListDiff;
  highlights: ResumeListDiff;
}

export interface ResumeRefreshPreview {
  draft_id: string;
  session_id: string;
  status: "needs_confirmation";
  summary: OnboardingProfileReview;
  diff: ResumeProfileDiff;
}

export interface ResumeRefreshConfirmResponse {
  draft_id: string;
  session_id: string;
  status: "confirmed";
  profile_version: string;
  preserved_preferences: true;
  summary: OnboardingProfileReview;
  diff: ResumeProfileDiff;
  profile: ProfilePayload;
  search_plan: Record<string, unknown>;
}

export interface ProfileUpdateRequest {
  identity: {
    name: string;
    email?: string;
    phone?: string;
    location?: string;
    links: string[];
  };
  skills: string[];
  role_families: string[];
  highlights: string[];
}

export interface ProfilePayload {
  id: string;
  version: string;
  profile: {
    identity: {
      name: string;
      email?: string;
      phone?: string;
      location?: string;
      links: string[];
    };
    skills: string[];
    role_families: string[];
    highlights: string[];
  };
  capsule: string;
  preferences: Preference[];
  evidence: Array<{
    id: string;
    category: string;
    text: string;
    source_location: string;
    confidence: number;
  }>;
  resume_bases: Array<{
    id: string;
    track: string;
    editable_kind: string;
    usable_for_tailoring: number;
  }>;
  search_plan?: {
    version: string;
    status: string;
    plan: Record<string, unknown>;
  };
}

export interface SearchRun {
  id: string;
  status: "queued" | "running" | "complete" | "partial" | "failed";
  stage: string;
  discovered_count: number;
  verified_count: number;
  ranked_count: number;
  coverage: SearchCoverage;
  error?: string;
}

export type ATSCheckStatus = "pass" | "warning" | "fail" | "not_applicable";

export interface ATSCheck {
  id: string;
  label: string;
  category: string;
  status: ATSCheckStatus;
  score: number;
  max_score: number;
  evidence: string[];
  suggestion: string;
}

export interface ATSCategorySummary {
  id: string;
  label: string;
  score: number;
  max_score: number;
  configured_max_score: number;
  percentage: number | null;
  applicable_checks: number;
  total_checks: number;
}

export interface ATSAnalysisBindings {
  jd_hash: string;
  pdf_hash: string;
  editable_source_hash: string;
  extracted_text_hash: string;
  variant: number;
  analysis_hash: string;
}

export interface ATSRequirementMatch {
  id: string;
  text: string;
  priority: "required" | "preferred" | "responsibility";
  category: string;
  entities: string[];
  match_status?: "direct" | "listed_only" | "transferable" | "unsupported";
  best_field?: string | null;
  matched_terms: string[];
  matched_entities: string[];
  demonstrated_entities: string[];
  entity_coverage?: number | null;
  lexical_coverage: number;
}

export interface ATSPerspective {
  id: string;
  label: string;
  status: "strong" | "review" | "needs_focus" | "blocked" | "insufficient_data";
  score: number | null;
  coverage?: number;
  confidence?: string;
  applicable_checks?: number;
  total_checks?: number;
  critical_failures?: string[];
  issues?: string[];
  required_score?: number | null;
  preferred_score?: number | null;
  responsibility_score?: number | null;
  counts?: Record<string, number>;
  requirement_count?: number;
  note?: string;
}

export interface ATSAnalysis {
  overall_score: number;
  parse_rate: number;
  category_summaries: ATSCategorySummary[];
  checks: ATSCheck[];
  critical_failures: string[];
  analyzer_version: string;
  disclaimer: string;
  scoring: {
    configured_max_score: number;
    applicable_max_score: number;
    earned_points: number;
    normalization_factor: number;
    not_applicable_check_ids: string[];
    rule: string;
  };
  protected_trait_policy: string;
  jd_quality?: {
    version: string;
    status: "complete" | "partial" | "insufficient";
    confidence: "high" | "medium" | "low" | "unavailable";
    word_count: number;
    requirement_count: number;
    required_count: number;
    preferred_count: number;
    responsibility_count: number;
    recognized_entity_count: number;
    recognized_entities: string[];
    reason: string;
    requirements: ATSRequirementMatch[];
  };
  structured_alignment?: {
    version: string;
    available: boolean;
    score: number | null;
    required_score: number | null;
    preferred_score: number | null;
    responsibility_score: number | null;
    counts: Record<"direct" | "listed_only" | "transferable" | "unsupported", number>;
    requirements: ATSRequirementMatch[];
  };
  assessment?: {
    version: string;
    status: ATSPerspective["status"];
    confidence: string;
    compatibility: ATSPerspective;
    evidence_alignment: ATSPerspective;
    content_quality: ATSPerspective;
    legacy_overall_score: number;
    legacy_score_deprecated: true;
    explanation: string;
  };
  report_summary: {
    readiness: "strong" | "review" | "needs_focus" | "blocked";
    status_counts: Record<ATSCheckStatus, number>;
    priority_actions: Array<{
      check_id: string;
      label: string;
      severity: "warning" | "fail";
      evidence: string[];
      suggestion: string;
    }>;
    strengths: Array<{
      check_id: string;
      label: string;
      evidence: string[];
    }>;
  };
  methodology: {
    feature_contract: string;
    score_scope: string;
    calibration_scope: string;
    human_review_required: boolean;
  };
  job_alignment: {
    available: boolean;
    target_title: string | null;
    hard_skills: { required: string[]; matched: string[]; missing: string[] };
    soft_skills: { required: string[]; matched: string[]; missing: string[] };
    action_verbs_present: string[];
    note: string;
  };
  recruiter_insights: {
    credibility_scope: string;
    interview_probes: Array<{
      kind: string;
      evidence: string;
      question: string;
      safe_action: string;
    }>;
    skill_evidence: {
      listed: string[];
      backed: string[];
      needs_evidence_review: string[];
      demonstrated_but_unlisted: string[];
    };
    safe_fix_policy: string;
  };
  bindings: ATSAnalysisBindings;
}

export interface ATSComparison {
  baseline_scope: string;
  baseline_score: number;
  current_score: number;
  score_delta: number;
  analyzer_version: string;
  categories: Array<{
    id: string;
    label: string;
    baseline: number | null;
    current: number | null;
    delta: number | null;
  }>;
}

export interface ATSEngine {
  id: "local" | "enhancv";
  label: string;
  available: boolean;
  external: boolean;
  configured: boolean;
  reason: string;
  sends_full_documents: boolean;
}

export interface ExternalATSReport {
  id: string;
  run_id: string;
  variant: number;
  resume_pdf_hash: string;
  job_description_hash: string;
  engine: "enhancv";
  status: "running" | "complete" | "failed";
  score?: number | null;
  error?: string | null;
  report: {
    ok?: boolean;
    provider?: string;
    mode?: string;
    score?: number | null;
    sections?: Record<string, string | number | null>;
    report_text?: string;
    blocker?: string | null;
    disclaimer?: string;
  };
  created_at?: string;
  updated_at?: string;
}

export interface ResumeSource {
  run_id: string;
  variant: number;
  language: "latex" | "markdown";
  editable: boolean;
  source: string;
  source_hash: string;
  filename: string;
}

export interface ATSSemanticFinding {
  category: string;
  severity: "info" | "low" | "medium" | "high";
  claim: string;
  resume_evidence: string;
  jd_evidence: string;
  recommendation: string;
  confidence: number;
  ai_assisted: true;
  evidence_verification: {
    status: "verified" | "unverified";
    resume_evidence: boolean;
    jd_evidence: boolean;
  };
}

export interface ATSSemanticReview {
  id: string;
  run_id: string;
  status: "running" | "complete" | "failed";
  provider: string;
  model: string;
  reasoning_effort: ReasoningEffort;
  error?: string | null;
  response?: {
    review_type: "ai_assisted_semantic";
    authoritative: false;
    disclaimer: string;
    findings: ATSSemanticFinding[];
    deterministic_reference: {
      overall_score: number;
      authoritative: true;
    };
  } | null;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    kind: string;
    latency_ms?: number | null;
  };
}

export interface ResumeRun {
  id: string;
  job_id: string;
  status: string;
  stage: string;
  mode: "build" | "tailor" | "audit" | "revise";
  interpretation: Array<Record<string, unknown>>;
  result: {
    status: string;
    source_compiler?: "tectonic" | "reportlab_fallback";
    editable_source_exact?: boolean;
    export_filename: string;
    mode: string;
    base_mode?: string;
    base_selection?: {
      score: number;
      rationale: string[];
      evaluated_base_count?: number;
    };
    approval?: {
      required: boolean;
      user_approved: boolean;
    };
    provenance?: Record<string, string>;
    custom_instruction_interpretation: Array<Record<string, unknown>>;
    coverage: Record<
      "direct" | "transferable" | "unsupported" | "unclear",
      Array<{
        requirement: string;
        classification: string;
        evidence_ids: string[];
      }>
    >;
    changes: Array<{
      type: string;
      before: string;
      after: string;
      evidence_ids: string[];
      reason: string;
    }>;
    validation: Record<string, unknown>;
    ats_analysis: ATSAnalysis;
    ats_comparison: ATSComparison;
    section_inventory?: Array<{
      id: string;
      label: string;
      expected: boolean;
      present: boolean;
      claim_count: number;
    }>;
    hiring_evaluation?: {
      status: "complete" | "unavailable" | "failed" | "disabled";
      version?: string;
      advisory: true;
      authoritative: false;
      provider?: string;
      model?: string | null;
    score?: number;
    max_score?: number;
    raw_model_score?: number;
    deterministic_ats_score?: number;
    score_basis?: string;
    verdict?: string;
      reason?: string;
      disclaimer?: string;
      dimensions: Array<{
        id: string;
        score: number;
        max: number;
        evidence_ids: string[];
        requirement_indices: number[];
        rationale: string;
        deterministic_baseline?: number;
        deterministic_evidence?: string[];
      }>;
      strengths: string[];
      concerns: string[];
      recommended_changes: string[];
      interview_probes: string[];
      missing_sections: string[];
      usage?: {
        input_tokens: number;
        output_tokens: number;
        cache_read_tokens: number;
        kind: string;
        latency_ms?: number;
      };
    };
    remaining_gaps: string[];
    interview_probes: string[];
    artifacts: Record<string, string>;
    variant: number;
  };
}

export interface ApplicationRecord {
  id: string;
  job_id: string;
  resume_run_id?: string;
  resume_variant?: number | null;
  resume_pdf_hash?: string | null;
  status: string;
  notes: string;
  title: string;
  company: string;
  location: string;
  apply_url: string;
  allowed_transitions: string[];
  created_at: string;
  updated_at: string;
}

export interface UsagePayload {
  totals: {
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    runs: number;
  };
  by_agent: Array<{
    agent: string;
    provider: string;
    usage_kind: string;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    runs: number;
  }>;
}
