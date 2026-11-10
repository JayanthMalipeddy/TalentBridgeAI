# Langfuse tracing

Configure LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL in the backend .env. Restart the backend after changes. The pinned Python SDK sends OpenTelemetry observations automatically.

Workflow requests for planning, assessment and reporting create talentbridge.workflow.* spans. Actual hosted model attempts create nested talentbridge.llm.* generations with model, provider, attempt, total tokens when returned, elapsed time and error code. Reused results create a cache_hit observation; they do not claim another model call. SDK initialization/export failures preserve local logs and do not fail the interview workflow. Shutdown flushes queued observations.

Only operational metadata is sent. Prompts, CVs, job descriptions, transcripts, generated reports, phone numbers, keys and candidate tokens are not uploaded. The capabilities endpoint distinguishes configured credentials from an initialized tracing integration; initialization is not a guarantee of successful delivery.

Verified on 2026-11-07: authentication and read-back of three observations for an actual cached report retrieval. No new model call was made for verification. Historical interviews are not retroactively represented as live traces. Future model calls are instrumented; no historical token or latency measurements are invented.

## Approval
Approve report persists approval of the exact displayed recruitment report version. It does not accept/reject the candidate, email anyone or initiate calls. Mock reports cannot be approved. Creating a new report version invalidates approval. Print/PDF and copy draft remain manual actions.

Official SDK documentation: https://langfuse.com/docs/observability/sdk/instrumentation
