from datetime import datetime, timedelta, timezone
import hashlib
from app.guest import COOKIE

ORIGIN = {"Origin": "http://localhost:5173"}


def guest(client):
    response = client.post('/api/guest-session', headers=ORIGIN)
    assert response.status_code == 200, response.text
    return response.json(), ORIGIN | {'X-CSRF-Token': response.json()['csrf_token']}


def create(client, headers, mode='recruitment'):
    response = client.post('/api/cases', headers=headers, data={
        'mode': mode, 'role': 'Integration Engineer', 'cv_text': 'Fictional CV', 'job_description': 'Fictional JD'})
    assert response.status_code == 201, response.text
    return response.json()['case_id']


def test_guest_bootstrap_resume_cookie_csrf(client):
    assert client.get('/api/session').status_code == 401
    assert client.post('/api/guest-session').status_code == 403
    assert client.post('/api/guest-session', headers={'Origin':'https://evil.invalid'}).status_code == 403
    response = client.post('/api/guest-session', headers=ORIGIN)
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    metadata = response.json()
    assert set(metadata) == {'workspace_id','csrf_token','expires_at'}
    assert client.post('/api/guest-session', headers=ORIGIN).json() == metadata
    assert client.get('/api/session').headers['cache-control'] == 'no-store'
    body = {'mode':'mock','role':'Engineer','cv_text':'CV','job_description':'JD'}
    assert client.post('/api/cases', data=body, headers=ORIGIN).status_code == 403
    assert client.post('/api/cases', data=body, headers=ORIGIN | {'X-CSRF-Token':'bad'}).status_code == 403
    assert client.post('/api/cases', data=body, headers={'Origin':'https://evil.invalid','X-CSRF-Token':metadata['csrf_token']}).status_code == 403


def test_workspace_isolation_and_legacy_admin(client, auth):
    a, ah = guest(client)
    case_a = create(client, ah)
    assert len(client.get('/api/cases').json()) == 1
    client.cookies.clear()
    b, bh = guest(client)
    assert b['workspace_id'] != a['workspace_id']
    create(client, bh)
    assert len(client.get('/api/cases').json()) == 1
    for suffix in ['', '/plan', '/assessment', '/interview', '/report']:
        assert client.get(f'/api/cases/{case_a}{suffix}').status_code == 404
    for suffix, body in [('plan',{}),('sessions',{'channel':'text'}),('assess',{}),('report',{}),('approve',{'report_version':'x'})]:
        assert client.post(f'/api/cases/{case_a}/{suffix}', headers=bh, json=body).status_code == 404
    assert client.get('/api/cases', headers=auth).json() == []
    assert client.get(f'/api/cases/{case_a}', headers=auth).status_code == 404
    assert client.get('/api/usage').status_code == 401


def test_guest_expiration_and_caps(client):
    ctx = client.app.state.ctx
    ctx.settings.guest_max_workspaces = 1
    ctx.settings.guest_max_cases = 1
    _, headers = guest(client)
    create(client, headers)
    body = {'mode':'mock','role':'Engineer','cv_text':'CV','job_description':'JD'}
    assert client.post('/api/cases', data=body, headers=headers).status_code == 429
    key = hashlib.sha256(client.cookies.get(COOKIE).encode()).hexdigest()
    session = ctx.repository.get('guest', key)
    session['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    ctx.repository.put('guest', key, session)
    assert client.get('/api/session').status_code == 401
    assert client.get('/api/cases').status_code == 401
    assert client.post('/api/guest-session', headers=ORIGIN).status_code == 429


def test_guest_mock_report_and_exact_approval(client, contracts):
    _, headers = guest(client)
    case_id = create(client, headers, 'mock')
    repo = client.app.state.ctx.repository
    repo.save_report(contracts['report'].model_copy(update={'case_id':case_id,'mode':'mock'}))
    assert client.get(f'/api/cases/{case_id}/report').status_code == 200
    assert client.post(f'/api/cases/{case_id}/approve', headers=headers, json={'report_version':'r1'}).status_code == 409
    case_id = create(client, headers)
    repo.save_report(contracts['report'].model_copy(update={'case_id':case_id}))
    assert client.post(f'/api/cases/{case_id}/approve', headers=headers, json={'report_version':'r1'}).json()['approval_status'] == 'approved'
    repo.save_report(contracts['report'].model_copy(update={'case_id':case_id,'report_version':'r2'}))
    assert client.post(f'/api/cases/{case_id}/approve', headers=headers, json={'report_version':'r1'}).status_code == 409


def test_guest_operation_limit_and_credentialed_cors(client):
    _, headers = guest(client)
    case_id = create(client, headers)
    client.app.state.ctx.settings.guest_max_operations = 1
    assert client.post(f'/api/cases/{case_id}/plan', headers=headers).status_code == 503
    assert client.post(f'/api/cases/{case_id}/plan', headers=headers).status_code == 429
    response = client.options('/api/cases', headers=ORIGIN | {'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-CSRF-Token'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-credentials'] == 'true'


def test_legacy_admin_cannot_read_mock_assessment(client, auth, contracts):
    repo = client.app.state.ctx.repository
    case = contracts['case'].model_copy(update={'mode':'mock'})
    repo.save_case(case)
    response = client.get(f'/api/cases/{case.case_id}/assessment', headers=auth)
    assert response.status_code == 403


def test_twenty_cases_and_delete_frees_capacity(client):
    _, headers = guest(client)
    cases = [create(client, headers) for _ in range(20)]
    body = {'mode':'mock','role':'Engineer','cv_text':'CV','job_description':'JD'}
    assert client.post('/api/cases', headers=headers, data=body).status_code == 429
    assert client.delete(f'/api/cases/{cases[0]}', headers=headers).status_code == 204
    assert len(client.get('/api/cases').json()) == 19
    assert client.get(f'/api/cases/{cases[0]}').status_code == 404
    create(client, headers)
    assert len(client.get('/api/cases').json()) == 20


def test_delete_requires_owner_and_csrf(client, auth):
    _, headers = guest(client)
    case_id = create(client, headers)
    assert client.delete(f'/api/cases/{case_id}', headers=ORIGIN).status_code == 403
    assert client.delete(f'/api/cases/{case_id}', headers=headers | {'Origin':'https://evil.invalid'}).status_code == 403
    assert client.delete(f'/api/cases/{case_id}', headers=auth).status_code == 404
    client.cookies.clear()
    _, other_headers = guest(client)
    assert client.delete(f'/api/cases/{case_id}', headers=other_headers).status_code == 404
    response = client.options('/api/cases/' + case_id, headers=ORIGIN | {'Access-Control-Request-Method':'DELETE','Access-Control-Request-Headers':'X-CSRF-Token'})
    assert response.status_code == 200


def test_delete_removes_associated_records_and_blocks_busy_case(client):
    _, headers = guest(client)
    case_id = create(client, headers)
    other = create(client, headers)
    repo = client.app.state.ctx.repository
    for kind in ('plan','assessment','report','approval','mock_owner','interview'):
        repo.put(kind, case_id, {'case_id':case_id})
    for kind in ('session','interview_session','workflow_event'):
        repo.put(kind, 'delete-session', {'case_id':case_id,'session_id':'delete-session','state':'completed'})
    repo.put('report_version', case_id + ':v1', {'case_id':case_id})
    repo.put('stage_run', case_id + ':plan', {'status':'running'})
    assert client.delete('/api/cases/' + case_id, headers=headers).status_code == 409
    repo.put('stage_run', case_id + ':plan', {'status':'succeeded'})
    repo.put('session', 'delete-session', {'case_id':case_id,'voice_issued':True,'provider_final':False})
    assert client.delete('/api/cases/' + case_id, headers=headers).status_code == 409
    repo.put('session', 'delete-session', {'case_id':case_id,'state':'processing'})
    assert client.delete('/api/cases/' + case_id, headers=headers).status_code == 409
    repo.put('session', 'delete-session', {'case_id':case_id,'state':'completed'})
    assert client.delete('/api/cases/' + case_id, headers=headers).status_code == 204
    for kind in ('case','case_owner','status','plan','assessment','report','approval','mock_owner','interview','session','interview_session','workflow_event','report_version','stage_run'):
        assert all(id not in {case_id, 'delete-session', case_id + ':v1', case_id + ':plan'} for id, _ in repo.all_records(kind))
    repo.put('workflow_event', 'delete-session', {'case_id':case_id,'status':'failed'})
    assert repo.all_records('workflow_event') == []
    assert client.get('/api/cases/' + other).status_code == 200
    assert client.delete('/api/cases/' + case_id, headers=headers).status_code == 404
