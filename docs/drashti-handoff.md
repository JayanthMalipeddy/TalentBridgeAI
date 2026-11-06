# Drashti: frontend and reporting handoff

Branch: `feat/reports-ui`, based on `origin/feat/platform-assessment`.

## Delivery status

The emerald landing, split-panel mode selection, application shell, CV/JD form,
plan display, honest unavailable interview state, assessment and report views are
implemented. No account, recruiter-token, subscription or demo-booking UI remains.
All four Start for free links open `/app`.

**The live end-to-end workflow is blocked by the foundation backend.** This branch
does not weaken authorization or return synthetic results from production code.
Guest endpoints are absent; all existing case endpoints still require recruiter
credentials. Planning, parsing, interviewing and assessment are placeholders.

The four reference screenshots were not present in the attachment directory;
the written visual specification was used. No Gana handoff or InterviewPage export
exists in this checkout. His reserved folder and interview logic were not changed.

## Routes and components

- `/`: `Landing.tsx`, responsive emerald hero, original TB wordmark, section links,
  clearly labelled fictional product preview, workflow/features and final CTA.
- `/app`: `Workspace.tsx`, server-session bootstrap and recruitment/mock selection.
- `/app/new`: details, plan, unavailable interview, assessment, report stages.
- `/app/overview`, `/app/interviews`, `/app/reports`: workspace-scoped case list
  integration and report retrieval. An empty list has a real new-interview action.
- `/interview/:id`: private invitation unavailable state; strips token fragments;
  never mounts owner planning or report controls.
- `Reports.tsx`: reusable report/evidence display, native accessible disclosures,
  exact-version approval, clipboard error handling, print CSS, private mock actions.
- `contracts.ts`: UI subsets of v1.0 backend contracts; `api.ts`: single API client.
- `style.css`: shared forest/mint tokens, mobile navigation, focus and print styles.

Only Integration Engineer is offered. PDF/DOCX files have extension, empty-file
and 5 MB validation, picker and drop support. The backend currently parses neither;
the UI explains this and permits pasted CV text. No fake result is substituted.
Saved cases retain their mode; changing the default does not change a saved case.
Form content remains in memory after errors. It is not persisted across reloads.

## Exact guest integration for Jayanth

Implement and merge the following on the existing integration branch:

1. `GET /api/session`: return HTTP 401 when no valid guest session exists.
2. `POST /api/guest-session`: create or resume an isolated workspace, set a random
   server-managed HttpOnly cookie and return safe metadata. Both endpoints should
   return `{ "workspace_id": "...", "expires_at": "ISO-8601", "csrf_token": "..." }`.
   This response is a **proposed boundary**, not an existing shared contract.
3. The client sends `credentials: include` on every request and `X-CSRF-Token`
   on subsequent writes. Bootstrap POST must be protected using validated Origin
   and same-site policy or a coordinated bootstrap CSRF mechanism. Never return
   provider credentials. Cookies must be Secure over HTTPS, with an explicit
   localhost-only development configuration and appropriate SameSite policy.
4. Permit only configured credentialed CORS origins and the CSRF header. Keep
   administrative/recruiter secrets server-side. Do not make case routes public.
5. Scope every case and its plan, interview session, transcript, assessment,
   report and approval to the workspace. Return only its cases from `/api/cases`.
   Changing an ID must not bypass ownership. Preserve candidate invitation scope.
6. Allow the guest owner to read its private mock reports through the shared
   `/api/cases/{id}/report` route, or coordinate a replacement before merging.
   This route currently rejects mock reports, so mock report resumption is blocked.
7. Keep existing multipart case, stage and exact-version approval bodies unchanged.
   The UI posts `{report_version: displayedVersion}` and adopts the returned report.
8. Enforce expiry, global and per-workspace anonymous usage/budget ceilings on the
   server. Creating new sessions must not bypass global provider limits. Add tests
   for cross-workspace access, expiry, candidate scope, CSRF, approval and budgets.
9. Add safe read endpoints for saved plans/assessments and interview completion
   state to support full resume without regenerating artifacts. Current frontend
   resumes case details/recruitment reports only. Include durations in a documented
   contract if the plan should show an estimate; none is currently available.

Bootstrap uses GET first, then POST only for 401. A missing endpoint, malformed
session response or network failure produces an explicit session-service error.
The new-workspace action retries POST and clears old artifact IDs on success,
while preserving entered CV/JD text. It does not promise recovery of expired cases.

## Gana integration

Export `InterviewPage` from the reserved feature folder and document its props,
session credential handoff and authenticated completion callback. Replace only the
unavailable stage in `Workspace.tsx`; do not duplicate microphone, transcript,
ElevenLabs or consent code. Use shared `--color-*` variables for styling. The
component must own consent, real connection/activity state, timer, start/stop,
microphone guidance and text recovery. Only request assessment after backend
completion confirmation. Candidate invitations must never render owner plans.

Currently the interview screen is explicitly disconnected, uses no microphone,
has no decorative listening activity and offers no fake completed interview.
The assessment-availability action delegates prerequisite enforcement to the API;
it does not synthesize an interview or completion state.

## Reporting agent

`backend/app/agents/reporting/agent.py` now builds schema-valid reports directly
from the assessment without an additional provider call. It rejects mismatched
case/plan IDs, incomplete/unconsented interviews and evidence that is not an exact
candidate transcript excerpt (source_id must be its turn_id). It preserves neutral
statuses, limitations and missing evidence, creates fresh UUID versions, supplies
verification questions for recruitment and rationale-based exercises for mock.
It does not invent scores, candidate identity, resources or email delivery.
Specific model-generated answer rewrites and curated learning resources remain
future work; the shared report schema has no dedicated answer-improvement field.

Reporting alone is enabled in workflow/capabilities. Planning and assessment flags
remain false. Existing repository approval and immutable version behavior remain.
Shared contract classes and security code are unchanged.

## Commands and verification

Prerequisites: Python 3.11 (`uv sync --locked`), Node 22.12+, installed Chrome.

```powershell
uv sync --locked
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.test-tmp-final
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

This machine initially lacked Node; a portable official Node 22.16.0 was downloaded
to `%TEMP%/talentbridge-node/node-v22.16.0-win-x64` and added to PATH for commands.
Dependency/build/test commands needed execution outside the filesystem sandbox.
Default pytest temp storage was inaccessible; a workspace-local basetemp fixed it.
Prettier was used temporarily without adding it to the manifest/lockfile.

Final verification: production build passed; browser suite passed 7/7 tests;
backend suite passed 25/25, including report generation through the real workflow,
approval, regeneration and rejection of a stale approved version.

Browser tests intercept APIs with synthetic data; they verify frontend integration,
not a working guest server or live provider. They cover CTA routing, no auth links,
session success/failure, CSRF headers, CV/JD validation, preserved errors, plan
display, voice-unavailable state, nullable assessment scores, exact evidence,
displayed-version approval and mock controls. Backend tests exercise real local
persistence/auth/version behavior with synthetic fixtures and no hosted calls.

## Screenshots

Generated by `frontend/tests/workflow.spec.ts` in `frontend/screenshots/`:

- `landing-1440.png`, `landing-768.png`, `landing-390.png`
- `mode-selection.png`, `upload.png`
- `interview-unavailable.png`, `assessment.png`, `recruitment-report.png`

All application captures have a prominent fixture-only fictional-data banner.
Landing captures contain the built-in Sample preview label. The interview capture
shows the actual disconnected integration state. No live interview is claimed.

## Companion instruction to Jayanth's coding assistant

Update TalentBridge AI for the approved no-signup flow: create/resume an isolated
guest workspace using POST /api/guest-session and GET /api/session with the metadata
above. Use random server-managed HttpOnly credentials, expiry, HTTPS Secure cookies,
explicit local-development settings, CSRF protection, restricted credentialed CORS,
workspace ownership on every artifact, scoped candidate invitations, global and
per-workspace budget limits. A guest owner may create recruitment cases and approve
only its own exact report version; candidates cannot read recruiter-only data or
approve. Mock reports remain private. Keep provider keys and operational admin
server-side. Do not expose all cases or disable authorization. Add isolation,
expiry, candidate, approval and budget tests, then commit and push the existing
integration branch and coordinate responses with Drashti.

No recipient/session for Jayanth's assistant is connected in this environment;
this companion is ready to forward. No external message was sent.
