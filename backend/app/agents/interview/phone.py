"""Recruiter-triggered ElevenLabs/Twilio calls, adapted from Gana's dial-once flow."""
import hashlib
import re
import secrets
from urllib.parse import quote
from datetime import timedelta, datetime
from uuid import uuid4
import httpx
from ...errors import AppError
from .service import now
from .voice import ElevenLabsClient, dynamic_variables, validate_agent, reconcile


def capability(settings):
    missing = []
    for name in ('elevenlabs_phone_number_id', 'elevenlabs_phone_agent_id'):
        if not getattr(settings, name): missing.append(name.upper())
    if not settings.elevenlabs_api_key.get_secret_value(): missing.append('ELEVENLABS_API_KEY')
    if not settings.elevenlabs_supervised: missing.append('ELEVENLABS_SUPERVISED')
    if 'minutes' not in settings.provider_budget_limits.get('elevenlabs', {}): missing.append('ElevenLabs minutes budget')
    if 'minutes' not in settings.provider_budget_limits.get('twilio', {}): missing.append('Twilio minutes budget')
    if not settings.elevenlabs_phone_enabled: missing.append('ELEVENLABS_PHONE_ENABLED')
    return {'available': not missing, 'missing': missing, 'transport': 'elevenlabs_twilio',
            'reason': 'Connect an outbound Twilio number in ElevenLabs; configure a dedicated phone agent and explicit minute limits.'}


def contact_numbers(text):
    # Suggest only explicit international numbers; never guess country codes.
    return list(dict.fromkeys(re.sub(r'[^+0-9]', '', m) for m in re.findall(r'(?<!\w)\+[1-9][0-9 ()-]{7,22}[0-9]', text)
                              if re.fullmatch(r'\+[1-9]\d{7,14}', re.sub(r'[^+0-9]', '', m))))


def public_call(s, ctx):
    return {'session_id': s['session_id'], 'case_id': s['case_id'], 'state': s.get('call_state', 'unknown'),
            'phone_last_four': s.get('phone_last_four'), 'provider_final': bool(s.get('provider_final')),
            'interview_status': (s.get('result') or {}).get('status'),
            'provider_status': s.get('provider_status'), 'processing_paused': bool(s.get('processing_paused')),
            'transcript_available': bool(s.get('provider_final') and (s.get('result') or {}).get('turns')),
            'case_status': ctx.repository.get('status', s['case_id']),
            'message': s.get('call_message', 'Waiting for provider-confirmed transcript.')}


async def start_call(case_id, number, permission, request_id, ctx):
    if not permission: raise AppError('CONTACT_PERMISSION_REQUIRED', 'Confirm that the candidate agreed to receive this interview call', 422)
    if not re.fullmatch(r'\+[1-9]\d{7,14}', number):
        raise AppError('INVALID_PHONE', 'Confirm an international number, for example + followed by country code and number, with no spaces', 422)
    case = ctx.repository.get_case(case_id)
    if case.mode != 'recruitment': raise AppError('PHONE_MODE', 'Outbound calls are for recruitment; mock interviews use browser voice', 409)
    fingerprint = hashlib.sha256(number.encode()).hexdigest()
    for s in ctx.repository.list_sessions():
        if s['case_id'] == case_id:
            if s.get('call_request_id') == request_id and s.get('phone_hash') == fingerprint:
                return public_call(s, ctx)
            raise AppError('SESSION_EXISTS', 'This case already has an interview attempt; it will not be dialled twice', 409)
    info = capability(ctx.settings)
    if not info['available']: raise AppError('PHONE_NOT_CONFIGURED', 'Required: ' + ', '.join(info['missing']), 503)
    for provider in ('elevenlabs', 'twilio'):
        if set(ctx.budget.limits.get(provider, {})) - {'minutes'}:
            raise AppError('QUOTA_UNSUPPORTED', 'Phone adapter requires separate minute limits for ElevenLabs and Twilio', 503)
    plan = ctx.repository.get_plan(case_id)
    if not plan.questions: raise AppError('INVALID_PLAN', 'Generate the interview plan first', 409)
    client = ElevenLabsClient(ctx.settings)
    agent = ctx.settings.elevenlabs_phone_agent_id
    numbers = await client.get('/v1/convai/phone-numbers')
    if not any(n.get('phone_number_id') == ctx.settings.elevenlabs_phone_number_id and n.get('provider') == 'twilio' for n in numbers):
        raise AppError('PHONE_NUMBER_UNAVAILABLE', 'Configured outbound Twilio number is not connected to this ElevenLabs account', 503)
    sid = str(uuid4())
    duration = min(ctx.settings.session_duration_seconds, ctx.settings.session_max_duration_seconds)
    s = dict(session_id=sid, case_id=case_id, channel='elevenlabs', mode=case.mode, transport='phone',
             expires_at=(now()+timedelta(seconds=ctx.settings.session_ttl_seconds)).isoformat(),
             token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(), frozen_plan=plan.model_dump(),
             max_duration_seconds=duration, state='awaiting_consent', consent_confirmed=False,
             contact_permission=True, turns=[], question_index=0, requests={}, warnings=list(plan.warnings),
             result=None, role=case.role, call_request_id=request_id, phone_hash=fingerprint,
             phone_last_four=number[-4:], call_state='preparing', voice_agent_id=agent)
    config = await client.get('/v1/convai/agents/' + quote(agent, safe=''))
    validate_agent(config, s, 'phone_prompt.md')
    collection = config.get('platform_settings', {}).get('data_collection', {})
    if not all(k in collection for k in ('consent_given', 'consent_withdrawn')):
        raise AppError('VOICE_AGENT_CONFIG', 'Configure boolean consent_given and consent_withdrawn data collection on the phone agent', 503)
    reservations, slot, persisted, sent = [], False, False, False
    try:
        ctx.repository.claim_voice_slot(sid); slot = True
        for provider in ('elevenlabs', 'twilio'):
            # Reserve the hard cap plus one minute for ringing/rounding.
            reservations.append(ctx.budget.reserve(provider, 'minutes', ctx.settings.session_max_duration_seconds/60 + 1))
        s.update(voice_reservation=reservations[0], phone_reservation=reservations[1])
        variables = dynamic_variables(s)
        variables['opening_message'] = "Hello, I am TalentBridge's AI interview assistant calling for your scheduled interview. This call will be transcribed for recruiter review. Do you consent to continue?"
        s.update(voice_variables=variables, call_state='dialling', voice_issued=True, started_at=now().isoformat(),
                 deadline=(now()+timedelta(seconds=duration+60)).isoformat(), call_started_at=now().isoformat())
        # Persist before sending. An uncertain outcome must never trigger an automatic redial.
        ctx.repository.save_session(s); persisted = True
        ctx.repository.set_status(case_id, 'interview_call_dialling')
        sent = True
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post('https://api.elevenlabs.io/v1/convai/twilio/outbound-call',
                    headers={'xi-api-key':ctx.settings.elevenlabs_api_key.get_secret_value()},
                    json={'agent_id':agent, 'agent_phone_number_id':ctx.settings.elevenlabs_phone_number_id,
                          'to_number':number, 'call_recording_enabled':False,
                          'conversation_initiation_client_data':{'dynamic_variables':variables},
                          'telephony_call_config':{'ringing_timeout_secs':45}})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError):
            ctx.repository.mutate_session(sid, lambda x:x.update(call_state='dial_unknown', call_message='Provider outcome uncertain. Check ElevenLabs before any new call; no automatic redial.'))
            ctx.repository.set_status(case_id, 'call_needs_review', {'code':'DIAL_UNKNOWN','message':'Verify provider outcome'})
            return public_call(ctx.repository.get_session(sid), ctx)
        if data.get('success') is not True or not data.get('conversation_id'):
            ctx.repository.mutate_session(sid, lambda x:x.update(call_state='dial_unknown', call_message='Provider did not confirm an identifiable conversation. Operator review required.'))
        else:
            ctx.repository.mutate_session(sid, lambda x:x.update(conversation_id=data['conversation_id'], call_state='connecting'))
            ctx.repository.set_status(case_id, 'interview_call_connecting')
        return public_call(ctx.repository.get_session(sid), ctx)
    except Exception:
        if not sent:
            for rid in reservations: ctx.budget.reconcile(rid, 0)
            if slot: ctx.repository.release_voice_slot(sid)
            if persisted: ctx.repository.mutate_session(sid, lambda x:x.update(call_state='failed'))
        raise


async def refresh_calls(ctx):
    for s in ctx.repository.list_sessions():
        if s.get('transport') != 'phone' or s.get('provider_final') or not s.get('conversation_id'): continue
        if (now()-datetime.fromisoformat(s['call_started_at'])).total_seconds() > s['max_duration_seconds'] + 180:
            if s.get('call_state') != 'needs_review':
                ctx.repository.mutate_session(s['session_id'], lambda x:x.update(call_state='needs_review',call_message='Transcript confirmation timed out. Reconcile the call in ElevenLabs; no automatic redial.'))
            continue
        try:
            await reconcile(s['session_id'], ctx)
        except AppError as exc:
            if exc.code != 'TRANSCRIPT_PENDING':
                ctx.repository.mutate_session(s['session_id'], lambda x:x.update(call_message='Transcript retrieval pending; provider returned '+exc.code))
