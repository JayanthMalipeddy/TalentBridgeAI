import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import pytest
from pydantic import ValidationError
from app.contracts import Question, SkillAssessment, Assessment, TranscriptTurn
from app.errors import AppError
from app.repository import Repository
from app.db import make_engine
from app.services.budget import BudgetService
from app.agents.interview.service import create_session


def test_contract_roundtrips(contracts):
    for value in contracts.values():
        assert type(value).model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("name,patch", [("question", {"rubric": {"0": "none"}}), ("skill", {"score": 4}), ("assessment", {"coverage": 1.1}), ("turn", {"end_ms": -1}), ("case", {"schema_version": "2.0"}), ("case", {"api_key": "secret"})])
def test_invalid_contracts(contracts, name, patch):
    value = contracts[name]
    with pytest.raises(ValidationError):
        type(value).model_validate(value.model_dump() | patch)


def seed(client, contracts, mode="recruitment"):
    repo = client.app.state.ctx.repository
    case = contracts["case"].model_copy(update={"mode": mode})
    repo.save_case(case)
    repo.save_plan(contracts["plan"])
    return repo, case


def test_persistence_and_approval(client, contracts):
    repo, case = seed(client, contracts)
    repo.save_session({"session_id": "s1", "case_id": case.case_id, "channel": "text", "token_hash": "unused", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    repo.save_interview(contracts["interview"])
    repo.save_assessment(contracts["assessment"])
    repo.save_report(contracts["report"])
    assert repo.approve_report(case.case_id, "r1").approval_status == "approved"
    repo.save_report(contracts["report"].model_copy(update={"report_version": "r2"}))
    assert repo.get_report(case.case_id).approval_status == "draft"
    assert repo.get("approval", case.case_id)["report_version"] is None
    with pytest.raises(AppError): repo.approve_report(case.case_id, "r1")
    with pytest.raises(AppError): repo.save_report(contracts["report"])
    reopened = Repository(make_engine(str(repo.engine.url)))
    assert reopened.get_case(case.case_id) == case
    assert reopened.get_plan(case.case_id) == contracts["plan"]
    assert reopened.get_interview(case.case_id) == contracts["interview"]
    assert reopened.get_assessment(case.case_id) == contracts["assessment"]
    assert reopened.get_report(case.case_id).report_version == "r2"
    reopened.engine.dispose()


def test_api_health_auth_and_failures(client, auth):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/usage").status_code == 401
    payload = {"mode": "recruitment", "role": "Engineer", "cv_text": "Synthetic CV", "job_description": "JD"}
    response = client.post("/api/cases", data=payload, headers=auth)
    assert response.status_code == 201
    id = response.json()["case_id"]
    for stage in ["plan", "assess", "report"]:
        response = client.post(f"/api/cases/{id}/{stage}", headers=auth)
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
    assert client.get(f"/api/cases/{id}", headers=auth).json()["status"] == "failed"
    assert "cv_text" not in client.get("/api/cases", headers=auth).json()[0]
    invalid = client.post("/api/cases", data={}, headers=auth)
    assert set(invalid.json()) == {"error"}
    assert client.get("/openapi.json").status_code == 200


def test_candidate_scope_expiration_and_mock_owner(client, contracts, auth):
    repo, case = seed(client, contracts, "mock")
    session = asyncio.run(create_session(case, contracts["plan"], "text", client.app.state.ctx))
    token = session["candidate_url"].split("#token=")[1]
    candidate_auth = {"Authorization": "Bearer " + token}
    id = session["session_id"]
    assert "token_hash" not in client.get(f"/api/interviews/{id}", headers=candidate_auth).json()
    assert client.get("/api/cases", headers=candidate_auth).status_code == 401
    assert client.get(f"/api/interviews/other/report", headers=candidate_auth).status_code == 401
    repo.save_report(contracts["report"].model_copy(update={"mode": "mock"}))
    assert client.get(f"/api/cases/{case.case_id}/report", headers=auth).status_code == 403
    assert client.get(f"/api/interviews/{id}/report", headers=candidate_auth).status_code == 200
    assert client.post(f"/api/cases/{case.case_id}/approve", headers=auth, json={"report_version": "r1"}).status_code == 409
    with pytest.raises(AppError): asyncio.run(create_session(case, contracts["plan"], "text", client.app.state.ctx))
    expired = repo.get_session(id) | {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    with repo.transaction() as conn: repo._put(conn, "session", id, expired)
    assert client.get(f"/api/interviews/{id}/report", headers=candidate_auth).status_code == 401


def test_budget_atomic_reservation(client):
    service = BudgetService(client.app.state.ctx.repository, {"groq": {"requests": 3}})
    def attempt(_):
        try: return service.reserve("groq", "requests", 1)
        except AppError: return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = [id for id in pool.map(attempt, range(10)) if id]
    assert len(ids) == 3
    service.reconcile(ids[0], 0)
    assert service.reserve("groq", "requests", 1)
    with pytest.raises(AppError): service.reconcile(ids[0], 0)
    with pytest.raises(AppError) as exc: service.reserve("groq", "money", 1)
    assert exc.value.code == "QUOTA_UNKNOWN"


def test_cors(client):
    response = client.options("/api/cases", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers
    response = client.options("/api/cases", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
