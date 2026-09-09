from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max", "ultra"]


class RuntimeModel(BaseModel):
    id: str
    name: str
    profile: Literal["efficient", "balanced", "quality", "local"]
    recommended: bool = False
    detail: Optional[str] = None
    reasoning_efforts: List[ReasoningEffort] = Field(
        default_factory=lambda: ["low"]
    )
    use_cases: List[str] = Field(default_factory=list)


class RuntimeProvider(BaseModel):
    id: str
    name: str
    kind: Literal["cli", "local_endpoint"]
    available: bool
    authenticated: Optional[bool] = None
    supports_sessions: bool = False
    supports_usage: bool = False
    privacy: Literal["local", "provider", "unknown"] = "unknown"
    detail: Optional[str] = None
    models: List[RuntimeModel] = Field(default_factory=list)
    selected_model: Optional[str] = None
    selected_reasoning_effort: Optional[str] = None


class RuntimeSettingsRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=160)
    reasoning_effort: ReasoningEffort = "low"
    fully_local: bool = False


class OnboardingQuestion(BaseModel):
    id: str
    prompt: str
    reason: str
    skippable: bool = True
    example: Optional[str] = None


class OnboardingImportResponse(BaseModel):
    session_id: str
    status: str
    summary: Dict[str, Any]
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    question: Optional[OnboardingQuestion] = None
    progress: Dict[str, int]


class OnboardingMessageRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str = Field(min_length=1, max_length=4000)


class OnboardingMessageResponse(BaseModel):
    status: str
    interpreted_answer: Dict[str, Any]
    question: Optional[OnboardingQuestion] = None
    progress: Dict[str, int]


class OnboardingProfileReview(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=80)
    links: List[str] = Field(default_factory=list, max_length=10)
    skills: List[str] = Field(default_factory=list, max_length=120)
    role_tracks: List[str] = Field(default_factory=list, max_length=30)
    highlights: List[str] = Field(default_factory=list, max_length=60)

    @field_validator("name")
    @classmethod
    def normalize_review_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Candidate name is required")
        return cleaned

    @field_validator("email", "phone")
    @classmethod
    def normalize_review_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("links", "skills", "role_tracks", "highlights")
    @classmethod
    def normalize_review_lists(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = " ".join(value.split())
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(cleaned)
        return normalized

    @model_validator(mode="after")
    def require_role_direction(self) -> "OnboardingProfileReview":
        if not self.role_tracks:
            raise ValueError("Confirm at least one role direction")
        return self


class OnboardingConfirmRequest(BaseModel):
    session_id: str
    start_search: bool = True
    profile_review: OnboardingProfileReview


class OnboardingConfirmResponse(BaseModel):
    profile_version: str
    preference_version: str
    search_plan_version: str
    search_run_id: Optional[str] = None


class ResumeIdentityValue(BaseModel):
    field: Literal["name", "email", "phone", "links"]
    value: Any


class ResumeIdentityChange(BaseModel):
    field: Literal["name", "email", "phone", "links"]
    before: Any
    after: Any


class ResumeIdentityDiff(BaseModel):
    added: List[ResumeIdentityValue] = Field(default_factory=list)
    removed: List[ResumeIdentityValue] = Field(default_factory=list)
    changed: List[ResumeIdentityChange] = Field(default_factory=list)


class ResumeListChange(BaseModel):
    before: str
    after: str


class ResumeListDiff(BaseModel):
    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    changed: List[ResumeListChange] = Field(default_factory=list)


class ResumeProfileDiff(BaseModel):
    identity: ResumeIdentityDiff
    skills: ResumeListDiff
    role_tracks: ResumeListDiff
    highlights: ResumeListDiff


class ResumeRefreshPreviewResponse(BaseModel):
    draft_id: str
    session_id: str
    status: Literal["needs_confirmation"]
    summary: OnboardingProfileReview
    diff: ResumeProfileDiff


class ResumeRefreshConfirmRequest(BaseModel):
    draft_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    profile_review: OnboardingProfileReview

    @model_validator(mode="after")
    def require_consistent_draft_id(self) -> "ResumeRefreshConfirmRequest":
        if not self.draft_id and not self.session_id:
            raise ValueError("Provide the replacement resume draft_id")
        if self.draft_id and self.session_id and self.draft_id != self.session_id:
            raise ValueError("draft_id and session_id must identify the same draft")
        return self

    @property
    def resolved_draft_id(self) -> str:
        return self.draft_id or self.session_id or ""


class ResumeRefreshConfirmResponse(BaseModel):
    draft_id: str
    session_id: str
    status: Literal["confirmed"]
    profile_version: str
    preserved_preferences: Literal[True]
    summary: OnboardingProfileReview
    diff: ResumeProfileDiff
    profile: Dict[str, Any]
    search_plan: Dict[str, Any]


class SearchRunRequest(BaseModel):
    reason: str = Field(default="manual", max_length=100)
    temporary_instruction: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("temporary_instruction")
    @classmethod
    def normalize_temporary_instruction(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        return normalized


class SearchScheduleRequest(BaseModel):
    enabled: bool = False
    cadence: Literal["daily", "weekly"] = "daily"
    time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int = Field(default=0, ge=0, le=6)
    notify: bool = False


class JobFeedbackRequest(BaseModel):
    action: Literal["save", "hide", "keep", "more_like_this"]
    reason: Optional[str] = Field(default=None, max_length=1000)


class ChatMessageRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=8000)
    selected_job_id: Optional[str] = None
    current_page: Optional[str] = Field(default=None, max_length=100)
    provider: str = Field(default="auto", max_length=50)
    model: Optional[str] = Field(default=None, max_length=160)
    use_ai: bool = True


class PreferenceChangeDecisionRequest(BaseModel):
    accept: bool


class PreferenceUpdateRequest(BaseModel):
    target_roles: List[str] = Field(default_factory=list, max_length=20)
    preferred_locations: List[str] = Field(default_factory=list, max_length=20)
    work_modes: List[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=list
    )
    seniority_tolerance: str = Field(default="", max_length=500)
    excluded_keywords: List[str] = Field(default_factory=list, max_length=40)
    excluded_locations: List[str] = Field(default_factory=list, max_length=20)
    preferred_industries: List[str] = Field(default_factory=list, max_length=20)
    preferred_companies: List[str] = Field(default_factory=list, max_length=50)
    excluded_companies: List[str] = Field(default_factory=list, max_length=50)
    priority_skills: List[str] = Field(default_factory=list, max_length=40)
    employment_types: List[str] = Field(default_factory=list, max_length=20)
    salary_min: Optional[float] = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    salary_currency: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
    )
    salary_period: Optional[
        Literal[
            "hour",
            "day",
            "week",
            "month",
            "year",
            "hourly",
            "daily",
            "weekly",
            "monthly",
            "yearly",
            "annual",
        ]
    ] = None
    location_policy: Literal["preference_order", "strict"] = "preference_order"
    freshness_hours: int = Field(default=48, ge=1, le=168)

    @field_validator(
        "target_roles",
        "preferred_locations",
        "preferred_industries",
        "preferred_companies",
        "excluded_companies",
        "priority_skills",
        "employment_types",
    )
    @classmethod
    def normalize_preference_values(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for value in values:
            cleaned = " ".join(value.split())
            if not cleaned:
                raise ValueError("Search preferences cannot contain blank values")
            if len(cleaned) > 200:
                raise ValueError("Search preference values cannot exceed 200 characters")
            deduplication_key = cleaned.casefold()
            if deduplication_key in seen:
                continue
            seen.add(deduplication_key)
            normalized.append(cleaned)
        return normalized

    @model_validator(mode="after")
    def require_search_scope(self) -> "PreferenceUpdateRequest":
        if not self.target_roles:
            raise ValueError("Choose at least one target role")
        if not self.preferred_locations:
            raise ValueError("Choose at least one preferred location")
        return self


class CandidateIdentityUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=80)
    location: Optional[str] = Field(default=None, max_length=300)
    links: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("name", "email", "phone", "location")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("links")
    @classmethod
    def validate_links(cls, values: List[str]) -> List[str]:
        normalized = PreferenceUpdateRequest.normalize_preference_values(values)
        for value in normalized:
            parsed = HttpUrl(value)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Profile links must use HTTP or HTTPS")
        return normalized


class CandidateProfileUpdateRequest(BaseModel):
    identity: CandidateIdentityUpdate
    skills: List[str] = Field(default_factory=list, max_length=120)
    role_families: List[str] = Field(default_factory=list, max_length=30)
    highlights: List[str] = Field(default_factory=list, max_length=60)

    @field_validator("skills", "role_families", "highlights")
    @classmethod
    def normalize_lists(cls, values: List[str]) -> List[str]:
        return PreferenceUpdateRequest.normalize_preference_values(values)

    @model_validator(mode="after")
    def require_profile_scope(self) -> "CandidateProfileUpdateRequest":
        if not self.role_families:
            raise ValueError("Keep at least one evidence-backed or confirmed role family")
        return self


class ResumeRunRequest(BaseModel):
    custom_instructions: str = Field(default="", max_length=5000)
    template: Optional[Literal["ai", "software", "balanced"]] = None
    provider: Literal["codex"] = "codex"
    model: Optional[str] = Field(default=None, max_length=160)
    reasoning_effort: Optional[ReasoningEffort] = None
    check_public_github: bool = False
    confirmed_public_github_access: bool = False

    @model_validator(mode="after")
    def require_github_confirmation(self) -> "ResumeRunRequest":
        if self.check_public_github and not self.confirmed_public_github_access:
            raise ValueError("Confirm public GitHub access before checking linked repositories")
        return self


class ResumeRunMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class ATSSemanticReviewRequest(BaseModel):
    provider: str = Field(default="auto", min_length=1, max_length=50)
    model: Optional[str] = Field(default=None, max_length=160)
    reasoning_effort: Optional[ReasoningEffort] = None
    confirmed_full_document_processing: bool = False


class ExternalATSRequest(BaseModel):
    confirmed_external_processing: bool = False


class ResumeSourceUpdateRequest(BaseModel):
    source: str = Field(min_length=200, max_length=120_000)
    instruction: str = Field(default="Manual TeX edit", max_length=1000)


class PrepareApplicationRequest(BaseModel):
    resume_run_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=5000)


class ApplicationPatchRequest(BaseModel):
    status: Literal[
        "draft",
        "opened",
        "applied",
        "interview",
        "rejected",
        "offer",
        "withdrawn",
    ]
    notes: Optional[str] = Field(default=None, max_length=5000)


class ManualJobRequest(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=2, max_length=300)
    location: str = Field(default="Unspecified", max_length=300)
    description: str = Field(min_length=20, max_length=120_000)
    apply_url: HttpUrl
    posted_at: Optional[str] = None
