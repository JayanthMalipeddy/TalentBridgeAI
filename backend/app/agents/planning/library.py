"""Load and validate the knowledge library (references, question records, skills).

Only ``knowledge/references`` and ``knowledge/questions`` are loaded here.
``knowledge/unreviewed`` (web research) is never loaded, so it can never become
scoring criteria.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ...errors import AppError

ReviewStatus = Literal["approved", "pending_review", "rejected"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str
    skill: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: ReviewStatus
    retrieved_at: str = Field(min_length=1)


class ReferenceChunk(_Record):
    section: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)

    @model_validator(mode="after")
    def needs_url(self):
        if not self.source_url.startswith("https://"):
            raise ValueError(f"{self.chunk_id}: references need an https source_url")
        return self


class QuestionRecord(_Record):
    question_id: str = Field(min_length=1)
    role: str
    seniority: str
    question: str = Field(min_length=1)
    expected_topics: list[str] = Field(min_length=1)
    rubric: dict[Literal["0", "1", "2", "3"], str]
    reference_chunk_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def complete(self):
        if set(self.rubric) != {"0", "1", "2", "3"}:
            raise ValueError(f"{self.question_id}: rubric needs scores 0-3")
        if self.chunk_id != self.question_id:
            raise ValueError(f"{self.question_id}: chunk_id must equal question_id")
        return self


class GenericRubric(_Record):
    rubric: dict[Literal["0", "1", "2", "3"], str]
    note: str = ""


class Skill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    name: str
    aliases: list[str]


@dataclass
class Library:
    skills: list[Skill]
    references: dict[str, ReferenceChunk]
    questions: dict[str, QuestionRecord]
    generic: GenericRubric
    role: str
    files: list[str] = field(default_factory=list)

    @property
    def skill_ids(self) -> list[str]:
        return [s.skill for s in self.skills]

    def skill(self, skill_id: str) -> Skill:
        return next(s for s in self.skills if s.skill == skill_id)

    def records(self):
        yield from self.references.values()
        yield from self.questions.values()

    def version(self, embedding_model: str = "") -> str:
        """Deterministic knowledge_version: content, review state and embedding model."""
        digest = hashlib.sha256()
        for record in sorted(self.records(), key=lambda r: r.chunk_id):
            digest.update(json.dumps(record.model_dump(), sort_keys=True).encode())
        digest.update(json.dumps(self.generic.model_dump(), sort_keys=True).encode())
        digest.update(Path(embedding_model).name.encode() if embedding_model else b"no-embedding")
        return "kb-" + digest.hexdigest()[:12]


def allowed_statuses(allow_pending_review: bool) -> set[str]:
    return {"approved", "pending_review"} if allow_pending_review else {"approved"}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError("KNOWLEDGE_INVALID", f"Cannot read knowledge file {path.name}: {type(exc).__name__}", 500)


def load_library(knowledge_dir: Path) -> Library:
    knowledge_dir = Path(knowledge_dir)
    if not (knowledge_dir / "skills.json").is_file():
        raise AppError("KNOWLEDGE_MISSING", f"Knowledge library not found at {knowledge_dir}", 503)
    try:
        skills_doc = _read(knowledge_dir / "skills.json")
        skills = [Skill.model_validate(s) for s in skills_doc["skills"]]
        references: dict[str, ReferenceChunk] = {}
        files = []
        for path in sorted((knowledge_dir / "references").glob("*.json")):
            files.append(path.name)
            for raw in _read(path)["chunks"]:
                chunk = ReferenceChunk.model_validate(raw)
                if chunk.chunk_id in references:
                    raise ValueError(f"duplicate chunk_id {chunk.chunk_id}")
                references[chunk.chunk_id] = chunk
        questions: dict[str, QuestionRecord] = {}
        for path in sorted((knowledge_dir / "questions").glob("*.json")):
            if path.name == "generic_rubric.json":
                continue
            files.append(path.name)
            for raw in _read(path)["records"]:
                record = QuestionRecord.model_validate(raw)
                if record.question_id in questions or record.question_id in references:
                    raise ValueError(f"duplicate id {record.question_id}")
                questions[record.question_id] = record
        generic = GenericRubric.model_validate(_read(knowledge_dir / "questions" / "generic_rubric.json"))
    except AppError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise AppError("KNOWLEDGE_INVALID", f"Knowledge library failed validation: {str(exc)[:300]}", 500)
    skill_ids = {s.skill for s in skills}
    for record in list(references.values()) + list(questions.values()):
        if record.skill not in skill_ids:
            raise AppError("KNOWLEDGE_INVALID", f"{record.chunk_id} uses unknown skill {record.skill}", 500)
    for record in questions.values():
        unknown = [c for c in record.reference_chunk_ids if c not in references]
        if unknown:
            raise AppError("KNOWLEDGE_INVALID", f"{record.question_id} cites unknown references {unknown}", 500)
    return Library(skills, references, questions, generic, skills_doc.get("role", ""), files)
