"""Persistent stage receipts; no automatic retries of failed billable operations."""
import hashlib
import json
from datetime import datetime, timezone
from typing import TypedDict
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from .db import records
from .context import AgentContext
from .contracts import InterviewPlan
from .agents.planning.agent import build_plan
from .agents.assessment.agent import assess_interview, PROMPT_VERSION, model_id
from .agents.reporting.agent import build_report
from .errors import AppError, unavailable

AGENTS_AVAILABLE = {"plan": True, "assess": True, "report": True}

class WorkflowState(TypedDict, total=False):
    case_id: str
    stage: str
    result: dict
    retry: bool


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inputs(ctx, case_id, stage):
    repo = ctx.repository
    case = repo.get_case(case_id)
    if stage == "plan": return case, None, None, None, case.model_dump()
    interview = repo.get_interview(case_id)
    session = repo.get_session(interview.session_id)
    if session.get("state") not in {"completed", "incomplete"}:
        raise AppError("INTERVIEW_NOT_FINAL", "Finish the interview before assessment", 409)
    if not interview.consent_confirmed or interview.status == "declined":
        raise AppError("CONSENT_REQUIRED", "Consent is required for assessment/reporting", 409)
    if session.get("conversation_id") and not session.get("provider_final"):
        raise AppError("TRANSCRIPT_PENDING", "Wait for the authoritative voice transcript", 409, True)
    plan = InterviewPlan.model_validate(session["frozen_plan"])
    if plan.case_id != case_id or repo.get_plan(case_id).model_dump() != plan.model_dump():
        raise AppError("VERSION_CONFLICT", "Stored plan differs from frozen session plan", 409)
    assessment = repo.get_assessment(case_id) if stage == "report" else None
    if assessment and assessment.plan_version != plan.plan_version:
        raise AppError("VERSION_CONFLICT", "Assessment uses a different plan version", 409)
    payload = {"case": case.model_dump(), "plan": plan.model_dump(), "interview": interview.model_dump(),
               "assessment": assessment.model_dump() if assessment else None,
               "model": model_id(ctx), "prompt_version": PROMPT_VERSION}
    return case, plan, interview, assessment, payload


def create_workflow(ctx: AgentContext):
    async def execute_inner(state: WorkflowState):
        repo, case_id, stage = ctx.repository, state["case_id"], state["stage"]
        receipt_id = None
        claimed = False
        try:
            repo.get_case(case_id)
            if stage not in AGENTS_AVAILABLE:
                raise AppError("INVALID_STAGE", "Unknown workflow stage")
            if not AGENTS_AVAILABLE[stage]: unavailable(stage)
            case, plan, interview, assessment, payload = inputs(ctx, case_id, stage)
            fingerprint = digest(payload)
            receipt_id = case_id + ":" + stage
            with repo.transaction() as conn:
                raw = conn.execute(select(records.c.payload).where(records.c.kind == "stage_run", records.c.id == receipt_id)).scalar_one_or_none()
                previous = json.loads(raw) if raw else None
                if previous and previous["status"] == "running":
                    raise AppError("STAGE_BUSY", "Stage is running or its outcome is uncertain; operator review required before retry", 409)
                if previous and previous["fingerprint"] == fingerprint:
                    if previous["status"] == "succeeded":
                        kind = {"plan": "plan", "assess": "assessment", "report": "report"}[stage]
                        with ctx.telemetry.observation("cache_hit", metadata={"stage": stage}):
                            return {"result": repo._get(conn, kind, case_id)}
                    if not state.get("retry", False):
                        raise AppError("STAGE_RETRY_REQUIRED", "Previous attempt failed; fix the cause then explicitly retry", 409)
                repo._put(conn, "stage_run", receipt_id, {"fingerprint": fingerprint, "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(), "stage": stage})
                claimed = True
            if stage == "plan": value = await build_plan(case, ctx)
            elif stage == "assess": value = await assess_interview(plan, interview, ctx)
            else: value = await build_report(case, plan, interview, assessment, ctx)
            # Commit artifact + receipt together, and recheck consent/transcript to
            # reject results completed after withdrawal or another input change.
            repo.save_stage_result(stage, value, receipt_id, fingerprint,
                                   interview.model_dump() if interview else None)
            return {"result": value.model_dump()}
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"
            message = exc.message if isinstance(exc, AppError) else "Stage failed"
            if claimed:
                repo.put("stage_run", receipt_id, {"fingerprint": fingerprint, "status": "failed", "stage": stage, "error": code})
            if code not in {"STAGE_BUSY", "STAGE_RETRY_REQUIRED"}:
                repo.set_status(case_id, "failed", {"stage": stage, "code": code, "message": message})
            raise
    async def execute(state: WorkflowState):
        with ctx.telemetry.observation("workflow." + state["stage"], metadata={
            "case_id": state["case_id"], "stage": state["stage"], "operation": "workflow_request",
            "prompt_version": PROMPT_VERSION}) as observation:
            result = await execute_inner(state)
            observation.update(metadata={"case_id": state["case_id"], "stage": state["stage"], "status": "succeeded"})
            return result

    graph = StateGraph(WorkflowState)
    graph.add_node("execute", execute)
    graph.add_edge(START, "execute")
    graph.add_edge("execute", END)
    return graph.compile()


async def process_completion_events(ctx, workflow, phone_only=False):
    """Opt-in single-instance worker; pending events survive restart/module delivery."""
    for event_id, event in ctx.repository.all_records("workflow_event"):
        if event["status"] not in {"pending", "waiting_dependency", "waiting_provider"}: continue
        try:
            interview = ctx.repository.get_interview(event["case_id"])
            session = ctx.repository.get_session(event["session_id"])
            if phone_only and session.get("transport") != "phone": continue
            if session.get("processing_paused"):
                event["status"] = "paused"
                ctx.repository.put("workflow_event", event_id, event)
                continue
            if session.get("conversation_id") and not session.get("provider_final"):
                event["status"] = "waiting_provider"
            elif interview.status not in {"completed", "incomplete"} or not interview.consent_confirmed or not interview.turns:
                event["status"] = "needs_review"
            else:
                for stage in ("assess", "report"):
                    if not AGENTS_AVAILABLE[stage]:
                        event["status"] = "waiting_dependency"
                        event["dependency"] = stage
                        break
                    await workflow.ainvoke({"case_id": event["case_id"], "stage": stage, "result": {}})
                else:
                    event["status"] = "completed"
                    event.pop("dependency", None)
        except AppError as exc:
            event.update(status="failed", error=exc.code)
        except Exception:
            event.update(status="failed", error="INTERNAL_ERROR")
        ctx.repository.put("workflow_event", event_id, event)
