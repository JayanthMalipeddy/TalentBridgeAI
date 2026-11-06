from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, Depends, Request, Form, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from pydantic import BaseModel
from .settings import Settings
from .contracts import CaseInput, InterviewPlan, Assessment, Report
from .context import AgentContext
from .db import make_engine
from .repository import Repository
from .errors import AppError
from .auth import recruiter
from .services.budget import BudgetService
from .services.telemetry import Telemetry
from .services.llm import LLMClient
from .agents.interview.router import router
from .agents.interview.service import create_session
from .agents.planning.agent import parse_cv
from .workflow import create_workflow

class SessionRequest(BaseModel):
    channel: Literal["text", "elevenlabs"]

class ApprovalRequest(BaseModel):
    report_version: str

def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        repo = Repository(make_engine(settings.database_url))
        budget, telemetry = BudgetService(repo, settings.provider_budget_limits), Telemetry()
        app.state.ctx = AgentContext(LLMClient(settings, budget, telemetry), repo, budget, telemetry, settings)
        app.state.workflow = create_workflow(app.state.ctx)
        yield
        repo.engine.dispose()
    app = FastAPI(title="TalentBridge AI Foundation", version="1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.frontend_origin.split(",")], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

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
        return {"providers": request.app.state.ctx.llm.capabilities(), "agents": {name: {"available": False, "code": "NOT_IMPLEMENTED"} for name in ["planning", "interview", "assessment", "reporting"]}, "sessions": {"text": True, "elevenlabs": False}, "integrations": {name: {"configured": value, "available": False, "reason": "Integration pending"} for name, value in configured.items()}}

    @app.post("/api/cases", dependencies=[Depends(recruiter)], response_model=CaseInput, status_code=201)
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
        ctx.repository.save_case(case)
        return case

    @app.get("/api/cases", dependencies=[Depends(recruiter)])
    def cases(request: Request):
        return request.app.state.ctx.repository.list_cases()

    @app.get("/api/cases/{case_id}", dependencies=[Depends(recruiter)])
    def case(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        return {"case": repo.get_case(case_id), **repo.get("status", case_id)}

    async def run_stage(case_id, stage, request):
        request.app.state.ctx.repository.get_case(case_id)
        state = await request.app.state.workflow.ainvoke({"case_id": case_id, "stage": stage, "result": {}})
        return state["result"]

    @app.post("/api/cases/{case_id}/plan", dependencies=[Depends(recruiter)], response_model=InterviewPlan)
    async def plan(case_id: str, request: Request):
        return await run_stage(case_id, "plan", request)

    @app.post("/api/cases/{case_id}/sessions", dependencies=[Depends(recruiter)])
    async def sessions(case_id: str, body: SessionRequest, request: Request):
        ctx = request.app.state.ctx
        return await create_session(ctx.repository.get_case(case_id), ctx.repository.get_plan(case_id), body.channel, ctx)

    @app.post("/api/cases/{case_id}/assess", dependencies=[Depends(recruiter)], response_model=Assessment)
    async def assess(case_id: str, request: Request):
        return await run_stage(case_id, "assess", request)

    @app.post("/api/cases/{case_id}/report", dependencies=[Depends(recruiter)], response_model=Report)
    async def report(case_id: str, request: Request):
        return await run_stage(case_id, "report", request)

    @app.get("/api/cases/{case_id}/report", dependencies=[Depends(recruiter)], response_model=Report)
    def read_report(case_id: str, request: Request):
        repo = request.app.state.ctx.repository
        if repo.get_case(case_id).mode == "mock":
            raise AppError("FORBIDDEN", "Mock reports are accessible only to their owning session", 403)
        return repo.get_report(case_id)

    @app.post("/api/cases/{case_id}/approve", dependencies=[Depends(recruiter)], response_model=Report)
    def approve(case_id: str, body: ApprovalRequest, request: Request):
        return request.app.state.ctx.repository.approve_report(case_id, body.report_version)

    @app.get("/api/usage", dependencies=[Depends(recruiter)])
    def get_usage(request: Request):
        return request.app.state.ctx.repository.usage_records()

    app.include_router(router, prefix="/api/interviews", tags=["interviews"])
    return app

app = create_app()
