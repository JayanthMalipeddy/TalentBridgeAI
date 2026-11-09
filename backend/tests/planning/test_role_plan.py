from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.contracts import CaseInput
from app.agents.planning.agent import build_plan
from app.agents.planning.role_plan import RoleQuestions, RoleQuestion, source_sections
from app.errors import AppError


def setup():
    case=CaseInput(case_id='role-test',mode='recruitment',role='Accountant',cv_text='Prepared reconciliations.',job_description='Prepare financial statements and reconcile accounts.')
    question=RoleQuestion(skill='Reconciliation',question='How do you investigate a reconciliation discrepancy?',expected_topics=['Evidence','Reconciliation'],rubric={str(i):f'Anchor {i}' for i in range(4)},source_ids=['jd-1','cv-2'])
    output=RoleQuestions(questions=[question.model_copy(deep=True) for _ in range(5)])
    ctx=SimpleNamespace(llm=SimpleNamespace(generate_structured=AsyncMock(return_value=output)))
    return case,ctx,output


async def test_other_role_uses_actual_jd_and_validated_citations():
    case,ctx,_=setup()
    plan=await build_plan(case,ctx)
    assert ctx.llm.generate_structured.call_args.args[2]['role']=='Accountant'
    assert len({q.question_id for q in plan.questions})==5
    assert all(q.evidence[0].source_id==case.case_id for q in plan.questions)
    assert plan.knowledge_version=='jd-grounded-v1'
    assert any('not yet human-approved' in w for w in plan.warnings)


async def test_other_role_rejects_invented_evidence():
    case,ctx,output=setup();output.questions[0].source_ids=['invented-section']
    with pytest.raises(AppError) as error:await build_plan(case,ctx)
    assert error.value.code=='PLAN_EVIDENCE'


async def test_original_question_gets_source_text_without_model_copying_quotes():
    case,ctx,_=setup()
    plan=await build_plan(case,ctx)
    q=plan.questions[0]
    assert q.question not in case.job_description
    assert q.evidence[0].excerpt==case.job_description
    assert q.evidence[1].excerpt==case.cv_text
    payload=ctx.llm.generate_structured.call_args.args[2]
    assert payload['sections'][0]['source_id']=='jd-1'


async def test_cv_only_reference_cannot_replace_jd_requirement():
    case,ctx,output=setup();output.questions[0].source_ids=['cv-2']
    with pytest.raises(AppError) as error:await build_plan(case,ctx)
    assert error.value.code=='PLAN_EVIDENCE'


def test_section_offsets_preserve_unicode_whitespace_and_long_documents():
    case,_,_=setup()
    case.cv_text='  SQL\tand café experience.\r\n'+'a lengthy experience claim '*600
    sections=source_sections(case)
    for ref in sections.values():
        start,end=map(int,ref.locator.removeprefix('characters:').split('-'))
        source=case.cv_text if ref.source_type=='cv' else case.job_description
        assert source[start:end]==ref.excerpt
        assert end<=12000
        assert len(ref.excerpt)<=600
