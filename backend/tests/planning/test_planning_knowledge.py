import json
import pytest
from app.errors import AppError
from app.settings import Settings
from app.agents.planning.index import read_manifest, rebuild
from app.agents.planning.library import load_library
from app.agents.planning.retrieval import KnowledgeRetriever
from planning_helpers import KNOWLEDGE, SYNTHETIC

REQUIRED = ["document_id", "chunk_id", "title", "source_url", "skill", "version", "review_status", "retrieved_at"]


def test_library_metadata_and_separation():
    library = load_library(KNOWLEDGE)
    assert 15 <= len(library.questions) <= 20
    assert set(library.skill_ids) == {"rest_http", "api_auth_security", "sql_database", "messaging_idempotency", "integration_troubleshooting"}
    for record in library.records():
        data = record.model_dump()
        assert all(data[field] for field in REQUIRED if field != "source_url")
        assert data["source_url"].startswith("https://")
        # Not labelled human-approved until a teammate review is recorded.
        assert record.review_status == "pending_review"
    for record in library.questions.values():
        assert set(record.rubric) == {"0", "1", "2", "3"} and record.expected_topics
    # Unreviewed web research lives in its own folder and is never loaded.
    loaded = set(library.files)
    assert not any(name.startswith("web-") for name in loaded)


def test_unreviewed_research_never_loaded(knowledge_copy):
    (knowledge_copy / "unreviewed" / "web-test.json").write_text(json.dumps({"review_status": "unreviewed", "results": [{"chunk_id": "web-x"}]}))
    library = load_library(knowledge_copy)
    assert "web-x" not in library.references and "web-x" not in library.questions


def test_invalid_library_is_rejected(knowledge_copy):
    path = knowledge_copy / "questions" / "integration_engineer.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][0]["rubric"].pop("3")
    path.write_text(json.dumps(data))
    with pytest.raises(AppError) as exc:
        load_library(knowledge_copy)
    assert exc.value.code == "KNOWLEDGE_INVALID"


def test_rebuild_is_idempotent_and_updates_by_id(tmp_path, embedding_dir, knowledge_copy):
    settings = Settings(_env_file=None, embedding_model=str(embedding_dir), chroma_path=str(tmp_path / "chroma"))
    first = rebuild(settings, knowledge_copy)
    second = rebuild(settings, knowledge_copy)
    assert first["records_indexed"] == first["collection_count"] == second["collection_count"] == 55
    assert second["added_or_updated"] == 0 and second["knowledge_version"] == first["knowledge_version"]
    path = knowledge_copy / "questions" / "integration_engineer.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][0]["review_status"] = "approved"
    data["records"] = data["records"][:-1]  # retire one record
    path.write_text(json.dumps(data))
    third = rebuild(settings, knowledge_copy)
    assert third["added_or_updated"] == 1 and third["removed"] == 1 and third["collection_count"] == 54
    assert third["knowledge_version"] != first["knowledge_version"]
    assert read_manifest(settings)["knowledge_version"] == third["knowledge_version"]


def test_retrieval_filters_by_review_status_and_skill(indexed_settings):
    library = load_library(KNOWLEDGE)
    approved_only = KnowledgeRetriever(indexed_settings, library, {"approved"})
    assert approved_only.retrieve("SQL upsert duplicates", "sql_database", "question") == []
    with_pending = KnowledgeRetriever(indexed_settings, library, {"approved", "pending_review"})
    hits = with_pending.retrieve("SQL upsert duplicates", "sql_database", "question")
    assert 1 <= len(hits) <= 3 and all(library.questions[h.chunk_id].skill == "sql_database" for h in hits)
    refs = with_pending.retrieve("bearer token TLS", "api_auth_security", "reference")
    assert refs and all(h.chunk_id in library.references for h in refs)


def test_retrieval_context_is_bounded(indexed_settings):
    library = load_library(KNOWLEDGE)
    loose = KnowledgeRetriever(indexed_settings, library, {"pending_review"}, top_k=3, max_chars=10_000)
    tight = KnowledgeRetriever(indexed_settings, library, {"pending_review"}, top_k=3, max_chars=150)
    query = "retry backoff idempotency"
    hits = tight.retrieve(query, "messaging_idempotency", "question")
    assert len(loose.retrieve(query, "messaging_idempotency", "question")) == 3
    assert 1 <= len(hits) < 3
    assert sum(len(library.questions[h.chunk_id].question) for h in hits) <= 150


def test_labelled_queries_retrieve_relevant_chunks(indexed_settings):
    library = load_library(KNOWLEDGE)
    retriever = KnowledgeRetriever(indexed_settings, library, {"pending_review"})
    rows = [json.loads(line) for line in (SYNTHETIC / "retrieval_labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 10
    hits = sum(bool(set(h.chunk_id for h in retriever.retrieve(r["query"], r["skill"], "question")) & set(r["relevant_chunk_ids"])) for r in rows)
    # Test embeddings are a tiny bag-of-words model; real-model measurements are recorded by evaluate.py.
    assert hits / len(rows) >= 0.75


def test_missing_embedding_model_is_actionable():
    library = load_library(KNOWLEDGE)
    retriever = KnowledgeRetriever(Settings(_env_file=None, embedding_model=""), library, {"approved"})
    with pytest.raises(AppError) as exc:
        retriever.retrieve("sql", "sql_database", "question")
    assert exc.value.code == "EMBEDDINGS_NOT_CONFIGURED"
