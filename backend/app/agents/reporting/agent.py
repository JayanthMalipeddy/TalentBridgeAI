from ...contracts import CaseInput, InterviewPlan, InterviewResult, Assessment, Report
from ...context import AgentContext
from ...errors import unavailable

async def build_report(case: CaseInput, plan: InterviewPlan, interview: InterviewResult, assessment: Assessment, ctx: AgentContext) -> Report:
    unavailable("Reporting (Drashti)")
