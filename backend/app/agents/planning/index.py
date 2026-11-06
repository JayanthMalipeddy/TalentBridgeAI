"""Rebuild the knowledge index in the shared persistent Chroma collection.

Usage (from the repository root, PowerShell):
    $env:PYTHONPATH = "backend"
    .\\.venv\\Scripts\\python.exe -m app.agents.planning.index --rebuild

Only curated references and question records are indexed (never
``knowledge/unreviewed`` and never candidate CVs). ``rejected`` records are
skipped. ``review_status`` is stored on every node and filtered at query time,
so approval by a teammate takes effect after a rebuild.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from ...errors import AppError
from ...services.knowledge import local_knowledge
from .config import load_config
from .library import Library, QuestionRecord, ReferenceChunk, load_library

MANIFEST_NAME = "planning_index_manifest.json"


def node_text(record, library: Library) -> str:
    skill = library.skill(record.skill).name
    if isinstance(record, QuestionRecord):
        return f"{skill}. Interview question: {record.question} Expected topics: {'; '.join(record.expected_topics)}"
    return f"{skill}. {record.title}, {record.section}: {record.excerpt}"


def node_metadata(record, library: Library) -> dict:
    content_hash = hashlib.sha256(json.dumps(record.model_dump(), sort_keys=True).encode()).hexdigest()[:16]
    return {
        # "document_id" is reserved by LlamaIndex node metadata, so use a prefixed key.
        "kb_document_id": record.document_id,
        "chunk_id": record.chunk_id,
        "item_type": "question" if isinstance(record, QuestionRecord) else "reference",
        "skill": record.skill,
        "review_status": record.review_status,
        "version": record.version,
        "source_url": record.source_url,
        "content_hash": content_hash,
    }


def manifest_path(settings) -> Path:
    return Path(settings.chroma_path) / MANIFEST_NAME


def read_manifest(settings) -> dict | None:
    path = manifest_path(settings)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def rebuild(settings, knowledge_dir: Path | None = None) -> dict:
    from llama_index.core.schema import TextNode
    config = load_config()
    library = load_library(knowledge_dir or config.knowledge_dir)
    store, embedding = local_knowledge(settings)
    collection = store.client
    records = [r for r in library.records() if r.review_status != "rejected"]
    wanted = {r.chunk_id: (r, node_metadata(r, library)) for r in records}

    existing = collection.get(include=["metadatas"])
    existing_hash = {i: (m or {}).get("content_hash") for i, m in zip(existing["ids"], existing["metadatas"])}
    # Remove nodes that disappeared, changed, or were not created by this indexer.
    stale = [i for i, h in existing_hash.items() if i not in wanted or wanted[i][1]["content_hash"] != h]
    if stale:
        collection.delete(ids=stale)
    to_add = [cid for cid in wanted if cid not in existing_hash or cid in stale]
    nodes = []
    if to_add:
        texts = [node_text(wanted[cid][0], library) for cid in to_add]
        vectors = embedding.get_text_embedding_batch(texts)
        for cid, text, vector in zip(to_add, texts, vectors):
            nodes.append(TextNode(id_=cid, text=text, metadata=wanted[cid][1], embedding=vector))
        store.add(nodes)
    version = library.version(settings.embedding_model)
    stats = {
        "knowledge_version": version,
        "records_indexed": len(wanted),
        "added_or_updated": len(nodes),
        "removed": len([i for i in stale if i not in wanted]),
        "references": sum(isinstance(r, ReferenceChunk) for r, _ in wanted.values()),
        "questions": sum(isinstance(r, QuestionRecord) for r, _ in wanted.values()),
        "review_status_counts": {s: sum(r.review_status == s for r, _ in wanted.values()) for s in ("approved", "pending_review")},
        "embedding_model": Path(settings.embedding_model).name,
        "collection_count": collection.count(),
    }
    path = manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the TalentBridge planning knowledge index")
    parser.add_argument("--rebuild", action="store_true", help="validate the library and upsert it into Chroma")
    parser.add_argument("--validate-only", action="store_true", help="validate knowledge files without embedding")
    args = parser.parse_args(argv)
    from ...settings import Settings
    try:
        if args.validate_only:
            library = load_library(load_config().knowledge_dir)
            print(json.dumps({"valid": True, "references": len(library.references), "questions": len(library.questions)}, indent=2))
            return 0
        if not args.rebuild:
            parser.print_help()
            return 2
        print(json.dumps(rebuild(Settings()), indent=2))
        return 0
    except AppError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
