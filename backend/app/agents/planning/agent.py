"""Agent 1: CV review, knowledge retrieval and interview planning (owner: Priya).

Public interfaces (fixed by docs/contracts.md):
    async parse_cv(file_bytes, filename, ctx) -> str
    async build_plan(case, ctx) -> InterviewPlan

Flow of build_plan (two small LLM calls through ctx.llm.generate_structured):
1. Extract JD requirements and CV claims (CV/JD wrapped as untrusted data).
   Code keeps only catalogue skills and excerpts found verbatim in the documents,
   and adds a deterministic alias scan of the JD so required skills are not missed.
2. Rank JD skills and allocate five question slots.
3. Retrieve reviewed question records per skill from Chroma (filtered by skill,
   type and review status). Skills without records get the generic rubric, a
   missing_information entry and (optionally) unreviewed web research.
4. Ask the model only to reword the chosen questions around verified CV claims.
5. Assemble Questions in code: rubric and expected topics are copied from the
   reviewed records; evidence cites JD, CV and knowledge separately.
6. Stamp knowledge_version and a content-hash plan_version.
"""
import hashlib
import json
from ...contracts import CaseInput, EvidenceRef, InterviewPlan, Question
from ...context import AgentContext
from ...errors import AppError
from . import parser
from .config import PlanningConfig, load_config
from .evidence import document_ref, find_alias_line, knowledge_ref, suspicious_instructions
from .index import read_manifest
from .library import Library, QuestionRecord, allowed_statuses, load_library
from .prompts import EXTRACT_SYSTEM, PROMPT_VERSION, TAILOR_SYSTEM, Extraction, Tailoring, wrap
from .research import WebResearch
from .retrieval import KnowledgeRetriever

QUESTION_COUNT = 5
MAX_DOC_CHARS = 12000


async def parse_cv(file_bytes: bytes, filename: str, ctx: AgentContext) -> str:
    config = load_config(ctx.settings)
    return await parser.parse(file_bytes, filename, ctx, config.max_cv_pages, config.llamaparse_tier)


async def build_plan(case: CaseInput, ctx: AgentContext) -> InterviewPlan:
    if "integration" not in case.role.casefold():
        _ensure_not_frozen(case, ctx)
        from .role_plan import build_role_plan
        return await build_role_plan(case, ctx)
    return await plan_case(case, ctx)


def _ensure_not_frozen(case: CaseInput, ctx: AgentContext) -> None:
    repository = getattr(ctx, "repository", None)
    if repository is None:
        return
    try:
        repository.get_interview(case.case_id)
    except AppError:
        return
    raise AppError("PLAN_FROZEN", "An interview already exists for this case; its plan is frozen and cannot be regenerated.", 409)


def allocate(skills: list[str], count: int = QUESTION_COUNT) -> list[str]:
    """Give every JD skill one slot in priority order, then extra slots to the top skills."""
    slots = list(skills[:count])
    i = 0
    while skills and len(slots) < count:
        slots.append(skills[i % len(skills)])
        i += 1
    return slots


def _generic_question(name: str) -> str:
    return f"Tell me about a recent piece of work where you applied {name.lower()}. What did you personally do, and what was the outcome?"


async def plan_case(case: CaseInput, ctx: AgentContext, *, config: PlanningConfig | None = None,
                    retriever=None, research: WebResearch | None = None) -> InterviewPlan:
    config = config or load_config(ctx.settings)
    _ensure_not_frozen(case, ctx)
    library = load_library(config.knowledge_dir)
    allowed = allowed_statuses(config.allow_pending_review)
    knowledge_version = library.version(ctx.settings.embedding_model)
    warnings: list[str] = []
    missing: list[str] = []
    cv, jd = case.cv_text or "", case.job_description or ""

    if not jd.strip():
        missing.append("Job description is empty; questions follow the Integration Engineer role profile.")
    if not cv.strip():
        missing.append("CV text is empty; questions cannot be tailored to candidate claims.")
    if "integration" not in case.role.lower():
        warnings.append(f"The knowledge library covers the Integration Engineer role only; role '{case.role[:80]}' was planned with that material.")
    if config.allow_pending_review:
        warnings.append("Knowledge library records are pending teammate review (PLANNING_ALLOW_PENDING_REVIEW is on); rubrics are not yet human-approved.")
    if suspicious_instructions(cv) or suspicious_instructions(jd):
        warnings.append("Uploaded text contains phrases resembling instructions to the AI; they were treated as document content and ignored.")
    if len(cv) > MAX_DOC_CHARS or len(jd) > MAX_DOC_CHARS:
        missing.append(f"Documents were truncated to {MAX_DOC_CHARS} characters for analysis; later content was not reviewed.")

    # 1. Extraction (provider failures propagate so they are visible to the workflow).
    catalogue = [{"skill": s.skill, "name": s.name} for s in library.skills]
    extraction = await ctx.llm.generate_structured(
        "planning.extract", EXTRACT_SYSTEM,
        {"role": case.role[:200], "skill_catalogue": catalogue,
         "job_description": wrap("job_description", jd[:MAX_DOC_CHARS]), "cv": wrap("cv", cv[:MAX_DOC_CHARS])},
        Extraction,
    )
    skill_ids = set(library.skill_ids)
    importance: dict[str, int] = {}
    first_line: dict[str, int] = {}
    jd_refs: dict[str, list[EvidenceRef]] = {}
    cv_refs: dict[str, list[EvidenceRef]] = {}
    unknown = unverified = 0
    for item in extraction.jd_requirements:
        if item.skill not in skill_ids:
            unknown += 1
            continue
        ref = document_ref(case.case_id, "job_description", jd, item.excerpt)
        if ref is None:
            unverified += 1
            continue
        importance[item.skill] = max(importance.get(item.skill, 0), item.importance)
        first_line.setdefault(item.skill, int(ref.locator.split()[-1]))
        jd_refs.setdefault(item.skill, []).append(ref)
    for skill in library.skills:  # deterministic safety net for required skills
        if skill.skill in jd_refs:
            continue
        hit = find_alias_line(jd, skill.aliases)
        if hit:
            ref = document_ref(case.case_id, "job_description", jd, hit[1])
            if ref:
                importance[skill.skill] = max(importance.get(skill.skill, 0), 3)
                first_line.setdefault(skill.skill, int(ref.locator.split()[-1]))
                jd_refs[skill.skill] = [ref]
    for item in extraction.cv_claims:
        if item.skill not in skill_ids:
            unknown += 1
            continue
        ref = document_ref(case.case_id, "cv", cv, item.excerpt)
        if ref is None:
            unverified += 1
            continue
        cv_refs.setdefault(item.skill, []).append(ref)
    if unknown:
        warnings.append(f"Ignored {unknown} extracted item(s) outside the Integration Engineer skill catalogue.")
    if unverified:
        missing.append(f"{unverified} extracted excerpt(s) could not be found verbatim in the documents and were discarded.")
    missing.extend(f"Extraction uncertainty: {note.strip()[:200]}" for note in extraction.uncertainties if note.strip())

    # 2. Prioritise JD skills.
    jd_skills = sorted(importance, key=lambda s: (-importance[s], first_line.get(s, 10**6)))
    if not jd_skills:
        jd_skills = list(library.skill_ids)
        missing.append("No catalogue skills were identified in the job description; using the Integration Engineer role profile.")
    for skill in jd_skills:
        if skill in importance and skill not in cv_refs:
            missing.append(f"CV does not state experience with {library.skill(skill).name}; required by the job description and to be explored in the interview.")
    slots = allocate(jd_skills)

    # 3. Retrieve reviewed question records.
    manifest = read_manifest(ctx.settings)
    if manifest is None:
        warnings.append("Knowledge index manifest not found; run: python -m app.agents.planning.index --rebuild")
    elif manifest.get("knowledge_version") != knowledge_version:
        warnings.append("Knowledge index is stale relative to the library files; run: python -m app.agents.planning.index --rebuild")
    retriever = retriever or KnowledgeRetriever(ctx.settings, library, allowed, config.retrieval_top_k, config.max_context_chars)
    research = research or WebResearch(ctx, config.unreviewed_dir, [s.name for s in library.skills],
                                       config.enable_tavily_fallback, config.max_searches)
    used: set[str] = set()
    retrieval_failed = False
    chosen: list[tuple[str, QuestionRecord | None]] = []
    for skill in slots:
        query = " ".join(r.excerpt for r in jd_refs.get(skill, []) + cv_refs.get(skill, [])) or library.skill(skill).name
        candidates: list[str] = []
        if not retrieval_failed:
            try:
                candidates = [h.chunk_id for h in retriever.retrieve(query, skill, "question")]
            except AppError as exc:
                retrieval_failed = True
                warnings.append(f"Vector retrieval unavailable ({exc.code}: {exc.message}); questions selected from the library in file order.")
        if retrieval_failed:
            candidates = sorted(q.question_id for q in library.questions.values() if q.skill == skill and q.review_status in allowed)
        record = next((library.questions[c] for c in candidates if c not in used), None)
        if record is None and not retrieval_failed:  # top-k exhausted: fall back to remaining reviewed records
            record = next((q for q in sorted(library.questions.values(), key=lambda q: q.question_id)
                           if q.skill == skill and q.review_status in allowed and q.question_id not in used), None)
        if record:
            used.add(record.question_id)
        chosen.append((skill, record))

    for skill in dict.fromkeys(s for s, r in chosen if r is None):
        name = library.skill(skill).name
        missing.append(f"No reviewed question record for {name}; generic rubric used and the gap needs a teammate-reviewed question.")
        outcome = await research.research(skill, name)
        if outcome.stored_as:
            missing.append(f"Unreviewed web research for {name} saved to knowledge/unreviewed/{outcome.stored_as} for review; it is not used for scoring.")
        if outcome.warning:
            warnings.append(outcome.warning)

    # 4. Tailor wording around verified CV claims only.
    items = []
    for n, (skill, record) in enumerate(chosen, 1):
        qid = record.question_id if record else f"generic-{skill}-{n}"
        base = record.question if record else _generic_question(library.skill(skill).name)
        items.append({"question_id": qid, "skill": library.skill(skill).name, "approved_question": base,
                      "verified_cv_claims": [r.excerpt for r in cv_refs.get(skill, [])[:1]]})
    tailored: dict[str, str] = {}
    # Only questions with a verified CV claim are sent, keeping the response small enough
    # for the shared adapter's 1024-token completion cap (reasoning models included).
    to_tailor = [item for item in items if item["verified_cv_claims"]]
    if to_tailor:
        try:
            result = await ctx.llm.generate_structured("planning.tailor", TAILOR_SYSTEM, {"items": to_tailor}, Tailoring)
            valid_ids = {item["question_id"] for item in to_tailor}
            for q in result.questions:
                text = q.question.strip()
                if q.question_id in valid_ids and 15 <= len(text) <= 450 and not suspicious_instructions(text):
                    tailored[q.question_id] = text
        except AppError as exc:
            warnings.append(f"Question tailoring unavailable ({exc.code}); approved questions used unchanged.")

    # 5. Assemble questions in code.
    questions = []
    for item, (skill, record) in zip(items, chosen):
        evidence = jd_refs.get(skill, [])[:1] + cv_refs.get(skill, [])[:1]
        if record:
            refs = [library.references[c] for c in record.reference_chunk_ids if library.references[c].review_status in allowed]
            evidence += [knowledge_ref(c) for c in refs[:2]]
        if not evidence:
            missing.append(f"Question {item['question_id']} has no supporting JD, CV or reviewed knowledge evidence.")
        questions.append(Question(
            question_id=item["question_id"],
            skill=library.skill(skill).name,
            question=tailored.get(item["question_id"], item["approved_question"]),
            expected_topics=list(record.expected_topics) if record else ["specific example", "personal contribution", "outcome", "trade-offs"],
            rubric=dict(record.rubric) if record else dict(library.generic.rubric),
            evidence=evidence,
        ))

    # 6. Freeze versions.
    body = json.dumps({"case_id": case.case_id, "knowledge_version": knowledge_version, "prompt_version": PROMPT_VERSION,
                       "questions": [q.model_dump() for q in questions]}, sort_keys=True)
    plan_version = "plan-" + hashlib.sha256(body.encode()).hexdigest()[:12]
    return InterviewPlan(case_id=case.case_id, plan_version=plan_version, knowledge_version=knowledge_version,
                         questions=questions, missing_information=list(dict.fromkeys(missing)), warnings=list(dict.fromkeys(warnings)))
