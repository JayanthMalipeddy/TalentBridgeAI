from ...contracts import InterviewPlan, InterviewResult, Assessment
from ...context import AgentContext
from ...errors import unavailable

async def assess_interview(plan: InterviewPlan, interview: InterviewResult, ctx: AgentContext) -> Assessment:
    unavailable("Assessment (Jayanth)")
