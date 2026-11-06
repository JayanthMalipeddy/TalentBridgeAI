# Handoff: Agent 1, CV review, knowledge retrieval and interview planning

| Field | Value |
| --- | --- |
| Name | Priyadharshini Muniyandi (Priya) |
| Module | `backend/app/agents/planning/`, `knowledge/`, `data/synthetic/planning/`, `backend/tests/planning/` |
| Branch | `feat/planning-rag`, based on `feat/platform-assessment` (foundation `fd68eee`, the repo's default branch) |
| Commit / PR | See `git log feat/planning-rag` and the PR into `feat/platform-assessment` |
| Merge readiness | Ready for review. Integration requests 1 and 3 below are needed before PDF upload and the `/plan` endpoint work end to end. |

`AGENTS.md` does not exist in the repository. I followed `README.md`, `docs/contracts.md`, `docs/ownership.md`, `contracts.py`, `context.py` and `workflow.py`. No shared files were changed.

## Implemented

| Brief step | Implementation |
| --- | --- |
| 1. Local parsing | `parse_cv` in `agent.py` → `parser.py`. Handles text PDFs (pypdf, lazy import), DOCX (standard-library zip/XML) and UTF-8 .txt. Enforces the size limit (`MAX_CV_BYTES`) and page limit (`PLANNING_MAX_CV_PAGES`, default 10). Empty or unusable text raises `CV_UNREADABLE` (422) asking for a text CV or a clearer document, so an unreadable file never becomes an empty profile. Results are cached in memory by SHA-256 of the file and never written to disk. The optional LlamaParse v2 fallback runs only if `LLAMA_CLOUD_API_KEY`, `PLANNING_LLAMAPARSE_TIER` and a `llamaparse` budget are all set. |
| 2. Knowledge library | Integration Engineer role, 5 skills (`knowledge/skills.json`). 36 reference chunks from 15 sources (RFC 9110/6585/6749/6750/9457, OWASP, PostgreSQL, IETF Idempotency-Key draft, AWS Builders' Library, Amazon SQS, W3C Trace Context). 19 question/rubric records plus a generic fallback rubric. Each excerpt was copied from the downloaded source on 2026-11-06 and checked word for word by script. Every chunk carries `document_id, chunk_id, title, source_url, skill, version, review_status, retrieved_at`. Folders are kept separate: `references/` (curated), `unreviewed/` (web research), `questions/` (question/rubric records). Everything is `pending_review`; nothing is labelled approved. |
| Rebuild command | `python -m app.agents.planning.index --rebuild` (see Run). Upserts by `chunk_id` into the shared `talentbridge_knowledge` Chroma collection and removes retired or changed records. Writes `knowledge_version` to `CHROMA_PATH/planning_index_manifest.json`. A second run is a no-op. Unreviewed research and CVs are never indexed. |
| 3. RAG | `retrieval.py`: LlamaIndex `VectorStoreIndex.from_vector_store` over `services/knowledge.local_knowledge` (shared Chroma path and local embeddings). Results are filtered in the vector query by `skill`, `item_type` and `review_status IN allowed`, then re-checked in code. Context is limited to top-k ≤ 3 and a character cap. Excerpts come from the library by `chunk_id`, so they are exact. CV/JD evidence (`source_type` cv / job_description, `source_id` `<case>:cv|jd`) is kept separate from knowledge evidence. |
| 4. Web research | `research.py`: Keenable (`POST https://api.keenable.ai/v1/search`, `X-API-Key`) first. Tavily (`POST https://api.tavily.com/search`, Bearer) only when Keenable fails or returns nothing **and** `PLANNING_ENABLE_TAVILY_FALLBACK=true`. Each call goes through `ctx.budget.reserve/reconcile`. Queries come only from a fixed template plus the skill catalogue, and an allow-list guard rejects any other word, email, phone or URL. At most 2 searches per plan. Results are cached and saved to `knowledge/unreviewed/web-*.json` as `unreviewed`; they are never loaded, indexed or used for scoring. A failure only produces a warning. |
| 5. Planning agent | `build_plan` in `agent.py` makes 2 small `ctx.llm.generate_structured` calls, which fits the shared adapter's 1024-token output cap. (1) Extract JD requirements and CV claims, with CV and JD wrapped in `<cv>`/`<job_description>` tags as untrusted data. Code keeps only catalogue skills and excerpts found word for word on a single line, and a keyword scan of the JD acts as a safety net for required skills. (2) Reword only the chosen questions that have a verified CV claim (one claim each, under 45 words), and skip the call if none do. **Code** assembles exactly 5 questions in JD priority order. The rubric (0–3) and expected topics are copied from reviewed records, never written by the model. Each question cites JD, CV and knowledge evidence. Missing CV evidence, extraction uncertainty, discarded excerpts and knowledge gaps go to `missing_information`. Plan versioning: `knowledge_version` = hash of library content, review state and embedding model; `plan_version` = hash of the plan content. Re-planning is refused with `PLAN_FROZEN` once an interview exists. |
| 6. Tests | 36 planning tests in `backend/tests/planning/`, using fixtures, a fake LLM, `httpx.MockTransport` and a tiny local bag-of-words embedding model. No network calls. |

## Tests and actual results (2026-11-06)

`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` → **52 passed** (16 foundation + 36 planning).

The tests cover:
- readable PDF and DOCX, empty or scanned PDF, corrupt files, page/size/type limits, the hash cache, LlamaParse gating and a mocked fallback, upload through `POST /api/cases`
- library metadata and separation, rejection of invalid records, an idempotent rebuild with upsert and retirement, review-status and skill filters, bounded context, labelled retrieval, a missing embedding model
- a valid plan that round-trips through the contract, required-skill coverage (CV without SQL still gets a SQL question even when the model misses SQL), prompt injection in a CV, missing knowledge with search unavailable, no personal information in search queries plus the 2-search cap and caching, Tavily used only when enabled, frozen plans, visible provider failure, tailoring fallback, no tailoring call when the CV has no verified claims, vector index unavailable, unreviewed library unused by default, and the workflow saving a plan

The PDF tests need `pypdf` (see integration request 1). Without it they are skipped, not failed.

**Real retrieval measurement**, kept separate from the mocked tests: `python -m app.agents.planning.evaluate` with `bge-small-en-v1.5`, 12 labelled queries, k = 3. The result file is `data/synthetic/planning/retrieval_eval_results.json`.

| Metric | Result |
| --- | --- |
| Hit rate@3 | 1.000 |
| Mean recall@3 | 0.958 |
| MRR | 0.944 |

Caveat: retrieval is filtered to one skill, so each query ranks only about 4 records. This is an easy benchmark and not evidence of production quality. The labels were written by this module and still need a second teammate's review.

**Hosted smoke tests (2026-11-06): 3 Groq requests used of the 6-request local budget.** Each run was `build_plan` called directly on `cv-03-missing-sql.txt` + `jd-integration-engineer.txt`, with `PLANNING_ALLOW_PENDING_REVIEW=true`.

| Run | Model | Requests | Result |
| --- | --- | --- | --- |
| 1 | `llama-3.3-70b-versatile` | 1 | `PROVIDER_ERROR`. The model is listed in Groq's docs but is not available to this Groq account (checked with the free `GET /openai/v1/models`). Chat models the account can use: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` (preview). |
| 2 | `openai/gpt-oss-120b` | 2 | **Extraction succeeded** (about 15 s). The plan had 5 questions in JD priority order (REST, SQL, messaging, auth, troubleshooting), with no CV evidence for SQL. `missing_information` included "CV does not state experience with SQL…" plus the model's own notes. Every CV/JD/knowledge excerpt matched its source, and rubrics came from the library. **Tailoring returned `PROVIDER_ERROR`**, so the approved questions were used unchanged and a warning was added, as designed. |

Probable cause of the tailoring failure (not confirmed, because the shared adapter hides the provider's error body): `gpt-oss-120b` is a reasoning model, and with the adapter's `max_completion_tokens=1024`, reasoning plus five reworded questions likely exceeded the cap. A hint is that the tokens record for that call holds the reserved upper bound, which happens when usage isn't returned. Module-side mitigation, made after run 2: only questions with a verified CV claim are sent for tailoring, with one claim each and a request for under 45 words; if no question has a claim, no tailoring call is made. **This mitigation has not been re-tested live**, to stay within the 3-call smoke budget. See integration request 7 for the proper fix.

## Environment variables (names only)

- Shared: `GROQ_API_KEY`, `GROQ_MODEL`, `LLM_PROVIDER`, `PROVIDER_BUDGET_LIMITS` (e.g. `{"groq":{"requests":20,"tokens":50000}}`, plus `"keenable"`, `"tavily"` or `"llamaparse"` entries if those are used), `EMBEDDING_MODEL`, `EMBEDDING_MAX_LENGTH`, `CHROMA_PATH`, `MAX_CV_BYTES`, `KEENABLE_API_KEY`, `TAVILY_API_KEY`, `LLAMA_CLOUD_API_KEY`.
- Planning-only, read from the environment until added to `Settings`:
  - `PLANNING_ALLOW_PENDING_REVIEW` (default off; turn on only for development or demo before the review)
  - `PLANNING_MAX_CV_PAGES` (default 10)
  - `PLANNING_ENABLE_TAVILY_FALLBACK` (default off)
  - `PLANNING_LLAMAPARSE_TIER` (no default; the LlamaParse docs show `agentic`, and it costs credits)
  - `PLANNING_KNOWLEDGE_DIR` (optional)

## Manual setup

```powershell
uv sync --locked
uv pip install --python .venv\Scripts\python.exe pypdf   # local only, until integration request 1 lands
.\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5').save('.cache/models/bge-small-en-v1.5')"
# In .env: EMBEDDING_MODEL=.cache/models/bge-small-en-v1.5 (the .cache/ folder is git-ignored)
```

## Run and verify

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m app.agents.planning.index --validate-only   # check the knowledge files
.\.venv\Scripts\python.exe -m app.agents.planning.index --rebuild         # build or refresh the index (run twice: added_or_updated = 0)
.\.venv\Scripts\python.exe -m app.agents.planning.evaluate                # real retrieval measurement
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Hosted smoke test (up to 2 Groq requests), after Groq is configured with a model your account can use (check `GET https://api.groq.com/openai/v1/models`; `openai/gpt-oss-120b` was used above) and with `PLANNING_ALLOW_PENDING_REVIEW=true` until the review is done:
1. Start the backend using the command in the README.
2. Create a case: `POST /api/cases` with `data/synthetic/planning/cv-03-missing-sql.txt` and `jd-integration-engineer.txt`.
3. Request the plan: `POST /api/cases/{id}/plan`. This needs integration request 3.
4. Expect 5 questions, including a SQL question, and a `missing_information` entry saying the CV does not state SQL experience.

## Synthetic data

`data/synthetic/planning/` holds 2 fictional JDs, 5 fictional CVs and `cases.json`, which lists 5 case definitions with their expected behaviour written before running:
- strong candidate
- shallow candidate
- missing SQL
- conflicting seniority
- prompt injection

`retrieval_labels.jsonl` holds 12 labelled retrieval queries, for Jayanth's evaluations as well.

## Known limitations

- **Nothing is human-reviewed yet.** By default (`PLANNING_ALLOW_PENDING_REVIEW` off), plans use the generic rubric and list the gaps. To use the library, review it, set `review_status` to `approved` per record, and rebuild.
- The library covers the Integration Engineer role only. Other roles get a warning.
- Live Groq output has been checked on one case only (see the hosted smoke tests); quality across cases is unmeasured. Live tailoring has not yet succeeded with `gpt-oss-120b` under the 1024-token cap. If the provider fails during extraction, an error is raised (no plan is fabricated). If it fails during tailoring, the approved questions are used unchanged and a warning is added.
- LlamaParse and Keenable/Tavily were implemented from the official docs but tested only with mocks. No live calls were made.
- The prompt-injection defence is layered (tags, the system rule, catalogue/word-for-word checks, rubrics written in code, filtering of reworded questions), but it isn't a guarantee. Reworded questions are model text.
- Locators are line numbers in the stored `cv_text`/`job_description`. PDF page numbers are not kept.
- If the vector index isn't available, questions are picked in file order and the plan carries a visible warning.

## Integration requests

1. **Jayanth:** add `pypdf` to `pyproject.toml` and `uv.lock`. It is needed for PDF CVs; until then, PDF upload returns `PDF_PARSER_UNAVAILABLE` (503) asking for DOCX or text.
2. **Jayanth:** add `planning_max_cv_pages`, `planning_allow_pending_review`, `planning_enable_tavily_fallback` and `planning_llamaparse_tier` to `Settings`. The module reads environment variables until then.
3. **Jayanth:** set `AGENTS_AVAILABLE["plan"] = True` in `workflow.py` and mark planning as available in `/api/capabilities` (`main.py`).
4. **Jayanth:** optionally, have `repository.save_plan` refuse to overwrite a plan once a session or interview exists. `build_plan` already refuses once an interview exists, but the repository can't look up sessions by case.
5. **Gana and Drashti:** `Question.skill` holds the readable skill name (e.g. "SQL and database integration"). `question_id`s are stable library IDs (`ie-sql-02`) or `generic-<skill>-<n>`. Knowledge evidence uses `source_id` = `chunk_id`, and `locator` = `"<title>, <section> <url>"`.
6. **Reviewer (any teammate):** go through the checklist below and record your name and the date here. Then change `review_status` from `pending_review` to `approved` (or `rejected`) in the JSON files, and run the rebuild.
7. **Jayanth (`services/llm.py`):** for reasoning models such as `openai/gpt-oss-*`, raise `max_completion_tokens` above 1024, or send a low reasoning effort following Groq's documentation, and consider including the provider's error code in `PROVIDER_ERROR` details (without prompts or secrets). Assessment and reporting are likely to hit the same cap. Also confirm the team's `GROQ_MODEL`: `llama-3.3-70b-versatile` is not available on Priya's account.

## Source review checklist

Reviewer: ____________ Date: ____________. For each item, open the source, confirm the excerpt is word for word and accurate in context, and that the question and rubric are fair and relevant to the role.

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
