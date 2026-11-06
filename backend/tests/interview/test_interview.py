import asyncio
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock
import pytest
from app.agents.interview import service, voice
from app.errors import AppError
from app.repository import Repository
from app.db import make_engine, records
from sqlalchemy import select


def setup_session(client, contracts, mode="recruitment", channel="text"):
    ctx = client.app.state.ctx
    case = contracts["case"].model_copy(update={"mode": mode})
    questions = [contracts["question"].model_copy(update={"question_id": f"q{i}", "question": f"Explain integration topic {i}"}) for i in range(5)]
    plan = contracts["plan"].model_copy(update={"questions": questions})
    ctx.repository.save_case(case)
    ctx.repository.save_plan(plan)
    session = asyncio.run(service.create_session(case, plan, channel, ctx))
    token = session["candidate_url"].split("#token=")[1]
    return session["session_id"], {"Authorization": "Bearer " + token}, plan


def post(client, id, auth, action, body=None):
    return client.post(f"/api/interviews/{id}/{action}", headers=auth, json=body or {})


def test_five_question_text_completion_and_retry(client, contracts):
    id, auth, plan = setup_session(client, contracts)
    result = post(client, id, auth, "text-answer", {"turn_id":"x", "request_id":"x", "text":"Answer"})
    assert result.status_code == 409
    state = post(client, id, auth, "consent", {"confirmed":True}).json()
    for i in range(5):
        answer = {"turn_id":state["current_turn_id"], "request_id":f"r{i}", "text":f"Synthetic answer {i}"}
        response = post(client, id, auth, "text-answer", answer)
        assert response.status_code == 200, response.text
        state = response.json()
        assert post(client, id, auth, "text-answer", answer).json() == state
        assert post(client, id, auth, "text-answer", answer | {"text":"changed"}).status_code == 409
    assert state["state"] == "ready_to_complete"
    assert state["warnings"]  # unavailable follow-up must be visible, not fabricated
    done = post(client, id, auth, "complete").json()
    assert done["result"]["status"] == "completed"
    assert len(done["turns"]) == 10
    assert {t["question_id"] for t in done["turns"]} == {q.question_id for q in plan.questions}
    assert post(client, id, auth, "complete").json() == done
    repo = client.app.state.ctx.repository
    assert repo.get("workflow_event", id)["status"] == "pending"
    reopened = Repository(make_engine(str(repo.engine.url)))
    assert reopened.get("interview_session", id)["status"] == "completed"
    reopened.engine.dispose()
    assert "rubric" not in json.dumps(done) and "token_hash" not in done


@pytest.mark.parametrize("mode", ["mock", "recruitment"])
def test_decline_and_early_stop(client, contracts, mode):
    id, auth, _ = setup_session(client, contracts, mode)
    declined = post(client, id, auth, "consent", {"confirmed":False}).json()
    assert declined["state"] == "declined" and declined["result"]["turns"] == []
    assert post(client, id, auth, "consent", {"confirmed":True}).status_code == 409
    assert client.get(f"/api/interviews/{id}").status_code == 401


def test_withdrawal_and_scope(client, contracts):
    id, auth, _ = setup_session(client, contracts)
    post(client, id, auth, "consent", {"confirmed":True})
    result = post(client, id, auth, "stop", {"withdraw_consent":True}).json()
    assert result["result"]["status"] == "declined" and result["turns"] == []
    assert not result["consent_confirmed"]
    assert client.get("/api/interviews/another", headers=auth).status_code == 401
    assert client.get("/api/cases", headers=auth).status_code == 401
    assert client.get(f"/api/interviews/{id}/report", headers=auth).status_code == 403


def test_expiry_server_side_and_frozen_plan(client, contracts):
    id, auth, plan = setup_session(client, contracts)
    post(client, id, auth, "consent", {"confirmed":True})
    ctx = client.app.state.ctx
    ctx.repository.mutate_session(id, lambda s:s.update(deadline=(service.now()-timedelta(seconds=1)).isoformat()))
    service.expire_sessions(ctx)
    assert ctx.repository.get_session(id)["state"] == "incomplete"
    assert post(client, id, auth, "text-answer", {"turn_id":"x", "request_id":"x", "text":"Answer"}).status_code == 409
    with pytest.raises(AppError) as exc: ctx.repository.save_plan(plan.model_copy(update={"plan_version":"changed"}))
    assert exc.value.code == "PLAN_FROZEN"


def test_one_followup_then_core_and_stop(client, contracts):
    id, auth, _ = setup_session(client, contracts)
    llm = client.app.state.ctx.llm
    llm.generate_structured = AsyncMock(return_value=service.FollowUp(question="What did you personally change?"))
    state = post(client, id, auth, "consent", {"confirmed":True}).json()
    for i in range(2):
        state = post(client, id, auth, "text-answer", {"turn_id":state["current_turn_id"], "request_id":str(i), "text":"Synthetic example"}).json()
    assert llm.generate_structured.await_count == 1
    assert state["question_number"] == 2
    stopped = post(client, id, auth, "stop").json()
    assert stopped["state"] == "incomplete" and len(stopped["turns"]) == 5


def test_abandoned_followup_recovers_after_restart(client, contracts):
    id, auth, _ = setup_session(client, contracts)
    post(client, id, auth, "consent", {"confirmed":True})
    repo = client.app.state.ctx.repository
    repo.mutate_session(id, lambda s:s.update(state="processing", processing_until=(service.now()-timedelta(seconds=1)).isoformat()))
    service.expire_sessions(client.app.state.ctx)
    assert repo.get_session(id)["state"] == "active"
    assert repo.get_session(id)["question_index"] == 1


def configure_voice(client):
    ctx = client.app.state.ctx
    from pydantic import SecretStr
    ctx.settings.elevenlabs_api_key = SecretStr("test-key")
    ctx.settings.elevenlabs_webhook_secret = SecretStr("test-webhook")
    ctx.settings.elevenlabs_agent_id = "test-agent"
    ctx.settings.elevenlabs_voice_enabled = True
    ctx.settings.elevenlabs_supervised = True
    ctx.budget.limits = {"elevenlabs":{"minutes":8}}


def mock_provider(monkeypatch):
    async def get(self, path, params=None):
        if "/agents/" in path:
            from pathlib import Path
            return {"platform_settings":{"auth":{"enable_auth":True}, "call_limits":{"agent_concurrency_limit":1,"bursting_enabled":False}},
                    "conversation_config":{"agent":{"language":"en", "first_message":"{{opening_message}}", "prompt":{"prompt":Path(voice.__file__).with_name("interviewer_prompt.md").read_text(encoding="utf-8")}}, "conversation":{"max_duration_seconds":360}}}
        assert params["include_conversation_id"] == "true"
        return {"signed_url":"wss://api.elevenlabs.io/v1/convai/conversation?conversation_id=test-conversation", "conversation_id":"test-conversation"}
    monkeypatch.setattr(voice.ElevenLabsClient, "get", get)


def voice_session(client, contracts, monkeypatch):
    configure_voice(client)
    mock_provider(monkeypatch)
    id, auth, plan = setup_session(client, contracts, channel="elevenlabs")
    post(client, id, auth, "consent", {"confirmed":True})
    response = post(client, id, auth, "voice-token")
    assert response.status_code == 200, response.text
    assert "test-key" not in response.text
    return id, auth, plan


def payload(client, id, plan):
    return {"type":"post_call_transcription", "data":{"conversation_id":"test-conversation", "agent_id":"test-agent", "status":"done",
        "conversation_initiation_client_data":{"dynamic_variables":client.app.state.ctx.repository.get_session(id)["voice_variables"]},
        "metadata":{"call_duration_secs":100}, "analysis":{"data_collection_results":{"consent_given":{"value":True},"consent_withdrawn":{"value":False}}},
        "transcript":[turn for q in plan.questions for turn in [{"role":"agent","message":q.question}, {"role":"user","message":"Synthetic answer"}]]}}


def deliver(client, value, secret="test-webhook", timestamp=None):
    body = json.dumps(value).encode()
    ts = str(timestamp or int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode()+b"."+body, hashlib.sha256).hexdigest()
    return client.post("/api/interviews/webhooks/elevenlabs", content=body, headers={"ElevenLabs-Signature":f"t={ts},v0={sig}"})


def test_voice_webhook_exactly_once_and_no_invented_times(client, contracts, monkeypatch):
    id, auth, plan = voice_session(client, contracts, monkeypatch)
    assert post(client, id, auth, "voice-token").status_code == 409
    assert post(client, id, auth, "complete").status_code == 409
    data = payload(client, id, plan)
    assert deliver(client, data, secret="bad").status_code == 401
    assert deliver(client, data, timestamp=1000).status_code == 401
    assert deliver(client, data).json()["status"] == "recorded"
    assert deliver(client, data).json()["status"] == "duplicate"
    repo = client.app.state.ctx.repository
    result = repo.get_interview("test-case")
    assert result.status == "completed" and len(result.turns) == 10
    assert all(t.start_ms is None and t.end_ms is None for t in result.turns)
    assert repo.usage_records()[0]["amount"] == pytest.approx(100/60)
    with repo.engine.connect() as conn:
        assert len(list(conn.execute(select(records).where(records.c.kind == "workflow_event")))) == 1


def test_voice_binding_unknown_question_and_withdrawal(client, contracts, monkeypatch):
    id, auth, plan = voice_session(client, contracts, monkeypatch)
    data = payload(client, id, plan)
    data["data"]["conversation_initiation_client_data"]["dynamic_variables"]["case_id"] = "another"
    assert deliver(client, data).status_code == 409
    data = payload(client, id, plan)
    data["data"]["transcript"][0]["message"] = "Explain integration..."
    assert deliver(client, data).status_code == 200
    result = client.app.state.ctx.repository.get_interview("test-case")
    assert result.status == "incomplete" and result.turns[0].question_id is None
    post(client, id, auth, "stop", {"withdraw_consent":True})
    assert deliver(client, data).json()["status"] == "duplicate"
    assert client.app.state.ctx.repository.get_interview("test-case").turns == []


def test_voice_missing_config_and_budget_exhaustion(client, contracts, monkeypatch):
    id, auth, _ = setup_session(client, contracts)
    assert post(client, id, auth, "voice-token").status_code == 503
    configure_voice(client)
    repo = client.app.state.ctx.repository
    repo.mutate_session(id, lambda s:s.update(channel="elevenlabs"))
    post(client, id, auth, "consent", {"confirmed":True})
    client.app.state.ctx.budget.limits = {"elevenlabs":{"minutes":0}}
    mock = AsyncMock()
    monkeypatch.setattr(voice.ElevenLabsClient, "get", mock)
    response = post(client, id, auth, "voice-token")
    assert response.status_code == 429
    mock.assert_not_awaited()
    assert post(client, id, auth, "use-text").json()["channel"] == "text"


def test_voice_slot_atomic(client):
    repo = client.app.state.ctx.repository
    def claim(i):
        try: repo.claim_voice_slot(str(i)); return True
        except AppError: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(8))) == 1


def test_unsigned_webhook_and_bad_body(client):
    configure_voice(client)
    assert client.post("/api/interviews/webhooks/elevenlabs", content="{}").status_code == 401
    assert deliver(client, []).status_code == 422


def test_provider_timeout_retains_budget_and_slot_until_review(client, contracts, monkeypatch, auth):
    configure_voice(client)
    mock_provider(monkeypatch)
    get = voice.ElevenLabsClient.get
    async def timeout(self, path, params=None):
        if "get-signed-url" in path: raise AppError("ELEVENLABS_ERROR", "test timeout", 502)
        return await get(self, path, params)
    monkeypatch.setattr(voice.ElevenLabsClient, "get", timeout)
    id, candidate_auth, _ = setup_session(client, contracts, channel="elevenlabs")
    post(client, id, candidate_auth, "consent", {"confirmed":True})
    assert post(client, id, candidate_auth, "voice-token").status_code == 502
    assert client.app.state.ctx.repository.usage_records()[0]["state"] == "reserved"
    assert post(client, id, candidate_auth, "release-voice", {"confirmed_stopped_at_provider":True,"actual_minutes":0}).status_code == 401
    assert post(client, id, auth, "release-voice", {"confirmed_stopped_at_provider":False,"actual_minutes":0}).status_code == 409
    assert post(client, id, auth, "release-voice", {"confirmed_stopped_at_provider":True,"actual_minutes":0}).status_code == 200
    assert client.app.state.ctx.repository.usage_records()[0]["amount"] == 0


def test_provider_missing_consent_retains_no_transcript(client, contracts, monkeypatch):
    id, _, plan = voice_session(client, contracts, monkeypatch)
    data = payload(client, id, plan)
    data["data"]["analysis"] = {}
    assert deliver(client, data).status_code == 200
    result = client.app.state.ctx.repository.get_interview("test-case")
    assert result.status == "incomplete" and not result.consent_confirmed and result.turns == []


def test_reconcile_missed_webhook_and_stale_get_does_not_reset_case(client, contracts, monkeypatch, auth):
    id, candidate_auth, plan = voice_session(client, contracts, monkeypatch)
    data = payload(client, id, plan)
    monkeypatch.setattr(voice.ElevenLabsClient, "get", AsyncMock(return_value=data["data"]))
    assert post(client, id, auth, "reconcile").json()["status"] == "recorded"
    repo = client.app.state.ctx.repository
    repo.set_status("test-case", "assessment_ready")
    assert client.get(f"/api/interviews/{id}", headers=candidate_auth).status_code == 200
    assert repo.get("status", "test-case")["status"] == "assessment_ready"


def test_unsafe_provider_config_is_blocked_and_refunded(client, contracts, monkeypatch):
    configure_voice(client)
    monkeypatch.setattr(voice.ElevenLabsClient, "get", AsyncMock(return_value={"conversation_config":{"conversation":{"max_duration_seconds":10000}}}))
    id, auth, _ = setup_session(client, contracts, channel="elevenlabs")
    post(client, id, auth, "consent", {"confirmed":True})
    assert post(client, id, auth, "voice-token").status_code == 503
    assert client.app.state.ctx.repository.usage_records()[0]["amount"] == 0
