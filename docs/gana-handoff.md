# TalentBridge AI interview integration handoff

Owner of original delivery: Ghanashyama Mahanty (Gana). Integration/adaptation: Jayanth's shared platform branch.

Source: `talentbridge-voice-main.zip`, SHA-256 `2cb00a528727da306e420c11ac83910944a1dcc1922faba1b371ffeb01ac641d`. The ZIP was inspected without executing its setup, dialing or agent-sync tools. It contains no Git history, so this is an attributed source adaptation, not a Git merge of an existing feature branch.

## Findings and disposition

| Original ZIP component | Integrated treatment |
| --- | --- |
| `elevenlabs_webhook.py` | Ported signature verification and consent/transcript behavior to shared contracts; tightened signature freshness to 5 minutes; uncertain question IDs and timestamps remain null |
| `agent_config/interviewer_prompt.v0.2.md` | Retained versioned prompt with browser-only wording and no candidate first-name variable; one follow-up maximum |
| `attempts.py` | Preserved transactional result/event and deduplication semantics using the existing SQLAlchemy repository, without adding a database |
| `service.py`, `elevenlabs_client.py` | Adapted browser authorization and provider reconciliation into async shared services; no outbound dialing |
| Local mirrored contracts | Replaced by foundation CaseInput, InterviewPlan, InterviewResult and TranscriptTurn imports |
| Twilio helpers, phone-number configuration and agent lock files | Excluded; telephone calling is outside today's requirements |
| Live-call fixtures and recordings | Excluded because their participant consent/privacy cannot be established here |
| Text interview, API router and React page | Missing from the ZIP; implemented in the integrated application |

The reported call from a US number is consistent with the ZIP's explicit Twilio outbound-call path. It does not establish that the required browser flow worked. No call was placed during this integration and no live provider outcome is claimed.

## What works

- Both recruitment and mock modes use random expiring candidate links, explicit consent and the same shared contracts.
- A text interview asks the frozen plan's questions in order, persists answers immediately, and permits at most one AI clarification per core question. AI unavailability is visible and does not prevent answering planned questions.
- Text requests carry `turn_id`, `request_id` and `text`. Retries of the same request do not append turns or make another model call. Changed content under the same ID is rejected.
- Completion, early stop and consent withdrawal persist results. Withdrawal clears this application's transcript. Candidate GET responses exclude rubrics, expected topics, token hashes and provider secrets.
- The deadline is enforced by the server and a lifespan sweeper; a crashed follow-up resumes with the next core question. Sessions and transcripts survive restart.
- Voice uses the official React SDK, server-issued single-use signed URLs, provider-confirmed transcripts, HMAC webhooks, conversation binding and deduplication.
- One completion event per session is stored in `records(kind='workflow_event')` in the same transaction as the result. Assessment/report execution remains pending until the respective modules are implemented; no automatic duplicate assessment is triggered.

## Routes

Candidate bearer token required for:

| Method | `/api/interviews` suffix | Body |
| --- | --- | --- |
| GET | `/{session_id}` | Current safe state, turns and result |
| POST | `/{session_id}/consent` | `{ "confirmed": true }` or false |
| POST | `/{session_id}/text-answer` | `{ "turn_id": "...", "request_id": "unique-per-answer", "text": "..." }` |
| POST | `/{session_id}/complete` | `{}`; text requires all questions answered |
| POST | `/{session_id}/stop` | `{ "withdraw_consent": false }`; true clears retained transcript |
| POST | `/{session_id}/use-text` | `{}`; only before voice authorization |
| POST | `/{session_id}/voice-token` | `{}`; returns ephemeral signed URL, conversation ID and dynamic variables |
| GET | `/{session_id}/report` | Only the owning mock session's report |

`POST /webhooks/elevenlabs` requires `ElevenLabs-Signature`, not a candidate token. Only final `post_call_transcription` events are ingested. Browser-supplied transcripts are never authoritative. `POST /{session_id}/reconcile` requires the recruiter token and fetches the known conversation from ElevenLabs. This cannot substitute a candidate-supplied conversation ID.

For uncertain issuance, a recruiter can use `POST /{session_id}/release-voice` with `{ "confirmed_stopped_at_provider": true, "actual_minutes": 0 }` **only after checking the actual stopped state and actual minutes in ElevenLabs**. Supply actual usage, not a guessed zero. Unknown usage must retain its reservation. This route returns no private mock transcript.

## Frontend mounting

```tsx
import { InterviewPage } from './features/interview/InterviewPage';
<InterviewPage sessionId={sessionId} candidateToken={tokenFromFragment} />
```

Route: `/interview/:sessionId#token=...`. Capture the fragment into component memory before clearing it using `history.replaceState`. The root shell already does this. Never store it in localStorage or send it as a query parameter. A page refresh after fragment removal needs the original invitation. The feature owns its ConversationProvider; it requires no router provider. Drashti can mount it unchanged.

## Required environment names

For text: `DATABASE_URL`, `FRONTEND_ORIGIN`, `RECRUITER_API_TOKEN`, `SESSION_TTL_SECONDS`, `SESSION_DURATION_SECONDS`, `SESSION_MAX_DURATION_SECONDS`. Optional follow-ups use the configured shared LLM and its budget.

For browser voice: `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_WEBHOOK_SECRET`, `ELEVENLABS_VOICE_ENABLED=true`, `ELEVENLABS_SUPERVISED=true`, and an explicitly verified allowance in `PROVIDER_BUDGET_LIMITS`, for example an `elevenlabs` entry with `minutes: 8`. Names only should be shared with teammates; secrets stay local. Extra credit/money limits currently block voice because the adapter cannot safely convert those units.

Default interview duration is 360 seconds; hard application maximum is 480 seconds. Legacy foundation values above 480 are capped. Eight minutes are reserved before authorization; verified duration reconciles the reservation. Unknown outcomes retain budget and the single global voice slot. This prevents uncertain retries and concurrent billable sessions.

## Manual ElevenLabs browser-agent setup

1. Use a dedicated test/browser agent. Choose a voice and conversational model available to the account; no identifiers are embedded in source.
2. Set language to English (`en`). Paste `backend/app/agents/interview/interviewer_prompt.md` exactly as the system prompt. Set first message to `{{opening_message}}`.
3. Define the dynamic variables emitted by `voice.dynamic_variables`: session_id, case_id, mode, role_title, time_budget_minutes, max_follow_ups, interview_questions, mode_instructions, closing_instructions, opening_message. No CV, rubric, API key or phone number is sent.
4. Enable authentication. Configure allowed frontend origins. Set provider maximum conversation duration to 360 seconds (or the configured shorter session duration), agent concurrency to 1 and bursting off. The adapter reads and checks these settings before issuing access. Disable client prompt/language/duration overrides and telephone tools. Enable the end-call tool.
5. Configure boolean analysis data-collection fields `consent_given` and `consent_withdrawn`. Missing consent confirmation stores no speech. Withdrawal must be recognized even if the candidate originally agreed.
6. Configure a public HTTPS post-call transcription webhook to `/api/interviews/webhooks/elevenlabs` and set its generated HMAC secret on the server. Do not expose the recruiter token in this URL. Use a properly secured demo host/tunnel; localhost alone cannot receive provider callbacks.
7. Review provider recording/retention settings with the consented participant. Application withdrawal clears local text, but does not delete provider-held audio/history automatically; handle provider deletion manually.
8. Verify account limits and billing yourself; keep the demo supervised. Selecting Groq or Gemini inside ElevenLabs does not establish that our separate API credits are used. ElevenLabs agent/model billing or any configured custom LLM billing must be checked in that account. This code never changes subscriptions or enables paid overages.

Official docs checked: [React SDK](https://elevenlabs.io/docs/eleven-agents/libraries/react), [single-use signed URL](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get-signed-url), [post-call webhooks](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks), [provider duration limit](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow), [agent configuration](https://github.com/elevenlabs/plugin/blob/main/skills/general/agents/references/agent-configuration.md).

## Verify today without voice credentials

Run the backend/frontend using README commands. To create an explicitly labelled synthetic interview while Priya's planner is pending:

```powershell
.\.venv\Scripts\python.exe scripts/create_interview_demo.py --fixture-demo --mode recruitment
# Or use --mode mock
```

Open the invitation in `.cache/interview-demo-recruitment.txt` locally. That file contains a candidate token and must not be logged/shared in Git. The UI displays the fixture label. Complete five answers and click Complete interview. This demonstrates the real text lifecycle with a fixture plan; it does not demonstrate live planning, approved RAG, assessment or reporting.

Validation commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

## Known limitations and integration requests

Read-only agent configuration check during integration (no voice session started): the configured agent was accessible and English, with a 480-second provider cap. Authentication was disabled, concurrency was unlimited (`-1`), bursting was enabled, and the versioned prompt/consent opening did not match. Local voice/supervision flags were false and no minute quota was configured. These are concrete setup blockers, not missing API credentials. The live agent was not modified. Follow the setup above before enabling browser voice.

- No live ElevenLabs test was run during integration; credentials, an authenticated configured agent and an HTTPS webhook must be verified manually. All provider tests use synthetic payloads and mocks.
- Signed URLs are bearer credentials with provider-controlled validity. The application issues one per session and requests provider single-use authorization. It cannot revoke an already issued URL or force-end a conversation over a server REST endpoint. Provider duration limits and supervision remain necessary; a local expiry alone does not prove provider termination.
- A voice disconnect/stop leaves the transcript pending. Recruiter reconciliation can fetch a missed callback. Unknown issuance remains locked until operator review; no automatic redial or replacement authorization.
- Voice transcripts associate questions only when the interviewer utterance matches a frozen question exactly. Paraphrases/interruption may leave question_id null and the result incomplete; assessment must abstain or request human mapping, never infer fabricated coverage.
- One session per case for today; create another case for a new attempt. This avoids an old session overwriting another attempt's assessment input. Mock ownership is never reassigned.
- Priya must provide real plans and approved knowledge. Drashti must connect reporting and mount this component. Jayanth's assessment/workflow should consume the durable session completion event idempotently and use the frozen session plan, not guessed or refreshed criteria.
- Do not merge the original ZIP wholesale: it would introduce a second schema/database and phone-only recruitment requirements.

## Validation results

- Full backend suite: **32 passed** (foundation plus interview integration).
- Frontend interaction tests: **4 passed** (consent refusal/token scoping, typed answer submission, expired links, text alternative).
- TypeScript/Vite production build passed. The SDK increases the bundle size and Vite reports a chunk-size advisory; this does not block the build.
- Fixture-demo creation command was exercised against an isolated SQLite database. The candidate token was written only to an ignored local file.
- No live voice interview, real candidate interview, assessment quality score or end-to-end report completion is claimed.
