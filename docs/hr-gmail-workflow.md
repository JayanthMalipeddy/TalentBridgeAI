# HR review and Gmail delivery

Implemented in `backend/app/hr/` and `frontend/src/HRReview.tsx`. This extends the existing FastAPI, SQLite repository, React, voice recovery and shared LLM services. It does not replace the existing 0–3 foundation assessment contract. The HR-reviewed assessment has its own versioned 0–4 rubric and is the only assessment used for the new decision workflow.

## Using the screen

1. Create the interview plan from the CV and JD, then continue to the interview setup. Enter recruiter authorization and choose **Load CV details and prepare rubric**. This makes one bounded structured LLM request, cached against the CV/JD/plan fingerprint. Provider failures remain visible.
2. The model extracts candidate name/email from the CV; values absent from the source are discarded. Confirm/correct these fields. Enter job reference, company/client, optional contact name, client email, recruiter name/contact and threshold. Agency name is optional and is not shown in the UI. Confirm candidate email and CV-sharing authorization before continuing.
3. The original uploaded CV is retained; it is not reconstructed from parsed text. Pasted CVs are retained as TXT. No second upload is needed for newly created cases. Legacy cases without stored original bytes still require the original file.
4. The model-generated rubric covers planned questions with 0?4 anchors and weights. It is labelled `source=llm`, `reviewed=false` rather than falsely attributed to a human. The candidate interview runs against the frozen plan. The final bound transcript triggers assessment automatically.
5. Open **My interviews ? HR review and emails**. Application fields, recipients, attachment and rubric are already populated. The summary defaults to the current evidence-validated assessment rationales; HR may edit it. Reviewer name remains editable. Read the assessment, evidence and exact email previews; no separate rubric approval is required.
6. Click **Approve shortlist and submit** to record the final human approval and queue the client email. Candidate confirmation waits for Gmail acceptance. **Confirm not proceeding** sends candidate-only rejection; **Hold / request reassessment** queues neither. A job-related reason remains required in the UI when overriding the recommendation. Corrections retain the audited version workflow.
7. Refresh delivery history for independent decision/send states. Gmail must be connected and enabled. No score or LLM action sends email without final HR approval.

The existing **Approve report** button approves a report version only. It does not send email or make the new HR decision.

## Assessment and versioning

Each criterion references a question in the frozen plan. The LLM prepares expected principles, acceptable approaches, explicit weight and five anchors before the interview; HR reviews the resulting rubric and evidence at final approval. The shared structured-output model evaluates answer content against these rules, not CV similarity or keyword overlap. CV/transcript instructions are untrusted data. The prompt excludes accent, emotion, demographics and personality from evaluation.

The deterministic calculation is `100 × sum(weight × score) / sum(weight × 4)`, using Decimal arithmetic. Threshold comparison uses the unrounded value; the displayed rounded percentage never changes the recommendation. This is rubric performance, not a probability of job success.

Every score needs exact excerpts from candidate turns, with a matching question ID when known. Invalid citations cause abstention. Missing scores, uncertainty, insufficient transcript quality or incomplete interviews produce **Insufficient evidence — HR review required**, without silently reducing the denominator. This implementation conservatively requires evidence for every configured criterion, including ones marked nonessential. Exact citation validation does not prove semantic correctness; HR reviews it.

Records retain transcript hash/version, assessment version, rubric version, weights, threshold, reviewer, reason and approval snapshot. The single-case prototype assigns application-scoped `candidate:<case_id>` and `job:<case_id>` identifiers; job reference is editable metadata, not a cross-application job database. Existing provider conversation/session/frozen-plan binding and authenticated completion/recovery remain in place.

## Google Cloud and OAuth setup

1. Create/select a Google Cloud project and enable **Gmail API** in APIs & Services.
2. In Google Auth Platform configure Branding, Audience and Data Access. For an external app in Testing, add the exact sender account as a test user. Request `https://www.googleapis.com/auth/gmail.send` plus `openid` and `email` to identify the authenticated sender. No Gmail read, modify or full-mailbox scope is used. Public deployment may require Google's verification; external Testing refresh tokens for these permissions can expire after seven days.
3. Create an OAuth client of type **Web application**. Register the exact redirect URI. For this local Vite proxy use `http://localhost:5173/api/hr/gmail/callback` and open the application at `http://localhost:5173` (do not mix localhost and 127.0.0.1). For deployment use the same-origin public HTTPS URL with `/api/hr/gmail/callback`. The browser-bound state cookie must return to the same host.
4. Set server-only `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REDIRECT_URI`, and `GMAIL_TOKEN_ENCRYPTION_KEY` in the ignored environment file or secret store. Generate the encryption key once with `.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep the key outside source control and preserve it across restarts. Changing/loss of the key requires reconnecting Gmail.
5. Restart the backend using the existing project startup script. Open the HR screen, enter recruiter authorization and select **Connect Gmail**. Confirm the account shown afterward. OAuth uses expiring one-use state, a browser nonce and PKCE. Only encrypted refresh credentials are persisted server-side; access tokens are transient.
6. Keep `EMAIL_SEND_ENABLED=false` during development. Actual delivery requires both `APP_ENV=production` and `EMAIL_SEND_ENABLED=true`, a connected account, a current HR approval and valid recipients/attachment. Production requires HTTPS so the secure OAuth/session cookies work. **Enabling sending also processes already-queued approved messages: review the queue first.** This task did not enable real sending.

Defaults: `EMAIL_DAILY_CAP=10`, `EMAIL_PACING_SECONDS=30`, `EMAIL_MAX_ATTEMPTS=3`, `EMAIL_SEND_LEASE_SECONDS=180`. These are application safety limits, not purchased quota or a promise of provider availability. The cap counts attempts across all applications per UTC day. Gmail account sending restrictions and API quotas still apply; no paid service, top-up or billing change is made. The sender is the authenticated Gmail identity, not an arbitrary From address.

Official references: [OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server), [Gmail sending and MIME attachments](https://developers.google.com/workspace/gmail/api/guides/sending), [Gmail API quotas](https://developers.google.com/workspace/gmail/api/reference/quota), [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration), [Gmail account sending limits](https://support.google.com/mail/answer/22839).

## Durable delivery and recovery

The existing SQLite transaction boundary stores approval snapshots and the outbox together. Unique logical keys combine case, decision version and message purpose. A single-instance worker claims messages atomically and sends outside the transaction. Original CV bytes are attached only to the client email; no transcript, recording, CC or BCC is added. Pasted CV text is retained as an explicitly named TXT attachment.

States are `QUEUED`, `SENDING`, `SEND_ACCEPTED`, `FAILED`, `DELIVERY_UNKNOWN`. Attempt history and Gmail message IDs remain visible. A daily cap or pacing delay leaves the message queued. Authentication/known quota failures require an explicit retry after correction. A failed candidate notification never resends the accepted client submission.

Timeouts, uncertain server responses and abandoned sending leases become `DELIVERY_UNKNOWN`, not automatic retries. HR must inspect the sender's Sent Mail outside this app, record a verified Gmail message ID if sent, or record that it was not sent before retrying. The send-only scope cannot read Sent Mail. A unique logical key reduces duplicates but does not establish exactly-once delivery. Gmail acceptance establishes neither delivery nor a client hiring decision.

Changed recipients, content, attachment, transcript, rubric, threshold or sender connection invalidate pending approvals at send time. In-flight/unknown messages block edits until reconciled. Previously accepted messages cannot be recalled; a fresh decision may intentionally create new communications. Shared recruiter-token identity plus entered reviewer name is a demo audit trail, not independently authenticated employee identity. This prototype supports one Gmail sender and one backend instance.

## Verification and isolated demonstration

Run from the repository: `.\.venv\Scripts\python.exe -m pytest backend/tests/hr -q`.
Run from `frontend`: `npm.cmd run test:e2e -- tests/hr-review.spec.ts tests/visual-design.spec.ts`, then `npm.cmd run build`.

Backend tests create isolated databases and inject mocked Gmail transport. They demonstrate HR approval → accepted client submission with exact CV → candidate confirmation, candidate-only rejection, hold, threshold boundaries, missing/invented evidence, transcript corrections, recipient/CV changes, authentication and quota errors, unknown delivery, restart recovery, concurrency and duplicate approvals. Browser tests exercise real UI code with explicitly fictional API responses and save labelled screenshots. No test sends real emails or acts on existing candidates. There is no production mock-delivery toggle.

Remaining connection work: supply Google OAuth credentials and encryption key, authorize the sender, then deliberately enable production sending only when ready. Live Gmail delivery and live HR assessment on a real candidate were not exercised in this task.

Update verification: 32 isolated HR/backend tests, 8 frontend unit tests and 2 HR browser checks passed; production frontend build passed. Tests used mocked providers only. No live call or email was initiated for this change.

Role selection: New interview now accepts an editable job title. Integration roles retain the existing curated-catalogue path. Other roles use five LLM questions grounded in exact JD/CV excerpts, with an explicit warning that no approved role-specific library was used. No unrelated Integration Engineer skills are substituted. Provisional foundation assessments retain their existing abstention behavior; the HR workflow uses its separately frozen LLM rubric and final human decision.

Role-planning evidence: CV/JD text is split into bounded, numbered sections with original character offsets. The LLM generates original questions and selects section IDs; the backend attaches exact excerpts. Paraphrased question wording is valid. Unknown section IDs and questions without a JD reference are rejected. This avoids relying on model-copied quotations without weakening source validation.
