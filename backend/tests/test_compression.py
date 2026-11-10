import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from app.settings import Settings
from app.services.compression import PromptCompression,eligible,safe_text
from app.services.llm import LLMClient
from app.services.budget import BudgetService
from app.services.telemetry import Telemetry


def payload():
    text='Built reliable REST APIs. '+('Additional implementation context and explanatory background. '*24)
    return {'role':'Engineer','sections':[
        {'source_id':'jd-1','source_type':'job_description','text':'Required: SQL and reliable APIs.'},
        {'source_id':'cv-2','source_type':'cv','text':text},
        {'source_id':'cv-3','source_type':'cv','text':'contact@example.com'},
    ]}


def settings(**kwargs):
    kwargs.setdefault('groq_model','openai/gpt-oss-20b')
    return Settings(_env_file=None,llmlingua_enabled=True,**kwargs)


async def test_cv_draft_compression_keeps_protected_fields_and_original_payload():
    original=payload();snapshot=copy.deepcopy(original)
    runner=AsyncMock(return_value={'texts':['Built reliable REST APIs.'],'before':1000,'after':100})
    result,metrics=await PromptCompression(settings(),runner).prepare('planning.role',original)
    assert original==snapshot
    assert result['sections'][0]==original['sections'][0] and result['sections'][2]==original['sections'][2]
    assert result['sections'][1]['source_id']=='cv-2' and result['sections'][1]['abridged'] is True
    assert metrics['applied'] and metrics['saved_payload_tokens']==900


@pytest.mark.parametrize('task',['assessment','hr_assessment','hr_preparation','planning.extract','planning.tailor','report','interview_followup'])
async def test_scoring_and_evidence_tasks_are_never_compressed(task):
    runner=AsyncMock();original=payload()
    result,metrics=await PromptCompression(settings(),runner).prepare(task,original)
    assert result is original and metrics['status']=='protected_task'
    runner.assert_not_awaited()


def test_negation_contacts_numbers_and_new_word_protection():
    original=payload();original['sections'][1]['text']='Not experienced with SQL. '+('Extra context. '*80)
    assert eligible(original)==[]
    assert not safe_text('Built 3 integrations over 2 years.','Built 3 integrations.')
    assert not safe_text('Built APIs.','Led APIs.')
    assert not safe_text('Not skilled in SQL.','Skilled in SQL.')
    assert safe_text('Built 3 integrations with additional explanatory context.','Built 3 integrations.')


@pytest.mark.parametrize('response',[{'texts':['Invented skills'],'before':1000,'after':10},
    {'texts':['Built reliable REST APIs.'],'before':100,'after':100},{'texts':[],'before':1000,'after':10}])
async def test_invalid_or_inflated_result_uses_original(response):
    original=payload();result,metrics=await PromptCompression(settings(),AsyncMock(return_value=response)).prepare('planning.role',original)
    assert result is original and not metrics['applied']


async def test_timeout_failure_disabled_and_busy_use_original():
    async def slow(data):await asyncio.sleep(5)
    original=payload()
    result,metrics=await PromptCompression(settings(llmlingua_timeout_seconds=1),slow).prepare('planning.role',original)
    assert result is original and metrics['status']=='unavailable'
    runner=AsyncMock(side_effect=RuntimeError('internal detail must not enter logs'))
    service=PromptCompression(settings(),runner)
    assert (await service.prepare('planning.role',original))[0] is original
    service.settings.llmlingua_enabled=False
    assert (await service.prepare('planning.role',original))[1]['status']=='disabled'
    service.settings.llmlingua_enabled=True
    await service.gate.acquire()
    try:assert (await service.prepare('planning.role',original))[1]['status']=='busy'
    finally:service.gate.release()


async def test_groq_receives_compressed_payload_and_keeps_schema_validation(client,contracts):
    observed=[]
    def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':contracts['plan'].model_dump_json()}}],'usage':{'total_tokens':20}})
    config=settings(groq_api_key='test-only')
    llm=LLMClient(config,BudgetService(client.app.state.ctx.repository,{'groq':{'requests':1}}),Telemetry(),httpx.MockTransport(handler))
    llm.compression.runner=AsyncMock(return_value={'texts':['Built reliable REST APIs.'],'before':1000,'after':100})
    result=await llm.generate_structured('planning.role','Protected system instructions',payload(),type(contracts['plan']))
    assert result==contracts['plan'] and len(observed)==1
    sent=json.loads(observed[0]['messages'][1]['content'])
    assert sent['sections'][1]['text']=='Built reliable REST APIs.'
    assert observed[0]['messages'][0]['content'].startswith('Protected system instructions')
    receipt=client.app.state.ctx.repository.usage_records()[0]
    assert json.loads(receipt['details'])['compression']['saved_payload_tokens']==900


async def test_worker_environment_drops_credentials_and_arguments_never_include_cv(monkeypatch):
    captured={}
    class Input:
        def write(self,data):captured['stdin']=data
        async def drain(self):pass
        def close(self):pass
    class Output:
        async def readline(self):return b'{"texts":[],"before":0,"after":0}\n'
    process=SimpleNamespace(stdin=Input(),stdout=Output(),returncode=0,wait=AsyncMock())
    async def spawn(*args,**kwargs):captured.update(args=args,env=kwargs['env']);return process
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setenv('GROQ_API_KEY','must-not-be-inherited')
    monkeypatch.setenv('HF_TOKEN','must-not-be-inherited')
    await PromptCompression(settings())._run(payload())
    assert 'GROQ_API_KEY' not in captured['env'] and 'HF_TOKEN' not in captured['env']
    assert captured['env']['HF_HUB_OFFLINE']=='1'
    assert 'Built reliable' not in str(captured['args'])
    assert b'Built reliable' in captured['stdin']


def test_asset_manifest_detects_tampering_before_model_loading(tmp_path,monkeypatch):
    import hashlib
    from app.services import compression_assets as assets
    directory=tmp_path/'model';directory.mkdir()
    monkeypatch.setattr(assets,'ROOT',tmp_path);monkeypatch.setattr(assets,'ASSETS',directory)
    for name in assets.FILES:(directory/name).write_text('synthetic model asset')
    (directory/'config.json').write_text(json.dumps({'model_type':'bert'}))
    checksum=hashlib.sha256((directory/'model.safetensors').read_bytes()).hexdigest()
    monkeypatch.setattr(assets,'WEIGHTS_SHA256',checksum)
    manifest={'model_id':assets.MODEL_ID,'revision':assets.REVISION,'files':{n:assets.file_hash(directory/n) for n in assets.FILES}}
    (directory/'manifest.json').write_text(json.dumps(manifest))
    assert assets.verify_assets()==directory
    (directory/'config.json').write_text('{"auto_map":{"unsafe":"remote.module"}}')
    with pytest.raises(ValueError):assets.verify_assets()
