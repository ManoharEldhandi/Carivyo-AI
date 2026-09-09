from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.artifacts import ArtifactVault
from app.config import Settings
from app.db import Database
from app.observability import configure_logging
from app.schemas import (
    ApplicationPatchRequest,
    ATSSemanticReviewRequest,
    ExternalATSRequest,
    ChatMessageRequest,
    JobFeedbackRequest,
    CandidateProfileUpdateRequest,
    OnboardingConfirmRequest,
    OnboardingMessageRequest,
    PreferenceChangeDecisionRequest,
    PreferenceUpdateRequest,
    PrepareApplicationRequest,
    ResumeRefreshConfirmRequest,
    ResumeRefreshConfirmResponse,
    ResumeRefreshPreviewResponse,
    ResumeRunMessageRequest,
    ResumeRunRequest,
    ResumeSourceUpdateRequest,
    RuntimeSettingsRequest,
    SearchScheduleRequest,
    SearchRunRequest,
)
from app.security import LocalRateLimiter, SessionSecurity
from app.services.applications import ApplicationBlocked, ApplicationService
from app.services.ats_semantic import ATSSemanticReviewService, SemanticReviewInputError
from app.services.backup import BackupService
from app.services.chat import ChatService
from app.services.enhancv import EnhancvATSService, EnhancvUnavailable
from app.services.hiring_agent import LocalHiringAgent
from app.services.matching import MatchingService
from app.services.onboarding import OnboardingService
from app.services.preferences import PreferenceService
from app.services.profile import ProfileService
from app.services.resume import ResumeRunBlocked, ResumeService
from app.services.runtime import RuntimeGateway
from app.services.search import SearchService
from app.services.schedule import SearchScheduleService
from app.services.search_plan import SearchPlanService


@dataclass
class Container:
    settings: Settings
    database: Database
    vault: ArtifactVault
    security: SessionSecurity
    rate_limiter: LocalRateLimiter
    profiles: ProfileService
    onboarding: OnboardingService
    preferences: PreferenceService
    plans: SearchPlanService
    matching: MatchingService
    search: SearchService
    schedule: SearchScheduleService
    runtime: RuntimeGateway
    hiring_agent: LocalHiringAgent
    ats_semantic: ATSSemanticReviewService
    chat: ChatService
    resumes: ResumeService
    enhancv: EnhancvATSService
    applications: ApplicationService
    backup: BackupService


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int, paths: set[str]):
        self.app = app
        self.max_bytes = max_bytes
        self.paths = paths

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or scope.get("path") not in self.paths:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return
        received = 0
        exceeded = False
        buffered_messages: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise RequestBodyTooLarge
            return message

        async def buffered_send(message: Message) -> None:
            buffered_messages.append(message)

        try:
            await self.app(scope, limited_receive, buffered_send)
        except RequestBodyTooLarge:
            exceeded = True
        if exceeded:
            await self._reject(scope, receive, send)
            return
        for message in buffered_messages:
            await send(message)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Resume upload exceeds the local size limit"},
        )
        await response(scope, receive, send)


class RequestBodyTooLarge(Exception):
    pass


def build_container(settings: Settings) -> Container:
    settings.ensure_directories()
    database = Database(
        settings.database_path,
        Path(__file__).resolve().parent / "migrations",
    )
    database.initialize()
    vault = ArtifactVault(settings.artifacts_dir)
    security = SessionSecurity.create(
        settings.allowed_origins,
        settings.bootstrap_token,
    )
    rate_limiter = LocalRateLimiter(settings.api_requests_per_minute)
    profiles = ProfileService(database)
    onboarding = OnboardingService(settings, database, vault)
    preferences = PreferenceService(database)
    plans = SearchPlanService(database, profiles)
    matching = MatchingService(profiles, database)
    search = SearchService(settings, database, vault, profiles, plans, matching)
    schedule = SearchScheduleService(database, profiles, search)
    runtime = RuntimeGateway(settings, database)
    hiring_agent = LocalHiringAgent(
        database,
        runtime,
        enabled=settings.local_hiring_agent_enabled,
    )
    ats_semantic = ATSSemanticReviewService(database, runtime)
    chat = ChatService(
        database,
        profiles,
        preferences,
        search,
        runtime,
        settings.max_chat_input_tokens,
    )
    resumes = ResumeService(
        database, vault, profiles, search, hiring_agent, runtime=runtime
    )
    enhancv = EnhancvATSService(settings, database, vault)
    applications = ApplicationService(database, search, resumes)
    backup = BackupService(settings, database)
    return Container(
        settings=settings,
        database=database,
        vault=vault,
        security=security,
        rate_limiter=rate_limiter,
        profiles=profiles,
        onboarding=onboarding,
        preferences=preferences,
        plans=plans,
        matching=matching,
        search=search,
        schedule=schedule,
        runtime=runtime,
        hiring_agent=hiring_agent,
        ats_semantic=ats_semantic,
        chat=chat,
        resumes=resumes,
        enhancv=enhancv,
        applications=applications,
        backup=backup,
    )


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    application = FastAPI(
        title="Carivyo Local API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    application.state.container = container

    @application.on_event("startup")
    async def resume_interrupted_external_reports() -> None:
        # Running rows are durable queue entries. A process restart resumes
        # them from the immutable PDF/JD byte hashes recorded at consent time.
        for report_id in container.enhancv.pending():
            asyncio.create_task(asyncio.to_thread(container.enhancv.execute, report_id))

        async def scheduled_search_loop() -> None:
            while True:
                await container.schedule.tick()
                await asyncio.sleep(max(5, container.settings.scheduler_poll_seconds))

        application.state.schedule_task = asyncio.create_task(scheduled_search_loop())

    @application.on_event("shutdown")
    async def stop_scheduled_search_loop() -> None:
        task = getattr(application.state, "schedule_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-Carivyo-Bootstrap",
            "X-Carivyo-Session",
        ],
    )
    application.add_middleware(
        UploadSizeLimitMiddleware,
        max_bytes=settings.max_upload_bytes + 512 * 1024,
        paths={
            "/api/onboarding/import",
            "/api/profile/resume",
            "/api/profile/resume/preview",
        },
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            rate_key = (
                request.headers.get("x-carivyo-session")
                or (request.client.host if request.client else "unknown")
            )
            retry_after = container.rate_limiter.retry_after(rate_key)
            if retry_after is not None:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Local API request limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if not request.url.path.startswith("/api/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; object-src 'none'; "
                "form-action 'none'; script-src 'self'; "
                "worker-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
                "img-src 'self' blob: data:; connect-src 'self' "
                "http://127.0.0.1:* http://localhost:* "
                "ws://127.0.0.1:* ws://localhost:*"
            )
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.url.path.startswith("/api/") or request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    def require_session(
        request: Request,
        x_carivyo_session: Optional[str] = Header(default=None),
    ) -> None:
        container.security.require_session(request, x_carivyo_session)

    @application.exception_handler(KeyError)
    async def not_found(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @application.exception_handler(ResumeRunBlocked)
    @application.exception_handler(ApplicationBlocked)
    async def blocked(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "version": "0.1.0", "local_only": True}

    @application.get("/api/session")
    async def session(
        request: Request,
        x_carivyo_bootstrap: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        container.security.require_bootstrap(request, x_carivyo_bootstrap)
        return {
            "token": container.security.token,
            "api_version": "0.1.0",
            "data_directory": str(container.settings.resolved_data_dir),
        }

    @application.get("/api/runtime/providers", dependencies=[Depends(require_session)])
    async def runtime_providers() -> Dict[str, Any]:
        providers = await asyncio.to_thread(container.runtime.discover)
        selection = container.runtime.selection()
        local_provider = next((item for item in providers if item.id == "ollama"), None)
        return {
            "providers": [provider.model_dump() for provider in providers],
            "mode": "ai_available" if any(item.available for item in providers) else "degraded",
            "selection": selection,
            "execution": {
                "fully_local": bool(selection.get("fully_local")),
                "ready": bool(local_provider and local_provider.available),
                "boundary": (
                    "All model prompts stay on this device through Ollama."
                    if selection.get("fully_local")
                    else "The selected provider may process model prompts outside this device."
                ),
            },
        }

    @application.patch(
        "/api/runtime/settings", dependencies=[Depends(require_session)]
    )
    async def runtime_settings(payload: RuntimeSettingsRequest) -> Dict[str, Any]:
        try:
            selection = await asyncio.to_thread(
                container.runtime.configure,
                payload.provider,
                payload.model,
                payload.reasoning_effort,
                payload.fully_local,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        providers = await asyncio.to_thread(container.runtime.discover)
        return {
            "selection": selection,
            "providers": [item.model_dump() for item in providers],
            "execution": {
                "fully_local": bool(selection.get("fully_local")),
                "ready": any(item.id == "ollama" and item.available for item in providers),
            },
        }

    @application.post("/api/onboarding/import", dependencies=[Depends(require_session)])
    async def onboarding_import(resume: UploadFile = File(...)) -> Dict[str, Any]:
        try:
            return await container.onboarding.import_resume(resume)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get(
        "/api/onboarding/saved-masters", dependencies=[Depends(require_session)]
    )
    async def onboarding_saved_masters() -> Dict[str, Any]:
        return {"masters": container.onboarding.saved_masters()}

    @application.post(
        "/api/onboarding/saved-masters/{artifact_id}",
        dependencies=[Depends(require_session)],
    )
    async def onboarding_use_saved_master(artifact_id: str) -> Dict[str, Any]:
        try:
            return container.onboarding.begin_from_saved_master(artifact_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post("/api/onboarding/message", dependencies=[Depends(require_session)])
    async def onboarding_message(payload: OnboardingMessageRequest) -> Dict[str, Any]:
        try:
            return container.onboarding.answer(
                payload.session_id, payload.question_id, payload.answer
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post("/api/onboarding/confirm", dependencies=[Depends(require_session)])
    async def onboarding_confirm(
        payload: OnboardingConfirmRequest,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        try:
            result = container.onboarding.confirm(
                payload.session_id,
                payload.profile_review.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        plan = container.plans.compile()
        response = {
            **result,
            "preference_version": plan["preference_version"],
            "search_plan_version": plan["version"],
            "search_run_id": None,
        }
        if payload.start_search:
            search_run = container.search.create_run()
            response["search_run_id"] = search_run["id"]
            background_tasks.add_task(container.search.run, search_run["id"])
        return response

    @application.get("/api/profile", dependencies=[Depends(require_session)])
    async def profile() -> Dict[str, Any]:
        payload = container.profiles.profile_payload()
        if not payload:
            return {"onboarding_required": True}
        try:
            payload["search_plan"] = container.plans.active()
        except ValueError:
            payload["search_plan"] = None
        return payload

    @application.get("/api/preferences", dependencies=[Depends(require_session)])
    async def preferences() -> Dict[str, Any]:
        return {
            "version": container.profiles.preference_version(),
            "preferences": container.profiles.preferences(),
        }

    @application.patch("/api/preferences", dependencies=[Depends(require_session)])
    async def update_preferences(payload: PreferenceUpdateRequest) -> Dict[str, Any]:
        updates = [
            {"key": "target_roles", "value": payload.target_roles, "kind": "hard"},
            {
                "key": "preferred_locations",
                "value": payload.preferred_locations,
                "kind": "hard",
            },
            {"key": "work_modes", "value": payload.work_modes, "kind": "hard"},
            {
                "key": "seniority_tolerance",
                "value": payload.seniority_tolerance,
                "kind": "hard",
            },
            {
                "key": "excluded_keywords",
                "value": payload.excluded_keywords,
                "kind": "negative",
            },
            {
                "key": "excluded_locations",
                "value": payload.excluded_locations,
                "kind": "negative",
            },
            {
                "key": "location_policy",
                "value": payload.location_policy,
                "kind": "hard",
            },
            {
                "key": "freshness_hours",
                "value": payload.freshness_hours,
                "kind": "hard",
            },
            {
                "key": "source_policy",
                "value": "official_direct",
                "kind": "hard",
            },
        ]
        expanded_preferences = (
            ("preferred_industries", "soft"),
            ("preferred_companies", "soft"),
            ("excluded_companies", "negative"),
            ("priority_skills", "soft"),
            ("employment_types", "hard"),
            ("salary_min", "soft"),
            ("salary_currency", "soft"),
            ("salary_period", "soft"),
        )
        updates.extend(
            {
                "key": key,
                "value": getattr(payload, key),
                "kind": kind,
            }
            for key, kind in expanded_preferences
            if key in payload.model_fields_set
        )
        changed = container.preferences.set_many(updates)
        plan = container.plans.compile()
        return {
            "version": container.profiles.preference_version(),
            "changed": changed,
            "search_plan": plan,
        }

    @application.post("/api/profile/resume", dependencies=[Depends(require_session)])
    async def refresh_profile_resume(resume: UploadFile = File(...)) -> Dict[str, Any]:
        del resume
        raise HTTPException(
            status_code=409,
            detail=(
                "Direct resume replacement is deprecated. Upload to "
                "POST /api/profile/resume/preview, then confirm the reviewed "
                "summary with POST /api/profile/resume/confirm."
            ),
        )

    @application.post(
        "/api/profile/resume/preview",
        response_model=ResumeRefreshPreviewResponse,
        dependencies=[Depends(require_session)],
    )
    async def preview_profile_resume(resume: UploadFile = File(...)) -> Dict[str, Any]:
        try:
            return await container.onboarding.preview_resume_refresh(resume)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post(
        "/api/profile/resume/confirm",
        response_model=ResumeRefreshConfirmResponse,
        dependencies=[Depends(require_session)],
    )
    async def confirm_profile_resume(
        payload: ResumeRefreshConfirmRequest,
    ) -> Dict[str, Any]:
        try:
            refresh = container.onboarding.confirm_resume_refresh(
                payload.resolved_draft_id,
                payload.profile_review.model_dump(),
            )
            plan = container.plans.compile()
            profile_payload = container.profiles.profile_payload()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not profile_payload:
            raise HTTPException(status_code=409, detail="The confirmed profile is unavailable")
        return {**refresh, "profile": profile_payload, "search_plan": plan}

    @application.patch("/api/profile", dependencies=[Depends(require_session)])
    async def update_profile(payload: CandidateProfileUpdateRequest) -> Dict[str, Any]:
        try:
            profile_payload = container.profiles.update_profile(payload.model_dump())
            plan = container.plans.compile()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**profile_payload, "search_plan": plan}

    @application.post("/api/search-runs", dependencies=[Depends(require_session)])
    async def create_search_run(
        background_tasks: BackgroundTasks, payload: SearchRunRequest
    ) -> Dict[str, Any]:
        try:
            run = container.search.create_run(
                payload.temporary_instruction,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        background_tasks.add_task(container.search.run, run["id"])
        return container.search.run_status(run["id"])

    @application.get("/api/search-runs/{run_id}", dependencies=[Depends(require_session)])
    async def search_run(run_id: str) -> Dict[str, Any]:
        return container.search.run_status(run_id)

    @application.get("/api/runs/{run_id}/events", dependencies=[Depends(require_session)])
    async def run_events(run_id: str) -> StreamingResponse:
        async def stream() -> AsyncGenerator[str, None]:
            previous = None
            for _ in range(300):
                state = container.search.run_status(run_id)
                serialized = json.dumps(state, ensure_ascii=False)
                if serialized != previous:
                    yield f"event: progress\ndata: {serialized}\n\n"
                    previous = serialized
                if state["status"] in {"complete", "partial", "failed"}:
                    yield "event: end\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.4)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @application.get("/api/jobs", dependencies=[Depends(require_session)])
    async def jobs() -> Dict[str, Any]:
        results = await asyncio.to_thread(container.search.list_jobs)
        has_profile = container.profiles.active_profile() is not None
        return {
            "jobs": results,
            "count": len(results),
            "freshness": _count_by(results, "freshness_class"),
            "locations": _count_by(results, "location"),
            "contract": container.search.search_contract() if has_profile else None,
            "latest_run": container.search.latest_coverage(),
            "schedule": container.schedule.state(),
        }

    @application.get("/api/search-schedule", dependencies=[Depends(require_session)])
    async def search_schedule() -> Dict[str, Any]:
        return container.schedule.state()

    @application.put("/api/search-schedule", dependencies=[Depends(require_session)])
    async def update_search_schedule(
        payload: SearchScheduleRequest,
    ) -> Dict[str, Any]:
        try:
            return container.schedule.configure(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/api/jobs/{job_id}", dependencies=[Depends(require_session)])
    async def job(job_id: str) -> Dict[str, Any]:
        return container.search.get_job(job_id)

    @application.post("/api/jobs/{job_id}/verify", dependencies=[Depends(require_session)])
    async def verify_job(job_id: str) -> Dict[str, Any]:
        return await container.search.revalidate(job_id)

    @application.post("/api/jobs/{job_id}/feedback", dependencies=[Depends(require_session)])
    async def job_feedback(job_id: str, payload: JobFeedbackRequest) -> Dict[str, Any]:
        return container.search.feedback(job_id, payload.action, payload.reason)

    @application.post(
        "/api/jobs/{job_id}/resume-runs", dependencies=[Depends(require_session)]
    )
    async def create_resume_run(job_id: str, payload: ResumeRunRequest) -> Dict[str, Any]:
        return await container.resumes.create(
            job_id,
            payload.custom_instructions,
            payload.template,
            payload.model,
            payload.reasoning_effort,
            payload.check_public_github,
            payload.confirmed_public_github_access,
        )

    @application.get(
        "/api/jobs/{job_id}/resume-runs/latest",
        dependencies=[Depends(require_session)],
    )
    async def latest_resume_run(job_id: str) -> Dict[str, Any]:
        container.search.get_job(job_id)
        return {"run": container.resumes.latest_for_job(job_id)}

    @application.get("/api/resume-runs/{run_id}", dependencies=[Depends(require_session)])
    async def resume_run(run_id: str) -> Dict[str, Any]:
        return container.resumes.get(run_id)

    @application.get(
        "/api/resume-runs/{run_id}/ats-analysis",
        dependencies=[Depends(require_session)],
    )
    async def resume_ats_analysis(run_id: str) -> Dict[str, Any]:
        return container.resumes.ats_analysis(run_id)

    @application.get("/api/ats/engines", dependencies=[Depends(require_session)])
    async def ats_engines() -> Dict[str, Any]:
        return {
            "engines": [
                {
                    "id": "local",
                    "label": "Carivyo local ATS",
                    "available": True,
                    "external": False,
                    "configured": True,
                    "reason": "Deterministic 27-check analysis on this device",
                    "sends_full_documents": False,
                },
                container.enhancv.availability(),
            ],
            "default": "local",
        }

    @application.post(
        "/api/resume-runs/{run_id}/ats-reports/enhancv",
        dependencies=[Depends(require_session)],
    )
    async def create_enhancv_report(
        run_id: str,
        payload: ExternalATSRequest,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        if not payload.confirmed_external_processing:
            raise HTTPException(
                status_code=422,
                detail="Confirm sending this resume and job description to Enhancv",
            )
        try:
            report = container.enhancv.start(run_id)
        except EnhancvUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background_tasks.add_task(container.enhancv.execute, report["id"])
        return report

    @application.get(
        "/api/resume-runs/{run_id}/ats-reports/enhancv",
        dependencies=[Depends(require_session)],
    )
    async def enhancv_report(run_id: str) -> Dict[str, Any]:
        container.resumes.get(run_id)
        return {"report": container.enhancv.latest(run_id)}

    @application.get(
        "/api/resume-runs/{run_id}/ats-reports/enhancv/history",
        dependencies=[Depends(require_session)],
    )
    async def enhancv_report_history(run_id: str) -> Dict[str, Any]:
        container.resumes.get(run_id)
        reports = container.enhancv.history(run_id)
        return {"reports": reports, "count": len(reports)}

    @application.post(
        "/api/resume-runs/{run_id}/ats-semantic-review",
        dependencies=[Depends(require_session)],
    )
    def create_ats_semantic_review(
        run_id: str,
        payload: ATSSemanticReviewRequest,
    ) -> Dict[str, Any]:
        if not payload.confirmed_full_document_processing:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Confirm full resume and job-description processing before "
                    "running the optional AI review"
                ),
            )
        try:
            return container.ats_semantic.review_run(
                run_id,
                provider=payload.provider,
                model=payload.model,
                reasoning_effort=payload.reasoning_effort,
            )
        except SemanticReviewInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get(
        "/api/resume-runs/{run_id}/ats-semantic-reviews",
        dependencies=[Depends(require_session)],
    )
    def list_ats_semantic_reviews(run_id: str) -> Dict[str, Any]:
        container.resumes.get(run_id)
        reviews = container.ats_semantic.for_run(run_id)
        return {"reviews": reviews, "count": len(reviews)}

    @application.post(
        "/api/resume-runs/{run_id}/message", dependencies=[Depends(require_session)]
    )
    async def revise_resume_run(
        run_id: str, payload: ResumeRunMessageRequest
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            container.resumes.revise,
            run_id,
            payload.message,
        )

    @application.get(
        "/api/resume-runs/{run_id}/source", dependencies=[Depends(require_session)]
    )
    async def resume_source(run_id: str) -> Dict[str, Any]:
        return container.resumes.source(run_id)

    @application.put(
        "/api/resume-runs/{run_id}/source", dependencies=[Depends(require_session)]
    )
    async def update_resume_source(
        run_id: str, payload: ResumeSourceUpdateRequest
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            container.resumes.update_source,
            run_id,
            payload.source,
            payload.instruction,
        )

    @application.post(
        "/api/resume-runs/{run_id}/approve", dependencies=[Depends(require_session)]
    )
    async def approve_resume_run(run_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(container.resumes.approve, run_id)

    @application.get(
        "/api/resume-runs/{run_id}/artifact/{kind}",
        dependencies=[Depends(require_session)],
    )
    async def resume_artifact(run_id: str, kind: str) -> FileResponse:
        run = container.resumes.get(run_id)
        artifacts = run.get("result", {}).get("artifacts", {})
        mapping = {
            "pdf": artifacts.get("pdf"),
            "source": artifacts.get("editable_source"),
            "render": artifacts.get("render"),
            "validation": artifacts.get("validation_report"),
            "ats": artifacts.get("ats_report"),
        }
        selected = mapping.get(kind)
        if not selected:
            raise HTTPException(status_code=404, detail="Artifact is unavailable")
        path = container.vault.confined(Path(selected))
        media_type = {
            "pdf": "application/pdf",
            "source": "text/x-tex" if path.suffix == ".tex" else "text/markdown",
            "render": "image/png",
            "validation": "application/json",
            "ats": "application/json",
        }[kind]
        download_name = path.name
        if kind == "pdf":
            download_name = run.get("result", {}).get("export_filename") or path.name
        return FileResponse(path, media_type=media_type, filename=download_name)

    @application.post(
        "/api/jobs/{job_id}/prepare-application",
        dependencies=[Depends(require_session)],
    )
    async def prepare_application(
        job_id: str, payload: PrepareApplicationRequest
    ) -> Dict[str, Any]:
        return await container.applications.prepare(
            job_id, payload.resume_run_id, payload.notes
        )

    @application.post(
        "/api/jobs/{job_id}/open-apply", dependencies=[Depends(require_session)]
    )
    async def open_apply(job_id: str) -> Dict[str, Any]:
        return await container.applications.open(job_id)

    @application.get("/api/applications", dependencies=[Depends(require_session)])
    async def applications() -> Dict[str, Any]:
        items = container.applications.list()
        return {"applications": items, "count": len(items)}

    @application.patch(
        "/api/applications/{application_id}",
        dependencies=[Depends(require_session)],
    )
    async def update_application(
        application_id: str, payload: ApplicationPatchRequest
    ) -> Dict[str, Any]:
        return container.applications.update(
            application_id, payload.status, payload.notes
        )

    @application.post("/api/chat/messages", dependencies=[Depends(require_session)])
    async def chat_message(
        payload: ChatMessageRequest,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        result = await asyncio.to_thread(
            container.chat.send,
            payload.message,
            payload.conversation_id,
            payload.selected_job_id,
            payload.current_page,
            payload.provider,
            payload.use_ai,
            payload.model,
        )
        if result["search_requested"]:
            run = container.search.create_run()
            result["search_run_id"] = run["id"]
            background_tasks.add_task(container.search.run, run["id"])
        return result

    @application.get(
        "/api/chat/conversations/{conversation_id}",
        dependencies=[Depends(require_session)],
    )
    async def chat_history(conversation_id: str) -> Dict[str, Any]:
        return container.chat.history(conversation_id)

    @application.post(
        "/api/chat/preference-changes/{change_id}/decision",
        dependencies=[Depends(require_session)],
    )
    async def decide_preference_change(
        change_id: str,
        payload: PreferenceChangeDecisionRequest,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        try:
            result = container.chat.confirm_preference_change(
                change_id,
                payload.accept,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result["search_requested"]:
            run = container.search.create_run()
            result["search_run_id"] = run["id"]
            background_tasks.add_task(container.search.run, run["id"])
        return result

    @application.get("/api/ai-usage", dependencies=[Depends(require_session)])
    async def ai_usage() -> Dict[str, Any]:
        return container.chat.usage()

    @application.post("/api/backup", dependencies=[Depends(require_session)])
    async def backup() -> Dict[str, Any]:
        return await asyncio.to_thread(container.backup.create)

    @application.get(
        "/api/backups/{filename}", dependencies=[Depends(require_session)]
    )
    async def download_backup(filename: str) -> FileResponse:
        if Path(filename).name != filename or not filename.endswith(".zip"):
            raise HTTPException(status_code=404, detail="Backup not found")
        path = (container.settings.backups_dir / filename).resolve()
        if path.parent != container.settings.backups_dir.resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        return FileResponse(
            path,
            media_type="application/zip",
            filename=filename,
        )

    @application.get("/api/export", dependencies=[Depends(require_session)])
    async def export_data() -> Dict[str, Any]:
        return {
            "profile": container.profiles.profile_payload(),
            "applications": container.applications.list(),
            "usage": container.chat.usage(),
        }

    @application.delete("/api/data", dependencies=[Depends(require_session)])
    async def delete_data() -> Dict[str, Any]:
        deleted = await asyncio.to_thread(_delete_user_data, container)
        return {"deleted": True, **deleted}

    @application.delete(
        "/api/data/reset-keep-masters", dependencies=[Depends(require_session)]
    )
    async def reset_data_keep_masters() -> Dict[str, Any]:
        reset = await asyncio.to_thread(_reset_user_data_keep_masters, container)
        return {"reset": True, **reset}

    frontend_dist = settings.project_root / "frontend" / "dist"
    if frontend_dist.exists():
        application.mount(
            "/",
            StaticFiles(directory=str(frontend_dist), html=True),
            name="frontend",
        )
    return application


def _count_by(items: list[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "Unspecified")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _reset_user_data_keep_masters(container: Container) -> Dict[str, int]:
    """Start a local workspace over without discarding imported resume masters.

    This is intentionally distinct from the full privacy-delete endpoint. The
    preserved source files and pending evidence require an explicit "Use saved
    master" action during the next onboarding; no profile or preference becomes
    active automatically.
    """

    masters = container.database.fetch_all(
        "SELECT id, source_path, text_path FROM source_artifacts"
    )
    preserved_import_dirs: set[Path] = set()
    for master in masters:
        for key in ("source_path", "text_path"):
            path = Path(master[key]).resolve()
            try:
                container.vault.confined(path)
            except ValueError:
                continue
            preserved_import_dirs.add(path.parent)

    ordered_tables = [
        "applications",
        "ats_semantic_reviews",
        "ats_analyses",
        "resume_runs",
        "agent_runs",
        "memory_items",
        "messages",
        "pending_preference_changes",
        "conversations",
        "activity_events",
        "match_results",
        "job_verifications",
        "job_source_observations",
        "jobs",
        "search_runs",
        "search_plans",
        "preferences",
        "profile_snapshots",
        "onboarding_sessions",
        "settings",
    ]
    with container.database.transaction() as connection:
        connection.execute("PRAGMA secure_delete = ON")
        for table in ordered_tables:
            connection.execute(f"DELETE FROM {table}")
        # The only retained personal records are the explicit master-resume
        # sources. They return to pending status so a new onboarding review is
        # required before any claim can drive matching or resume tailoring.
        connection.execute(
            "UPDATE evidence_claims SET approval = 'pending', conflict_json = NULL"
        )

    removed_artifacts = 0
    imports_dir = container.settings.artifacts_dir / "imports"
    for child in list(container.settings.artifacts_dir.iterdir()):
        if child == imports_dir:
            for imported in list(child.iterdir()):
                if imported.resolve() not in preserved_import_dirs:
                    container.vault.secure_delete(imported)
                    removed_artifacts += 1
            continue
        container.vault.secure_delete(child)
        removed_artifacts += 1

    for child in list(container.settings.backups_dir.iterdir()):
        container.vault.secure_delete(child)
    for child in list(container.settings.runtime_dir.iterdir()):
        container.vault.secure_delete(child)
    container.database.compact_after_delete()
    return {
        "preserved_masters": len(masters),
        "removed_artifact_groups": removed_artifacts,
    }


def _delete_user_data(container: Container) -> Dict[str, int]:
    ordered_tables = [
        "applications",
        "ats_semantic_reviews",
        "ats_analyses",
        "resume_runs",
        "agent_runs",
        "memory_items",
        "messages",
        "pending_preference_changes",
        "conversations",
        "activity_events",
        "match_results",
        "job_verifications",
        "job_source_observations",
        "jobs",
        "search_runs",
        "search_plans",
        "preferences",
        "profile_snapshots",
        "resume_bases",
        "evidence_claims",
        "onboarding_sessions",
        "source_artifacts",
        "settings",
    ]
    with container.database.transaction() as connection:
        connection.execute("PRAGMA secure_delete = ON")
        for table in ordered_tables:
            connection.execute(f"DELETE FROM {table}")
    for child in list(container.settings.artifacts_dir.iterdir()):
        container.vault.secure_delete(child)
    deleted_backups = 0
    for child in list(container.settings.backups_dir.iterdir()):
        container.vault.secure_delete(child)
        deleted_backups += 1
    container.database.compact_after_delete()
    return {"deleted_backups": deleted_backups}


app = create_app()
