"""Lazy local infrastructure only. Priya owns ingestion and retrieval policy."""
from pathlib import Path
from ..errors import AppError


def local_knowledge(settings):
    if not settings.embedding_model or not Path(settings.embedding_model).is_dir():
        raise AppError("EMBEDDINGS_NOT_CONFIGURED", "Set EMBEDDING_MODEL to a downloaded local Sentence Transformers directory", 503)
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    from llama_index.vector_stores.chroma import ChromaVectorStore
    client = chromadb.PersistentClient(path=settings.chroma_path, settings=ChromaSettings(anonymized_telemetry=False))
    store = ChromaVectorStore(chroma_collection=client.get_or_create_collection("talentbridge_knowledge"))
    embedding = HuggingFaceEmbedding(model_name=settings.embedding_model, device="cpu", local_files_only=True, max_length=settings.embedding_max_length)
    return store, embedding
