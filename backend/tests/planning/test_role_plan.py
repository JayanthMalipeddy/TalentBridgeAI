from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.contracts import CaseInput, EvidenceRef, Question
from app.agents.planning.agent import build_plan
from app.agents.planning.role_plan import RoleQuestions
from app.errors import AppError


def setup():
    case=CaseInput(case_id='role-test',mode='recruitment',role='Accountant',cv_text='Prepared reconciliations.',job_description='Prepare financial statements and reconcile accounts.')
    question=Question(question_id='model-id',skill='Reconciliation',question='How do you investigate a reconciliation discrepancy?',expected_topics=['Evidence','Reconciliation'],rubric={str(i):f'Anchor {i}' for i in range(4)},evidence=[EvidenceRef(source_type='job_description',source_id='untrusted-model-id',locator='untrusted-location',excerpt='reconcile accounts')])
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
    case,ctx,output=setup();output.questions[0].evidence[0].excerpt='Invented qualification'
    with pytest.raises(AppError) as error:await build_plan(case,ctx)
    assert error.value.code=='PLAN_EVIDENCE'
