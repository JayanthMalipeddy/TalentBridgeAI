"""Build EvidenceRefs whose excerpts are verified verbatim against their sources."""
import re
from ...contracts import EvidenceRef
from .library import ReferenceChunk

INJECTION_PATTERNS = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(instructions|rubric)|"
    r"system prompt|you are now|act as (an?|the) |developer mode|score (this|the) candidate|give (me|this candidate) (a )?(score|3)",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate(text: str, excerpt: str) -> str | None:
    """Return 'line N' if the excerpt occurs verbatim (whitespace-normalised) in one line."""
    needle = _norm(excerpt)
    if len(needle) < 3:
        return None
    for number, line in enumerate(text.splitlines(), 1):
        if needle in _norm(line):
            return f"line {number}"
    return None


def document_ref(case_id: str, source_type: str, text: str, excerpt: str) -> EvidenceRef | None:
    locator = locate(text, excerpt)
    if locator is None:
        return None
    return EvidenceRef(source_type=source_type, source_id=f"{case_id}:{'cv' if source_type == 'cv' else 'jd'}", locator=locator, excerpt=_norm(excerpt))


def knowledge_ref(chunk: ReferenceChunk) -> EvidenceRef:
    return EvidenceRef(source_type="knowledge", source_id=chunk.chunk_id, locator=f"{chunk.title}, {chunk.section} <{chunk.source_url}>", excerpt=chunk.excerpt)


def find_alias_line(text: str, aliases: list[str]) -> tuple[str, str] | None:
    """Deterministic JD scan: first line mentioning a skill alias → (alias, line text)."""
    for line in text.splitlines():
        lowered = line.lower()
        for alias in aliases:
            if re.search(r"(?<![a-z0-9])" + re.escape(alias.lower()) + r"(?![a-z0-9])", lowered):
                return alias, line.strip()[:300]
    return None


def suspicious_instructions(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))
