"""Immutable allowlist for the reviewed local LLMLingua-2 assets."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
ASSETS=ROOT/'.cache'/'models'/'llmlingua2'
MODEL_ID='microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank'
REVISION='5f0c82792b7ea14c6484e015b6a072009496b7f2'
WEIGHTS_SHA256='22b9ecde52fec5c97e8c54a293be768727df95a81c6c8dccb03f262a50c58324'
FILES=('config.json','model.safetensors','special_tokens_map.json','tokenizer.json','tokenizer_config.json','vocab.txt')


def file_hash(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def verify_assets():
    if not ASSETS.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Assets must stay inside the workspace')
    manifest=json.loads((ASSETS/'manifest.json').read_text(encoding='utf-8'))
    if manifest['model_id']!=MODEL_ID or manifest['revision']!=REVISION:
        raise ValueError('Unreviewed model')
    if set(manifest['files'])!=set(FILES) or manifest['files']['model.safetensors']!=WEIGHTS_SHA256:
        raise ValueError('Invalid asset allowlist')
    for name in FILES:
        path=ASSETS/name
        if path.is_symlink() or path.resolve().parent!=ASSETS.resolve() or file_hash(path)!=manifest['files'][name]:
            raise ValueError('Model integrity check failed')
    config=json.loads((ASSETS/'config.json').read_text())
    if config.get('model_type')!='bert' or config.get('auto_map'):
        raise ValueError('Only standard BERT is allowed')
    return ASSETS
