"""Synthetic fixtures are test-only; never imported by the application."""
import pytest
from fastapi.testclient import TestClient
from app.contracts import CaseInput, EvidenceRef, Question, InterviewPlan, TranscriptTurn, InterviewResult, SkillAssessment, Assessment, LearningResource, Report
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def contracts():
    case = CaseInput(case_id="test-case", mode="recruitment", role="Engineer", cv_text="Synthetic CV", job_description="Synthetic JD")
    evidence = EvidenceRef(source_type="transcript", source_id="turn-1", locator="turn-1", excerpt="Synthetic answer")
    question = Question(question_id="q1", skill="Python", question="Explain a test", expected_topics=["assertions"], rubric={str(i): str(i) for i in range(4)}, evidence=[evidence])
    plan = InterviewPlan(case_id=case.case_id, plan_version="p1", knowledge_version="test-only", questions=[question], missing_information=[], warnings=[])
    turn = TranscriptTurn(turn_id="turn-1", speaker="candidate", question_id="q1", text="Synthetic answer", start_ms=0, end_ms=1000)
    interview = InterviewResult(case_id=case.case_id, session_id="s1", channel="text", consent_confirmed=True, status="completed", turns=[turn], duration_seconds=1, provider_conversation_id=None)
    skill = SkillAssessment(skill="Python", status="partially_demonstrated", score=1, rationale="Test only", evidence=[evidence], needs_verification=True)
    assessment = Assessment(case_id=case.case_id, plan_version="p1", skills=[skill], coverage=1, recommendation="needs_more_evidence", limitations=["Synthetic"], model_id="test-only", prompt_version="test-only")
    resource = LearningResource(title="Python documentation", url="https://docs.python.org/3/")
    report = Report(case_id=case.case_id, report_version="r1", mode="recruitment", summary="Test only", strengths=[], gaps=["More evidence"], evidence=[evidence], suggested_next_steps=[], learning_resources=[resource], draft_email=None, approval_status="draft")
    return dict(case=case, evidence=evidence, question=question, plan=plan, turn=turn, interview=interview, skill=skill, assessment=assessment, resource=resource, report=report)


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_url="sqlite:///" + str(tmp_path / "test.db"), recruiter_api_token="test-secret")
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def auth(): return {"Authorization": "Bearer test-secret"}
