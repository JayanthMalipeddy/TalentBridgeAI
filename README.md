# TalentBridge AI

Integrated recruitment and mock-interview prototype: Python 3.11, FastAPI/Pydantic v2, LangGraph, SQLite/SQLAlchemy, persistent Chroma with LlamaIndex/local embeddings, Groq, and React/TypeScript/Vite/Tailwind.

Priya's planning/RAG, Gana's text/browser interview integration, Drashti's frontend/reporting, and Jayanth's assessment/workflow are connected. The GitHub default branch is `feat/platform-assessment`; this release is prepared on `feat/release-integration`. Do not assume `main` exists.

## What works

Upload PDF/DOCX or paste CV text, generate five questions with local retrieval and Groq, conduct a consented text interview, assess exact transcript evidence, and generate an evidence-preserving recruitment report or private mock feedback. Recruitment approval targets an exact version. Reporting is deterministic and does not make another model call. Workspace cookies, CSRF checks and ownership isolate guest cases; recruiter credentials access legacy/operator APIs only.

The 55 library records currently have **pending human review** status. Default planning excludes them. Explicit `PLANNING_ALLOW_PENDING_REVIEW=true` permits provisional questions/feedback, visibly labelled, with all numerical scores withheld. A teammate must actually review criteria before changing their metadata to approved. Do not label this release's library human-approved.

ElevenLabs browser integration exists but live voice is disabled until the account setup, prompt, webhook, supervision and minute allowance pass checks. No telephone calls are placed. Gemini/Ollama and hosted Langfuse remain explicit unavailable integrations.

## Fresh checkout on Windows

```powershell
uv python install 3.11
uv sync --locked
Copy-Item .env.example .env
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe scripts/download_embeddings.py
$env:PYTHONPATH = 'backend'
$env:EMBEDDING_MODEL = '.cache/models/all-MiniLM-L6-v2'
.\.venv\Scripts\python.exe -m app.agents.planning.index --rebuild
```

Configure local `.env`: `GROQ_API_KEY`, `GROQ_MODEL` (an available JSON-mode model), `EMBEDDING_MODEL=.cache/models/all-MiniLM-L6-v2`, `RECRUITER_API_TOKEN`, and an explicit `PROVIDER_BUDGET_LIMITS` JSON object. Empty budgets deny calls. Example local cap: `{"groq":{"requests":12,"tokens":100000}}`; this is an application cap, not a claim about your provider balance. Configure provisional planning only with the limitations described above. Never commit credentials or candidate data.

Start both services in hidden processes:

```powershell
.\scripts\start-local.ps1
```

Open http://localhost:5173/app. Health: http://127.0.0.1:8000/api/health. OpenAPI: http://127.0.0.1:8000/docs. Use the same hostname for browser sessions. The script starts one backend and frontend; don't run it twice while ports 8000/5173 are occupied. PIDs/logs are in ignored `.cache/release-*` files.

Equivalent foreground commands:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
npm.cmd --prefix frontend run dev
```

## Checks and evidence

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run test:e2e
npm.cmd --prefix frontend run build
```

See [validation](docs/validation.md) and [actual synthetic live-provider artifacts](evals/live-integration-results.json). Automated tests mock hosted providers; the separately recorded live smoke exercised real Groq and persistent local retrieval. These are not human-reviewed benchmark results. Never present fixture screenshots as live results.

## Team handoff

Read [contracts](docs/contracts.md), [ownership](docs/ownership.md), [release status](docs/PROJECT_STATUS.md), and [Jayanth's integration handoff](docs/jayanth-handoff.md). Module notes: [Priya](docs/priya-handoff.md), [Gana](docs/gana-handoff.md), [Drashti](docs/drashti-handoff.md).

No automatic email, submission, telephone interview, paid overage, or silent provider fallback is implemented. Failed billable stages require explicit retry; uncertain interrupted stages require operator reconciliation via `scripts/recover_stage.py`. Preserve the database and Chroma path across restarts.
