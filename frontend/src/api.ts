import type {
  ApplicationRecord,
  ATSAnalysis,
  ATSEngine,
  ExternalATSReport,
  ATSSemanticReview,
  Job,
  JobsPayload,
  OnboardingProfileReview,
  OnboardingState,
  PreferenceSettings,
  PreferenceUpdateResponse,
  ProfilePayload,
  ProfileUpdateRequest,
  ResumeRefreshConfirmResponse,
  ResumeRefreshPreview,
  ResumeRun,
  ResumeSource,
  RuntimeSelection,
  RuntimeSettingsResponse,
  RuntimeState,
  SearchRun,
  UsagePayload
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";
let sessionToken = "";
const BOOTSTRAP_STORAGE_KEY = "carivyo-bootstrap-token";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function initializeSession(): Promise<void> {
  const bootstrapToken = localBootstrapToken();
  const response = await fetch(`${API_BASE}/api/session`, {
    credentials: "omit",
    headers: {
      Accept: "application/json",
      ...(bootstrapToken ? { "X-Carivyo-Bootstrap": bootstrapToken } : {})
    }
  });
  if (!response.ok) {
    if (response.status === 401) {
      window.sessionStorage.removeItem(BOOTSTRAP_STORAGE_KEY);
    }
    let detail = "Could not establish the local Carivyo session.";
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // The local service may be unavailable rather than returning JSON.
    }
    throw new ApiError(response.status, detail);
  }
  sessionToken = (await response.json()).token;
}

function localBootstrapToken(): string {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const launched = hash.get("bootstrap") ?? "";
  if (launched) {
    window.sessionStorage.setItem(BOOTSTRAP_STORAGE_KEY, launched);
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    return launched;
  }
  return (
    import.meta.env.VITE_CARIVYO_BOOTSTRAP_TOKEN ??
    window.sessionStorage.getItem(BOOTSTRAP_STORAGE_KEY) ??
    ""
  );
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  responseType: "json" | "blob" = "json",
  allowSessionRefresh = true
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Carivyo-Session", sessionToken);
  if (!(init.body instanceof FormData) && init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", responseType === "blob" ? "*/*" : "application/json");
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "omit"
  });
  if ([401, 403].includes(response.status) && allowSessionRefresh) {
    await initializeSession();
    return request<T>(path, init, responseType, false);
  }
  if (!response.ok) {
    let detail = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // The fallback message remains useful for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return (responseType === "blob" ? response.blob() : response.json()) as Promise<T>;
}

export const api = {
  runtimes: () => request<RuntimeState>("/api/runtime/providers"),
  updateRuntimeSettings: (selection: RuntimeSelection) =>
    request<RuntimeSettingsResponse>("/api/runtime/settings", {
      method: "PATCH",
      body: JSON.stringify(selection)
    }),
  profile: () =>
    request<ProfilePayload | { onboarding_required: true }>("/api/profile"),
  updateProfile: (profile: ProfileUpdateRequest) =>
    request<ProfilePayload>("/api/profile", {
      method: "PATCH",
      body: JSON.stringify(profile)
    }),
  updatePreferences: (preferences: PreferenceSettings) =>
    request<PreferenceUpdateResponse>("/api/preferences", {
      method: "PATCH",
      body: JSON.stringify(preferences)
    }),
  previewResumeReplacement: (file: File) => {
    const form = new FormData();
    form.append("resume", file);
    return request<ResumeRefreshPreview>("/api/profile/resume/preview", {
      method: "POST",
      body: form
    });
  },
  confirmResumeReplacement: (draftId: string, profileReview: OnboardingProfileReview) =>
    request<ResumeRefreshConfirmResponse>("/api/profile/resume/confirm", {
      method: "POST",
      body: JSON.stringify({ draft_id: draftId, profile_review: profileReview })
    }),
  importResume: (file: File) => {
    const form = new FormData();
    form.append("resume", file);
    return request<OnboardingState>("/api/onboarding/import", {
      method: "POST",
      body: form
    });
  },
  answerOnboarding: (sessionId: string, questionId: string, answer: string) =>
    request<{
      status: string;
      interpreted_answer: Record<string, unknown>;
      question?: OnboardingState["question"];
      progress: OnboardingState["progress"];
    }>("/api/onboarding/message", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        question_id: questionId,
        answer
      })
    }),
  confirmOnboarding: (sessionId: string, profileReview: OnboardingProfileReview) =>
    request<{
      profile_version: string;
      preference_version: string;
      search_plan_version: string;
      search_run_id?: string;
    }>("/api/onboarding/confirm", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        start_search: true,
        profile_review: profileReview
      })
    }),
  createSearch: (temporaryInstruction?: string) =>
    request<SearchRun>("/api/search-runs", {
      method: "POST",
      body: JSON.stringify({ temporary_instruction: temporaryInstruction || null })
    }),
  searchRun: (id: string) => request<SearchRun>(`/api/search-runs/${id}`),
  jobs: () => request<JobsPayload>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  verifyJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/verify`, { method: "POST", body: "{}" }),
  feedback: (id: string, action: string, reason?: string) =>
    request(`/api/jobs/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ action, reason })
    }),
  createResume: (jobId: string, customInstructions: string) =>
    request<ResumeRun>(`/api/jobs/${jobId}/resume-runs`, {
      method: "POST",
      body: JSON.stringify({ custom_instructions: customInstructions })
    }),
  latestResumeRun: (jobId: string) =>
    request<{ run: ResumeRun | null }>(`/api/jobs/${jobId}/resume-runs/latest`),
  resumeRun: (id: string) => request<ResumeRun>(`/api/resume-runs/${id}`),
  reviseResume: (id: string, message: string) =>
    request<ResumeRun>(`/api/resume-runs/${id}/message`, {
      method: "POST",
      body: JSON.stringify({ message })
    }),
  approveResume: (id: string) =>
    request<ResumeRun>(`/api/resume-runs/${id}/approve`, {
      method: "POST",
      body: "{}"
    }),
  atsAnalysis: (runId: string) =>
    request<ATSAnalysis>(`/api/resume-runs/${runId}/ats-analysis`),
  atsEngines: () =>
    request<{ engines: ATSEngine[]; default: "local" }>("/api/ats/engines"),
  createEnhancvReport: (runId: string, confirmedExternalProcessing: boolean) =>
    request<ExternalATSReport>(`/api/resume-runs/${runId}/ats-reports/enhancv`, {
      method: "POST",
      body: JSON.stringify({
        confirmed_external_processing: confirmedExternalProcessing
      })
    }),
  enhancvReport: (runId: string) =>
    request<{ report: ExternalATSReport | null }>(
      `/api/resume-runs/${runId}/ats-reports/enhancv`
    ),
  resumeSource: (runId: string) =>
    request<ResumeSource>(`/api/resume-runs/${runId}/source`),
  updateResumeSource: (runId: string, source: string, instruction: string) =>
    request<ResumeRun>(`/api/resume-runs/${runId}/source`, {
      method: "PUT",
      body: JSON.stringify({ source, instruction })
    }),
  createAtsSemanticReview: (runId: string, confirmedFullDocumentProcessing: boolean) =>
    request<ATSSemanticReview>(`/api/resume-runs/${runId}/ats-semantic-review`, {
      method: "POST",
      body: JSON.stringify({
        provider: "auto",
        confirmed_full_document_processing: confirmedFullDocumentProcessing
      })
    }),
  artifact: (
    runId: string,
    kind: "pdf" | "source" | "render" | "validation" | "ats"
  ) =>
    request<Blob>(`/api/resume-runs/${runId}/artifact/${kind}`, {}, "blob"),
  prepareApplication: (jobId: string, resumeRunId?: string, notes = "") =>
    request<ApplicationRecord>(`/api/jobs/${jobId}/prepare-application`, {
      method: "POST",
      body: JSON.stringify({ resume_run_id: resumeRunId, notes })
    }),
  openApply: (jobId: string) =>
    request<{
      application: ApplicationRecord;
      official_url: string;
      warning: string;
    }>(`/api/jobs/${jobId}/open-apply`, { method: "POST", body: "{}" }),
  applications: () =>
    request<{ applications: ApplicationRecord[]; count: number }>(
      "/api/applications"
    ),
  updateApplication: (id: string, status: string, notes?: string) =>
    request<ApplicationRecord>(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, notes })
    }),
  sendChat: (payload: {
    conversation_id?: string;
    message: string;
    selected_job_id?: string;
    current_page?: string;
    provider?: string;
    model?: string;
    use_ai?: boolean;
  }) =>
    request<{
      conversation_id: string;
      message_id: string;
      content: string;
      provider: string;
      model: string;
      usage: {
        input_tokens: number;
        output_tokens: number;
        cache_read_tokens: number;
        kind: string;
        session_reused?: boolean;
        context: Array<{
          name: string;
          tokens: number;
        }>;
      };
      intent: string;
      search_requested: boolean;
      search_run_id?: string;
      preference_confirmation?: {
        id: string;
        summary: string;
      };
    }>("/api/chat/messages", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  chatHistory: (id: string) =>
    request<{
      conversation: {
        id: string;
        provider?: string;
        model?: string;
        [key: string]: string | undefined;
      };
      messages: Array<{
        id: string;
        role: "user" | "assistant";
        content: string;
        created_at: string;
        entity_refs?: Record<string, unknown>;
      }>;
    }>(`/api/chat/conversations/${id}`),
  decidePreferenceChange: (id: string, accept: boolean) =>
    request<{
      id: string;
      status: "applied" | "rejected";
      summary: string;
      search_requested: boolean;
      search_run_id?: string;
    }>(`/api/chat/preference-changes/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ accept })
    }),
  usage: () => request<UsagePayload>("/api/ai-usage"),
  backup: () =>
    request<{ filename: string; size_bytes: number }>("/api/backup", {
      method: "POST",
      body: "{}"
    }),
  downloadBackup: (filename: string) =>
    request<Blob>(`/api/backups/${encodeURIComponent(filename)}`, {}, "blob"),
  exportData: () => request<Record<string, unknown>>("/api/export"),
  deleteData: () =>
    request<{ deleted: true; deleted_backups: number }>("/api/data", {
      method: "DELETE"
    })
};
