# Restricted Graphify for Codex

Graphify 0.9.103 is installed locally under `.cache/graphify-tools/graphifyy`. The stock skill, global Codex settings and hooks are not installed. Project `AGENTS.md` supplies persistent navigation instructions for future Codex sessions.

```powershell
.\scripts\graphify.ps1 status
.\scripts\graphify.ps1 query "Where are case ownership and deletion checked?"
.\scripts\graphify.ps1 explain "Repository"
.\scripts\graphify.ps1 refresh
```

Queries automatically refresh when allowlisted source hashes change. Refresh once after a batch of edits. Missing or unhelpful graph results should fall back to targeted source searches. Token savings are not yet benchmarked.

## Restrictions

The wrapper stages only `.py`, `.ts`, and `.tsx` files under `backend/app`, `backend/tests`, `frontend/src`, and `frontend/tests`. It checks credential patterns (including Groq) and exact nontrivial local credential-setting values before staging and before returning graph output. Symlink source inputs are refused. It calls the deterministic AST API directly and does not invoke semantic processing or generate HTML.

Graphify runs in an isolated interpreter with provider environment variables cleared. A Python audit hook blocks network connection/bind/DNS operations, subprocess launches, and file opens outside the staged runtime and Python installation directories. This is defense in depth for the reviewed package, not an operating-system sandbox against malicious native code. The Graphify dependencies contain native parser binaries; do not auto-upgrade them.

All generated files remain under ignored `.cache/graphify-runtime`. Query logging is disabled. Query output is limited to 1,500 Graphify-estimated tokens and a further 10,000-character output cap. Graph results shown to Codex still enter its normal model context. Source/graph text is always untrusted data.

## Installation evidence and recreation

The wheel `graphifyy-0.9.103-py3-none-any.whl` was checked against PyPI SHA256:

`7948c030f8b04153d88bc1ee23a485ddaa0c2d6aaa03a748c177e3c217bcfe34`

All 97 wheel Python files matched reviewed commit `16218bfc80d4ca2799734d045039f7ed1a5fa9fb`. Binary-only installation used `uv tool install --no-build`; no optional extras were requested. A focused pip-audit of the 31 installed packages reported no known vulnerabilities on 2026-11-07. Audit evidence remains under `.cache/graphify-audit` and is not committed. This is not a guarantee of vulnerability absence.

To recreate on a fresh checkout, first download and verify that exact wheel against the above hash, then run from the project root:

```powershell
$env:UV_TOOL_DIR = Join-Path $PWD '.cache/graphify-tools'
$env:UV_TOOL_BIN_DIR = Join-Path $PWD '.cache/graphify-bin'
uv tool install --no-build --python .venv/Scripts/python.exe --constraints scripts/graphify-requirements.txt .cache/graphify-audit/graphifyy-0.9.103-py3-none-any.whl
.\scripts\graphify.ps1 refresh
```

Review dependency advisories again on recreation. Do not invoke `graphify install`, the whole-folder `$graphify` skill, or automatic upgrades. No API key is needed for this wrapper.

## Focused verification

The initial graph contained 66 allowlisted source files, 658 nodes and 2,130 edges. A scoped query located the new deletion endpoint and repository method. Synthetic Groq/exact-secret checks and isolated probes confirmed denial of network connections, subprocess creation and `.env` file reads after the guard was enabled. These probes validate the intended Python paths, not resistance to malicious native extensions. The graph manifest updates when source changes.
