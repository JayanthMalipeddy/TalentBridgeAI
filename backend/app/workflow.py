"""One explicit stage per invocation; never skip candidate consent/interview."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .context import AgentContext
from .agents.planning.agent import build_plan
from .agents.assessment.agent import assess_interview
from .agents.reporting.agent import build_report
from .errors import AppError, unavailable

AGENTS_AVAILABLE = {"plan": False, "assess": False, "report": True}

class WorkflowState(TypedDict):
    case_id: str
    stage: str
    result: dict

def create_workflow(ctx: AgentContext):
    async def execute(state: WorkflowState):
        repo, id, stage = ctx.repository, state["case_id"], state["stage"]
        try:
            case = repo.get_case(id)
            if stage in AGENTS_AVAILABLE and not AGENTS_AVAILABLE[stage]:
                unavailable(stage)
            if stage == "plan":
                value = await build_plan(case, ctx)
                repo.save_plan(value)
            elif stage == "assess":
                value = await assess_interview(repo.get_plan(id), repo.get_interview(id), ctx)
                repo.save_assessment(value)
            elif stage == "report":
                value = await build_report(case, repo.get_plan(id), repo.get_interview(id), repo.get_assessment(id), ctx)
                repo.save_report(value)
            else:
                raise AppError("INVALID_STAGE", "Unknown workflow stage")
            return {"result": value.model_dump()}
        except AppError as exc:
            repo.set_status(id, "failed", {"stage": stage, "code": exc.code, "message": exc.message})
            raise
        except Exception:
            repo.set_status(id, "failed", {"stage": stage, "code": "INTERNAL_ERROR", "message": "Stage failed"})
            raise
    graph = StateGraph(WorkflowState)
    graph.add_node("execute", execute)
    graph.add_edge(START, "execute")
    graph.add_edge("execute", END)
    return graph.compile()
