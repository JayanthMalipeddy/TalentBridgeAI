# Recruitment workflow audit — 9 November 2026

Final automated verification: **167 backend tests, 10 frontend unit tests, 18 browser scenarios passed**. Seven additional focused planning checks passed after constraining source IDs in the response schema and rejecting unreadable JD prefixes before any provider call. The production frontend build passed with the existing large-JavaScript-bundle warning. These results are software regression checks, not a benchmark of hiring accuracy.

## Current flow

HR uploads a CV and JD and enters the actual role. The planner generates five questions. Non-catalogue roles use numbered CV/JD sections; original excerpts and offsets are attached by the backend. HR confirms extracted contact details, job/client information and CV-sharing permission, then clicks **Candidate ready for interview**. The same original CV is retained for submission.

The candidate gives consent and completes the planned interview. The final bound transcript triggers one HR assessment. A report is composed from that same version of the assessment and its verified transcript evidence. HR reviews the score, criteria, answers, uncertainty, exact recipients and proposed emails. Explicit shortlist approval queues the client email; Gmail acceptance then queues candidate confirmation. Rejection approval queues candidate-only notification. Hold/incomplete evidence queues neither.

The threshold is configurable from 60 to 70 percent, default 70. Scores within ten points below it are flagged for closer review. Every employment decision remains human-confirmed, including high and low scores. AI recommendations alone cannot send decision messages.

## What the audit fixed

- Confirmed phone details are stored and passed to the call screen; local email extraction fills missing model extraction when there is one unambiguous address.
- New recruitment cases require readiness before a session starts; changes to the plan, rubric, configuration or CV require readiness again.
- Text follow-ups use the actual job role rather than a fixed Integration Engineer prompt.
- HR transcript loading returns the actual turns, enabling audited corrections.
- Recruitment completion uses the HR assessment/report path instead of running a duplicate legacy assessment and spending more Groq requests.
- HR corrections survive cached retries and worker ticks, and remain associated with their report version.
- The rubric is frozen after interview start. Deletion is blocked while preparation, assessment or uncertain sending is active.
- Completed calls and text interviews lead to HR review. New HR reports route to the email decision instead of the legacy report-approval button.
- HR processing and outbox statuses refresh while there are no unsaved edits.
- Budget errors report the local limit, recorded usage and requested reservation; malformed Gmail acceptance IDs require reconciliation.

## Verification matrix

| Scenario | Evidence |
|---|---|
| CV upload through question generation, readiness, five answers, assessment, report and approved mail | `backend/tests/hr/test_recruitment_e2e.py` exercises the HTTP routes, parsing, shared repository and workflow; external model/delivery responses are mocked |
| Strong, borderline, low and incomplete answers | The same end-to-end test checks recommendation bands, HR confirmation and appropriate delivery purposes |
| Client before candidate; rejection candidate-only; hold no messages | Outbox tests and end-to-end tests verify actual claimed/sent sequence |
| Duplicate completion, repeated approval, concurrent workers | Interview/HR tests verify deduplication and stable versions |
| Dropped calls, delayed transcript, invalid signature, binding mismatch, repeated webhook | `backend/tests/interview/` covers recovery and prevents automatic redial |
| Missing providers, app quota exhaustion, Gmail auth/rate errors and uncertain sends | Existing provider/budget/HR negative tests; uncertain delivery never retries blindly |
| Correct original CV, recipient, source excerpts and assessment version | Planning, HR and HTTP end-to-end assertions |
| HR correction followed by worker/retry | HR tests verify that the corrected version remains current |
| Ownership, cross-session access, mock privacy, deletion and approval invalidation | Backend security/persistence suites |
| Desktop/tablet/mobile, real role submission, forms, report handoff and explicit HR approval | 18 browser scenarios with labelled fictional API fixtures |

## Live connection checks and practical limits

Read-only configuration inspection confirmed Groq and telephone credentials are configured, Gmail authorization is stored without a recorded reconnect flag, sending is enabled, and the production outbox was empty. Configuration presence does not prove provider availability or remaining provider quota.

A capped synthetic Groq check was attempted but stopped **before a provider request**: the local ledger held 145,348 of 150,000 tokens, while the next reservation required 10,077. The cap was not bypassed or usage reset. Any increased allowance requires operator approval and a backend restart to load the environment. Provider rate limits remain separate from this application allowance.

No existing candidate was called or reassessed for the audit. No real decision email was sent. Live telephony and Gmail delivery were not re-exercised; their failure paths were verified with mocked responses. External outages, revoked credentials, exhausted quota and poor transcripts still require visible recovery; zero future runtime failures cannot be guaranteed.

Restart the backend running in VS Code once to load this release. Keep the configured database and encryption key. Environment files and local video/demo scripts are excluded from the GitHub update.
