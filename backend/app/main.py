from contextlib import asynccontextmanager
import asyncio
import logging
from typing import Literal
from uuid import uuid4
from pathlib import Path
from fastapi import FastAPI, Depends, Request, Response, Form, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from .settings import Settings
from .contracts import CaseInput, InterviewPlan, Assessment, Report
from .context import AgentContext
from .db import make_engine
from .repository import Repository
from .errors import AppError
from .auth import recruiter
from .guest import owner, owned_case, bootstrap, get_guest, metadata
from .services.budget import BudgetService
from .services.telemetry import Telemetry
from .services.llm import LLMClient
from .agents.interview.router import router
from .agents.interview.service import create_session, expire_sessions, voice_available
from .agents.planning.agent import parse_cv
from .agents.interview import phone
from .hr.router import router as hr_router
from .hr.worker import tick as hr_tick
from .workflow import create_workflow, AGENTS_AVAILABLE, process_completion_events

class SessionRequest(BaseModel):
    channel: Literal["text", "elevenlabs"]

class PhoneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    contact_permission: bool
    request_id: str = Field(min_length=8, max_length=100)

class ApprovalRequest(BaseModel):
    report_version: str

def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        repo = Repository(make_engine(settings.database_url))
        budget, telemetry = BudgetService(repo, settings.provider_budget_limits), Telemetry(settings)
        app.state.ctx = AgentContext(LLMClient(settings, budget, telemetry), repo, budget, telemetry, settings)
        app.state.workflow = create_workflow(app.state.ctx)
        async def sweep():
            while True:
                try:
                    expire_sessions(app.state.ctx)
                except Exception:
                    logging.getLogger("talentbridge.interview").error("session_expiry_failed")
                await asyncio.sleep(5)
        async def phone_worker():
            while True:
                try:
                    await phone.refresh_calls(app.state.ctx)
                    await process_completion_events(app.state.ctx, app.state.workflow, phone_only=not settings.workflow_auto_process)
                except Exception:
                    logging.getLogger("talentbridge.interview").error("completion_worker_failed")
                await asyncio.sleep(15)
        async def hr_worker():
            while True:
                try:
                    await hr_tick(app.state.ctx)
                except Exception:
                    logging.getLogger("talentbridge.hr").error("hr_worker_failed")
                await asyncio.sleep(5)
        hr_task = asyncio.create_task(hr_worker())
        worker = asyncio.create_task(phone_worker())
        sweeper = asyncio.create_task(sweep())
        try:
            yield
        finally:
            hr_task.cancel()
            try: await hr_task
            except asyncio.CancelledError: pass
            worker.cancel()
            try: await worker
            except asyncio.CancelledError: pass
            sweeper.cancel()
            try: await sweeper
            except asyncio.CancelledError: pass
            await asyncio.to_thread(telemetry.flush)
            repo.engine.dispose()
    app = FastAPI(title="TalentBridge AI Foundation", version="1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.frontend_origin.split(",")], allow_methods=["GET", "POST", "DELETE"], allow_credentials=True, allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Recruiter-Token"])

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return await app_error(request, AppError("VALIDATION_ERROR", "Request fields do not match the API schema", 422))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return await app_error(request, AppError("HTTP_ERROR", "Request could not be served", exc.status_code))

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return await app_error(request, AppError("INTERNAL_ERROR", "Unexpected server error", 500))

    @app.get("/api/session")
    def guest_session(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return metadata(get_guest(request))

    @app.post("/api/guest-session")
    def new_guest_session(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return bootstrap(request, response)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "schema_version": "1.0"}

    @app.get("/api/capabilities")
    def capabilities(request: Request):
        configured = {
            "knowledge": bool(settings.embedding_model),
            "elevenlabs": bool(settings.elevenlabs_api_key.get_secret_value() and settings.elevenlabs_agent_id),
            "keenable": bool(settings.keenable_api_key.get_secret_value()),
            "tavily": bool(settings.tavily_api_key.get_secret_value()),
            "llamaparse": bool(settings.llama_cloud_api_key.get_secret_value()),
            "langfuse": bool(settings.langfuse_public_key and settings.langfuse_secret_key.get_secret_value()),
        }
        agents = {name: {"available": AGENTS_AVAILABLE[stage], "code": "AVAILABLE" if AGENTS_AVAILABLE[stage] else "NOT_IMPLEMENTED"} for name, stage in [("planning", "plan"), ("assessment", "assess"), ("reporting", "report")]}
        agents["interview"] = {"available": True, "channels": ["text"] + (["elevenlabs"] if voice_available(settings) else [])}
        integrations = {name: {"configured": value, "available": False, "reason": "Integration pending"} for name, value in configured.items()}
        integrations["elevenlabs"] = {"configured": configured["elevenlabs"], "available": voice_available(settings), "reason": "Supervised browser mode; provider configuration and minute quota checked at authorization"}
        integrations["langfuse"] = request.app.state.ctx.telemetry.capability()
        integrations["knowledge"] = {"configured": bool(settings.embedding_model), "available": Path(settings.embedding_model).is_dir() and (Path(settings.chroma_path) / "planning_index_manifest.json").is_file(), "provisional_criteria": settings.planning_allow_pending_review, "reason": "Only human-reviewed records may be used for scoring; provisional feedback withholds scores"}
        return {"providers": request.app.state.ctx.llm.capabilities(), "agents": agents, "sessions": {"text": True, "elevenlabs": voice_available(settings)}, "phone": phone.capability(settings), "integrations": integrations, "fixture_demo": settings.app_env == "fixture-demo"}

    @app.post("/api/cases", dependencies=[Depends(owner)], response_model=CaseInput, status_code=201)
    async def new_case(request: Request, job_description: str = Form(min_length=1), mode: Literal["recruitment", "mock"] = Form(), role: str = Form(min_length=1), cv_text: str | None = Form(default=None), cv_file: UploadFile | None = File(default=None)):
        ctx = request.app.state.ctx
        if (cv_file is None) == (cv_text is None):
            raise AppError("INVALID_CV", "Supply exactly one of cv_file or cv_text", 422)
        if cv_file:
            content = await cv_file.read(settings.max_cv_bytes + 1)
            if len(content) > settings.max_cv_bytes:
                raise AppError("CV_TOO_LARGE", "CV exceeds MAX_CV_BYTES", 413)
            if (cv_file.filename or "").lower().endswith(".txt"):
                try:
                    cv_text = content.decode("utf-8")
                except UnicodeDecodeError:
                    raise AppError("INVALID_CV", "Text CV must use UTF-8", 422)
            else:
                cv_text = await parse_cv(content, cv_file.filename or "", ctx)
        if not cv_text or not cv_text.strip():
            raise AppError("INVALID_CV", "CV must not be empty", 422)
        if len(cv_text.encode()) > settings.max_cv_bytes:
            raise AppError("CV_TOO_LARGE", "CV exceeds MAX_CV_BYTES", 413)
        case = CaseInput(case_id=str(uuid4()), mode=mode, role=role, cv_text=cv_text, job_description=job_description)
        ctx.repository.save_case(case, owner(request), settings.guest_max_cases)
        if mode == "recruitment":
            from .hr.service import HRService
            HRService(ctx).attachment(case.case_id, cv_file.filename if cv_file else "candidate_cv.txt", content if cv_file else cv_text.encode("utf-8"))
        return case

    @app.get("/api/cases", dependencies=[Depends(owner)])
    def cases(request: Request):
        return request.app.state.ctx.repository.list_cases(owner(request))

    @app.get("/api/cases/{case_id}", dependencies=[Depends(owned_case)])
    def case(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        return {"case": repo.get_case(case_id), **repo.get("status", case_id)}

    @app.delete("/api/cases/{case_id}", dependencies=[Depends(owned_case)], status_code=204)
    def delete_case(case_id: str, request: Request):
        request.app.state.ctx.repository.delete_case(case_id, owner(request))
        return Response(status_code=204)

    async def run_stage(case_id, stage, request):
        request.app.state.ctx.repository.get_case(case_id)
        request.app.state.ctx.repository.consume_workspace_operation(owner(request), settings.guest_max_operations)
        state = await request.app.state.workflow.ainvoke({"case_id": case_id, "stage": stage, "result": {}, "retry": request.query_params.get("retry") == "true"})
        return state["result"]

    @app.post("/api/cases/{case_id}/plan", dependencies=[Depends(owned_case)], response_model=InterviewPlan)
    async def plan(case_id: str, request: Request):
        return await run_stage(case_id, "plan", request)

    @app.post("/api/cases/{case_id}/sessions", dependencies=[Depends(owned_case)])
    async def sessions(case_id: str, body: SessionRequest, request: Request):
        ctx = request.app.state.ctx
        from .hr.service import HRService
        HRService(ctx).ensure_ready(case_id)
        return await create_session(ctx.repository.get_case(case_id), ctx.repository.get_plan(case_id), body.channel, ctx)

    @app.get("/api/cases/{case_id}/contact", dependencies=[Depends(owned_case)])
    def contact(case_id: str, request: Request):
        from .hr.contacts import contacts
        from .hr.common import maybe
        repo=request.app.state.ctx.repository
        suggestions=contacts(repo.get_case(case_id).cv_text)
        with repo.engine.connect() as c:config=maybe(repo,c,'hr_config',case_id)
        confirmed=config and config['data'].get('candidate_phone')
        if confirmed:suggestions['suggested_numbers']=[confirmed]
        return suggestions

    @app.post("/api/cases/{case_id}/phone-call", dependencies=[Depends(owned_case)])
    async def call_candidate(case_id: str, body: PhoneRequest, request: Request):
        # Workspace ownership plus operator authorization; guest access alone cannot spend on calls.
        recruiter(request, "Bearer " + request.headers.get("x-recruiter-token", ""))
        from .hr.service import HRService
        HRService(request.app.state.ctx).ensure_ready(case_id)
        return await phone.start_call(case_id, body.phone_number, body.contact_permission, body.request_id, request.app.state.ctx)

    @app.get("/api/cases/{case_id}/phone-call", dependencies=[Depends(owned_case)])
    def call_status(case_id: str, request: Request):
        ctx = request.app.state.ctx
        matches = [s for s in ctx.repository.list_sessions() if s["case_id"] == case_id and s.get("transport") == "phone"]
        if not matches: raise AppError("NOT_FOUND", "No phone interview started", 404)
        return phone.public_call(matches[0], ctx)

    @app.get("/api/cases/{case_id}/phone-call/transcript", dependencies=[Depends(owned_case)])
    def phone_transcript(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        matches = [s for s in repo.list_sessions() if s["case_id"] == case_id and s.get("transport") == "phone"]
        if not matches or not matches[0].get("provider_final"):
            raise AppError("TRANSCRIPT_PENDING", "Provider transcript is not available yet", 409)
        result = repo.get_interview(case_id)
        if not result.consent_confirmed:
            raise AppError("CONSENT_REQUIRED", "No consented transcript is retained", 409)
        return result

    @app.post("/api/cases/{case_id}/assess", dependencies=[Depends(owned_case)], response_model=Assessment)
    async def assess(case_id: str, request: Request):
        return await run_stage(case_id, "assess", request)

    @app.post("/api/cases/{case_id}/report", dependencies=[Depends(owned_case)], response_model=Report)
    async def report(case_id: str, request: Request):
        return await run_stage(case_id, "report", request)

    @app.get("/api/cases/{case_id}/report", dependencies=[Depends(owned_case)], response_model=Report)
    def read_report(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        if repo.get_case(case_id).mode == "mock" and owner(request) is None:
            raise AppError("FORBIDDEN", "Mock reports are accessible only to their owning session", 403)
        return repo.get_report(case_id)

    @app.get("/api/cases/{case_id}/plan", dependencies=[Depends(owned_case)], response_model=InterviewPlan)
    def read_plan(case_id: str, request: Request):
        return request.app.state.ctx.repository.get_plan(case_id)

    @app.get("/api/cases/{case_id}/assessment", dependencies=[Depends(owned_case)], response_model=Assessment)
    def read_assessment(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        if repo.get_case(case_id).mode == "mock" and owner(request) is None:
            raise AppError("FORBIDDEN", "Mock assessments are private to their owner", 403)
        return repo.get_assessment(case_id)

    @app.get("/api/cases/{case_id}/interview", dependencies=[Depends(owned_case)])
    def read_interview(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        if repo.get_case(case_id).mode == "mock" and owner(request) is None:
            raise AppError("FORBIDDEN", "Mock results are private to their owner", 403)
        result = repo.get_interview(case_id)
        return result

    @app.post("/api/cases/{case_id}/approve", dependencies=[Depends(owned_case)], response_model=Report)
    def approve(case_id: str, body: ApprovalRequest, request: Request):
        return request.app.state.ctx.repository.approve_report(case_id, body.report_version)

    @app.get("/api/usage", dependencies=[Depends(recruiter)])
    def get_usage(request: Request):
        return request.app.state.ctx.repository.usage_records()

    app.include_router(hr_router, prefix="/api/hr", tags=["HR review and Gmail"])
    app.include_router(router, prefix="/api/interviews", tags=["interviews"])
    return app

app = create_app()
