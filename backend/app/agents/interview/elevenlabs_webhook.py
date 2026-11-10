"""Adapted from Gana's ZIP webhook adapter; shared contracts replace local mirrors.

Conservative changes: exact question matching, unknown timestamps stay null,
and consent plus signed provider data are required before storing speech.
"""
import hashlib
import hmac
import time
import re
from ...contracts import InterviewResult, TranscriptTurn
from ...errors import AppError


def verify_signature(raw_body, signature_header, secret, now=None):
    if not secret:
        raise AppError("WEBHOOK_NOT_CONFIGURED", "Set ELEVENLABS_WEBHOOK_SECRET", 503)
    parts = dict(p.strip().split("=", 1) for p in (signature_header or "").split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v0")
    clock = time.time() if now is None else now
    if not ts or not sig or len(ts) > 16 or not ts.isdigit() or abs(clock - int(ts)) > 300:
        raise AppError("INVALID_WEBHOOK_SIGNATURE", "Missing, malformed or expired webhook signature", 401)
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AppError("INVALID_WEBHOOK_SIGNATURE", "Invalid webhook signature", 401)


def flag(data, name):
    value = ((data.get("analysis") or {}).get("data_collection_results") or {}).get(name, {})
    value = value.get("value") if isinstance(value, dict) else None
    if value is True or value == "true": return True
    if value is False or value == "false": return False
    return None


def build_result(data, session):
    consent = (session.get("contact_permission", False) if session.get("transport") == "phone" else session["consent_confirmed"]) and flag(data, "consent_given") is True
    withdrawn = session.get("consent_withdrawn") or flag(data, "consent_withdrawn") is True
    duration = (data.get("metadata") or {}).get("call_duration_secs")
    valid_duration = isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 <= duration < float("inf")
    if not valid_duration: duration = 0
    turns, answered, current_qid = [], set(), None
    # No consent, no transcript; preserve this rule from Gana's implementation.
    if consent and not withdrawn:
        for entry in data.get("transcript") or []:
            text, role = entry.get("message"), entry.get("role")
            if not isinstance(text, str) or not text.strip() or role not in {"agent", "user"}: continue
            if role == "agent":
                # Voice turns often add a greeting or transition around an unchanged question.
                # Require the entire normalized question and a unique match; never fuzzy-match paraphrases.
                normalize = lambda value: " ".join(re.findall(r"\w+", value.casefold()))
                spoken = " " + normalize(text) + " "
                matches = [q["question_id"] for q in session["frozen_plan"]["questions"]
                           if normalize(q["question"]) and " " + normalize(q["question"]) + " " in spoken]
                current_qid = matches[0] if len(matches) == 1 else None
            elif current_qid: answered.add(current_qid)
            start = entry.get("time_in_call_secs")
            valid_start = isinstance(start, (int, float)) and not isinstance(start, bool) and 0 <= start < float("inf")
            turns.append(TranscriptTurn(turn_id=f"{session['session_id']}:t{len(turns)+1:03d}",
                speaker="interviewer" if role == "agent" else "candidate", question_id=current_qid, text=text,
                start_ms=round(start * 1000) if valid_start else None, end_ms=None))
    all_ids = {q["question_id"] for q in session["frozen_plan"]["questions"]}
    status = "incomplete"
    if withdrawn or flag(data, "consent_given") is False: status = "declined"
    elif consent and valid_duration and data.get("status") == "done" and all_ids.issubset(answered): status = "completed"
    return InterviewResult(case_id=session["case_id"], session_id=session["session_id"], channel="elevenlabs",
        consent_confirmed=bool(consent and not withdrawn), status=status, turns=turns,
        duration_seconds=duration, provider_conversation_id=data["conversation_id"])
