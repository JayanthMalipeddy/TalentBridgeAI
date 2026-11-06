"""Session issuance is shared security infrastructure; interview logic belongs to Gana."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from ...contracts import CaseInput, InterviewPlan
from ...context import AgentContext
from ...errors import AppError, unavailable

async def create_session(case: CaseInput, plan: InterviewPlan, channel: str, ctx: AgentContext) -> dict:
    if channel not in {"text", "elevenlabs"}:
        raise AppError("INVALID_CHANNEL", "Choose text or elevenlabs")
    if plan.case_id != case.case_id:
        raise AppError("CASE_MISMATCH", "Plan belongs to another case", 409)
    if channel == "elevenlabs":
        unavailable("ElevenLabs browser interview (Gana)")
    token, session_id = secrets.token_urlsafe(32), str(uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ctx.settings.session_ttl_seconds)).isoformat()
    ctx.repository.save_session({"session_id": session_id, "case_id": case.case_id, "channel": channel, "expires_at": expires_at, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "max_duration_seconds": ctx.settings.session_max_duration_seconds})
    return {"session_id": session_id, "case_id": case.case_id, "channel": channel, "candidate_url": ctx.settings.frontend_origin.split(",")[0].rstrip("/") + "/interview/" + session_id + "#token=" + token, "expires_at": expires_at}
