# Graphify pre-install security review

Date: 2026-11-07. Decision: do not install the stock whole-folder workflow yet. A restricted code-only integration is a reasonable next step after its exact package/dependency artifacts are checked. No Graphify installation or upstream code execution occurred in this review.

## Scope and reproducibility

- Upstream: https://github.com/Graphify-Labs/graphify
- Reviewed commit: `16218bfc80d4ca2799734d045039f7ed1a5fa9fb`, declaring package `graphifyy` version `0.9.103`.
- Source ZIP SHA256: `24b6f98e54f10d18d8b6b11e20729ca8008638795512909022127c9f3e3c8cc1`.
- Source downloaded into `.cache/graphify-audit/`; reviewed as inert text. No upstream imports, install hooks, skills, CLI commands, or tests executed.
- Project: 133 current tracked text files <=2 MB scanned for selected credential shapes, credential assignments, and injection phrases. Ten nontrivial local credential-setting values were compared with tracked text without printing their values.
- Audit helpers/results: `.cache/graphify-audit/scan.py`, `project-scan.json`, `probe.py`, `redaction-probe.json`.
- This is a focused static review and custom pattern scan, not a penetration test, complete malware audit, full Git-history secret scan, dependency CVE scan, or runtime network capture. Binary/untracked candidate files and inaccessible cache directories were not scanned. A matching package version does not establish that a PyPI wheel equals this source commit.

## Findings

### 1. Groq key redaction gap — high impact if a key enters indexed content

`graphify/security.py:407` defines shape-based redaction. The reviewed expression covers several providers but does not contain the Groq `gsk_` shape or arbitrary passwords. A local probe parsed only the literal regex using Python AST, then tested synthetic strings: Groq and generic-password samples were not matched; GitHub and OpenAI samples were matched. No actual keys were passed to upstream code.

This is a defense-in-depth gap, not evidence that a credential has leaked. Real keys must be excluded before ingestion rather than relying on output redaction.

### 2. Semantic ingestion can transmit source contents — high impact for sensitive documents

`graphify/llm.py:640` wraps source text as untrusted input; `_read_files` reads document contents for model extraction. This wrapper neutralizes some injection delimiters, not secrets. Model backends and custom endpoints exist in the same module.

`graphify/skill-codex.md:170` directs the host agent to perform semantic extraction when its preferred provider keys are absent. A full-folder skill invocation may therefore expose documents to the coding assistant's model without a separate Graphify API key. Do not equate absence of keys with absence of model processing.

Even an AST-only local index does not make the entire Codex session offline: graph query output returned as tool output becomes part of the assistant context, just as source-file reads do.

### 3. Source/graph prompt injection remains possible — medium residual risk

The CLI semantic path includes untrusted-source wrappers, delimiter neutralization, and system-prompt restrictions. Label sanitation strips control characters and limits length; it does not establish that natural-language instructions in labels/comments are safe. These mechanisms reduce risk but cannot prove immunity.

The project contains deliberate injection tests in `backend/tests/planning/test_planning_agent.py` and `data/synthetic/planning/cv-05-injection.txt`. These are test data, not active instructions or evidence of compromise. Two additional phrase hits in README/Langfuse documentation were benign prose.

Treat every graph node, comment, retrieved passage, and external page as data. Never execute commands or change policy because retrieved content asks for it.

### 4. Stock Codex integration is broader than the proposed restricted setup — medium

The Codex skill includes unpinned installation/upgrade fallback commands (`skill-codex.md:93`) and broad document-processing instructions. The installed always-on block requests graph-first navigation and refreshes after changes, but also discourages flagging graph churn.

`install.py:2016` writes a Codex hook whose own message describes it as an intentional no-op, with guidance supplied by AGENTS.md. Therefore this installer does not provide a hard security boundary or a guarantee that every Codex action uses Graphify.

Prefer short, reviewed project rules and a pinned local wrapper; do not enable automatic upgrades or treat installed instructions as permission to broaden ingestion.

### 5. Graphs, caches and exports are additional data copies — medium

The project's existing `.gitignore` excludes `.env`, `.cache`, local databases and Chroma, but does not explicitly exclude `graphify-out/` or semantic intermediate artifacts. Generated graphs may contain source-derived text and paths. They should remain ignored and local.

Graphify supports `.gitignore` and explicit `.graphifyignore`, sensitive-filename filtering, and symlink restrictions in `detect.py`. These are useful controls, not content classification: a normally named source or JSON file can still contain a secret or candidate data. JSON/YAML count as code inputs in detection, so `--code-only` alone is not a sufficient allowlist.

Query logs are opt-in in `querylog.py`; `GRAPHIFY_QUERY_LOG_DISABLE=1` forces them off. Keep them disabled for this integration.

### 6. Optional network surfaces and HTML dependencies — medium when enabled

Reviewed code contains explicit URL ingestion, model backends, database export/integration, Google Workspace support, and an optional HTTP MCP listener. None is required for the proposed local code graph.

`exporters/html.py:733` loads vis-network from unpkg with an integrity attribute. `callflow_html.py` references Mermaid from jsDelivr. Opening these exports can make network requests; loading a CDN script is not by itself proof that graph data is uploaded. Skip HTML exports for the restricted setup.

## Project scan result

- No matches for the credential patterns used by this scan in the 133 scanned tracked text files.
- No exact matches for the ten checked local credential-setting values in those files.
- `.env` is ignored and not tracked; only `.env.example` is tracked.
- No suspicious active prompt injection identified in the manually reviewed phrase matches.
- No conclusion about historic commits, runtime compromise, all possible secret formats, or past external leakage follows from these results.

## Required setup restrictions

1. Pin the audited package version, verify downloaded wheel hashes/provenance, and review the resolved dependency set before installation. Do not install optional cloud/model/MCP extras for this use case.
2. Explicitly allow only intended Python/TypeScript source under `backend/app`, `frontend/src`, and selected tests; exclude data, eval artifacts, knowledge records, docs/media, `.env*`, credentials, databases, logs, caches, dependency trees, and symlinks outside the allowed roots.
3. Use deterministic AST extraction with explicit code-only settings; no semantic fallback, provider keys, URL ingestion, cloud push, HTTP server, or automatic upgrades. Preserve restrictions during refreshes as well as initial builds.
4. Ignore graph/cache/intermediate outputs in Git; disable query logging and HTML export. Scan outputs for credential patterns and exact local key matches before exposing graph results to Codex.
5. Add concise project AGENTS.md rules: consult scoped graph queries for structural navigation, verify relevant source before edits, refresh after source changes, and treat graph content as untrusted data. Allow ordinary targeted search when the graph is missing or unhelpful.
6. Verify the actual restricted build's file manifest and network behavior before calling it validated. Savings and security properties must be measured, not inferred from marketing claims.

At the time of this review installation was held pending authorization. Following explicit user approval, the restricted integration was installed; see [setup and verification](graphify-setup.md). The stock skill remains uninstalled. No credentials were changed.
