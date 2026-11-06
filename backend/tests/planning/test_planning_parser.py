import json
import httpx
import pytest
from app.errors import AppError
from app.settings import Settings
from app.agents.planning import parser
from planning_helpers import FakeBudget, make_ctx, make_docx, make_pdf, read

CV_LINES = [line for line in read("cv-01-strong.txt").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def clear_cache():
    parser._CACHE.clear()
    yield
    parser._CACHE.clear()


def ctx(**settings):
    return make_ctx(Settings(_env_file=None, **settings))


async def test_readable_pdf():
    pytest.importorskip("pypdf")
    text = await parser.parse(make_pdf([CV_LINES[:8], CV_LINES[8:]]), "cv.pdf", ctx(), max_pages=3)
    assert "Integration engineer with 5 years" in text
    assert "dead-letter queue" in text


async def test_readable_docx():
    text = await parser.parse(make_docx(CV_LINES), "cv.docx", ctx(), max_pages=3)
    assert "INSERT ... ON CONFLICT upserts" in text
    assert text.splitlines()[0] == CV_LINES[0]


async def test_empty_pdf_is_rejected_not_blank():
    pytest.importorskip("pypdf")
    with pytest.raises(AppError) as exc:
        await parser.parse(make_pdf([[]]), "scan.pdf", ctx(), max_pages=3)
    assert exc.value.code == "CV_UNREADABLE"
    assert "text-based PDF or DOCX" in exc.value.message


@pytest.mark.parametrize("data,name", [(b"%PDF-1.4 garbage", "broken.pdf"), (b"not a zip", "broken.docx"), (make_docx(["Hello"]), "tiny.docx"), (b"", "empty.docx")])
async def test_unreadable_or_near_empty_documents(data, name):
    if name.endswith(".pdf"):
        pytest.importorskip("pypdf")
    with pytest.raises(AppError) as exc:
        await parser.parse(data, name, ctx(), max_pages=3)
    assert exc.value.code == "CV_UNREADABLE"


async def test_page_and_size_limits_and_type():
    with pytest.raises(AppError) as exc:
        await parser.parse(make_docx(CV_LINES, pages=9), "long.docx", ctx(), max_pages=3)
    assert exc.value.code == "CV_TOO_MANY_PAGES"
    with pytest.raises(AppError) as exc:
        await parser.parse(make_docx(CV_LINES), "cv.docx", ctx(max_cv_bytes=100), max_pages=3)
    assert exc.value.code == "CV_TOO_LARGE"
    with pytest.raises(AppError) as exc:
        await parser.parse(b"\x89PNG....", "photo.png", ctx(), max_pages=3)
    assert exc.value.code == "UNSUPPORTED_CV_TYPE"


async def test_pdf_page_limit():
    pytest.importorskip("pypdf")
    with pytest.raises(AppError) as exc:
        await parser.parse(make_pdf([CV_LINES[:3]] * 4), "long.pdf", ctx(), max_pages=3)
    assert exc.value.code == "CV_TOO_MANY_PAGES"


async def test_cache_by_content_hash():
    data = make_docx(CV_LINES)
    first = await parser.parse(data, "cv.docx", ctx(), max_pages=3)
    assert len(parser._CACHE) == 1
    assert await parser.parse(data, "renamed.docx", ctx(), max_pages=3) == first
    assert len(parser._CACHE) == 1


async def test_llamaparse_not_configured_asks_for_text_cv():
    with pytest.raises(AppError) as exc:
        await parser.parse(make_docx(["x"]), "tiny.docx", ctx(llama_cloud_api_key="test"), max_pages=3, llamaparse_tier="")
    assert exc.value.code == "CV_UNREADABLE" and "not configured" in exc.value.message


async def test_llamaparse_requires_budget_allowance():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    with pytest.raises(AppError) as exc:
        await parser.parse(make_docx(["x"]), "tiny.docx", ctx(llama_cloud_api_key="test"), max_pages=3, llamaparse_tier="agentic", transport=transport)
    assert exc.value.code == "CV_UNREADABLE" and "QUOTA_UNKNOWN" in exc.value.message
    assert calls == []


async def test_llamaparse_fallback_used_within_allowance():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/beta/files"):
            return httpx.Response(200, json={"id": "file-1"})
        if request.method == "POST":
            assert json.loads(request.content)["tier"] == "agentic"
            return httpx.Response(200, json={"id": "job-1", "status": "PENDING"})
        return httpx.Response(200, json={"job": {"status": "COMPLETED"}, "markdown": {"pages": [{"markdown": "\n".join(CV_LINES)}]}})

    budget = FakeBudget({"llamaparse": {"requests": 1}})
    context = make_ctx(Settings(_env_file=None, llama_cloud_api_key="test"), budget=budget)
    text = await parser.parse(make_docx(["x"]), "scan.docx", context, max_pages=3, llamaparse_tier="agentic", transport=httpx.MockTransport(handler))
    assert "Integration engineer with 5 years" in text
    assert seen == [("POST", "/api/v1/beta/files"), ("POST", "/api/v2/parse"), ("GET", "/api/v2/parse/job-1")]
    assert len(budget.reserved) == 1 and len(budget.reconciled) == 1


async def test_case_upload_uses_parse_cv(client, auth):
    response = client.post("/api/cases", headers=auth, data={"job_description": read("jd-integration-engineer.txt"), "mode": "mock", "role": "Integration Engineer"},
                           files={"cv_file": ("cv.docx", make_docx(CV_LINES), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert response.status_code == 201
    assert "Bluefin Payments" in response.json()["cv_text"]
    unreadable = client.post("/api/cases", headers=auth, data={"job_description": "JD", "mode": "mock", "role": "Integration Engineer"},
                             files={"cv_file": ("cv.docx", make_docx(["x"]), "application/octet-stream")})
    assert unreadable.status_code == 422
    assert unreadable.json()["error"]["code"] == "CV_UNREADABLE"
