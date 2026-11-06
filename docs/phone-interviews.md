# Outbound recruitment interviews

The user's confirmed requirement replaces the original no-telephone/no-Twilio restriction. Recruitment now defaults to an outbound ElevenLabs/Twilio call. Mock interviews retain browser voice/text. Existing CaseInput/InterviewResult contracts are unchanged: phone sessions use channel=elevenlabs and internal transport=phone.

## Flow

Upload CV/JD -> retrieved plan -> confirm international phone number -> recruiter authorization and prior permission to contact -> Call candidate now -> AI identifies itself and asks spoken consent -> planned interview -> provider-confirmed transcript -> automatic assessment/report -> explicit recruiter approval.

CV parsing suggests only explicit international numbers; no country code is guessed. Multiple/no matches require entering the intended number. Uploading or refreshing never dials automatically. Recruiter plan preview is separate from the candidate's spoken questions.

## Current account blocker

Read-only GET /v1/convai/phone-numbers returned **zero connected numbers** on 6 November 2026. The local environment has no TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER or ELEVENLABS_PHONE_NUMBER_ID. Gana's ZIP contains outbound code, but no credentials. His working phone connection must be connected/shared in the ElevenLabs workspace used by this app. No number was purchased and no call placed.

## Required provider setup

1. In ElevenLabs Phone Numbers, connect an existing outbound-capable Twilio number. Store its ElevenLabs ID (not the literal phone number) in ELEVENLABS_PHONE_NUMBER_ID. Twilio credentials stay with that provider connection; the app calls ElevenLabs server-side.
2. Use a dedicated phone agent, recorded in ELEVENLABS_PHONE_AGENT_ID, to preserve Gana's existing agent configuration. Install backend/app/agents/interview/phone_prompt.md exactly. First message: {{opening_message}}. Language: English. Keep the existing configured voice/model; no IDs are invented here.
3. Configure maximum duration 360 seconds (at most the app's session duration), concurrency one, bursting disabled, and authentication enabled. Enable the agent's end_call tool. Configure boolean post-call data collection fields consent_given and consent_withdrawn using the candidate's explicit response, never inferred sentiment.
4. Set explicit separate minute caps under PROVIDER_BUDGET_LIMITS for elevenlabs and twilio. Each call reserves the configured hard maximum plus one minute for ringing/rounding. Example bounded allowance: elevenlabs/minutes=9 and twilio/minutes=9 permits one attempt at the default eight-minute hard cap; this does not represent purchased credits or provider balance.
5. Set ELEVENLABS_SUPERVISED=true and ELEVENLABS_PHONE_ENABLED=true once that setup is verified. These flags do not bypass live agent/number preflight validation. No billing/top-up settings are changed.
6. Optional signed post_call_transcription webhook: /api/interviews/webhooks/elevenlabs with ELEVENLABS_WEBHOOK_SECRET. Localhost cannot receive a remote callback. The server also retrieves the known conversation via authenticated provider API every 15 seconds, so localhost can recover the transcript without a tunnel.

ElevenLabs model/voice usage and Twilio telephone charges are separate. ElevenLabs duration reconciles only its own reservation; Twilio's conservative reservation stays charged until operator verification of billed minutes. POST /api/interviews/{session_id}/release-voice accepts confirmed_stopped_at_provider, actual_minutes, and actual_twilio_minutes for explicit reconciliation. No automatic credit-to-money conversion or overage occurs.

## API and authorization

- GET /api/cases/{case_id}/contact: protected owner-only international number suggestions.
- POST /api/cases/{case_id}/phone-call: protected case ownership plus X-Recruiter-Token. Body: phone_number (E.164), contact_permission (true), request_id (stable across retry). Guest cookie alone cannot place a billable call. Credentials are entered at runtime and cleared from UI memory after success.
- GET /api/cases/{case_id}/phone-call: protected status; only final four digits returned.
- Browser/candidate tokens cannot initiate calls or read other cases.

Attempts persist before POSTing to the provider. Same request/destination returns the existing attempt; a different request for that case is rejected. HTTP/network uncertainty retains the reservations and concurrency slot for operator review. No redial occurs. A failed/preparing call is not reported as an answered interview.

The provider-side duration cap is enforced before dialling. Hang-up/withdrawal are spoken requests to the agent; supervise the provider dashboard. The app does not claim a separate server hang-up API. Transcript polling stops after duration plus three minutes and requires operator review/reconciliation. A server restart retains attempts, reservations and stage receipts.

Only confirmed spoken consent permits local transcript retention. Unknown mappings remain unassessed; exact planned question matching is conservative. Completed phone transcripts trigger the existing deduplicated workflow automatically. Incomplete/declined calls do not become successful reports. Model/provider failures remain visible and require explicit stage retry.

## Verification

Automated phone tests use synthetic numbers and mocked provider responses. They verify call-once semantics, request binding, authorization, separate quotas, unknown outcomes, consent and duplicate transcript processing through reporting. No live PSTN validation is claimed until an outbound number is connected and an explicitly consented test recipient is available.

Official API: https://elevenlabs.io/docs/eleven-agents/api-reference/integrations/twilio/outbound-call
Phone inventory: https://elevenlabs.io/docs/eleven-agents/api-reference/phone-numbers/list
