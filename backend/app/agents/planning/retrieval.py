"""Filtered, bounded retrieval over the approved knowledge index (LlamaIndex + Chroma).

Filters (skill, item type, allowed review statuses) are applied inside the
vector query and re-checked in code. Returned excerpts always come from the
validated library files by chunk_id, so they are exact and never a model or
index paraphrase. Candidate CV/JD text is only used as a transient query and is
never written to the index.
"""
from dataclasses import dataclass
from ...errors import AppError
from ...services.knowledge import local_knowledge
from .library import Library, QuestionRecord


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    item_type: str
    skill: str
    score: float | None


class KnowledgeRetriever:
    def __init__(self, settings, library: Library, allowed: set[str], top_k: int = 3, max_chars: int = 2400):
        self.settings, self.library, self.allowed = settings, library, set(allowed)
        self.top_k, self.max_chars = max(1, min(top_k, 5)), max_chars
        self._index = None

    def _vector_index(self):
        if self._index is None:
            from llama_index.core import VectorStoreIndex
            store, embedding = local_knowledge(self.settings)
            if store.client.count() == 0:
                raise AppError("KNOWLEDGE_INDEX_EMPTY", "Knowledge index is empty; run: python -m app.agents.planning.index --rebuild", 503)
            self._index = VectorStoreIndex.from_vector_store(store, embed_model=embedding)
        return self._index

    def retrieve(self, query: str, skill: str, item_type: str) -> list[Hit]:
        from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters
        filters = MetadataFilters(filters=[
            MetadataFilter(key="skill", value=skill, operator=FilterOperator.EQ),
            MetadataFilter(key="item_type", value=item_type, operator=FilterOperator.EQ),
            MetadataFilter(key="review_status", value=sorted(self.allowed), operator=FilterOperator.IN),
        ])
        retriever = self._vector_index().as_retriever(similarity_top_k=self.top_k, filters=filters)
        hits, used_chars = [], 0
        for result in retriever.retrieve(query[:2000]):
            meta = result.node.metadata or {}
            chunk_id = meta.get("chunk_id") or result.node.node_id
            record = self.library.questions.get(chunk_id) or self.library.references.get(chunk_id)
            # Defence in depth: drop anything the library does not vouch for.
            if record is None or record.skill != skill or record.review_status not in self.allowed:
                continue
            if (item_type == "question") != isinstance(record, QuestionRecord):
                continue
            size = len(record.question if isinstance(record, QuestionRecord) else record.excerpt)
            if hits and used_chars + size > self.max_chars:
                break
            used_chars += size
            hits.append(Hit(chunk_id, item_type, skill, result.score))
        return hits
