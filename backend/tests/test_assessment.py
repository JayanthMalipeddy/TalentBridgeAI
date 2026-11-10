from unittest.mock import AsyncMock
import pytest
from app.agents.assessment.agent import assess_interview, Findings
from app.errors import AppError


def configure(client, contracts, skills=None):
    ctx = client.app.state.ctx
    ctx.llm.generate_structured = AsyncMock(return_value=Findings(skills=skills if skills is not None else [contracts['skill']]))
    return ctx


async def test_evidence_grounded_assessment(client, contracts):
    ctx = configure(client, contracts)
    result = await assess_interview(contracts['plan'], contracts['interview'], ctx)
    assert result.coverage == 1 and result.skills[0].score == 1
    assert result.model_id.startswith('groq:')
    assert result.skills[0].evidence[0].excerpt == 'Synthetic answer'
    assert result.recommendation == 'needs_more_evidence'
    payload = ctx.llm.generate_structured.call_args.args[2]
    assert 'candidate_answers' in payload and 'cv_text' not in payload


@pytest.mark.parametrize('patch', [
    {'excerpt':'Invented excellent project'}, {'source_id':'unknown'},
    {'source_type':'knowledge'}, {'excerpt':'  '},
])
async def test_rejects_invalid_evidence(client, contracts, patch):
    skill = contracts['skill'].model_copy(update={'evidence':[contracts['evidence'].model_copy(update=patch)]})
    result = await assess_interview(contracts['plan'], contracts['interview'], configure(client,contracts,[skill]))
    assert result.coverage == 0 and result.skills[0].score is None
    assert result.skills[0].status == 'not_assessed'


async def test_missing_answers_no_model_call(client, contracts):
    ctx = configure(client, contracts)
    interview = contracts['interview'].model_copy(update={'turns':[], 'status':'incomplete'})
    result = await assess_interview(contracts['plan'], interview, ctx)
    assert result.coverage == 0 and result.skills[0].score is None
    assert result.model_id == 'none:no-assessable-answers'
    ctx.llm.generate_structured.assert_not_awaited()


async def test_wrong_skill_or_interviewer_citation_rejected(client, contracts):
    ctx = configure(client, contracts)
    t = contracts['turn'].model_copy(update={'turn_id':'other','speaker':'candidate','question_id':'q2'})
    q = contracts['question'].model_copy(update={'question_id':'q2','skill':'SQL'})
    plan = contracts['plan'].model_copy(update={'questions':[contracts['question'],q]})
    interview = contracts['interview'].model_copy(update={'turns':[contracts['turn'],t]})
    skill = contracts['skill'].model_copy(update={'evidence':[contracts['evidence'].model_copy(update={'source_id':'other'})]})
    ctx.llm.generate_structured.return_value = Findings(skills=[skill])
    result = await assess_interview(plan, interview, ctx)
    assert result.coverage == 0
    interviewer = contracts['turn'].model_copy(update={'turn_id':'interviewer','speaker':'interviewer'})
    ctx.llm.generate_structured.return_value = Findings(skills=[contracts['skill'].model_copy(update={
        'evidence':[contracts['evidence'].model_copy(update={'source_id':'interviewer'})]})])
    result = await assess_interview(contracts['plan'], interview.model_copy(update={'turns':[contracts['turn'],interviewer]}),ctx)
    assert result.coverage == 0


async def test_duplicate_skills_and_status_normalization(client, contracts):
    ctx = configure(client,contracts,[contracts['skill'],contracts['skill']])
    assert (await assess_interview(contracts['plan'],contracts['interview'],ctx)).coverage == 0
    ctx.llm.generate_structured.return_value = Findings(skills=[contracts['skill'].model_copy(update={'score':0,'status':'demonstrated','needs_verification':False})])
    result = await assess_interview(contracts['plan'], contracts['interview'],ctx)
    assert result.skills[0].status == 'not_demonstrated'
    assert result.recommendation == 'does_not_yet_demonstrate_requirements'


async def test_consent_mismatch_and_provider_failure(client, contracts):
    ctx = configure(client,contracts)
    for patch in [{'consent_confirmed':False}, {'case_id':'wrong'}, {'turns':[contracts['turn'],contracts['turn']]}]:
        with pytest.raises(AppError):
            await assess_interview(contracts['plan'],contracts['interview'].model_copy(update=patch),ctx)
    ctx.llm.generate_structured.assert_not_awaited()
    ctx.llm.generate_structured.side_effect = AppError('BUDGET_EXCEEDED','No quota',429)
    with pytest.raises(AppError) as exc:
        await assess_interview(contracts['plan'],contracts['interview'],ctx)
    assert exc.value.code == 'BUDGET_EXCEEDED'


async def test_pending_criteria_never_receive_scores(client, contracts):
    ctx = configure(client, contracts)
    plan = contracts['plan'].model_copy(update={'warnings':['Rubrics are not yet human-approved.']})
    result = await assess_interview(plan, contracts['interview'], ctx)
    assert result.skills[0].score is None
    assert result.skills[0].status == 'not_assessed'
    assert result.skills[0].evidence
    assert result.coverage == 0
    assert result.recommendation == 'needs_more_evidence'
    assert 'rubric' not in ctx.llm.generate_structured.call_args.args[2]['rubrics'][0]


@pytest.mark.parametrize('valid', [True, False])
async def test_contextual_mapping_requires_real_adjacent_question(client, contracts, valid):
    from app.agents.assessment.agent import AnswerLink
    c = contracts
    ctx = configure(client, c)
    interviewer = c['turn'].model_copy(update={'turn_id':'ask', 'speaker':'interviewer', 'question_id':None, 'text':'How would you write a test?'})
    answer = c['turn'].model_copy(update={'question_id':None})
    interview = c['interview'].model_copy(update={'turns':[interviewer, answer], 'status':'incomplete'})
    ctx.llm.generate_structured.return_value = Findings(skills=[c['skill']], answer_links=[AnswerLink(
        turn_id=answer.turn_id, question_id='q1', interviewer_turn_id='ask',
        interviewer_excerpt=interviewer.text if valid else 'Invented question')])
    result = await assess_interview(c['plan'], interview, ctx)
    assert result.coverage == (1 if valid else 0)
    assert result.recommendation == 'needs_more_evidence'
    assert ctx.llm.generate_structured.await_count == 1
