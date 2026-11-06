# TalentBridge AI — shared foundation

Stage-one integration foundation using Python 3.11, FastAPI, Pydantic v2, SQLAlchemy/SQLite, LangGraph, persistent Chroma, LlamaIndex/local Sentence Transformers and React/TypeScript/Vite/Tailwind.

The repository was empty when inspected. GitHub repository metadata identifies `main` as its default branch; no branch refs or commits existed. Work is on `feat/platform-assessment`.

Working: emerald landing page, no-signup frontend screens, evidence-preserving reporting/coaching, health/capabilities, recruiter-authenticated case APIs, transactional persistence, expiring case-scoped session issuance, exact-version approval, budgets and schema-validated Groq adapter. Planning, interview execution and assessment return `NOT_IMPLEMENTED`. Guest-session endpoints are not implemented yet: the frontend shows an explicit session-service error rather than bypassing authentication. A fresh case cannot yet complete the live interview workflow. See [Drashti's integration handoff](docs/drashti-handoff.md).
Working: foundation APIs, recruiter authentication, transactional persistence, exact-version approval, budgets, schema-validated Groq adapter, and the integrated text interview. Gana's ZIP has been adapted to the shared repository and contracts; browser ElevenLabs support is gated on explicit configuration and supervision. Planning, assessment and reporting still return `NOT_IMPLEMENTED` pending their implementations. Session issuance requires a saved plan. See [Gana's integration handoff](docs/gana-handoff.md) for the complete API, setup and limitations.

## Start on Windows PowerShell

Prerequisites: Python 3.11 via `uv`, Node 22.12+ (tested with Node 24.18.0).

From the repository root:

```powershell
uv python install 3.11
uv sync --locked
Copy-Item .env.example .env
notepad .env
```

Set `RECRUITER_API_TOKEN` to a long random secret for the existing operational API routes. The redesigned frontend never requests this secret; it awaits the guest-cookie backend described in the handoff. No AI key is required to start the foundation or generate a report from an existing assessment. Do not commit `.env`.

Terminal 1, repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

Terminal 2, repository root:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

Open http://localhost:5173. Health: http://127.0.0.1:8000/api/health. OpenAPI: http://127.0.0.1:8000/openapi.json; interactive docs: http://127.0.0.1:8000/docs. Keep the single-instance development servers local. If exposing a demo, terminate HTTPS and limit request body size at your proxy. CORS accepts only `FRONTEND_ORIGIN` (comma-separated exact origins).

## Validate

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
npm.cmd --prefix frontend run build
```

`uv.lock` pins the full Python dependency graph and `frontend/package-lock.json` pins npm dependencies. Use locked installs. Tests cover every shared contract, persistence/reopening, report version approval, auth isolation, expiration, CORS, concurrent reservations, bounded schema repair and local retrieval wiring. No live hosted-provider test or production embedding-model quality evaluation is claimed.

## Providers and budgets

Groq is the default implemented LLM adapter. Configure `GROQ_API_KEY`, a model available to your account supporting JSON mode in `GROQ_MODEL`, and an explicit request allowance, e.g. `PROVIDER_BUDGET_LIMITS={"groq":{"requests":20,"tokens":50000}}`. This is a local lifetime spending ceiling, not a declaration of your provider's real quota. Choose limits within verified free allowances and disable paid overages in the provider account. Empty or unknown quotas deny calls. The application never enables paid overages.

The budget service distinguishes requests, tokens, credits, minutes and money. Groq reserves one request per attempt, optionally reserves a conservative token bound, and reconciles usage. A repair is a separately budgeted call. Configured money/credit/minute constraints disable Groq calls because their cost cannot be safely estimated by this adapter. Missing token counts retain the conservative reservation. Provider errors retain the request charge. Local quotas do not track calls made outside this application.

Gemini and Ollama settings are present with explicit unavailable adapters. ElevenLabs, Keenable, Tavily, LlamaParse and Langfuse are unavailable integrations in this stage. Planning, interviewing and assessment are placeholders; reporting is implemented without an additional provider call. See `/api/capabilities` for configuration and implementation state.
Gemini and Ollama settings are present with explicit unavailable adapters. Keenable, Tavily, LlamaParse and Langfuse remain unavailable integrations. The interview agent supports text; ElevenLabs browser mode is disabled by default until credentials, an authenticated agent, supervised operation, webhook and minute budget are configured. No telephone calling is included. See `/api/capabilities` for configuration and implementation state.

`services/knowledge.py` provides a lazy persistent Chroma/LlamaIndex adapter. Set `EMBEDDING_MODEL` to a downloaded local Sentence Transformers directory. It uses CPU and local files only. Startup does not download a model or index CVs. Priya owns knowledge content and retrieval. Test embedding models are test-only.

Candidate links contain random tokens in the URL fragment, never query strings, and the database stores only SHA-256 hashes. Sessions expire after `SESSION_TTL_SECONDS`. The candidate page captures the token into memory, clears the fragment and requires consent. Refreshing requires reopening the original invitation. Each case has one frozen interview session; mock ownership cannot be reassigned. Recruiter routes cannot read mock reports. An expired owning session loses report access; renewal is not implemented.

Default interview duration is six minutes, with an eight-minute hard cap. The server expires sessions without relying on the browser timer. Provider-side termination uses the separately verified ElevenLabs duration limit; voice must remain supervised. Unknown provider outcomes retain their reservation until confirmed or reviewed by the recruiter.

## Try the integrated text interview

Until Priya's planner arrives, create an explicitly labelled fixture demo. This uses fictional data and a manually authored plan, not live AI planning or approved RAG:

```powershell
.\.venv\Scripts\python.exe scripts/create_interview_demo.py --fixture-demo --mode recruitment
# Use --mode mock for a private mock session.
```

Open the invitation stored in `.cache/interview-demo-recruitment.txt` locally. Do not commit or log this token-bearing file. The candidate page displays the fixture warning. Consent, five questions, typed answers, stopping and completion use the real integrated APIs. Follow-ups use the shared LLM only when configured and budgeted; otherwise planned questions continue with a visible warning. Assessment/reporting remain pending.

Frontend interaction tests: `npm.cmd --prefix frontend test`. Provider tests are mocked; no live call is claimed. Browser agent setup and billing/retention details are in [gana-handoff.md](docs/gana-handoff.md).

## Handoff

Read [contracts](docs/contracts.md), [ownership](docs/ownership.md), [contracts.py](backend/app/contracts.py), [context.py](backend/app/context.py), [repository.py](backend/app/repository.py), and [workflow.py](backend/app/workflow.py).

Official references checked for implementation:

- [Groq JSON output and validation](https://console.groq.com/docs/structured-outputs)
- [Groq API endpoint and request fields](https://console.groq.com/docs/api-reference)
- [LangGraph StateGraph compilation](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile)
- [Chroma persistent client](https://docs.trychroma.com/reference/python)
- [LlamaIndex local embeddings](https://developers.llamaindex.ai/python/framework/module_guides/models/embeddings/)
