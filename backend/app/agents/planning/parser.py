"""Local CV parsing (text PDF, DOCX, UTF-8 text) with an optional LlamaParse fallback.

* Size limit: ``settings.max_cv_bytes`` (shared). Page limit: PLANNING_MAX_CV_PAGES.
* Unreadable or near-empty extraction raises ``CV_UNREADABLE``; it is never
  returned as an empty candidate profile.
* Parsed text is cached in memory by SHA-256 of the file bytes (never on disk).
* LlamaParse is used only when local extraction is unusable AND
  LLAMA_CLOUD_API_KEY, PLANNING_LLAMAPARSE_TIER and a ``llamaparse`` budget are
  configured. API shape follows https://developers.llamaindex.ai/llamaparse/parse/getting_started/
"""
import asyncio
import hashlib
import io
import re
import zipfile
from collections import OrderedDict
from xml.etree import ElementTree
import httpx
from ...errors import AppError

MIN_WORDS = 30
MIN_LETTERS = 150
MAX_DOCX_XML_BYTES = 20_000_000
_CACHE: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 64
UNREADABLE_MESSAGE = "Could not extract readable text from the CV. Upload a text-based PDF or DOCX, or paste the CV as text."
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LLAMA_BASE = "https://api.cloud.llamaindex.ai"


class Unreadable(Exception):
    """Local extraction produced no usable text (eligible for fallback)."""


def usable(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'+#.-]*", text)
    return len(words) >= MIN_WORDS and sum(ch.isalpha() for ch in text) >= MIN_LETTERS


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_pdf(data: bytes, max_pages: int) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise AppError("PDF_PARSER_UNAVAILABLE", "PDF parsing needs the pypdf package (integration request pending). Upload a DOCX or paste the CV text.", 503)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AppError("CV_ENCRYPTED", "The PDF is password-protected. Upload an unprotected PDF, a DOCX, or paste the CV text.", 422)
        if len(reader.pages) > max_pages:
            raise AppError("CV_TOO_MANY_PAGES", f"The CV has more than {max_pages} pages. Upload a shorter CV.", 413)
        pages = [page.extract_text() or "" for page in reader.pages]
    except AppError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise Unreadable(type(exc).__name__)
    return "\n\n".join(pages)


def extract_docx(data: bytes, max_pages: int) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise AppError("CV_TOO_LARGE", "The DOCX content is too large.", 413)
            if "docProps/app.xml" in archive.namelist():
                pages = re.search(rb"<Pages>(\d+)</Pages>", archive.read("docProps/app.xml"))
                if pages and int(pages.group(1)) > max_pages:
                    raise AppError("CV_TOO_MANY_PAGES", f"The CV has more than {max_pages} pages. Upload a shorter CV.", 413)
            root = ElementTree.fromstring(archive.read(info))
    except AppError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise Unreadable(type(exc).__name__)
    paragraphs = []
    for paragraph in root.iter(W + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def extract_local(data: bytes, filename: str, max_pages: int) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return extract_pdf(data, max_pages)
    if name.endswith(".docx"):
        return extract_docx(data, max_pages)
    if name.endswith(".txt"):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise AppError("INVALID_CV", "Text CV must use UTF-8.", 422)
    raise AppError("UNSUPPORTED_CV_TYPE", "Unsupported CV format. Upload a text-based PDF, DOCX or UTF-8 .txt file, or paste the CV text.", 415)


async def llamaparse(data: bytes, filename: str, ctx, tier: str, transport=None, poll_seconds: float = 2.0, max_polls: int = 30) -> str:
    """Parse with LlamaParse v2 (upload → parse job → poll with expand=markdown)."""
    key = ctx.settings.llama_cloud_api_key.get_secret_value()
    if not key or not tier:
        raise AppError("CV_UNREADABLE", UNREADABLE_MESSAGE + " (LlamaParse fallback is not configured.)", 422)
    try:
        reservation = ctx.budget.reserve("llamaparse", "requests", 1)  # fails closed without a configured allowance
    except AppError as exc:
        raise AppError("CV_UNREADABLE", UNREADABLE_MESSAGE + f" (LlamaParse fallback not permitted: {exc.code}.)", 422)
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    error = None
    try:
        async with httpx.AsyncClient(timeout=60, transport=transport) as client:
            upload = await client.post(LLAMA_BASE + "/api/v1/beta/files", headers=headers, data={"purpose": "parse"}, files={"file": (filename or "cv", data)})
            upload.raise_for_status()
            job = await client.post(LLAMA_BASE + "/api/v2/parse", headers=headers, json={"file_id": upload.json()["id"], "tier": tier, "version": "latest"})
            job.raise_for_status()
            job_id = job.json()["id"]
            for _ in range(max_polls):
                result = await client.get(f"{LLAMA_BASE}/api/v2/parse/{job_id}", headers=headers, params={"expand": "markdown"})
                result.raise_for_status()
                body = result.json()
                status = (body.get("job") or {}).get("status")
                if status == "COMPLETED":
                    pages = ((body.get("markdown") or {}).get("pages")) or []
                    return "\n\n".join(p.get("markdown", "") for p in pages)
                if status in {"FAILED", "CANCELLED"}:
                    error = "LLAMAPARSE_" + status
                    break
                await asyncio.sleep(poll_seconds)
            else:
                error = "LLAMAPARSE_TIMEOUT"
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        error = "LLAMAPARSE_ERROR:" + type(exc).__name__
    finally:
        # Provider requests stay charged even on failure (shared budget policy).
        ctx.budget.reconcile(reservation, 1, {"error": error})
    raise AppError("CV_UNREADABLE", UNREADABLE_MESSAGE + " (LlamaParse fallback failed.)", 422, retryable=True)


async def parse(file_bytes: bytes, filename: str, ctx, max_pages: int, llamaparse_tier: str = "", transport=None) -> str:
    if not file_bytes:
        raise AppError("CV_UNREADABLE", UNREADABLE_MESSAGE, 422)
    if len(file_bytes) > ctx.settings.max_cv_bytes:
        raise AppError("CV_TOO_LARGE", "CV exceeds MAX_CV_BYTES", 413)
    digest = hashlib.sha256(file_bytes).hexdigest()
    if digest in _CACHE:
        _CACHE.move_to_end(digest)
        return _CACHE[digest]
    try:
        text = _clean(extract_local(file_bytes, filename, max_pages))
        if not usable(text):
            raise Unreadable("too little text")
    except Unreadable:
        text = _clean(await llamaparse(file_bytes, filename, ctx, llamaparse_tier, transport))
        if not usable(text):
            raise AppError("CV_UNREADABLE", UNREADABLE_MESSAGE, 422)
    _CACHE[digest] = text
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return text
