"""Explicit synthetic fixture demo: never pretends that planning/RAG is implemented."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.settings import Settings
from app.db import make_engine
from app.repository import Repository
from app.context import AgentContext
from app.contracts import CaseInput, InterviewPlan, Question
from app.services.budget import BudgetService
from app.services.telemetry import Telemetry
from app.services.llm import LLMClient
from app.agents.interview.service import create_session


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-demo", action="store_true", required=True, help="Acknowledge that this uses a labelled synthetic plan, not live planning/RAG")
    parser.add_argument("--mode", choices=["recruitment", "mock"], default="recruitment")
    args = parser.parse_args()
    settings = Settings()
    repo = Repository(make_engine(settings.database_url))
    budget, telemetry = BudgetService(repo, settings.provider_budget_limits), Telemetry()
    ctx = AgentContext(LLMClient(settings, budget, telemetry), repo, budget, telemetry, settings)
    fixture = json.loads((ROOT / "data/synthetic/interview/fixture-demo.json").read_text(encoding="utf-8"))
    case = CaseInput(case_id=str(uuid4()), mode=args.mode, role="Integration Engineer", cv_text=fixture["cv_text"], job_description=fixture["job_description"])
    plan = InterviewPlan(case_id=case.case_id, plan_version="fixture-demo-v1", knowledge_version="fixture-only-not-approved",
        questions=[Question(question_id=f"fixture-q{i+1}", skill=q["skill"], question=q["question"], expected_topics=[],
            rubric={str(n):"Fixture-only anchor; not approved for scoring" for n in range(4)}, evidence=[]) for i,q in enumerate(fixture["questions"])],
        missing_information=[], warnings=["FIXTURE DEMO: synthetic case and manually authored plan. Planning/RAG and approved scoring criteria have not been integrated."])
    repo.save_case(case)
    repo.save_plan(plan)
    session = await create_session(case, plan, "text", ctx)
    output = ROOT / ".cache" / f"interview-demo-{args.mode}.txt"
    output.parent.mkdir(exist_ok=True)
    output.write_text("FIXTURE DEMO — synthetic inputs, not live AI planning\n" + session["candidate_url"] + "\n", encoding="utf-8")
    print(f"Created labelled {args.mode} text demo. Open the invitation stored in {output}. Do not commit or log that file.")
    repo.engine.dispose()


if __name__ == "__main__": asyncio.run(main())
