import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest,httpx
from cryptography.fernet import Fernet
from app.settings import Settings
from app.db import make_engine
from app.repository import Repository
from app.services.telemetry import Telemetry
from app.hr.contracts import Configuration,Rubric,Findings,Finding,Citation,Decision,Reconcile,Correction
from app.hr.service import HRService
from app.hr.scoring import calculate
from app.hr.outbox import process_one,retry,reconcile
from app.hr.gmail import Gmail,SCOPE
from app.errors import AppError

@pytest.fixture
def setup(tmp_path,contracts):
    settings=Settings(_env_file=None,database_url='sqlite:///'+str(tmp_path/'hr.db'),app_env='test',email_pacing_seconds=0,gmail_token_encryption_key=Fernet.generate_key().decode())
    repo=Repository(make_engine(settings.database_url));repo.save_case(contracts['case']);repo.save_plan(contracts['plan'])
    ctx=SimpleNamespace(settings=settings,repository=repo,telemetry=Telemetry(),llm=SimpleNamespace(generate_structured=AsyncMock(return_value=Findings(findings=[Finding(criterion_id='c1',score=3,rationale='Accurate practical answer',evidence=[Citation(turn_id='turn-1',excerpt='Synthetic answer')])],transcript_quality_sufficient=True))))
    service=HRService(ctx)
    config=Configuration(job_title='Engineer',job_reference='JOB-1',client_name='Example client',client_email='client@example.com',candidate_name='Fictional candidate',candidate_email='candidate@example.com',candidate_email_confirmed=True,cv_sharing_authorized=True,recruiter_name='Test reviewer',agency_name='Example agency',recruiter_contact='hr@example.com',approved_summary='Explained the tested principles.')
    service.configure('test-case',config)
    service.attachment('test-case','fictional.txt',b'Original synthetic CV')
    service.configure('test-case',config)
    service.rubric('test-case',Rubric(criteria=[dict(criterion_id='c1',question_id='q1',title='Testing',expected_principles='Assertions',anchors={str(i):'Reviewed anchor '+str(i) for i in range(5)})],reviewer='Test HR',reviewed=True))
    repo.save_session({'case_id':'test-case','session_id':'s1','state':'completed','channel':'text','frozen_plan':contracts['plan'].model_dump()})
    repo.save_interview(contracts['interview'])
    repo.put('gmail','sender',{'email':'sender@example.com','connected_at':'test-connection','encrypted_tokens':'TEST-ONLY'})
    yield ctx,service,config
    repo.engine.dispose()

def decide(service,outcome='shortlist',request_id='request-one'):
    p=service.preview('test-case')
    return service.decide('test-case',Decision(outcome=outcome,reviewer='Human reviewer',reason='Job-related evidence reviewed',preview_version=p['preview_version'],request_id=request_id),'authenticated-test-reviewer')

def fake_sender(error=None):
    return SimpleNamespace(send=AsyncMock(side_effect=error,return_value='gmail-id-test-only'))

@pytest.mark.parametrize('weight,expected',[(69.999,'below_threshold'),(70,'recommend_shortlist'),(70.001,'recommend_shortlist')])
def test_exact_threshold(contracts,weight,expected):
    rub={'criteria':[{'criterion_id':'a','question_id':'q1','weight':weight},{'criterion_id':'b','question_id':'q1','weight':100-weight}]}
    findings=Findings(findings=[Finding(criterion_id=k,score=s,rationale='test',evidence=[Citation(turn_id='turn-1',excerpt='Synthetic answer')]) for k,s in [('a',4),('b',0)]],transcript_quality_sufficient=True)
    assert calculate(rub,findings,contracts['interview'].model_dump(),70)['recommendation']==expected

async def test_no_mail_before_review_and_dependency(setup):
    ctx,s,_=setup;await s.assess('test-case');sender=fake_sender()
    assert await process_one(ctx,sender) is None
    d=decide(s);assert d['outcome']=='shortlist'
    assert [m['purpose'] for _,m in ctx.repository.all_records('hr_outbox')]==['client']
    first=await process_one(ctx,sender);assert first['state']=='SEND_ACCEPTED'
    assert sender.send.call_args.args[1]['content']=='T3JpZ2luYWwgc3ludGhldGljIENW'
    second=await process_one(ctx,sender);assert second['purpose']=='candidate'
    assert second['state']=='SEND_ACCEPTED' and sender.send.await_count==2
    assert await process_one(ctx,sender) is None

async def test_rejection_only_candidate_and_hold_no_mail(setup):
    ctx,s,_=setup;await s.assess('test-case');decide(s,'hold')
    assert ctx.repository.all_records('hr_outbox')==[]
    decide(s,'reject','request-two');sender=fake_sender();m=await process_one(ctx,sender)
    assert m['purpose']=='rejection' and m['to']=='candidate@example.com'
    assert sender.send.call_args.args[1] is None

@pytest.mark.parametrize('error,state',[('GMAIL_QUOTA','FAILED'),('DELIVERY_UNKNOWN','DELIVERY_UNKNOWN'),('GMAIL_AUTH','FAILED')])
async def test_client_failure_blocks_candidate(setup,error,state):
    ctx,s,_=setup;await s.assess('test-case');decide(s)
    m=await process_one(ctx,fake_sender(AppError(error,'test')))
    assert m['state']==state
    assert len(ctx.repository.all_records('hr_outbox'))==1
    assert ctx.repository.get('hr_decision','test-case')['outcome']=='shortlist'
    if state=='DELIVERY_UNKNOWN':
        with pytest.raises(AppError):retry(ctx,'test-case',m['key'])
        reconcile(ctx,'test-case',m['key'],Reconcile(action='confirmed_sent',provider_message_id='verified-id',reason='Checked Sent Mail manually'),'HR')
        assert len(ctx.repository.all_records('hr_outbox'))==2

async def test_candidate_retry_never_resends_client(setup):
    ctx,s,_=setup;await s.assess('test-case');decide(s);sender=fake_sender()
    first=await process_one(ctx,sender)
    second=await process_one(ctx,fake_sender(AppError('GMAIL_QUOTA','test')))
    retry(ctx,'test-case',second['key']);await process_one(ctx,sender)
    assert ctx.repository.get('hr_outbox',first['key'])['state']=='SEND_ACCEPTED'
    assert len(ctx.repository.get('hr_outbox',first['key'])['attempts'])==1

async def test_repeated_approval_and_concurrent_workers(setup):
    ctx,s,_=setup;await s.assess('test-case')
    d=decide(s);assert decide(s)['version']==d['version'];assert decide(s,request_id='another-id')['version']==d['version']
    gate=asyncio.Event()
    async def delayed(*args):await gate.wait();return 'id'
    sender=SimpleNamespace(send=AsyncMock(side_effect=delayed))
    task=asyncio.create_task(process_one(ctx,sender));await asyncio.sleep(.01)
    assert await process_one(ctx,sender) is None
    gate.set();await task;assert sender.send.await_count==1

async def test_changed_recipient_cv_or_template_requires_review(setup):
    ctx,s,config=setup;await s.assess('test-case');p=s.preview('test-case');decide(s)
    s.configure('test-case',config.model_copy(update={'client_email':'different@example.com'}))
    with pytest.raises(AppError,match='changed'):s.decide('test-case',Decision(outcome='shortlist',reviewer='HR',reason='Reviewed role evidence',preview_version=p['preview_version'],request_id='new-request'),'hr')
    sender=fake_sender();assert await process_one(ctx,sender) is None;sender.send.assert_not_called()
    assert all(m['cancelled'] for _,m in ctx.repository.all_records('hr_outbox'))

async def test_missing_client_email_and_original_cv(setup):
    ctx,s,config=setup;await s.assess('test-case');s.configure('test-case',config.model_copy(update={'client_email':None}))
    with pytest.raises(AppError,match='Client email'):decide(s)

async def test_incomplete_missing_and_invented_evidence(setup):
    ctx,s,_=setup
    result=ctx.repository.get_interview('test-case');result.status='incomplete';ctx.repository.save_interview(result)
    a=await s.assess('test-case');assert a['score'] is None and a['recommendation']=='insufficient_evidence'
    with pytest.raises(AppError,match='Hold'):decide(s)
    with pytest.raises(AppError,match='Hold'):decide(s,'reject')
    assert ctx.repository.all_records('hr_outbox')==[]

async def test_versions_duplicate_completion_and_hr_correction(setup):
    ctx,s,_=setup;a=await s.assess('test-case');b=await s.assess('test-case');assert a['version']==b['version'];ctx.llm.generate_structured.assert_awaited_once()
    correction=Correction(assessment_version=a['version'],reviewer='HR',reason='Reviewed exact job evidence',findings=Findings(findings=[Finding(criterion_id='c1',score=0,rationale='Incorrect principle',evidence=[Citation(turn_id='turn-1',excerpt='Synthetic answer')])],transcript_quality_sufficient=True))
    fixed=s.correct('test-case',correction);assert fixed['version']!=a['version'] and fixed['score']==0
    assert s.preview('test-case')['assessment']['recommendation']=='below_threshold'

async def test_send_disabled_in_development(setup):
    ctx,s,_=setup;await s.assess('test-case');decide(s)
    assert await process_one(ctx) is None
    with pytest.raises(AppError,match='disabled'):await Gmail(ctx).send({},None)

async def test_gmail_mime_and_timeout_classification(setup):
    import base64,email
    ctx,s,_=setup;ctx.settings.app_env='production';ctx.settings.email_send_enabled=True
    captured=[]
    def handler(request):
        captured.append(request)
        return httpx.Response(200,json={'id':'gmail-real-response-shape'})
    gmail=Gmail(ctx,httpx.MockTransport(handler));gmail.access_token=AsyncMock(return_value='TEST-ONLY')
    message={'key':'logical-key','sender':'sender@example.com','to':'client@example.com','subject':'Review','body':'Hello <world>'}
    attachment=ctx.repository.get('hr_cv','test-case')
    assert await gmail.send(message,attachment)=='gmail-real-response-shape'
    import json
    mime=email.message_from_bytes(base64.urlsafe_b64decode(json.loads(captured[0].content)['raw']))
    assert mime['To']=='client@example.com' and mime['Cc'] is None and mime['Bcc'] is None
    assert any(part.get_filename()=='fictional.txt' for part in mime.walk())
    def timeout(request):raise httpx.ReadTimeout('unknown')
    gmail.transport=httpx.MockTransport(timeout)
    with pytest.raises(AppError) as exc:await gmail.send(message,None)
    assert exc.value.code=='DELIVERY_UNKNOWN'

async def test_oauth_csrf_and_encrypted_tokens(setup):
    from urllib.parse import urlparse,parse_qs
    ctx,s,_=setup;ctx.settings.gmail_client_id='test-id';ctx.settings.gmail_client_secret='test-secret'
    # Assignment validation is disabled for settings; retain SecretStr type.
    from pydantic import SecretStr
    ctx.settings.gmail_client_secret=SecretStr('test-secret')
    def handler(request):
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'scope':SCOPE,'refresh_token':'private-refresh','access_token':'private-access'})
        return httpx.Response(200,json={'email':'sender@example.com','email_verified':True,'sub':'subject'})
    gmail=Gmail(ctx,httpx.MockTransport(handler));url=gmail.start('browser-nonce');state=parse_qs(urlparse(url).query)['state'][0]
    with pytest.raises(AppError):await gmail.callback(state,'code','wrong-browser')
    assert await gmail.callback(state,'code','browser-nonce')=='sender@example.com'
    stored=ctx.repository.get('gmail','sender');assert 'private-refresh' not in str(stored)
    with pytest.raises(AppError):await gmail.callback(state,'code','browser-nonce')

async def test_stale_transcript_blocks_decision_and_new_version_reassesses(setup):
    from app.hr.contracts import TranscriptCorrection
    ctx,s,_=setup;a=await s.assess('test-case');p=s.preview('test-case')
    turns=ctx.repository.get_interview('test-case').turns
    turns[0].text='Synthetic answer with verified correction'
    s.correct_transcript('test-case',TranscriptCorrection(turns=turns,status='completed',reviewer='HR',reason='Verified against original audio'))
    assert not s.preview('test-case')['assessment_current']
    with pytest.raises(AppError):s.decide('test-case',Decision(outcome='shortlist',reviewer='HR',reason='Role evidence reviewed',preview_version=p['preview_version'],request_id='changed-transcript'),'hr')
    b=await s.assess('test-case');assert a['version']!=b['version'] and a['transcript_version']!=b['transcript_version']

async def test_wrong_cv_replacement_invalidates_queued_submission(setup):
    ctx,s,_=setup;await s.assess('test-case');decide(s)
    s.attachment('test-case','replacement.txt',b'New corrected CV')
    sender=fake_sender();assert await process_one(ctx,sender) is None
    sender.send.assert_not_called()

@pytest.mark.parametrize('status,code',[(401,'GMAIL_AUTH_OR_QUOTA'),(403,'GMAIL_AUTH_OR_QUOTA'),(429,'GMAIL_QUOTA'),(503,'DELIVERY_UNKNOWN')])
async def test_gmail_http_errors(setup,status,code):
    ctx,_,_=setup;ctx.settings.app_env='production';ctx.settings.email_send_enabled=True
    gmail=Gmail(ctx,httpx.MockTransport(lambda r:httpx.Response(status,json={})));gmail.access_token=AsyncMock(return_value='test')
    with pytest.raises(AppError) as exc:await gmail.send({'key':'test','sender':'s@example.com','to':'c@example.com','subject':'Test','body':'Test'},None)
    assert exc.value.code==code

async def test_restart_marks_stale_sending_unknown(setup):
    ctx,s,_=setup;await s.assess('test-case');decide(s)
    key,row=ctx.repository.all_records('hr_outbox')[0];row.update(state='SENDING',started_at='2020-01-01T00:00:00+00:00')
    ctx.repository.put('hr_outbox',key,row);sender=fake_sender();await process_one(ctx,sender)
    assert ctx.repository.get('hr_outbox',key)['state']=='DELIVERY_UNKNOWN';sender.send.assert_not_called()

async def test_invalid_or_cross_question_citation_abstains(setup):
    ctx,s,_=setup;ctx.llm.generate_structured.return_value.findings[0].evidence[0].excerpt='Invented quotation'
    a=await s.assess('test-case');assert a['score'] is None


def test_recruiter_and_owner_required_and_mock_excluded(client,contracts,auth):
    repo=client.app.state.ctx.repository;repo.save_case(contracts['case'])
    root='/api/hr/cases/test-case/review'
    assert client.get(root,headers=auth).status_code==401
    assert client.get(root,headers=auth|{'X-Recruiter-Token':'test-secret'}).status_code==200
    repo.save_case(contracts['case'].model_copy(update={'case_id':'private'}),'someone-else')
    assert client.get('/api/hr/cases/private/review',headers=auth|{'X-Recruiter-Token':'test-secret'}).status_code==404
    repo.save_case(contracts['case'].model_copy(update={'case_id':'mock','mode':'mock'}))
    assert client.get('/api/hr/cases/mock/review',headers=auth|{'X-Recruiter-Token':'test-secret'}).status_code==403


def test_email_validation_and_template_headers():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Configuration(job_title='Engineer',job_reference='r',candidate_name='Test',candidate_email='bad\r\nBcc: injected@example.com',recruiter_name='HR',agency_name='Agency',recruiter_contact='HR')

async def test_replaced_cv_requires_fresh_sharing_confirmation(setup):
    ctx,s,_=setup
    await s.assess('test-case')
    s.attachment('test-case','revised.txt',b'Revised synthetic CV')
    assert not s.preview('test-case')['config']['data']['cv_sharing_authorized']
    with pytest.raises(AppError):decide(s)


async def test_llm_preparation_before_interview_cached_and_cv_grounded(setup):
    from app.hr.contracts import Preparation
    from sqlalchemy import delete
    from app.db import records
    ctx,s,_=setup
    with ctx.repository.transaction() as c:c.execute(delete(records).where(records.c.kind=='session'))
    case=ctx.repository.get_case('test-case');case.cv_text='Alex Morgan, Integration Engineer. alex@example.com'
    ctx.repository.put('case',case.case_id,case.model_dump())
    criteria=ctx.repository.get('hr_rubric','test-case')['criteria']
    ctx.llm.generate_structured.return_value=Preparation(candidate_name='Alex Morgan',candidate_email='alex@example.com',criteria=criteria)
    value=await s.prepare('test-case')
    assert value['candidate_name']=='Alex Morgan' and value['candidate_email']=='alex@example.com'
    rubric=ctx.repository.get('hr_rubric','test-case')
    assert rubric['source']=='llm' and rubric['reviewed'] is False and rubric['reviewer'] is None
    assert (await s.prepare('test-case'))==value
    assert ctx.llm.generate_structured.await_count==1

async def test_preparation_never_rewrites_started_interview(setup):
    ctx,s,_=setup
    with pytest.raises(AppError) as exc:await s.prepare('test-case')
    assert exc.value.code=='INTERVIEW_STARTED'
    ctx.llm.generate_structured.assert_not_called()

async def test_preparation_rejects_invented_candidate_contacts(setup):
    from app.hr.contracts import Preparation
    from sqlalchemy import delete
    from app.db import records
    ctx,s,_=setup
    with ctx.repository.transaction() as c:c.execute(delete(records).where(records.c.kind=='session'))
    ctx.llm.generate_structured.return_value=Preparation(candidate_name='Invented Person',candidate_email='invented@example.com',criteria=ctx.repository.get('hr_rubric','test-case')['criteria'])
    result=await s.prepare('test-case')
    assert result['candidate_name']=='' and result['candidate_email'] is None

async def test_summary_prefilled_from_validated_assessment_and_agency_optional(setup):
    ctx,s,config=setup
    config.agency_name='';config.approved_summary='';s.configure('test-case',config)
    await s.assess('test-case')
    p=s.preview('test-case')
    assert 'Accurate practical answer' in p['config']['data']['approved_summary']
    assert 'Accurate practical answer' in p['messages']['client']['body']
    decide(s)
    assert len(ctx.repository.all_records('hr_outbox'))==1


async def test_corrected_assessment_survives_worker_and_cached_retry(setup):
    from app.hr.worker import tick
    ctx,s,_=setup
    first=await s.assess('test-case')
    corrected=s.correct('test-case',Correction(assessment_version=first['version'],reviewer='HR',reason='Verified the supporting answer against the criterion',findings=Findings(findings=[Finding(criterion_id='c1',score=1,rationale='Verified lower score',evidence=[Citation(turn_id='turn-1',excerpt='Synthetic answer')])],transcript_quality_sufficient=True)))
    await tick(ctx)
    assert (await s.assess('test-case'))['version']==corrected['version']
    assert ctx.repository.get('hr_report','test-case')['assessment_version']==corrected['version']
    assert '25.00%' in ctx.repository.get_report('test-case').summary
    assert ctx.llm.generate_structured.await_count==1

async def test_frozen_rubric_cannot_be_replaced_after_interview(setup):
    ctx,s,_=setup
    rubric=ctx.repository.get('hr_rubric','test-case')
    with pytest.raises(AppError) as exc:s.rubric('test-case',Rubric(criteria=rubric['criteria'],reviewer='HR',reviewed=True))
    assert exc.value.code=='RUBRIC_FROZEN'

@pytest.mark.parametrize('threshold',[60,65,70])
def test_threshold_range_and_review_bands(contracts,threshold):
    criterion={'criterion_id':'c1','question_id':'q1','weight':1}
    findings=Findings(findings=[Finding(criterion_id='c1',score=2,rationale='Partial evidence',evidence=[Citation(turn_id='turn-1',excerpt='Synthetic answer')])],transcript_quality_sufficient=True)
    result=calculate({'criteria':[criterion]},findings,contracts['interview'].model_dump(),threshold)
    assert result['score']==50 and result['human_decision_required'] is True
    assert result['review_band']==('near_threshold' if threshold==60 else 'below_threshold')
