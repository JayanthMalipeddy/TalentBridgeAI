"""Explicit asset preparation; no candidate text or production API credentials required."""
import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services.compression_assets import ASSETS,FILES,MODEL_ID,REVISION,WEIGHTS_SHA256,file_hash,verify_assets


def download_weights(url,destination):
    # Bounded HTTP ranges avoid a single large transfer stalling indefinitely.
    probe=urllib.request.Request(url,headers={'Range':'bytes=0-0'})
    with urllib.request.urlopen(probe,timeout=30) as response:
        total=int(response.headers['Content-Range'].split('/')[-1])
        response.read(1)
    if not 600_000_000<total<800_000_000:raise ValueError('Unexpected model size')
    chunk_size=4*1024*1024
    def fetch(start):
        end=min(start+chunk_size,total)-1
        request=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
        with urllib.request.urlopen(request,timeout=30) as response:
            if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{total}':
                raise ValueError('Invalid download range')
            value=response.read(end-start+2)
        if len(value)!=end-start+1:raise ValueError('Incomplete model range')
        return value
    with destination.open('wb') as out,ThreadPoolExecutor(max_workers=4) as pool:
        starts=list(range(0,total,chunk_size))
        for offset in range(0,len(starts),4):
            for chunk in pool.map(fetch,starts[offset:offset+4]):out.write(chunk)
            print(f'Model download: {min((offset+4)*chunk_size,total)*100//total}%',flush=True)


def main():
    ASSETS.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        target=ASSETS/name
        if name=='model.safetensors' and target.exists() and file_hash(target)==WEIGHTS_SHA256:continue
        print('Preparing '+name,flush=True)
        temporary=target.with_suffix(target.suffix+'.partial')
        url=f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
        if name=='model.safetensors':download_weights(url,temporary)
        else:
            with urllib.request.urlopen(url,timeout=30) as response,temporary.open('wb') as out:
                out.write(response.read(10_000_001))
            if temporary.stat().st_size>10_000_000:raise ValueError('Tokenizer asset too large')
        if name=='model.safetensors' and file_hash(temporary)!=WEIGHTS_SHA256:
            raise ValueError('Downloaded model checksum mismatch')
        temporary.replace(target)
    manifest={'model_id':MODEL_ID,'revision':REVISION,'files':{n:file_hash(ASSETS/n) for n in FILES}}
    (ASSETS/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    verify_assets()
    # tiktoken has its own data files. Prepare both explicitly for offline runtime.
    os.environ['TIKTOKEN_CACHE_DIR']=str(ASSETS/'tokenizer-cache')
    (ASSETS/'nltk-data').mkdir(exist_ok=True)
    import tiktoken
    for name in ('cl100k_base','o200k_harmony'):tiktoken.get_encoding(name)
    print('Pinned model verified; tokenizer caches prepared. No LLM call made.')


if __name__=='__main__':main()
