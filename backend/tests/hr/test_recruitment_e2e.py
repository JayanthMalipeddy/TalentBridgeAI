"""Real HTTP/repository/orchestration flow; only external model/mail delivery is mocked."""
import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from app.agents.planning.role_plan import RoleQuestions, RoleQuestion
from app.hr.contracts import Preparation, Findings, Finding, Citation
from app.hr.worker import tick
from app.hr.outbox import process_one
from app.hr.contacts import contacts


@pytest.mark.parametrize('scores,early,outcome,band',[
    ([3]*5,False,'shortlist','meets_threshold'),
    ([3,3,3,2,2],False,'shortlist','near_threshold'),
    ([1]*5,False,'reject','below_threshold'),
    ([3]*5,True,'hold','insufficient_evidence'),
])
def test_upload_through_interview_review_and_email(client,monkeypatch,scores,early,outcome,band):
    import app.main as main
    # Drive the real worker explicitly so timing does not affect assertions.
    monkeypatch.setattr(main,'hr_tick',AsyncMock())
    ctx=client.app.state.ctx
    ctx.settings.interview_followups_enabled=False
    ctx.settings.email_pacing_seconds=0
    ctx.repository.put('gmail','sender',{'email':'sender@example.com','connected_at':'test-only','encrypted_tokens':'TEST-ONLY'})
    raw_cv=('Alex Morgan\nalex@example.com\n+1 (202) 555-0123\n'+
        'Synthetic candidate profile. Prepared financial statements, reconciled accounts and investigated discrepancies using supporting records. '*32).encode()
    jd='Prepare financial statements, reconcile accounts and investigate accounting discrepancies. '*22
    def post(path,**kwargs):
        response=client.post(path,**kwargs)
        assert response.status_code<300,response.text
        return response.json()
    guest=post('/api/guest-session',headers={'Origin':'http://localhost:5173'})
    headers={'Origin':'http://localhost:5173','X-CSRF-Token':guest['csrf_token'],'X-Recruiter-Token':'test-secret'}
    case=post('/api/cases',headers=headers,data={'mode':'recruitment','role':'Accountant','job_description':jd},files={'cv_file':('original.txt',raw_cv,'text/plain')})
    cid=case['case_id'];base=f'/api/hr/cases/{cid}'
    assert client.post(f'/api/cases/{cid}/sessions',headers=headers,json={'channel':'text'}).status_code==409
    async def model(task,system,payload,response_model,provider=None):
        if task=='planning.role':
            jd_id=next(x['source_id'] for x in payload['sections'] if x['source_type']=='job_description')
            return RoleQuestions(questions=[RoleQuestion(skill=f'Accounting {i}',question=f'How would you reconcile accounts in scenario {i}?',expected_topics=['Reconciliation','Supporting evidence'],rubric={str(n):f'Score anchor {n}' for n in range(4)},source_ids=[jd_id]) for i in range(5)])
        if task=='hr_preparation':
            return Preparation(candidate_name='Alex Morgan',candidate_email=None,criteria=[dict(criterion_id=q['question_id'],question_id=q['question_id'],title=q['skill'],weight=1,expected_principles='Reconcile entries against supporting evidence',anchors={str(n):f'Anchor {n}' for n in range(5)}) for q in payload['plan']['questions']])
        if task=='hr_assessment':
            answers=[t for t in payload['transcript'] if t['speaker']=='candidate']
            return Findings(findings=[Finding(criterion_id=c['criterion_id'],score=scores[i] if i<len(answers) else None,rationale='Evidence reviewed for this criterion.',evidence=[Citation(turn_id=answers[i]['turn_id'],excerpt=answers[i]['text'])] if i<len(answers) else []) for i,c in enumerate(payload['rubric'])],transcript_quality_sufficient=True)
        raise AssertionError('Unexpected model task: '+task)
    ctx.llm.generate_structured=AsyncMock(side_effect=model)
    post(f'/api/cases/{cid}/plan',headers=headers)
    prep=post(base+'/prepare',headers=headers)
    assert prep['candidate_name']=='Alex Morgan'
    assert prep['candidate_email']=='alex@example.com'  # Local fallback when model omits it.
    assert prep['suggested_numbers']==['+12025550123']
    config=dict(job_title='Accountant',job_reference='AUDIT-1',client_name='Fictional client',client_email='client@example.com',candidate_name=prep['candidate_name'],candidate_email=prep['candidate_email'],candidate_phone='+12025550123',candidate_email_confirmed=True,cv_sharing_authorized=True,recruiter_name='Test HR',recruiter_contact='hr@example.com',threshold=70)
    post(base+'/configuration',headers=headers,json=config)
    post(base+'/ready',headers=headers)
    link=post(f'/api/cases/{cid}/sessions',headers=headers,json={'channel':'text'})
    sid=link['session_id'];candidate={'Authorization':'Bearer '+link['candidate_url'].split('#token=')[1]}
    state=post(f'/api/interviews/{sid}/consent',headers=candidate,json={'confirmed':True})
    for i in range(2 if early else 5):
        state=post(f'/api/interviews/{sid}/text-answer',headers=candidate,json={'turn_id':state['current_turn_id'],'request_id':f'answer-{i}','text':f'Synthetic answer {i}: compare ledger entries with source documents, isolate discrepancies, correct verified entries and retain an audit trail.'})
    final=post(f'/api/interviews/{sid}/'+('stop' if early else 'complete'),headers=candidate,json={})
    # Replayed completion cannot call or assess the candidate a second time.
    assert post(f'/api/interviews/{sid}/complete',headers=candidate)==final
    transcript=client.get(f'/api/cases/{cid}/interview',headers=headers).json()
    assert len(transcript['turns'])>=4
    asyncio.run(tick(ctx));asyncio.run(tick(ctx))
    from app.workflow import process_completion_events
    asyncio.run(process_completion_events(ctx,client.app.state.workflow))
    report=client.get(f'/api/cases/{cid}/report',headers=headers).json()
    assert report['case_id']==cid and report['summary']
    review=client.get(base+'/review',headers=headers).json()
    assert review['assessment']['review_band']==band
    assert review['assessment']['human_decision_required'] is True
    assert len(ctx.repository.all_records('hr_outbox'))==0
    assert client.get(base+'/cv',headers=headers).content==raw_cv
    if early:
        bad=client.post(base+'/decision',headers=headers,json={'outcome':'reject','reviewer':'HR','reason':'Insufficient evidence reviewed','preview_version':review['preview_version'],'request_id':'incomplete-reject'})
        assert bad.status_code==409
    decision={'outcome':outcome,'reviewer':'Test HR','reason':'Reviewed job-related criterion evidence, recipients and CV.','preview_version':review['preview_version'],'request_id':'audit-decision'}
    approved=post(base+'/decision',headers=headers,json=decision)
    assert post(base+'/decision',headers=headers,json=decision)==approved
    sender=SimpleNamespace(send=AsyncMock(return_value='mock-gmail-id'))
    first=asyncio.run(process_one(ctx,sender));second=asyncio.run(process_one(ctx,sender))
    sent=[m['purpose'] for m in [first,second] if m is not None]
    rows=[r for _,r in ctx.repository.all_records('hr_outbox')]
    assert sent==({'shortlist':['client','candidate'],'reject':['rejection'],'hold':[]}[outcome])
    assert all(r['state']=='SEND_ACCEPTED' for r in rows)
    assert ctx.llm.generate_structured.await_count==3
    # No production send path was enabled by the test.
    assert not ctx.settings.email_send_enabled


def test_contact_extraction_ambiguity_and_no_guessed_country():
    found=contacts('one@example.com two@example.com one@example.com; +44 7700 900123; local 07700900123')
    assert found['suggested_emails']==['one@example.com','two@example.com']
    assert found['suggested_numbers']==['+447700900123']
