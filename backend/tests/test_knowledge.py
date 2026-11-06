def test_local_embedding_and_persistent_chroma(tmp_path):
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.sentence_transformer import modules
    from app.services.knowledge import local_knowledge
    from app.settings import Settings
    # Tiny locally constructed model tests wiring without downloads or live fixtures.
    model_dir = tmp_path / "model"
    SentenceTransformer(modules=[modules.BoW(vocab=["python", "testing", "evidence"])]).save(str(model_dir))
    settings = Settings(_env_file=None, embedding_model=str(model_dir), chroma_path=str(tmp_path / "chroma"))
    store, embedding = local_knowledge(settings)
    vector = embedding.get_text_embedding("python testing")
    assert len(vector) == 3
    store.client.add(ids=["test-only"], embeddings=[vector], documents=["python testing"])
    reopened, _ = local_knowledge(settings)
    assert reopened.client.get(ids=["test-only"])["ids"] == ["test-only"]
