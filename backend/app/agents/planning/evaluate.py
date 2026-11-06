"""Measure real retrieval quality against labelled queries (no LLM, no network).

Usage (repository root, PowerShell):
    $env:PYTHONPATH = "backend"
    .\\.venv\\Scripts\\python.exe -m app.agents.planning.evaluate

Uses the real local embedding model and Chroma index. Results are written to
data/synthetic/planning/retrieval_eval_results.json and are separate from the
mocked unit tests. Evaluation includes pending_review records because it
measures ranking quality, not approval state.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from ...errors import AppError
from .config import REPO_ROOT, load_config
from .library import load_library
from .retrieval import KnowledgeRetriever

LABELS = REPO_ROOT / "data" / "synthetic" / "planning" / "retrieval_labels.jsonl"
RESULTS = REPO_ROOT / "data" / "synthetic" / "planning" / "retrieval_eval_results.json"


def evaluate(settings, labels_path: Path = LABELS, k: int = 3) -> dict:
    library = load_library(load_config().knowledge_dir)
    retriever = KnowledgeRetriever(settings, library, {"approved", "pending_review"}, top_k=k, max_chars=10**6)
    rows = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    per_query, hits, recall_sum, rr_sum = [], 0, 0.0, 0.0
    for row in rows:
        ranked = [h.chunk_id for h in retriever.retrieve(row["query"], row["skill"], "question")]
        relevant = set(row["relevant_chunk_ids"])
        found = [c for c in ranked[:k] if c in relevant]
        rank = next((i for i, c in enumerate(ranked, 1) if c in relevant), None)
        hits += bool(found)
        recall_sum += len(found) / len(relevant)
        rr_sum += 1 / rank if rank else 0
        per_query.append({"query_id": row["query_id"], "skill": row["skill"], "retrieved": ranked, "relevant": sorted(relevant), "hit": bool(found)})
    n = len(rows)
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "knowledge_version": library.version(settings.embedding_model),
        "embedding_model": Path(settings.embedding_model).name,
        "k": k, "queries": n,
        "hit_rate_at_k": round(hits / n, 3), "mean_recall_at_k": round(recall_sum / n, 3), "mrr": round(rr_sum / n, 3),
        "note": "Retrieval is filtered by skill, so this measures ranking within a skill. Labels authored by Priya's module; second-teammate review pending.",
        "per_query": per_query,
    }


def main() -> int:
    from ...settings import Settings
    try:
        result = evaluate(Settings())
    except AppError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    RESULTS.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "per_query"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
