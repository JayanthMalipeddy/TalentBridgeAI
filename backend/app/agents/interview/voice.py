"""ElevenLabs browser authorization and shared transcript reconciliation."""
import json
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse, parse_qs
import httpx
from ...errors import AppError
from .service import voice_available, now, expire, public_session
from .elevenlabs_webhook import build_result


class ElevenLabsClient:
    def __init__(self, settings): self.settings = settings

    async def get(self, path, params=None):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get("https://api.elevenlabs.io" + path, params=params,
                    headers={"xi-api-key": self.settings.elevenlabs_api_key.get_secret_value()})
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise AppError("ELEVENLABS_ERROR", "ElevenLabs request failed; check agent access and provider status", 502, True)


def validate_agent(config, session, prompt_file="interviewer_prompt.md"):
    platform = config.get("platform_settings", {})
    conversation = config.get("conversation_config", {})
    duration = conversation.get("conversation", {}).get("max_duration_seconds")
    if not isinstance(duration, (int, float)) or not 0 < duration <= session["max_duration_seconds"]:
        raise AppError("VOICE_AGENT_CONFIG", "Set the agent's provider-side maximum duration to the session duration (default 360 seconds)", 503)
    call_limits = platform.get("call_limits", {})
    if platform.get("auth", {}).get("enable_auth") is not True or call_limits.get("agent_concurrency_limit") != 1 or call_limits.get("bursting_enabled") is not False:
        raise AppError("VOICE_AGENT_CONFIG", "Enable agent authentication, set concurrency to one and disable bursting in ElevenLabs", 503)
    if conversation.get("agent", {}).get("language") != "en":
        raise AppError("VOICE_AGENT_CONFIG", "Configure the agent language as English", 503)
    if conversation.get("agent", {}).get("first_message") != "{{opening_message}}":
        raise AppError("VOICE_AGENT_CONFIG", "Set the agent first message to {{opening_message}} for the consent disclosure", 503)
    expected_prompt = Path(__file__).with_name(prompt_file).read_text(encoding="utf-8").strip()
    if conversation.get("agent", {}).get("prompt", {}).get("prompt", "").strip() != expected_prompt:
        raise AppError("VOICE_AGENT_CONFIG", "Install the versioned interview prompt on the ElevenLabs agent", 503)


def dynamic_variables(s):
    return {"session_id": s["session_id"], "case_id": s["case_id"], "mode": s["mode"], "role_title": s["role"],
        "time_budget_minutes": str(s["max_duration_seconds"] / 60), "max_follow_ups": "1",
        "interview_questions": "\n".join(q["question"] for q in s["frozen_plan"]["questions"]),
        "mode_instructions": "Do not coach or reveal answers during the interview. Feedback is provided separately after completion.",
        "closing_instructions": "Thank the candidate and say their interview is complete; the team will review the evidence.",
        "opening_message": "I am TalentBridge's AI interview assistant. This browser interview will be transcribed. Do you consent to continue?"}


async def issue_voice_token(id, ctx):
    if not voice_available(ctx.settings):
        raise AppError("VOICE_UNAVAILABLE", "Configure ElevenLabs and supervised browser mode, or choose a text session", 503)
    limits = ctx.budget.limits.get("elevenlabs", {})
    if set(limits) - {"minutes"}:
        raise AppError("QUOTA_UNSUPPORTED", "This voice adapter enforces minutes only; unsupported credit/money limits block issuance", 503)
    def prepare(s):
        expire(s)
        if s["channel"] != "elevenlabs" or s["state"] != "active" or not s["consent_confirmed"]:
            raise AppError("CONSENT_REQUIRED", "An active voice session with consent is required", 409)
        if s.get("voice_issued") or s.get("voice_authorizing"):
            raise AppError("VOICE_ALREADY_ISSUED", "Voice authorization is issued once; reconcile the session before retrying", 409)
        s["voice_authorizing"] = True
    session = ctx.repository.mutate_session(id, prepare)
    reservation, slot, sent = None, False, False
    try:
        ctx.repository.claim_voice_slot(id)
        slot = True
        reservation = ctx.budget.reserve("elevenlabs", "minutes", ctx.settings.session_max_duration_seconds / 60)
        ctx.repository.mutate_session(id, lambda s: s.update(voice_reservation=reservation))
        client = ElevenLabsClient(ctx.settings)
        config = await client.get("/v1/convai/agents/" + quote(ctx.settings.elevenlabs_agent_id, safe=""))
        validate_agent(config, session)
        sent = True
        data = await client.get("/v1/convai/conversation/get-signed-url", {"agent_id": ctx.settings.elevenlabs_agent_id, "include_conversation_id": "true"})
        signed = data.get("signed_url", "")
        parsed = urlparse(signed)
        conversation_id = data.get("conversation_id") or parse_qs(parsed.query).get("conversation_id", [None])[0]
        if parsed.scheme != "wss" or parsed.hostname != "api.elevenlabs.io" or not isinstance(conversation_id, str) or not conversation_id:
            raise AppError("VOICE_AUTH_INVALID", "Provider did not return a single-use URL with a conversation ID; voice remains blocked pending operator review", 502)
        def store(s):
            expire(s)
            s.update(conversation_id=conversation_id, voice_issued=True, voice_authorizing=False, voice_agent_id=ctx.settings.elevenlabs_agent_id,
                     voice_issued_at=now().isoformat(), voice_variables=dynamic_variables(s))
        saved = ctx.repository.mutate_session(id, store)
        if saved["state"] != "active" or not saved["consent_confirmed"]:
            raise AppError("SESSION_STATE", "Session stopped while voice was being authorized; authorization was not delivered", 409)
        return {"signed_url": signed, "conversation_id": conversation_id, "dynamic_variables": saved["voice_variables"], "deadline": saved["deadline"]}
    except Exception:
        if not sent:
            if reservation: ctx.budget.reconcile(reservation, 0, {"status": "not_issued"})
            if slot: ctx.repository.release_voice_slot(id)
            ctx.repository.mutate_session(id, lambda s: s.update(voice_authorizing=False, voice_reservation=None))
        # Once a request might have issued authorization, retain budget/slot for review.
        raise


def ingest_payload(payload, ctx):
    if payload.get("type") != "post_call_transcription":
        return {"status": "ignored", "reason": "Only browser transcript events are supported"}
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("conversation_id"), str):
        raise AppError("INVALID_WEBHOOK", "Missing conversation data", 422)
    matches = [s for s in ctx.repository.list_sessions() if s.get("conversation_id") == data["conversation_id"]]
    if len(matches) != 1:
        raise AppError("UNKNOWN_CONVERSATION", "Conversation was not authorized by this application", 409)
    session = matches[0]
    if data.get("status") not in {"done", "failed"}:
        raise AppError("TRANSCRIPT_PENDING", "Provider conversation is not final", 409, True)
    initiation = data.get("conversation_initiation_client_data") or {}
    if not isinstance(initiation, dict) or not isinstance(initiation.get("dynamic_variables", {}), dict):
        raise AppError("INVALID_WEBHOOK", "Invalid conversation binding fields", 422)
    variables = initiation.get("dynamic_variables") or {}
    if data.get("agent_id") != session.get("voice_agent_id") or any(variables.get(k) != v for k, v in session["voice_variables"].items()):
        raise AppError("VOICE_BINDING_MISMATCH", "Provider conversation does not match the frozen interview configuration", 409)
    duplicate = False
    def record(s):
        nonlocal duplicate
        if s.get("provider_final"):
            duplicate = True
            return
        try:
            result = build_result(data, s)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AppError("INVALID_WEBHOOK", "Transcript does not match the expected provider schema", 422)
        s.update(call_state=result.status, call_message="Provider transcript received. Unmapped answers require review." if result.status == "incomplete" else "Provider transcript received.", provider_status=data["status"], result=result.model_dump(), turns=[t.model_dump() for t in result.turns], state=result.status,
                 consent_confirmed=result.consent_confirmed, provider_final=True, current_turn_id=None)
        s["warnings"].append("Voice question IDs require a unique full-question match after punctuation normalization; uncertain turns remain unassigned.")
        if (data.get("metadata") or {}).get("call_duration_secs") is None:
            s["warnings"].append("Provider duration is unknown; result duration is 0 and reserved minutes are retained.")
    saved = ctx.repository.mutate_session(session["session_id"], record)
    duration = (data.get("metadata") or {}).get("call_duration_secs")
    if saved.get("voice_reservation") and isinstance(duration, (float, int)) and not isinstance(duration, bool) and 0 <= duration < float("inf"):
        try: ctx.budget.reconcile(saved["voice_reservation"], duration / 60, {"session_id": saved["session_id"], "status": "provider_confirmed"})
        except AppError as exc:
            if exc.code != "RESERVATION_CLOSED": raise
    ctx.repository.release_voice_slot(saved["session_id"])
    return {"status": "duplicate" if duplicate else "recorded", "session_id": saved["session_id"]}


async def reconcile(id, ctx):
    session = ctx.repository.get_session(id)
    if not session.get("conversation_id"):
        raise AppError("VOICE_REVIEW_REQUIRED", "No confirmed conversation ID; operator must verify provider usage before releasing the reserved slot", 409)
    if session.get("provider_final"): return {"status": "already_recorded"}
    data = await ElevenLabsClient(ctx.settings).get("/v1/convai/conversations/" + quote(session["conversation_id"], safe=""))
    return ingest_payload({"type": "post_call_transcription", "data": data}, ctx)


def release_after_operator_review(id, actual_minutes, ctx, actual_twilio_minutes=None):
    """Only the recruiter route exposes this after explicit provider-side review."""
    session = ctx.repository.get_session(id)
    if session.get("phone_reservation"):
        if actual_twilio_minutes is None:
            raise AppError("PHONE_USAGE_REQUIRED", "Confirm Twilio billed minutes separately; they are not inferred from ElevenLabs duration", 422)
        try: ctx.budget.reconcile(session["phone_reservation"], actual_twilio_minutes, {"session_id":id, "status":"operator_verified"})
        except AppError as exc:
            if exc.code != "RESERVATION_CLOSED": raise
    if session.get("voice_reservation"):
        try: ctx.budget.reconcile(session["voice_reservation"], actual_minutes, {"session_id":id, "status":"operator_verified"})
        except AppError as exc:
            if exc.code != "RESERVATION_CLOSED": raise
    ctx.repository.release_voice_slot(id)
    def close(s):
        from .service import finish, TERMINAL
        if s["state"] not in TERMINAL: finish(s, "incomplete")
        s["warnings"].append("Voice usage was manually reconciled by the recruiter; no transcript was invented.")
    return public_session(ctx.repository.mutate_session(id, close))
