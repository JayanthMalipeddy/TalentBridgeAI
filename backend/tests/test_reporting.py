import pytest
from app.agents.reporting.agent import build_report
from app.errors import AppError


async def test_report_keeps_evidence_and_creates_new_versions(contracts):
    c = contracts
    args = [c[k] for k in ("case", "plan", "interview", "assessment")]
    first = await build_report(*args, None)
    second = await build_report(*args, None)
    assert first.report_version != second.report_version
    assert first.approval_status == "draft"
    assert first.evidence == [c["evidence"]]
    assert first.strengths == []
    assert first.draft_email and "Verification questions" in first.draft_email


async def test_mock_has_no_client_controls(contracts):
    c = contracts
    result = await build_report(c["case"].model_copy(update={"mode": "mock"}), c["plan"], c["interview"], c["assessment"], None)
    assert result.draft_email is None
    assert result.approval_status == "not_applicable"
    assert result.suggested_next_steps[0].startswith("Practise")


@pytest.mark.parametrize("change", ["case", "plan", "declined", "consent", "evidence"])
async def test_rejects_invalid_inputs(contracts, change):
    c = contracts
    if change == "case": c["assessment"].case_id = "other"
    if change == "plan": c["assessment"].plan_version = "other"
    if change == "declined": c["interview"].status = "declined"
    if change == "consent": c["interview"].consent_confirmed = False
    if change == "evidence": c["assessment"].skills[0].evidence[0].excerpt = "Invented answer"
    with pytest.raises(AppError):
        await build_report(c["case"], c["plan"], c["interview"], c["assessment"], None)


async def test_unassessed_is_not_zero(contracts):
    c = contracts
    c["assessment"].skills[0].status = "not_assessed"
    c["assessment"].skills[0].score = None
    report = await build_report(c["case"], c["plan"], c["interview"], c["assessment"], None)
    assert "not assessed" in report.gaps[0]
    assert "0/3" not in report.model_dump_json()


def test_reporting_route_and_version_approval(client, contracts, auth):
    from datetime import datetime, timedelta, timezone
    c = contracts
    repo = client.app.state.ctx.repository
    repo.save_case(c["case"])
    repo.save_plan(c["plan"])
    repo.save_session({"session_id": "s1", "case_id": c["case"].case_id, "channel": "text", "token_hash": "test-only", "state": "completed", "frozen_plan": c["plan"].model_dump(), "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    repo.save_interview(c["interview"])
    repo.save_assessment(c["assessment"])
    url = f"/api/cases/{c['case'].case_id}"
    first = client.post(url + "/report", headers=auth)
    assert first.status_code == 200
    version = first.json()["report_version"]
    assert client.post(url + "/approve", json={"report_version": version}, headers=auth).json()["approval_status"] == "approved"
    cached = client.post(url + "/report", headers=auth)
    assert cached.json()["report_version"] == version
    changed = c["assessment"].model_copy(update={"limitations": ["Additional verification required"]})
    repo.save_assessment(changed)
    newer = client.post(url + "/report", headers=auth)
    assert newer.json()["report_version"] != version
    assert newer.json()["approval_status"] == "draft"
    assert client.post(url + "/approve", json={"report_version": version}, headers=auth).status_code == 409


async def test_partial_interview_report_preserves_limitations(contracts):
    c = contracts
    c['interview'].status = 'incomplete'
    report = await build_report(c['case'], c['plan'], c['interview'], c['assessment'], None)
    assert any('Missing answers are not evidence of failure' in gap for gap in report.gaps)
    assert report.approval_status == 'draft'
