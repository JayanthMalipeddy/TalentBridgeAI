from unittest.mock import AsyncMock
import pytest
from app.agents.assessment.agent import Findings
from app.agents.interview.service import create_session, stop
from app.errors import AppError
from app.workflow import create_workflow, process_completion_events


async def seeded(client, contracts):
    ctx = client.app.state.ctx
    ctx.repository.save_case(contracts['case'])
    ctx.repository.save_plan(contracts['plan'])
    session = await create_session(contracts['case'],contracts['plan'],'text',ctx)
    result = contracts['interview'].model_copy(update={'session_id':session['session_id']})
    ctx.repository.mutate_session(session['session_id'],lambda s:s.update(
        result=result.model_dump(), state='completed',consent_confirmed=True,
        turns=[t.model_dump() for t in result.turns]))
    ctx.llm.generate_structured = AsyncMock(return_value=Findings(skills=[contracts['skill']]))
    return ctx, session


async def test_idempotent_assessment_and_restart(client, contracts):
    ctx, session = await seeded(client,contracts)
    workflow = create_workflow(ctx)
    state = {'case_id':'test-case','stage':'assess','result':{}}
    a = await workflow.ainvoke(state)
    b = await create_workflow(ctx).ainvoke(state)
    assert a['result'] == b['result']
    ctx.llm.generate_structured.assert_awaited_once()
    assert ctx.repository.get('stage_run','test-case:assess')['status'] == 'succeeded'
    assert ctx.repository.get_assessment('test-case').plan_version == 'p1'


async def test_worker_completes_reporting_without_rebilling(client, contracts):
    ctx, session = await seeded(client,contracts)
    workflow = create_workflow(ctx)
    await process_completion_events(ctx,workflow)
    assert ctx.repository.get('workflow_event',session['session_id'])['status'] == 'completed'
    await process_completion_events(ctx,create_workflow(ctx))
    ctx.llm.generate_structured.assert_awaited_once()


async def test_failed_provider_requires_explicit_retry(client, contracts):
    ctx, _ = await seeded(client,contracts)
    ctx.llm.generate_structured.side_effect = AppError('PROVIDER_ERROR','Unavailable',502)
    state = {'case_id':'test-case','stage':'assess','result':{}}
    workflow = create_workflow(ctx)
    with pytest.raises(AppError): await workflow.ainvoke(state)
    with pytest.raises(AppError) as exc: await workflow.ainvoke(state)
    assert exc.value.code == 'STAGE_RETRY_REQUIRED'
    ctx.llm.generate_structured.assert_awaited_once()
    ctx.llm.generate_structured.side_effect = None
    assert (await workflow.ainvoke(state | {'retry':True}))['result']['coverage'] == 1


async def test_uncertain_running_stage_does_not_rebill(client, contracts):
    ctx, _ = await seeded(client,contracts)
    ctx.repository.put('stage_run','test-case:assess',{'status':'running','fingerprint':'unknown'})
    with pytest.raises(AppError) as exc:
        await create_workflow(ctx).ainvoke({'case_id':'test-case','stage':'assess','retry':True})
    assert exc.value.code == 'STAGE_BUSY'
    ctx.llm.generate_structured.assert_not_awaited()


async def test_withdrawal_removes_assessment_and_cached_results(client, contracts):
    ctx, session = await seeded(client,contracts)
    workflow = create_workflow(ctx)
    state = {'case_id':'test-case','stage':'assess','result':{}}
    await workflow.ainvoke(state)
    ctx.repository.save_report(contracts['report'])
    stop(session['session_id'],True,ctx)
    for kind in ['assessment','report','report_version']:
        assert ctx.repository.all_records(kind) == []
    with pytest.raises(AppError): await workflow.ainvoke(state)
    ctx.llm.generate_structured.assert_awaited_once()


async def test_withdrawal_during_llm_rejects_output(client, contracts):
    ctx, session = await seeded(client,contracts)
    async def withdraw(*args,**kwargs):
        stop(session['session_id'],True,ctx)
        return Findings(skills=[contracts['skill']])
    ctx.llm.generate_structured.side_effect = withdraw
    with pytest.raises(AppError) as exc:
        await create_workflow(ctx).ainvoke({'case_id':'test-case','stage':'assess','result':{}})
    assert exc.value.code == 'INPUT_CHANGED'
    assert ctx.repository.all_records('assessment') == []


async def test_active_session_not_assessed(client, contracts):
    ctx, session = await seeded(client,contracts)
    ctx.repository.mutate_session(session['session_id'],lambda s:s.update(state='active'))
    with pytest.raises(AppError) as exc:
        await create_workflow(ctx).ainvoke({'case_id':'test-case','stage':'assess'})
    assert exc.value.code == 'INTERVIEW_NOT_FINAL'
    ctx.llm.generate_structured.assert_not_awaited()


def test_manual_recovery_preserves_budget_and_requires_running(client, contracts):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('recover_stage', Path(__file__).parents[2] / 'scripts' / 'recover_stage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = client.app.state.ctx.repository
    case = contracts['case']
    repo.save_case(case)
    key = case.case_id + ':assess'
    repo.put('stage_run', key, {'status':'running','fingerprint':'unchanged','stage':'assess'})
    before = repo.usage_records()
    module.recover(repo, case.case_id, 'assess')
    assert repo.get('stage_run', key)['status'] == 'failed'
    assert repo.get('stage_run', key)['fingerprint'] == 'unchanged'
    assert repo.usage_records() == before
    with pytest.raises(AppError, match='Only running'):
        module.recover(repo, case.case_id, 'assess')
