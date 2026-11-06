# Jayanth integration handoff

Branch: feat/release-integration. Base: default feat/platform-assessment at 2e274c32998a30b4b54163898908d8c90f8bc89d.

Teammate code and the reviewed patch are integrated. Public Pydantic contracts remain unchanged. New workspace APIs match Drashti's cookie/CSRF client; Gana's InterviewPage is mounted in the workspace and candidate route. Assessment is real Groq with frozen-plan, candidate-only, same-skill exact citation validation. Pending criteria produce descriptive feedback only. Reports preserve the assessment without another provider call.

Shared settings now include planning options, completion-token cap, optional follow-ups and guest limits. PDF parsing dependency pypdf is locked. Explicit retries are available in the UI; no automatic paid fallback. Workflow receipts survive restarts and prevent duplicate billing for identical successful stages. Approval invalidates on changed report inputs.

Read README for exact setup/background startup and docs/validation.md for actual results. See docs/PROJECT_STATUS.md for remaining manual work. Do not use historical teammate screenshots or unit-test fixtures as live evidence.

Demo: open /app, choose recruitment or mock, use fictional sample or upload a consented CV, generate plan, inspect evidence/provisional warning, start text interview, consent, answer five questions, complete, assess saved interview, prepare report. Recruitment requires explicit exact-version approval; mock omits client actions. Services and usage shows capabilities and operator-only usage with a runtime token. Browser invitation tokens never grant access to other cases.

The local no-signup workspace is a reviewed-patch addition to the original recruiter-token design; each guest can access only its own cases. Operator token never grants access to guest-owned private data. No production identity claims are made.
