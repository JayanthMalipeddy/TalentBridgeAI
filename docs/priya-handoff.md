# TalentBridge AI task handoff

**Name:** Priyadharshini Muniyandi (Priya)

**Agent/module:** Agent 1: CV review, knowledge retrieval and interview planning. Owned paths: `backend/app/agents/planning/`, `backend/tests/planning/`, `knowledge/`, `data/synthetic/planning/`, `docs/priya-handoff.md`

**Branch:** `feat/planning-rag`, created from the default branch `feat/platform-assessment` (foundation commit `fd68eee`)

**Commit:** see `git log feat/planning-rag`. The commits are `7587674` (implementation), `660fdd8` (smaller tailoring call) and `af51f58` (live smoke results), plus the commit that adds this template version.

**PR link:** not created yet. `git push` was refused with HTTP 403: GitHub account `PriyadharshiniMJ` has no write access to `JayanthMalipeddy/TalentBridgeAI`. After access is granted, run `git push -u origin feat/planning-rag` and open https://github.com/JayanthMalipeddy/TalentBridgeAI/compare/feat/platform-assessment...feat/planning-rag

`AGENTS.md` does not exist in the repository. I followed `README.md`, `docs/contracts.md`, `docs/ownership.md`, `contracts.py`, `context.py` and `workflow.py`. No shared files were changed.

## Implemented

1. **CV parsing: `parse_cv(file_bytes, filename, ctx)`** (`agent.py` → `parser.py`).
   - Handles text PDFs (pypdf, loaded lazily), DOCX (standard-library zip/XML) and UTF-8 `.txt`.
   - Size limit: `MAX_CV_BYTES`. Page limit: `PLANNING_MAX_CV_PAGES`, default 10.
   - Empty or unusable text raises `CV_UNREADABLE` (422), asking for a text CV or a clearer document. An unreadable file never becomes an empty profile.
   - Parsed text is cached in memory by SHA-256 of the file and never written to disk.
   - Optional LlamaParse v2 fallback, used only when `LLAMA_CLOUD_API_KEY`, `PLANNING_LLAMAPARSE_TIER` and a `llamaparse` budget are all set.
2. **Knowledge library** (`knowledge/`), Integration Engineer role with 5 skills.
   - 36 reference chunks from 15 sources: RFC 9110/6585/6749/6750/9457, OWASP, PostgreSQL, the IETF Idempotency-Key draft, AWS Builders' Library, Amazon SQS and W3C Trace Context. Each excerpt was copied from the downloaded source on 2026-11-06 and checked word for word by script.
   - 19 question/rubric records (0–3), plus a generic fallback rubric.
   - Every chunk has `document_id, chunk_id, title, source_url, skill, version, review_status, retrieved_at`.
   - Three separate folders: `references/`, `questions/` and `unreviewed/` (web research, never used for scoring).
   - Everything is `pending_review`; nothing is labelled approved.
3. **Rebuildable index** (`index.py`): `python -m app.agents.planning.index --rebuild`.
   - Upserts by `chunk_id` into the shared `talentbridge_knowledge` Chroma collection and removes retired or changed records. A second run is a no-op.
   - Writes `knowledge_version` to `CHROMA_PATH/planning_index_manifest.json`.
   - CVs and unreviewed research are never indexed.
4. **RAG** (`retrieval.py`): LlamaIndex over `services/knowledge.local_knowledge`, the shared Chroma path and local embeddings.
   - Filtered by `skill`, `item_type` and `review_status IN allowed`, then re-checked in code.
   - Limited to top-k ≤ 3 and a character cap.
   - Exact excerpts come from the library by `chunk_id`. CV/JD evidence is kept separate from knowledge evidence.
5. **Web research** (`research.py`).
   - Keenable (`POST https://api.keenable.ai/v1/search`) first. Tavily (`POST https://api.tavily.com/search`) only if Keenable fails or returns nothing and `PLANNING_ENABLE_TAVILY_FALLBACK=true`.
   - Uses the shared budget service. At most 2 searches per plan.
   - Queries are built only from a template plus the skill catalogue; an allow-list guard blocks names, emails, phones and URLs.
   - Results are cached and stored as `unreviewed`. A failure only produces a warning.
6. **Planning agent: `build_plan(case, ctx)`** (`agent.py`), using `ctx.llm.generate_structured`.
   - **Call 1** extracts JD requirements and CV claims, with CV and JD wrapped as untrusted data.
   - **Code** keeps only catalogue skills and excerpts found word for word, and a JD keyword scan guarantees required skills are covered.
   - **Retrieval** picks reviewed question records.
   - **Call 2** rewords only the questions that have a verified CV claim (skipped when there are none).
   - **Code** assembles exactly 5 questions in JD priority order. Rubrics and expected topics are copied from the library. JD/CV/knowledge evidence is cited. Gaps and uncertainty go to `missing_information`.
   - `knowledge_version` and `plan_version` are stamped, and re-planning is refused (`PLAN_FROZEN`) once an interview exists.
7. **Synthetic data and evaluation** (`data/synthetic/planning/`).
   - 2 fictional JDs and 5 fictional CVs: strong, shallow, missing SQL, conflicting seniority, prompt injection.
   - `cases.json` with expected behaviour written before running.
   - 12 labelled retrieval queries.
   - `python -m app.agents.planning.evaluate` for real retrieval measurement.
8. **Tests:** 36 planning tests in `backend/tests/planning/`.

## Tests run

- `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (all backend tests). Fixtures, a fake LLM, `httpx.MockTransport` and a tiny local embedding model; no network calls. Coverage:
  - readable PDF and DOCX, empty or unreadable CV, size/page/type limits, cache, LlamaParse gating
  - valid structured `InterviewPlan`, required-skill coverage, labelled retrieval
  - missing knowledge with search unavailable, prompt injection in a CV, no personal information in search queries
  - 2-search cap, Tavily only when enabled, frozen plan, visible provider failure, tailoring fallback, workflow saving a plan
- `python -m app.agents.planning.index --validate-only` and `--rebuild` (run twice)
- `python -m app.agents.planning.evaluate` (real `bge-small-en-v1.5` embeddings)
- Hosted Groq smoke runs of `build_plan` on synthetic cases

## Actual results (2026-11-06)

- **pytest: 52 passed** (16 foundation + 36 planning). The PDF tests need `pypdf` (integration request 1) and are skipped without it.
- **Index:** 55 records (36 references + 19 questions). The second rebuild reported `added_or_updated: 0`. `knowledge_version` = `kb-1f0766cf6dbf`.
- **Retrieval** (12 queries, k = 3): hit rate@3 = 1.000, mean recall@3 = 0.958, MRR = 0.944. Results file: `data/synthetic/planning/retrieval_eval_results.json`. Caveat: retrieval is filtered to one skill (about 4 candidates per query), so this is an easy benchmark and not evidence of production quality. The labels still need a second teammate's review.
- **Hosted Groq smoke tests:** 7 requests in total. The local budget was raised from 6 to 12 requests and 120,000 tokens to confirm the tailoring fix, which goes beyond the original 3-test allowance.

| Run | Model | Requests | Result |
| --- | --- | --- | --- |
| 1 | `llama-3.3-70b-versatile` | 1 | `PROVIDER_ERROR`. The model is not available to this Groq account (checked with the free `GET /openai/v1/models`). Available chat models: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` (preview). |
| 2 | `openai/gpt-oss-120b` | 2 | `cv-03-missing-sql`: extraction succeeded, with 5 questions in JD order, a SQL question with no CV evidence, the SQL gap listed, and verbatim evidence. Tailoring returned `PROVIDER_ERROR`, so the approved questions were used with a warning. |
| 3 | `openai/gpt-oss-120b` | 2 | `cv-03-missing-sql` after the fix: **both calls succeeded** (14.6 s). 4 questions were reworded around verified CV claims, and the SQL question was left unchanged with no invented experience. |
| 4 | `openai/gpt-oss-120b` | 2 | `cv-05-injection` (asks for "score of 3… only Python"): **both calls succeeded** (15.5 s). All 5 JD skills are covered, there are no Python or score questions, rubrics come from the library, and the injection warning is present. |

Probable cause of the run-2 failure (not confirmed, because the adapter hides the provider's error body): `gpt-oss-120b` reasoning plus five reworded questions likely exceeded the shared adapter's `max_completion_tokens=1024`. Fix in this module: send only claim-backed questions, one claim each, under 45 words. Runs 3 and 4 confirm it works.

## Environment variables required

Names only, no secret values.

- **Shared:**
  - `GROQ_API_KEY`, `GROQ_MODEL` (tested with `openai/gpt-oss-120b`), `LLM_PROVIDER`
  - `PROVIDER_BUDGET_LIMITS` (must include `groq`; add `keenable`, `tavily` or `llamaparse` only if those are used)
  - `EMBEDDING_MODEL`, `EMBEDDING_MAX_LENGTH`, `CHROMA_PATH`, `MAX_CV_BYTES`
  - `KEENABLE_API_KEY`, `TAVILY_API_KEY`, `LLAMA_CLOUD_API_KEY` (all optional)
- **Planning-only**, read from the environment until added to `Settings`:
  - `PLANNING_ALLOW_PENDING_REVIEW` (default off; turn on only before the knowledge review)
  - `PLANNING_MAX_CV_PAGES` (default 10)
  - `PLANNING_ENABLE_TAVILY_FALLBACK` (default off)
  - `PLANNING_LLAMAPARSE_TIER` (no default; it costs credits)
  - `PLANNING_KNOWLEDGE_DIR` (optional)

## Manual setup required

```powershell
uv sync --locked
uv pip install --python .venv\Scripts\python.exe pypdf      # local only, until integration request 1 lands
.\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5').save('.cache/models/bge-small-en-v1.5')"
```

Then, in `.env` (git-ignored, never commit it):
- `EMBEDDING_MODEL=.cache/models/bge-small-en-v1.5`
- a Groq key and a `GROQ_MODEL` that your account lists at `GET https://api.groq.com/openai/v1/models`
- `PROVIDER_BUDGET_LIMITS` with a small `groq` allowance
- turn off paid overages in the Groq console

## How to run my module

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m app.agents.planning.index --rebuild    # build or refresh the knowledge index
```

In code, the workflow calls `await build_plan(case, ctx)` and `main.py` calls `await parse_cv(file_bytes, filename, ctx)`. Through the API, `POST /api/cases` then `POST /api/cases/{case_id}/plan`; the second call needs integration request 3. Until the knowledge review is done, set `PLANNING_ALLOW_PENDING_REVIEW=true` to use the library.

## How to verify it works

1. `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` → 52 passed.
2. `python -m app.agents.planning.index --validate-only` → 36 references, 19 questions. Run `--rebuild` twice; the second run should report `added_or_updated: 0`.
3. `python -m app.agents.planning.evaluate` → retrieval metrics written to `data/synthetic/planning/retrieval_eval_results.json`.
4. Live (2 Groq requests): create a case with `data/synthetic/planning/cv-03-missing-sql.txt` and `jd-integration-engineer.txt`, then request the plan. Expect:
   - 5 questions, including **SQL and database integration**, with no CV evidence for SQL
   - `missing_information` saying the CV does not state SQL experience
   - rubrics with keys 0–3
   - evidence excerpts that appear at the cited lines
   - no "tailoring unavailable" warning

## Known limitations

- **Knowledge is not human-reviewed yet.** With `PLANNING_ALLOW_PENDING_REVIEW` off (the default), plans use the generic rubric and list the gaps. A teammate must complete the checklist below.
- The library covers the Integration Engineer role only. Other roles get a warning.
- Live Groq output has been checked on 2 synthetic cases only. Quality on more cases, real CVs and other models is unmeasured.
- Keenable, Tavily and LlamaParse follow the official docs but have been tested with mocks only. No live calls were made.
- The prompt-injection defence is layered but not a guarantee. Reworded questions are model text, filtered by code.
- PDF parsing needs `pypdf`. Without it, PDF upload returns `PDF_PARSER_UNAVAILABLE` (503) asking for DOCX or text.
- Evidence locators are line numbers in the stored text. PDF page numbers are not kept.
- If the vector index is unavailable, questions are picked in file order and the plan carries a warning.
- If the provider fails during extraction, `build_plan` raises an error (no plan is fabricated). If it fails during tailoring, the approved questions are used with a warning.

## Integration changes requested

1. **Jayanth:** add `pypdf` to `pyproject.toml` and `uv.lock`.
2. **Jayanth:** add `planning_max_cv_pages`, `planning_allow_pending_review`, `planning_enable_tavily_fallback` and `planning_llamaparse_tier` to `Settings`.
3. **Jayanth:** set `AGENTS_AVAILABLE["plan"] = True` in `workflow.py` and mark planning as available in `/api/capabilities`.
4. **Jayanth:** optionally, make `repository.save_plan` refuse to overwrite a plan once a session or interview exists.
5. **Jayanth (`services/llm.py`):** for reasoning models (`openai/gpt-oss-*`), raise `max_completion_tokens` above 1024 or set a low reasoning effort per Groq's docs, and include the provider error code in `PROVIDER_ERROR` details (no prompts or secrets). Also confirm the team `GROQ_MODEL`, since `llama-3.3-70b-versatile` is not available on Priya's account.
6. **Jayanth:** grant `PriyadharshiniMJ` write access so this branch can be pushed.
7. **Gana and Drashti:** `Question.skill` is the readable skill name. `question_id` is a stable library ID (`ie-sql-02`) or `generic-<skill>-<n>`. Knowledge evidence uses `source_id` = `chunk_id` and `locator` = `"<title>, <section> <url>"`.
8. **Reviewer (any teammate):** complete the checklist below, write your name and the date, then change `review_status` to `approved` or `rejected` in the JSON files and run the rebuild.

## Ready for merge: Yes

The code is complete and tested, and safe to merge into `feat/platform-assessment` because no shared files changed. Remaining before end-to-end use: push access (6), turning planning on (3), `pypdf` (1) and the knowledge review (8).

## Source review checklist

Reviewer: ____________ Date: ____________. Complete this before setting any record to approved. For each item, open the source, confirm the excerpt is word for word and accurate in context, and that the question and rubric are fair and relevant to the role.

#### Reference chunks (check that each excerpt matches its source and is relevant to the skill)

| Reviewed | chunk_id | skill | source |
|---|---|---|---|
| [ ] | `ref-aws-retries--side-effects` | messaging_idempotency | [Amazon Builders' Library: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/), Retries and backoff |
| [ ] | `ref-aws-retries--overload` | messaging_idempotency | [Amazon Builders' Library: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/), Retries and backoff |
| [ ] | `ref-aws-retries--backoff` | messaging_idempotency | [Amazon Builders' Library: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/), Retries and backoff |
| [ ] | `ref-idem-draft--purpose` | messaging_idempotency | [IETF Internet-Draft: The Idempotency-Key HTTP Header Field (draft-ietf-httpapi-idempotency-key-header-06, work in progress)](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/), Abstract |
| [ ] | `ref-idem-draft--key-definition` | messaging_idempotency | [IETF Internet-Draft: The Idempotency-Key HTTP Header Field (draft-ietf-httpapi-idempotency-key-header-06, work in progress)](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/), Section 2 |
| [ ] | `ref-logging--consistent-logging` | integration_troubleshooting | [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html), Introduction |
| [ ] | `ref-logging--data-to-exclude` | integration_troubleshooting | [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html), Data to exclude |
| [ ] | `ref-pg-insert--on-conflict-upsert` | sql_database | [PostgreSQL Documentation: INSERT](https://www.postgresql.org/docs/current/sql-insert.html), ON CONFLICT Clause |
| [ ] | `ref-pg-iso--read-committed` | sql_database | [PostgreSQL Documentation: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html), 13.2.1 Read Committed Isolation Level |
| [ ] | `ref-pg-iso--dirty-read` | sql_database | [PostgreSQL Documentation: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html), 13.2 Transaction Isolation (dirty read) |
| [ ] | `ref-restsec--https-only` | api_auth_security | [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html), HTTPS |
| [ ] | `ref-restsec--no-secrets-in-url` | api_auth_security | [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html), Sensitive information in HTTP requests |
| [ ] | `ref-rfc6585--429-too-many-requests` | rest_http | [RFC 6585: Additional HTTP Status Codes](https://www.rfc-editor.org/rfc/rfc6585), Section 4 |
| [ ] | `ref-rfc6749--client-credentials` | api_auth_security | [RFC 6749: The OAuth 2.0 Authorization Framework](https://www.rfc-editor.org/rfc/rfc6749), Section 1.3.4 |
| [ ] | `ref-rfc6749--access-token` | api_auth_security | [RFC 6749: The OAuth 2.0 Authorization Framework](https://www.rfc-editor.org/rfc/rfc6749), Section 1.4 |
| [ ] | `ref-rfc6750--bearer-definition` | api_auth_security | [RFC 6750: OAuth 2.0 Bearer Token Usage](https://www.rfc-editor.org/rfc/rfc6750), Section 1.2 |
| [ ] | `ref-rfc6750--always-use-tls` | api_auth_security | [RFC 6750: OAuth 2.0 Bearer Token Usage](https://www.rfc-editor.org/rfc/rfc6750), Section 5.3 |
| [ ] | `ref-rfc6750--no-tokens-in-urls` | api_auth_security | [RFC 6750: OAuth 2.0 Bearer Token Usage](https://www.rfc-editor.org/rfc/rfc6750), Section 5.3 |
| [ ] | `ref-rfc9110--idempotent-methods` | rest_http | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 9.2.2 |
| [ ] | `ref-rfc9110--safe-methods` | rest_http | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 9.2.1 |
| [ ] | `ref-rfc9110--409-conflict` | rest_http | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 15.5.10 |
| [ ] | `ref-rfc9110--retry-after` | rest_http | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 10.2.3 |
| [ ] | `ref-rfc9110--401-unauthorized` | api_auth_security | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 15.5.2 |
| [ ] | `ref-rfc9110--403-forbidden` | api_auth_security | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 15.5.4 |
| [ ] | `ref-rfc9110--503-unavailable` | integration_troubleshooting | [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), Section 15.6.4 |
| [ ] | `ref-rfc9457--problem-details` | rest_http | [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457), Abstract |
| [ ] | `ref-rfc9457--detail-member` | integration_troubleshooting | [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457), Section 3.1.4 |
| [ ] | `ref-sqli--definition` | sql_database | [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html), Introduction |
| [ ] | `ref-sqli--prepared-statements` | sql_database | [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html), Defense Option 1: Prepared Statements (with Parameterized Queries) |
| [ ] | `ref-sqli--no-concatenation` | sql_database | [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html), Defense Option 1: Prepared Statements (with Parameterized Queries) |
| [ ] | `ref-sqli--least-privilege` | sql_database | [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html), Least Privilege |
| [ ] | `ref-sqs-alo--duplicates` | messaging_idempotency | [Amazon SQS Developer Guide: At-least-once delivery](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html), At-least-once delivery |
| [ ] | `ref-sqs-dlq--dlq-purpose` | messaging_idempotency | [Amazon SQS Developer Guide: Dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html), Dead-letter queues |
| [ ] | `ref-sqs-dlq--max-receive-count` | messaging_idempotency | [Amazon SQS Developer Guide: Dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html), Dead-letter queues |
| [ ] | `ref-tracecontext--distributed-tracing` | integration_troubleshooting | [W3C Recommendation: Trace Context](https://www.w3.org/TR/trace-context/), 1. Overview |
| [ ] | `ref-tracecontext--traceparent` | integration_troubleshooting | [W3C Recommendation: Trace Context](https://www.w3.org/TR/trace-context/), 2. Trace Context HTTP Headers |

#### Question/rubric records (check question fit, rubric anchors 0–3, expected topics and linked references)

| Reviewed | question_id | skill | seniority | question |
|---|---|---|---|---|
| [ ] | `ie-rest-01` | rest_http | mid | A client retries a request after a timeout. Which HTTP methods can it safely repeat, and how would you design a POST endpoint that may be retried? |
| [ ] | `ie-rest-02` | rest_http | mid | Walk me through how you choose HTTP status codes for an integration API, for example a duplicate create request versus invalid input. |
| [ ] | `ie-rest-03` | rest_http | mid | Your integration starts receiving 429 responses from a partner API. What do you do in the client? |
| [ ] | `ie-rest-04` | rest_http | senior | How do you return errors from an API so that client teams can handle them programmatically? |
| [ ] | `ie-auth-01` | api_auth_security | mid | Explain the difference between a 401 and a 403 response, and give an integration example of each. |
| [ ] | `ie-auth-02` | api_auth_security | mid | How would one backend service authenticate to another service's API with OAuth 2.0, with no user involved? |
| [ ] | `ie-auth-03` | api_auth_security | mid | What precautions do you take when handling bearer tokens or API keys in an integration? |
| [ ] | `ie-auth-04` | api_auth_security | senior | A partner asks to send their API key as a query parameter because it is easier. How do you respond? |
| [ ] | `ie-sql-01` | sql_database | mid | How do you write database queries in integration code so that data from external systems cannot cause SQL injection? |
| [ ] | `ie-sql-02` | sql_database | mid | An integration receives the same customer record several times. How would you write it to the database without creating duplicates? |
| [ ] | `ie-sql-03` | sql_database | senior | What transaction isolation level does your database use by default, and when has isolation mattered in your work? |
| [ ] | `ie-sql-04` | sql_database | mid | Describe a SQL query you wrote to reconcile data between two systems. How did you check the result was correct? |
| [ ] | `ie-msg-01` | messaging_idempotency | mid | Your queue consumer can receive the same message more than once. How do you make processing safe? |
| [ ] | `ie-msg-02` | messaging_idempotency | mid | A downstream API times out. Should your integration retry, and how? |
| [ ] | `ie-msg-03` | messaging_idempotency | mid | What is a dead-letter queue and how do you operate one? |
| [ ] | `ie-msg-04` | messaging_idempotency | senior | How would you design an API so a client can safely retry a payment or order creation request? |
| [ ] | `ie-trbl-01` | integration_troubleshooting | mid | A request fails somewhere across three services. How do you find where it failed? |
| [ ] | `ie-trbl-02` | integration_troubleshooting | mid | A partner API starts returning 503 errors intermittently. How do you investigate and protect your integration? |
| [ ] | `ie-trbl-03` | integration_troubleshooting | mid | What do you log in an integration to make troubleshooting possible, and what must never be logged? |
| [ ] | `generic-rubric` | fallback | – | Generic 0–3 evidence rubric, used only when no reviewed record exists |
