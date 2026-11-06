"""Version 1.0 integration contracts; no provider credentials belong here."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseInput(Contract):
    case_id: str
    mode: Literal["recruitment", "mock"]
    role: str
    cv_text: str
    job_description: str
    schema_version: Literal["1.0"] = "1.0"


class EvidenceRef(Contract):
    source_type: Literal["cv", "job_description", "knowledge", "transcript"]
    source_id: str
    locator: str
    excerpt: str


class Question(Contract):
    question_id: str
    skill: str
    question: str
    expected_topics: list[str]
    rubric: dict[Literal["0", "1", "2", "3"], str]
    evidence: list[EvidenceRef]

    @model_validator(mode="after")
    def complete_rubric(self):
        if set(self.rubric) != {"0", "1", "2", "3"}:
            raise ValueError("Rubric requires all four scores")
        return self


class InterviewPlan(Contract):
    case_id: str
    plan_version: str
    knowledge_version: str
    questions: list[Question]
    missing_information: list[str]
    warnings: list[str]


class TranscriptTurn(Contract):
    turn_id: str
    speaker: Literal["interviewer", "candidate"]
    question_id: str | None
    text: str
    start_ms: int | None = Field(ge=0)
    end_ms: int | None = Field(ge=0)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms precedes start_ms")
        return self


class InterviewResult(Contract):
    case_id: str
    session_id: str
    channel: Literal["text", "elevenlabs"]
    consent_confirmed: bool
    status: Literal["completed", "incomplete", "declined"]
    turns: list[TranscriptTurn]
    duration_seconds: float = Field(ge=0)
    provider_conversation_id: str | None


class SkillAssessment(Contract):
    skill: str
    status: Literal["demonstrated", "partially_demonstrated", "not_demonstrated", "not_assessed"]
    score: int | None = Field(ge=0, le=3)
    rationale: str
    evidence: list[EvidenceRef]
    needs_verification: bool


class Assessment(Contract):
    case_id: str
    plan_version: str
    skills: list[SkillAssessment]
    coverage: float = Field(ge=0, le=1)
    recommendation: Literal["review_for_submission", "needs_more_evidence", "does_not_yet_demonstrate_requirements"]
    limitations: list[str]
    model_id: str
    prompt_version: str


class LearningResource(Contract):
    title: str
    url: str


class Report(Contract):
    case_id: str
    report_version: str
    mode: Literal["recruitment", "mock"]
    summary: str
    strengths: list[str]
    gaps: list[str]
    evidence: list[EvidenceRef]
    suggested_next_steps: list[str]
    learning_resources: list[LearningResource]
    draft_email: str | None
    approval_status: Literal["draft", "approved", "not_applicable"]
