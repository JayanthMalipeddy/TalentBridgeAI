from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from app.agents.interview import phone, voice
from app.agents.interview.elevenlabs_webhook import build_result
from app.agents.assessment.agent import Findings
from app.errors import AppError
from app.workflow import process_completion_events, create_workflow


def setup(client, contracts, monkeypatch):
    ctx=client.app.state.ctx
    ctx.repository.save_case(contracts['case']);ctx.repository.save_plan(contracts['plan'])
    ctx.settings.elevenlabs_phone_enabled=True;ctx.settings.elevenlabs_supervised=True
    ctx.settings.elevenlabs_phone_agent_id='phone-agent';ctx.settings.elevenlabs_phone_number_id='phone-number'
    from pydantic import SecretStr
    ctx.settings.elevenlabs_api_key=SecretStr('test-only')
    ctx.settings.provider_budget_limits={'elevenlabs':{'minutes':20},'twilio':{'minutes':20}}
    ctx.budget.limits=ctx.settings.provider_budget_limits
    config={'platform_settings':{'auth':{'enable_auth':True},'call_limits':{'agent_concurrency_limit':1,'bursting_enabled':False},'data_collection':{'consent_given':{},'consent_withdrawn':{}}},
            'conversation_config':{'conversation':{'max_duration_seconds':360},'agent':{'language':'en','first_message':'{{opening_message}}','prompt':{'prompt':Path(phone.__file__).with_name('phone_prompt.md').read_text()}}}}
    async def get(self,path,params=None):
        return [{'provider':'twilio','phone_number_id':'phone-number'}] if 'phone-numbers' in path else config
    monkeypatch.setattr(voice.ElevenLabsClient,'get',get)
    post=AsyncMock(return_value=httpx.Response(200,json={'success':True,'conversation_id':'conv-phone'},request=httpx.Request('POST','https://api.elevenlabs.io')))
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    return ctx,post,config


async def test_phone_dial_once_and_bound_payload(client,contracts,monkeypatch):
    ctx,post,_=setup(client,contracts,monkeypatch)
    a=await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    b=await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    assert a==b and a['state']=='connecting'
    post.assert_awaited_once()
    body=post.call_args.kwargs['json']
    assert body['agent_phone_number_id']=='phone-number'
    assert body['conversation_initiation_client_data']['dynamic_variables']['interview_questions']==contracts['question'].question
    assert 'cv_text' not in str(body)
    assert '+12025550123' not in str(a)
    s=ctx.repository.get_session(a['session_id'])
    assert s['consent_confirmed'] is False
    assert len(ctx.repository.usage_records())==2
    with pytest.raises(AppError): await phone.start_call('test-case','+12025550123',True,'request-2',ctx)
    post.assert_awaited_once()


async def test_phone_timeout_keeps_budget_and_no_redial(client,contracts,monkeypatch):
    ctx,post,_=setup(client,contracts,monkeypatch);post.side_effect=httpx.ReadTimeout('synthetic timeout')
    a=await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    assert a['state']=='dial_unknown'
    await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    post.assert_awaited_once()
    assert all(r['state']=='reserved' for r in ctx.repository.usage_records())
    with pytest.raises(AppError):ctx.repository.claim_voice_slot('other')


async def test_phone_missing_config_and_invalid_inputs(client,contracts,monkeypatch):
    ctx,post,_=setup(client,contracts,monkeypatch)
    for number,permission in [('+12025550123',False),('2025550123',True)]:
        with pytest.raises(AppError):await phone.start_call('test-case',number,permission,'request-1',ctx)
    ctx.settings.elevenlabs_phone_number_id=''
    with pytest.raises(AppError) as e:await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    assert e.value.code=='PHONE_NOT_CONFIGURED'
    assert ctx.repository.list_sessions()==[]
    post.assert_not_awaited()


async def test_phone_quota_atomic_cleanup(client,contracts,monkeypatch):
    ctx,post,_=setup(client,contracts,monkeypatch);ctx.budget.limits['twilio']['minutes']=0
    with pytest.raises(AppError) as e:await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    assert e.value.code=='BUDGET_EXCEEDED'
    assert ctx.repository.list_sessions()==[]
    assert ctx.repository.usage_records()[0]['amount']==0
    ctx.repository.claim_voice_slot('next')
    post.assert_not_awaited()


async def test_phone_final_transcript_drives_report_once(client,contracts,monkeypatch):
    ctx,post,_=setup(client,contracts,monkeypatch)
    a=await phone.start_call('test-case','+12025550123',True,'request-1',ctx)
    s=ctx.repository.get_session(a['session_id'])
    data={'agent_id':'phone-agent','conversation_id':'conv-phone','status':'done','metadata':{'call_duration_secs':40},
          'conversation_initiation_client_data':{'dynamic_variables':s['voice_variables']},
          'analysis':{'data_collection_results':{'consent_given':{'value':True},'consent_withdrawn':{'value':False}}},
          'transcript':[{'role':'agent','message':contracts['question'].question,'time_in_call_secs':3}, {'role':'user','message':'Synthetic answer','time_in_call_secs':5}]}
    assert voice.ingest_payload({'type':'post_call_transcription','data':data},ctx)['status']=='recorded'
    interview=ctx.repository.get_interview('test-case')
    assert interview.status=='completed' and interview.consent_confirmed
    evidence=contracts['evidence'].model_copy(update={'source_id':interview.turns[1].turn_id,'locator':interview.turns[1].turn_id})
    ctx.llm.generate_structured=AsyncMock(return_value=Findings(skills=[contracts['skill'].model_copy(update={'evidence':[evidence]})]))
    await process_completion_events(ctx,create_workflow(ctx),phone_only=True)
    assert ctx.repository.get_report('test-case').approval_status=='draft'
    assert voice.ingest_payload({'type':'post_call_transcription','data':data},ctx)['status']=='duplicate'
    await process_completion_events(ctx,create_workflow(ctx),phone_only=True)
    ctx.llm.generate_structured.assert_awaited_once()
    data['analysis']['data_collection_results']['consent_given']['value']=False
    declined=build_result(data,s)
    assert declined.status=='declined' and declined.turns==[]


def test_phone_route_operator_and_workspace_auth(client,contracts,monkeypatch,auth):
    setup(client,contracts,monkeypatch)
    body={'phone_number':'+12025550123','contact_permission':True,'request_id':'request-1'}
    assert client.post('/api/cases/test-case/phone-call',json=body,headers=auth).status_code==401
    assert client.post('/api/cases/test-case/phone-call',json=body,headers=auth|{'X-Recruiter-Token':'test-secret'}).status_code==200
    client.post('/api/guest-session',headers={'Origin':'http://localhost:5173'})
    assert client.get('/api/cases/test-case/phone-call').status_code==404


def test_international_phone_suggestions():
    assert phone.contact_numbers('Fictional CV, contact +1 (202) 555-0123. No country: 2025550123.')==['+12025550123']
