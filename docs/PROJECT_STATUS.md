# Integrated release status — 6 November 2026

All teammate PRs (#1 interview, #2 reports/UI, #3 planning/RAG) were present on default branch `feat/platform-assessment` at `2e274c32998a30b4b54163898908d8c90f8bc89d`. The reviewed patch was applied selectively on `feat/release-integration`, preserving the newer modules.

Working: local PDF/DOCX parsing, Groq CV/JD extraction and tailoring, persistent local retrieval, consented five-question text interviews, citation-checked assessment, recruiter reports with exact-version approval, private mock feedback, persistent stage deduplication/recovery, guest ownership/CSRF, budgets and runtime operator usage display.

Real-provider validation completed recruitment and mock flows with fictional data. The first mock assessment failed at the provider and succeeded on one explicit retry. Recruitment's initial assessment rejected four misattributed citations; those skills remain unassessed. The strengthened skill-labelled prompt used on mock recovery yielded five validated references. This checks quotation existence, not human-reviewed semantic correctness.

## Missing or manual

- Human review: 36 reference chunks and 19 question records remain pending review. Provisional mode shows feedback but withholds scores. Approval must be performed by a teammate, followed by an index rebuild.
- Voice: implementation present, no live browser conversation validated. Previous read-only account check found authentication/concurrency/bursting/prompt setup blockers. Keep disabled; see Gana's handoff. An incoming US phone call is not evidence of this browser integration working.
- Evaluation: no reviewed 12-case golden set or baseline comparison. Two live synthetic smoke cases are not a quality benchmark.
- Secondary providers: unavailable adapters; no silent fallback. Langfuse metadata tracing is implemented; see docs/langfuse.md for verification and privacy scope.
- Mock learning resources remain empty; reporting preserves assessment evidence deterministically rather than calling another LLM.
- The guest UI is a local prototype, not enterprise identity. Original candidate invitation links must be retained to resume an active interview after refreshing. An expired guest cookie cannot recover prior private cases automatically.
- Vite build passes with a large JavaScript chunk advisory.

Local runtime uses a separate ignored release-demo SQLite file, downloaded embeddings, provisional criteria, text interviews without optional follow-ups, and a cap of 12 Groq requests/100,000 reserved tokens. No subscription or overage settings were changed. Budget limits are not provider balance estimates.

## Outbound phone scope update

The user explicitly requested telephone calls, superseding the initial browser-only restriction. Recruitment now defaults to a recruiter-triggered ElevenLabs/Twilio call, with confirmed phone number, contact permission, idempotent dial, separate minute reservations, provider transcript polling and automatic assessment/reporting. See [phone handoff](phone-interviews.md). The connected ElevenLabs account returned zero phone numbers; live calling is blocked on that provider connection. No live test call was made.
