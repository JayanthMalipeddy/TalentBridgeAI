# Integration ownership

| Owner | Paths and responsibility |
| --- | --- |
| Priya | `backend/app/agents/planning/`, `knowledge/`; CV parsing, planning, ingestion and retrieval policy |
| Gana | `backend/app/agents/interview/`, `frontend/src/features/interview/`; consent, text/ElevenLabs interviews, authenticated completion and webhooks |
| Drashti | `backend/app/agents/reporting/`, remaining `frontend/`; reports and recruiter/mock UI |
| Jayanth | Shared backend, API, contracts, repository, providers, budgets, assessment, workflow and integration tests |

Read `contracts.md`, `../README.md`, `../backend/app/contracts.py`, `../backend/app/context.py`, and `../backend/app/workflow.py` before integrating.

The interview service contains shared session security infrastructure only. No production agent reasoning, interview interaction, report generation or CV parsing is implemented. All placeholders raise `NOT_IMPLEMENTED`. Test fixtures must stay in `backend/tests/`.

Keep public async signatures stable. Return validated contracts; do not call hosted providers directly. Use `ctx.llm.generate_structured`, `ctx.repository`, `ctx.budget`, and `ctx.telemetry`. Do not serialize AgentContext. It holds secrets indirectly and is deliberately not a Pydantic model.

When a stage is implemented, enable its flag in `workflow.AGENTS_AVAILABLE` and the matching API capability. Add its behavior and failure tests. Interview results must be associated with the authenticated session and original plan; enforce consent, duration limit, question IDs, case ownership, and signed webhook verification before accepting provider transcripts. Do not send ElevenLabs server keys to the browser.

Reports use new immutable version IDs. Only repository approval may mark the current recruitment report approved. Saving a new version invalidates approval. Mock report retrieval is restricted to the single owning candidate session, including against recruiter credentials. No email is sent by this prototype.

SQLite is for one application instance. Budget reservations are durable, fail closed on missing quotas, and must be reconciled. Interrupted reservations remain charged until an operator reconciles verified usage; never silently refund an uncertain provider request.
