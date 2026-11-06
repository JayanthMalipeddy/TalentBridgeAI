# Shared contracts v1.0

Authoritative definitions: `backend/app/contracts.py`. All contracts forbid extra fields and validate at boundaries. Nullable fields accept JSON null; schema_version defaults to literal `1.0`. `docs/schemas.json` contains generated schemas for every contract; `/openapi.json` contains HTTP request/response schemas.

| Contract | Fields |
| --- | --- |
| CaseInput | case_id, mode (recruitment/mock), role, cv_text, job_description, schema_version (1.0) |
| EvidenceRef | source_type (cv/job_description/knowledge/transcript), source_id, locator, excerpt |
| Question | question_id, skill, question, expected_topics[], rubric (all string keys 0–3 required), evidence[] |
| InterviewPlan | case_id, plan_version, knowledge_version, questions[], missing_information[], warnings[] |
| TranscriptTurn | turn_id, speaker (interviewer/candidate), question_id nullable, text, start_ms/end_ms nullable nonnegative integers |
| InterviewResult | case_id, session_id, channel (text/elevenlabs), consent_confirmed, status (completed/incomplete/declined), turns[], duration_seconds nonnegative, provider_conversation_id nullable |
| SkillAssessment | skill, status (demonstrated/partially_demonstrated/not_demonstrated/not_assessed), score nullable integer 0–3, rationale, evidence[], needs_verification |
| Assessment | case_id, plan_version, skills[], coverage 0–1, recommendation (review_for_submission/needs_more_evidence/does_not_yet_demonstrate_requirements), limitations[], model_id, prompt_version |
| Report | case_id, report_version, mode, summary, strengths[], gaps[], evidence[], suggested_next_steps[], learning_resources[{title,url}], draft_email nullable, approval_status (draft/approved/not_applicable) |

## Python integration

```python
async def build_plan(case: CaseInput, ctx: AgentContext) -> InterviewPlan: ...
async def parse_cv(file_bytes: bytes, filename: str, ctx: AgentContext) -> str: ...
async def assess_interview(plan: InterviewPlan, interview: InterviewResult, ctx: AgentContext) -> Assessment: ...
async def build_report(case: CaseInput, plan: InterviewPlan, interview: InterviewResult, assessment: Assessment, ctx: AgentContext) -> Report: ...
async def create_session(case: CaseInput, plan: InterviewPlan, channel: str, ctx: AgentContext) -> dict: ...
async def generate_structured(task: str, system_prompt: str, user_payload: dict, response_model: type, provider: str | None = None): ...
```

`generate_structured` is a method of `ctx.llm`. It returns an instance of response_model, validates every output and attempts at most one schema repair. Context is a Python dataclass containing llm, repository, budget, telemetry and settings; never serialize it. Session issuance returns exactly session_id, case_id, channel, candidate_url, expires_at. No server key is returned.

## HTTP integration

Public: `GET /api/health`, `GET /api/capabilities`, `/docs`, `/openapi.json`.

All recruiter operations require `Authorization: Bearer <RECRUITER_API_TOKEN>` validated on the server:

| Method | Path | Body / result |
| --- | --- | --- |
| POST | /api/cases | Multipart: cv_file XOR cv_text, job_description, mode, role; returns CaseInput with generated stable UUID |
| GET | /api/cases | Case summaries excluding CV and JD |
| GET | /api/cases/{case_id} | case, status, failure |
| POST | /api/cases/{case_id}/plan | InterviewPlan or NOT_IMPLEMENTED |
| POST | /api/cases/{case_id}/sessions | JSON channel text/elevenlabs; session object |
| POST | /api/cases/{case_id}/assess | Assessment or NOT_IMPLEMENTED |
| POST | /api/cases/{case_id}/report | Report or NOT_IMPLEMENTED |
| GET | /api/cases/{case_id}/report | Recruitment report only |
| POST | /api/cases/{case_id}/approve | JSON report_version; exact current recruitment version only |
| GET | /api/usage | Per-provider reservations/reconciled usage; no prompts |

UTF-8 .txt uploads are accepted. Other document types return NOT_IMPLEMENTED until Priya supplies parse_cv. No fixture plan is exposed via API.

Candidate routes under `/api/interviews` require their own bearer token and matching session_id:

- `GET /{session_id}` returns safe session metadata.
- `GET /{session_id}/report` returns only the owning session's mock report.
- `POST /{session_id}/start` returns NOT_IMPLEMENTED.

The candidate cannot read other sessions, recruiter APIs, or recruitment reports. Tokens are random, hashed at rest and time-limited. Mock ownership cannot be silently reassigned. All application errors use `{"error":{"code":"...","message":"...","retryable":false}}`; validation errors omit submitted input to avoid echoing CVs or credentials. Unexpected errors use sanitized messages. CORS preflight rejection is handled by the CORS middleware.

## Persistence and versioning

Repository exposes save/get case, plan, interview, assessment, report and session, plus list_cases, set_status, approve_report, authenticate_session, usage_records. All writes use SQLite immediate transactions. Report versions are immutable, approval applies only to the current version and a new version clears approval. Status and sanitized failure stage/code/message are recorded. BudgetService owns usage writes through the same repository transaction boundary.

SQLite stores sensitive prototype content locally in `data/talentbridge.db`; this file and Chroma storage are git-ignored. No automatic external telemetry is enabled. LLM telemetry records only provider/model, available token counts, elapsed time and sanitized error code.
