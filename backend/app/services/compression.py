"""Optional local compression of CV drafting context; all other tasks bypass it."""
import asyncio
from collections import Counter
import copy
import json
import os
import re
import sys
import time
import importlib.util
from .compression_assets import ROOT,ASSETS

NEGATIONS={'not','no','never','without','neither','nor','cannot',"can't","isn't","wasn't","didn't"}


def words(text):return re.findall(r"\w+(?:'\w+)?|[^\w\s]",text)


def eligible(payload):
    result=[]
    sections=payload.get('sections',[])
    if not isinstance(sections,list) or len(sections)>128:return []
    for i,section in enumerate(sections):
        if not isinstance(section,dict) or section.get('source_type')!='cv':continue
        text=section.get('text')
        if not isinstance(text,str) or not 100<=len(text)<=2000:continue
        if '@' in text or '://' in text or re.search(r'\+\d',text):continue
        if NEGATIONS.intersection(w.casefold() for w in words(text)):continue
        result.append(i)
    return result


def safe_text(original,compressed):
    if not isinstance(compressed,str) or not compressed.strip() or len(compressed)>=len(original):return False
    before,after=words(original),words(compressed)
    cursor=iter(before)
    if not all(any(t==word for t in cursor) for word in after):return False
    # Numbers must retain every occurrence, not just the same set of digits.
    protected=lambda tokens:Counter(w for w in tokens if any(c.isdigit() for c in w) or w.casefold() in NEGATIONS)
    return protected(before)==protected(after)


class PromptCompression:
    def __init__(self,settings,runner=None):
        self.settings=settings;self.runner=runner or self._run;self.gate=asyncio.Semaphore(1)

    def capability(self):
        assets=(ASSETS/'manifest.json').is_file()
        installed=importlib.util.find_spec('llmlingua') is not None
        enabled=self.settings.llmlingua_enabled
        return {'configured':enabled,'available':enabled and assets and installed,'implemented':True,
            'scope':'CV context for question drafting only',
            'reason':'Enabled; model integrity is checked per use' if enabled and assets and installed else 'Disabled' if not enabled else 'Prepare the pinned model and install the compression extra'}

    async def _run(self,payload):
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC'}}
        env.update(PYTHONPATH=str(ROOT/'backend'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
            HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1',TOKENIZERS_PARALLELISM='false',
            NLTK_DATA=str(ASSETS/'nltk-data'),
            TIKTOKEN_CACHE_DIR=str(ASSETS/'tokenizer-cache'))
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','app.services.compression_worker',
            cwd=str(ROOT),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,limit=131072)
        try:
            request=json.dumps({'payload':payload,'rate':self.settings.llmlingua_rate},ensure_ascii=False).encode()+b'\n'
            process.stdin.write(request);await process.stdin.drain();process.stdin.close()
            response=await process.stdout.readline()
            await process.wait()
            if process.returncode!=0 or len(response)>131072:raise ValueError('Worker unavailable')
            return json.loads(response)
        finally:
            if process.returncode is None:
                try:process.kill()
                except ProcessLookupError:pass
                await process.wait()

    async def prepare(self,task,payload):
        metrics={'status':'disabled','applied':False}
        if not self.settings.llmlingua_enabled:return payload,metrics
        if task!='planning.role':return payload,{'status':'protected_task','applied':False}
        if self.settings.groq_model not in {'openai/gpt-oss-20b','openai/gpt-oss-120b'}:
            return payload,{'status':'unsupported_tokenizer','applied':False}
        indices=eligible(payload)
        size=sum(len(payload['sections'][i]['text']) for i in indices)
        if size<self.settings.llmlingua_min_chars or size>16000:return payload,{'status':'below_minimum_or_oversize','applied':False}
        if len(json.dumps(payload,ensure_ascii=False).encode())>100000:return payload,{'status':'oversize','applied':False}
        if self.gate.locked():return payload,{'status':'busy','applied':False}
        started=time.monotonic()
        try:
            async with self.gate:
                response=await asyncio.wait_for(self.runner(copy.deepcopy(payload)),self.settings.llmlingua_timeout_seconds)
            texts=response['texts']
            if not isinstance(texts,list) or len(texts)!=len(indices):raise ValueError('Invalid result')
            result=copy.deepcopy(payload);changed=0
            for i,text in zip(indices,texts):
                original=payload['sections'][i]['text']
                if text==original:continue
                if not safe_text(original,text):raise ValueError('Unsafe compression')
                result['sections'][i]['text']=text;result['sections'][i]['abridged']=True;changed+=1
            before,after=response['before'],response['after']
            if not all(isinstance(n,int) and n>=0 for n in (before,after)):raise ValueError('Invalid counts')
            if not changed or before-after<self.settings.llmlingua_min_saved_tokens or len(json.dumps(result).encode())>=len(json.dumps(payload).encode()):
                return payload,{'status':'no_savings','applied':False}
            metrics={'status':'compressed','applied':True,'payload_tokens_before':before,'payload_tokens_after':after,
                'saved_payload_tokens':before-after,'sections_compressed':changed,'elapsed_seconds':round(time.monotonic()-started,3)}
            return result,metrics
        except asyncio.CancelledError:raise
        except Exception:
            return payload,{'status':'unavailable','applied':False,'elapsed_seconds':round(time.monotonic()-started,3)}
