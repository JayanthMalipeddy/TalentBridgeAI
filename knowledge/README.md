# Knowledge workspace

Owned by Priya. It covers the Integration Engineer role. See `docs/priya-handoff.md` for the review checklist.

| Path | Contents | Used for scoring? |
| --- | --- | --- |
| `skills.json` | Skill catalogue (ids, names, aliases for JD scanning) | No |
| `references/` | Curated reference chunks with verbatim excerpts and source URLs | Only after a teammate approves them |
| `questions/` | Question and rubric records (0–3), plus the generic fallback rubric | Only after a teammate approves them |
| `unreviewed/` | Cached web research (Keenable/Tavily), written at runtime | Never. It is not indexed or loaded |

Every chunk carries `document_id, chunk_id, title, source_url, skill, version, review_status, retrieved_at`.
`review_status` is `pending_review` until a teammate reviews the record. Then set it to `approved` or `rejected` and rebuild:

    $env:PYTHONPATH = "backend"; .\.venv\Scripts\python.exe -m app.agents.planning.index --rebuild

No candidate CVs are stored here or in the index.
