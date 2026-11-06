from ...contracts import CaseInput, InterviewPlan
from ...context import AgentContext
from ...errors import unavailable

async def build_plan(case: CaseInput, ctx: AgentContext) -> InterviewPlan:
    unavailable("Planning (Priya)")

async def parse_cv(file_bytes: bytes, filename: str, ctx: AgentContext) -> str:
    unavailable("CV parsing (Priya); submit cv_text or a UTF-8 .txt file")
