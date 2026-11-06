# Foundation validation

## Interview integration update

The integrated suite now has **32 passing backend tests** and **4 passing frontend interaction tests**. TypeScript/Vite production build passes. Tests exercise five-question text completion, one bounded follow-up, failure fallback, consent refusal/withdrawal, expiration, persistence/recovery, frozen plans, case isolation, authenticated webhooks, duplicate events, exact transcript mapping, unknown timestamps, uncertain authorization, quota/concurrency controls and explicit operator reconciliation. Hosted interview responses remain mocked in tests.

A read-only request verified access to the configured ElevenLabs agent and identified authentication/concurrency/bursting/prompt setup blockers documented in `gana-handoff.md`. No call was initiated and no provider settings were changed. The fixture-demo CLI was exercised against an isolated SQLite file; its invitation is excluded from Git.

## Original foundation checks

Validated on Windows with Python 3.11.16 and Node 24.18.0.

- `python -m pytest -q -p no:cacheprovider`: 16 passed, including contract validation, SQL persistence/reopening, approval invalidation, auth and session isolation, CORS, atomic concurrent reservations, schema repair limits, fail-closed budgets, local Sentence Transformers embeddings and persistent Chroma/LlamaIndex wiring.
- `npm run build`: TypeScript and Vite production build passed.
- `npm audit`: zero reported vulnerabilities after updating Vite to 7.3.7.

Hosted provider calls are tested with HTTP mocks. No production provider credentials were supplied or used. The local embedding smoke test constructs a tiny test-only model without downloading weights; it does not measure retrieval quality. No end-to-end agent or browser voice interview is claimed, since those integrations are placeholders.

Initial sandboxed pytest execution was unable to access the Windows pytest temp directory. Tests passed when run with the required filesystem access. A test-only embedding model exposed a missing sequence-length value; the adapter now uses configurable EMBEDDING_MAX_LENGTH (512 by default), and the full suite passes.

Python's resolver reports that a transitive dependency requests the removed `huggingface-hub[inference]` extra. Installed versions import and the local embedding integration passes; hosted Hugging Face inference is neither used nor supported here.
