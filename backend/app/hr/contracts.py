"""Versioned HR contracts; foundation interview contracts remain unchanged."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Message(Strict):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    @field_validator('subject')
    @classmethod
    def safe_header(cls, value):
        if '\r' in value or '\n' in value: raise ValueError('Subject must be one line')
        return value

class Configuration(Strict):
    job_title: str = Field(min_length=1, max_length=200)
    job_reference: str = Field(min_length=1, max_length=100)
    client_name: str = Field(default='', max_length=200)
    client_contact_name: str = Field(default='', max_length=200)
    client_email: EmailStr | None = None
    candidate_name: str = Field(min_length=1, max_length=200)
    candidate_email: EmailStr | None = None
    candidate_email_confirmed: bool = False
    cv_sharing_authorized: bool = False
    recruiter_name: str = Field(min_length=1, max_length=200)
    agency_name: str = Field(default='', max_length=200)
    recruiter_contact: str = Field(min_length=1, max_length=500)
    threshold: float = Field(default=70, ge=65, le=70, allow_inf_nan=False)
    approved_summary: str = Field(default='', max_length=12000)
    templates: dict[Literal['client','candidate','rejection'], Message] = Field(default_factory=dict)

class Criterion(Strict):
    criterion_id: str = Field(min_length=1, max_length=100)
    question_id: str
    title: str = Field(min_length=1, max_length=200)
    weight: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    essential: bool = True
    expected_principles: str = Field(min_length=1, max_length=4000)
    anchors: dict[Literal['0','1','2','3','4'], str]
    @field_validator('anchors')
    @classmethod
    def anchors_complete(cls,value):
        if set(value)!=set('01234') or any(not v.strip() for v in value.values()): raise ValueError('All five score anchors are required')
        return value

class Rubric(Strict):
    criteria: list[Criterion] = Field(min_length=1, max_length=20)
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed: Literal[True]

class Citation(Strict):
    turn_id: str
    excerpt: str = Field(min_length=1)

class Finding(Strict):
    criterion_id: str
    score: int | None = Field(ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=4000)
    evidence: list[Citation]
    uncertainty: str = ''

class Findings(Strict):
    findings: list[Finding]
    transcript_quality_sufficient: bool

class Decision(Strict):
    outcome: Literal['shortlist','reject','hold']
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=4000)
    preview_version: str
    request_id: str = Field(min_length=8, max_length=100)

class Correction(Strict):
    assessment_version: str
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=4000)
    findings: Findings

class Reconcile(Strict):
    action: Literal['confirmed_sent','confirmed_not_sent']
    reason: str = Field(min_length=5, max_length=4000)
    provider_message_id: str | None = Field(default=None, max_length=200)


from ..contracts import TranscriptTurn

class TranscriptCorrection(Strict):
    turns: list[TranscriptTurn] = Field(min_length=1, max_length=1000)
    status: Literal['completed','incomplete']
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=4000)

class Preparation(Strict):
    candidate_name: str = ''
    candidate_email: EmailStr | None = None
    criteria: list[Criterion] = Field(min_length=1, max_length=20)
