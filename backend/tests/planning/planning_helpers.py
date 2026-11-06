"""Planning test helpers and fixtures: synthetic data, fake providers and a tiny local embedding model.

Everything here is test-only. No network calls are made: the LLM is a fake,
web search and LlamaParse use httpx.MockTransport, and embeddings use a tiny
bag-of-words Sentence Transformers model built locally (as in test_knowledge.py).
"""
import io
import shutil
import zipfile
from pathlib import Path
import pytest
from app.context import AgentContext
from app.errors import AppError
from app.settings import Settings
from app.agents.planning.config import PlanningConfig, REPO_ROOT

KNOWLEDGE = REPO_ROOT / "knowledge"
SYNTHETIC = REPO_ROOT / "data" / "synthetic" / "planning"
CATALOGUE = ["REST APIs and HTTP", "Authentication and secure API handling", "SQL and database integration", "Messaging, retries and idempotency", "Integration troubleshooting"]
VOCAB = sorted(set("""
sql postgresql query queries injection parameterised prepared upsert upserts duplicates transactions transaction isolation
database records reconcile join insert conflict retry retries retried timeout timed backoff exponential idempotent
idempotency key keys payment duplicate message messages queue queues consumer consumers dead letter dead-letter rabbitmq sqs kafka
rest http api apis status codes code 409 429 503 rate limits error errors client clients endpoint machine readable
oauth credentials client token tokens bearer tls https secure unauthorized forbidden 401 403 key secret
troubleshooting logs logging correlation tracing trace distributed incident partner unavailable service
""".split()))


def read(name: str) -> str:
    return (SYNTHETIC / name).read_text(encoding="utf-8")


class FakeLLM:
    """Stands in for ctx.llm; returns scripted structured outputs and records payloads."""

    def __init__(self, responses):
        self.responses, self.calls = responses, []

    async def generate_structured(self, task, system_prompt, user_payload, response_model, provider=None):
        self.calls.append({"task": task, "system": system_prompt, "payload": user_payload})
        value = self.responses.get(task)
        if value is None:
            raise AppError("PROVIDER_NOT_CONFIGURED", "fake: no scripted response", 503)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(user_payload)
        return response_model.model_validate(value)


class FakeBudget:
    def __init__(self, limits=None):
        self.limits, self.reserved, self.reconciled = limits or {}, [], []

    def reserve(self, provider, unit, amount):
        limit = self.limits.get(provider, {}).get(unit)
        if limit is None:
            raise AppError("QUOTA_UNKNOWN", f"Configure PROVIDER_BUDGET_LIMITS for {provider}/{unit}", 503)
        used = sum(a for p, u, a in self.reserved if p == provider and u == unit)
        if used + amount > limit:
            raise AppError("BUDGET_EXCEEDED", f"Budget exhausted for {provider}/{unit}", 429)
        self.reserved.append((provider, unit, amount))
        return len(self.reserved) - 1

    def reconcile(self, reservation, actual, details=None):
        self.reconciled.append((reservation, actual, details))


class FakeRepository:
    def __init__(self, interview_exists=False):
        self.interview_exists = interview_exists

    def get_interview(self, case_id):
        if not self.interview_exists:
            raise AppError("NOT_FOUND", "interview not found", 404)
        return object()


def make_ctx(settings, llm=None, budget=None, repository=None):
    return AgentContext(llm=llm or FakeLLM({}), repository=repository or FakeRepository(), budget=budget or FakeBudget(), telemetry=None, settings=settings)


def make_config(knowledge_dir: Path = KNOWLEDGE, allow_pending_review=True, **overrides) -> PlanningConfig:
    values = dict(knowledge_dir=knowledge_dir, max_cv_pages=3, allow_pending_review=allow_pending_review,
                  enable_tavily_fallback=False, llamaparse_tier="")
    values.update(overrides)
    return PlanningConfig(**values)


@pytest.fixture(scope="session")
def embedding_dir(tmp_path_factory):
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.sentence_transformer import modules
    path = tmp_path_factory.mktemp("model") / "bow-test-model"
    SentenceTransformer(modules=[modules.BoW(vocab=VOCAB)]).save(str(path))
    return path


@pytest.fixture(scope="session")
def indexed_settings(tmp_path_factory, embedding_dir):
    """Settings with a Chroma index built from the real knowledge library (test embeddings)."""
    from app.agents.planning.index import rebuild
    settings = Settings(_env_file=None, embedding_model=str(embedding_dir), chroma_path=str(tmp_path_factory.mktemp("chroma")))
    rebuild(settings, KNOWLEDGE)
    return settings


@pytest.fixture
def knowledge_copy(tmp_path):
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE, target, ignore=shutil.ignore_patterns("unreviewed"))
    (target / "unreviewed").mkdir()
    return target


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """Build a minimal valid text PDF (Helvetica) with one content stream per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        page_no = len(objects) + 1
        kids.append(f"{page_no} 0 R")
        if lines:
            content = "BT /F1 10 Tf 40 760 Td 13 TL " + " ".join(f"({_pdf_escape(l)}) Tj T*" for l in lines) + " ET"
            objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_no + 1} 0 R >>")
            objects.append(f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream")
        else:
            objects.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs: list[str], pages: int | None = None) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p.replace('&', '&amp;').replace('<', '&lt;')}</w:t></w:r></w:p>" for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
        if pages is not None:
            archive.writestr("docProps/app.xml", f"<Properties><Pages>{pages}</Pages></Properties>")
    return out.getvalue()


def extraction_for(jd_requirements, cv_claims, uncertainties=()):
    return {"jd_requirements": [{"skill": s, "importance": i, "excerpt": e} for s, i, e in jd_requirements],
            "cv_claims": [{"skill": s, "excerpt": e} for s, e in cv_claims], "uncertainties": list(uncertainties)}
