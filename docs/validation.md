# Integration validation — 6 November 2026

Windows, Python 3.11.16, Node 24.18.0. Integrated teammate code plus reviewed patch:

- Backend: 101 pytest tests passed; provider responses mocked in automated tests.
- Frontend components: 4 Vitest tests passed.
- Frontend browser regressions: 7 Playwright tests passed with labelled mocked APIs, covering workspace/auth errors, plan flow, assessment evidence, exact approval and mock controls.
- Production build: TypeScript/Vite passed; large-chunk advisory remains.
- Local retrieval: downloaded Sentence Transformers all-MiniLM-L6-v2; persistent Chroma index rebuilt with 55 records (36 references, 19 questions), all pending human review.
- Real-provider smoke: two fictional cases completed five-question text interviews, real Groq planning/assessment and evidence-preserving reports. Recruitment approval and mock approval rejection checked. Reporting retries reused the same version. Mock assessment required an explicit retry after a provider error.

See `evals/live-integration-results.json` for actual inputs, frozen plans, transcripts, output limitations and recorded provider usage. Unknown token usage on failed calls is conservatively charged at the reserved bound, not reported as measured provider consumption. No live voice test, human-reviewed score agreement, baseline comparison or production validation is claimed.

Official model references used during setup: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 and https://console.groq.com/docs/model/openai/gpt-oss-20b . The configured Groq model was verified by actual calls.

## Phone integration checks

108 backend tests passed, including seven new phone-flow tests; 6 frontend component tests and 7 browser regressions passed; production build passed. Phone tests mock providers and cover explicit recruiter authorization, dial-once behavior, unknown outcomes, quota cleanup, spoken-consent handling and confirmed transcript to report. A read-only ElevenLabs phone inventory returned zero connected numbers. No live phone call was placed.
