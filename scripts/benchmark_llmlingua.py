"""Actual local compression measurements on fictional data; never calls Groq."""
import asyncio
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.settings import Settings
from app.services.compression import PromptCompression
from app.services.compression_assets import MODEL_ID,REVISION


async def main():
    samples=[
        'Fictional profile. Developed REST APIs and SQL integrations. In addition to this work, provided explanatory documentation for colleagues and collaborated on implementation details, background discussions, routine coordination and general project communication. ',
        'Fictional profile. Built automated software tests and supported deployment pipelines. The surrounding project involved regular meetings, general background information, additional explanatory material and routine administrative communication with colleagues. ',
    ]
    settings=Settings(_env_file=None,llmlingua_enabled=True,groq_model='openai/gpt-oss-20b',llmlingua_timeout_seconds=90)
    service=PromptCompression(settings);rows=[]
    for i,sample in enumerate(samples):
        payload={'role':'Software Engineer','sections':[{'source_id':'jd-1','source_type':'job_description','text':'Design REST APIs, use SQL, build tests and explain engineering trade-offs.'}]+
            [{'source_id':f'cv-{n}','source_type':'cv','text':sample*2} for n in range(8)]}
        started=time.monotonic();output,metrics=await service.prepare('planning.role',payload)
        assert output['sections'][0]==payload['sections'][0]
        assert [x['source_id'] for x in output['sections']]==[x['source_id'] for x in payload['sections']]
        row={'sample':i+1,'data':'fictional','original_cv_characters':sum(len(x['text']) for x in payload['sections'][1:]),'wall_seconds':round(time.monotonic()-started,3),**metrics}
        rows.append(row);print(json.dumps(row),flush=True)
    report={'model':MODEL_ID,'revision':REVISION,'hosted_requests':0,'samples':rows,
        'limitations':'Measures local payload token reduction and latency only. No downstream LLM or human-reviewed assessment-quality evaluation was performed.'}
    target=Path('.cache/llmlingua-benchmark.json');target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Local benchmark saved to '+str(target),flush=True)


if __name__=='__main__':asyncio.run(main())
