"""One-shot offline worker. Accepts only bounded CV drafting context on stdin."""
import json
import socket
import sys
from .compression_assets import verify_assets,MODEL_ID


def blocked(*args,**kwargs):raise OSError('Networking disabled in compression worker')


def main():
    socket.socket.connect=blocked
    socket.socket.connect_ex=blocked
    socket.create_connection=blocked
    from importlib.metadata import version
    if version('llmlingua')!='0.2.2':raise ValueError('Unreviewed compressor version')
    request=json.loads(sys.stdin.buffer.readline(131073))
    from .compression import eligible,safe_text
    import copy
    payload=request['payload'];indices=eligible(payload)
    texts=[payload['sections'][i]['text'] for i in indices]
    if not texts or len(texts)>128 or sum(len(t) for t in texts)>16000:raise ValueError('Invalid input')
    rate=float(request['rate'])
    if not .5<=rate<=.95:raise ValueError('Invalid rate')
    directory=verify_assets()
    import torch
    torch.set_num_threads(2)
    from transformers import BertConfig,BertTokenizerFast,BertForTokenClassification
    from llmlingua import PromptCompressor
    class LocalCompressor(PromptCompressor):
        def load_model(self,model_name,device_map='cpu',model_config=None):
            args={'local_files_only':True,'trust_remote_code':False,'token':False}
            config=BertConfig.from_pretrained(str(directory),**args)
            self.tokenizer=BertTokenizerFast.from_pretrained(str(directory),**args)
            self.model=BertForTokenClassification.from_pretrained(str(directory),config=config,use_safetensors=True,**args).eval()
            self.device='cpu';self.context_idxs=[];self.max_position_embeddings=config.max_position_embeddings
    # The name selects upstream word-piece handling; our loader still uses only
    # the verified local directory and never resolves this identifier remotely.
    compressor=LocalCompressor(model_name=MODEL_ID,device_map='cpu',use_llmlingua2=True,
        llmlingua2_config={'max_batch_size':4,'max_force_token':32})
    # Direct v2 invocation cannot enter the older expression-evaluation/retrieval paths.
    output=compressor.compress_prompt_llmlingua2(texts,rate=rate,
        use_context_level_filter=False,use_token_level_filter=True,force_reserve_digit=True,
        force_tokens=['not','no','never','without','cannot','neither','nor'],drop_consecutive=False)
    import tiktoken
    encoder=tiktoken.get_encoding('o200k_harmony')
    compressed=output['compressed_prompt_list']
    if len(compressed)!=len(texts):raise ValueError('Invalid result')
    result=copy.deepcopy(payload);accepted=[]
    for i,original,text in zip(indices,texts,compressed):
        text=text if safe_text(original,text) else original
        accepted.append(text)
        if text!=original:result['sections'][i].update(text=text,abridged=True)
    count=lambda value:len(encoder.encode(json.dumps(value),disallowed_special=()))
    print(json.dumps({'texts':accepted,'before':count(payload),'after':count(result)},separators=(',',':')),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        print('{"error":"COMPRESSION_UNAVAILABLE"}',flush=True)
        sys.exit(1)
