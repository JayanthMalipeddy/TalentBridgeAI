"""Explicit local model download; no candidate data or hosted inference."""
from huggingface_hub import snapshot_download

if __name__ == '__main__':
    snapshot_download('sentence-transformers/all-MiniLM-L6-v2',
                      local_dir='.cache/models/all-MiniLM-L6-v2',
                      allow_patterns=['*.json', '*.txt', '*.safetensors', '1_Pooling/*'])
    print('Local model ready. Set EMBEDDING_MODEL=.cache/models/all-MiniLM-L6-v2, then rebuild the index.')
