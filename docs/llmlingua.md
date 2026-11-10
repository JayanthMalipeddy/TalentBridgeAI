# Local prompt compression

TalentBridge integrates Microsoft's LLMLingua-2 through an optional dependency. Read the [security review](llmlingua-security-review.md) before changing the allowed model or processing paths.

## Setup

From the project root:

```powershell
uv sync --locked --extra compression
.\.venv\Scripts\python.exe scripts/prepare_llmlingua.py
```

Preparation downloads the pinned Microsoft BERT model (about 709 MB), verifies its SafeTensors checksum and prepares offline tokenizer caches. Models stay in ignored `.cache/models/llmlingua2/`; they are not committed. Runtime does not download files. An unavailable worker uses the original prompt.

Server environment settings:

```dotenv
LLMLINGUA_ENABLED=true
LLMLINGUA_RATE=0.8
LLMLINGUA_MIN_CHARS=1000
LLMLINGUA_MIN_SAVED_TOKENS=20
LLMLINGUA_TIMEOUT_SECONDS=45
```

Restart the backend after editing the environment. Defaults keep the feature disabled on fresh installations until assets are prepared. `LLMLINGUA_RATE` is a target retention rate, not a guaranteed saving; actual measurements determine whether the output is adopted. Application/provider budget limits are unchanged.

## What is compressed

Only `planning.role` CV sections used to draft questions are eligible. Existing Integration Engineer catalogue extraction, all JD requirements, original CV storage, contact sections, source IDs/locators, quoted evidence, frozen rubrics, candidate transcripts, assessments, reporting and email content/recipients stay unchanged. Negative statements are excluded from compression; numerical facts must retain all occurrences. Short prompts and concurrent/busy workers bypass compression.

The model selects section IDs from the same constrained schema. The backend still attaches original excerpts from the stored CV/JD. Drafting prompts identify abridged context, and the plan warns HR to review tailored claims. A compressed representation is not a substitute for original evidence.

## Reliability and measurements

The worker is isolated from API credentials and ordinary logs, with a bounded input, output and deadline. It uses CPU inference with two threads, local-only model loading and network connections blocked. An exception, missing/integrity-failed model, timeout, unsupported task, altered protected fact, non-extractive output or insufficient saving falls back to the original payload. Compression makes no hosted LLM request and adds no automatic provider retry.

Usage receipts and Langfuse metadata include fixed status codes, elapsed time, sections changed and payload token counts before/after compression. Counts use `o200k_harmony` for the currently supported Groq GPT-OSS family; they describe the user payload, excluding system/schema/chat framing and generated output. Groq's reported usage remains authoritative. Changing to another tokenizer family requires new measurement support before enabling compression for that provider/model.

CPU processing can add latency. A smaller input does not guarantee a faster complete request, and deletion can lose nuance. Keep HR review and test representative cases; do not claim a percentage improvement before measuring it.

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_compression.py backend/tests/test_llm.py backend/tests/planning/test_role_plan.py -q
```

The automated suite uses fixture worker output and mocked Groq responses. Separate local measurements must use the actual reviewed model and clearly labelled fictional text; no candidate data or email sending is required.


## Actual local measurements (10 November 2026)

The reviewed model ran offline on two fictional CV contexts of 4,176 and 4,144 characters. User-payload tokens changed from **839 to 728** (13.2% reduction) and **775 to 672** (13.3% reduction), with **22.468 s** and **24.188 s** wall time respectively. Source IDs and the JD section were unchanged. These payload counts exclude system/schema framing and generated output. [Raw measurements](security/llmlingua-benchmark.json).

No Groq request was made for this benchmark; downstream question/assessment quality was not measured. The added latency is significant on this CPU. Local configuration enables this drafting-only feature after measurement; fresh installations remain opt-in. The existing Groq budget and provider quotas are unchanged. Restart the VS Code backend to load the setting and integration.

Verification: the final full backend regression suite passed 185 tests with the integrity/offline-loader fixes in place. Focused compression, LLM-adapter and planning checks also passed. The actual local worker also loaded and compressed both samples without network access. The first benchmark exposed an NLTK directory initialization failure; it used the original-prompt fallback and was corrected before the reported measurements.
