import json
from fastapi import APIRouter, Depends, Request, Header
from pydantic import BaseModel, ConfigDict, Field
from ...auth import candidate, recruiter
from ...errors import AppError
from . import service, voice
from .elevenlabs_webhook import verify_signature

router = APIRouter()


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    turn_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    withdraw_consent: bool = False


class VoiceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    confirmed_stopped_at_provider: bool
    actual_minutes: float = Field(ge=0)


@router.post("/webhooks/elevenlabs")
async def webhook(request: Request, elevenlabs_signature: str | None = Header(default=None)):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2_000_000:
            raise AppError("WEBHOOK_TOO_LARGE", "Webhook exceeds the payload limit", 413)
    ctx = request.app.state.ctx
    verify_signature(bytes(body), elevenlabs_signature, ctx.settings.elevenlabs_webhook_secret.get_secret_value())
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict): raise ValueError()
    except (ValueError, UnicodeDecodeError):
        raise AppError("INVALID_WEBHOOK", "Webhook must be a JSON object", 422)
    return voice.ingest_payload(payload, ctx)


@router.get("/{session_id}")
def get_session(request: Request, session: dict = Depends(candidate)):
    return service.get_session(session["session_id"], request.app.state.ctx)


@router.post("/{session_id}/consent")
def consent(body: ConsentRequest, request: Request, session: dict = Depends(candidate)):
    return service.consent(session["session_id"], body.confirmed, request.app.state.ctx)


@router.post("/{session_id}/text-answer")
async def answer(body: AnswerRequest, request: Request, session: dict = Depends(candidate)):
    return await service.text_answer(session["session_id"], body.turn_id, body.request_id, body.text, request.app.state.ctx)


@router.post("/{session_id}/complete")
def complete(request: Request, session: dict = Depends(candidate)):
    return service.complete(session["session_id"], request.app.state.ctx)


@router.post("/{session_id}/stop")
def stop(body: StopRequest, request: Request, session: dict = Depends(candidate)):
    return service.stop(session["session_id"], body.withdraw_consent, request.app.state.ctx)


@router.post("/{session_id}/use-text")
def use_text(request: Request, session: dict = Depends(candidate)):
    def switch(s):
        service.expire(s)
        if s.get("voice_authorizing") or s.get("voice_issued") or s["state"] not in {"active", "awaiting_consent"}:
            raise AppError("SESSION_STATE", "Text alternative must be selected before voice authorization", 409)
        if s["channel"] == "text": return
        s["channel"] = "text"
        if s["consent_confirmed"]: service.ask_core(s)
    return service.public_session(request.app.state.ctx.repository.mutate_session(session["session_id"], switch))


@router.post("/{session_id}/voice-token")
async def voice_token(request: Request, session: dict = Depends(candidate)):
    return await voice.issue_voice_token(session["session_id"], request.app.state.ctx)


@router.post("/{session_id}/reconcile", dependencies=[Depends(recruiter)])
async def reconcile(session_id: str, request: Request):
    return await voice.reconcile(session_id, request.app.state.ctx)


@router.get("/{session_id}/report")
def get_owned_report(request: Request, session: dict = Depends(candidate)):
    repo = request.app.state.ctx.repository
    case = repo.get_case(session["case_id"])
    if case.mode != "mock" or repo.get("mock_owner", case.case_id)["session_id"] != session["session_id"]:
        raise AppError("FORBIDDEN", "Only the owning mock session may read this report", 403)
    return repo.get_report(case.case_id)


@router.post("/{session_id}/release-voice", dependencies=[Depends(recruiter)])
def release_voice(session_id: str, body: VoiceReviewRequest, request: Request):
    if not body.confirmed_stopped_at_provider:
        raise AppError("VOICE_REVIEW_REQUIRED", "Verify that the conversation stopped and check usage in ElevenLabs before release", 409)
    # Return only usage/release state to recruiters, never private mock transcripts.
    voice.release_after_operator_review(session_id, body.actual_minutes, request.app.state.ctx)
    return {"status":"released", "session_id":session_id}
