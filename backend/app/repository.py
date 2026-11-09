import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import select, delete, func
from sqlalchemy.dialects.sqlite import insert
from .db import records, usage
from .contracts import CaseInput, InterviewPlan, InterviewResult, Assessment, Report
from .errors import AppError


class Repository:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _get(self, conn, kind, id):
        value = conn.execute(select(records.c.payload).where(records.c.kind == kind, records.c.id == id)).scalar_one_or_none()
        if value is None:
            raise AppError("NOT_FOUND", f"{kind} not found", 404)
        return json.loads(value)

    def _put(self, conn, kind, id, payload):
        stmt = insert(records).values(kind=kind, id=id, payload=json.dumps(payload))
        conn.execute(stmt.on_conflict_do_update(index_elements=[records.c.kind, records.c.id], set_={"payload": stmt.excluded.payload}))

    def get(self, kind, id):
        with self.engine.connect() as conn:
            return self._get(conn, kind, id)

    def save_case(self, case: CaseInput, workspace_id=None, max_cases=None):
        with self.transaction() as conn:
            if workspace_id is not None and max_cases is not None:
                owners = conn.execute(select(records.c.payload).where(records.c.kind == "case_owner")).scalars()
                if sum(json.loads(raw)["workspace_id"] == workspace_id for raw in owners) >= max_cases:
                    raise AppError("WORKSPACE_LIMIT", "Workspace case allowance exhausted", 429)
            conn.execute(insert(records).values(kind="case", id=case.case_id, payload=case.model_dump_json()))
            self._put(conn, "case_owner", case.case_id, {"workspace_id": workspace_id})
            self._put(conn, "status", case.case_id, {"status": "created", "failure": None})

    def get_case(self, id):
        return CaseInput.model_validate(self.get("case", id))

    def delete_case(self, case_id, workspace_id):
        """Atomically remove local case data and revoke all candidate sessions."""
        with self.transaction() as conn:
            self._get(conn, "case", case_id)
            raw = conn.execute(select(records.c.payload).where(records.c.kind == "case_owner", records.c.id == case_id)).scalar_one_or_none()
            if (json.loads(raw)["workspace_id"] if raw else None) != workspace_id:
                raise AppError("NOT_FOUND", "case not found", 404)
            rows = [(row.kind, row.id, json.loads(row.payload)) for row in conn.execute(select(records))]
            if any(kind == "hr_outbox" and value.get("case_id") == case_id and value.get("state") in {"SENDING", "DELIVERY_UNKNOWN"}
                   or kind == "hr_run" and value.get("case_id") == case_id and value.get("state") == "running" for kind, _, value in rows):
                raise AppError("CASE_BUSY", "Finish or reconcile HR processing and emails before deleting this case", 409)
            sessions = {id: value for kind, id, value in rows if kind == "session" and value.get("case_id") == case_id}
            if any(kind == "stage_run" and id.startswith(case_id + ":") and value.get("status") == "running"
                   for kind, id, value in rows):
                raise AppError("CASE_BUSY", "Wait for processing to finish before deleting this interview.", 409)
            if any(s.get("state") == "processing" or (s.get("voice_issued") and not s.get("provider_final") and s.get("call_state") != "failed") for s in sessions.values()):
                raise AppError("CASE_BUSY", "Finish or reconcile the active interview before deleting it.", 409)
            if any(kind == "voice_slot" and value.get("session_id") in sessions for kind, _, value in rows):
                raise AppError("CASE_BUSY", "Reconcile the reserved voice session before deleting this interview.", 409)
            case_kinds = {"case", "case_owner", "status", "plan", "interview", "assessment", "report", "approval", "mock_owner"}
            for kind, id, value in rows:
                belongs = (kind.startswith("hr_") and value.get("case_id") == case_id
                           or kind in case_kinds and id == case_id
                           or kind in {"stage_run", "report_version"} and id.startswith(case_id + ":")
                           or kind in {"session", "interview_session", "workflow_event"} and (id in sessions or value.get("case_id") == case_id))
                if belongs:
                    conn.execute(delete(records).where(records.c.kind == kind, records.c.id == id))

    def list_cases(self, workspace_id=None):
        with self.engine.connect() as conn:
            rows = conn.execute(select(records.c.payload).where(records.c.kind == "case")).scalars()
            owners = {row.id: json.loads(row.payload)["workspace_id"] for row in conn.execute(select(records).where(records.c.kind == "case_owner"))}
            statuses = {row.id: json.loads(row.payload).get("status", "created") for row in conn.execute(select(records).where(records.c.kind == "status"))}
            return [dict({k: v for k, v in case.items() if k not in {"cv_text", "job_description"}}, status=statuses.get(case["case_id"], "created"))
                    for case in map(json.loads, rows) if owners.get(case["case_id"]) == workspace_id]

    def set_status(self, id, status, failure=None):
        with self.transaction() as conn:
            self._get(conn, "case", id)
            self._put(conn, "status", id, {"status": status, "failure": failure})

    def _save_artifact(self, kind, value):
        with self.transaction() as conn:
            self._save_artifact_in(conn, kind, value)

    def _save_artifact_in(self, conn, kind, value):
        case = self._get(conn, "case", value.case_id)
        if kind == "plan":
            sessions = conn.execute(select(records.c.payload).where(records.c.kind == "session")).scalars()
            for raw in sessions:
                session = json.loads(raw)
                if session["case_id"] == value.case_id and session.get("frozen_plan") != value.model_dump():
                    raise AppError("PLAN_FROZEN", "An interview already uses this plan; create a new case for a revised plan", 409)
        if kind == "assessment":
            plan = self._get(conn, "plan", value.case_id)
            if plan["plan_version"] != value.plan_version:
                raise AppError("VERSION_CONFLICT", "Assessment plan version is stale", 409)
        if kind == "interview":
            session = self._get(conn, "session", value.session_id)
            if session["case_id"] != value.case_id or session["channel"] != value.channel:
                raise AppError("SESSION_MISMATCH", "Interview does not match its session", 409)
        if kind == "report":
            if value.mode != case["mode"]:
                raise AppError("MODE_MISMATCH", "Report mode does not match case", 409)
            # Versions are immutable; approval can only happen through approve_report.
            version_id = value.case_id + ":" + value.report_version
            value = value.model_copy(update={"approval_status": "not_applicable" if value.mode == "mock" else "draft"})
            exists = conn.execute(select(records.c.id).where(records.c.kind == "report_version", records.c.id == version_id)).first()
            if exists:
                raise AppError("VERSION_CONFLICT", "Create a new report version", 409)
            self._put(conn, "report_version", version_id, value.model_dump())
            self._put(conn, "approval", value.case_id, {"report_version": None})
        self._put(conn, kind, value.case_id, value.model_dump())
        self._put(conn, "status", value.case_id, {"status": kind + "_ready", "failure": None})


    def save_plan(self, value: InterviewPlan): self._save_artifact("plan", value)
    def get_plan(self, id): return InterviewPlan.model_validate(self.get("plan", id))
    def save_interview(self, value: InterviewResult): self._save_artifact("interview", value)
    def get_interview(self, id): return InterviewResult.model_validate(self.get("interview", id))
    def save_assessment(self, value: Assessment): self._save_artifact("assessment", value)
    def get_assessment(self, id): return Assessment.model_validate(self.get("assessment", id))
    def save_report(self, value: Report): self._save_artifact("report", value)
    def get_report(self, id): return Report.model_validate(self.get("report", id))

    def approve_report(self, id, version):
        with self.transaction() as conn:
            report = self._get(conn, "report", id)
            if report["mode"] == "mock":
                raise AppError("MOCK_APPROVAL_FORBIDDEN", "Mock reports cannot be approved", 409)
            if report["report_version"] != version:
                raise AppError("VERSION_CONFLICT", "Report version is no longer current", 409)
            report["approval_status"] = "approved"
            self._put(conn, "report", id, report)
            self._put(conn, "approval", id, {"report_version": version})
            return Report.model_validate(report)

    def save_session(self, session):
        with self.transaction() as conn:
            case = self._get(conn, "case", session["case_id"])
            if case["mode"] == "recruitment":
                existing = conn.execute(select(records.c.payload).where(records.c.kind == "session")).scalars()
                if any(json.loads(raw)["case_id"] == case["case_id"] for raw in existing):
                    raise AppError("SESSION_EXISTS", "This case already has an interview; create a new case for another attempt", 409)
            if case["mode"] == "mock":
                existing = conn.execute(select(records.c.id).where(records.c.kind == "mock_owner", records.c.id == case["case_id"])).first()
                if existing:
                    raise AppError("OWNER_EXISTS", "Mock case already has an owning session", 409)
                self._put(conn, "mock_owner", case["case_id"], {"session_id": session["session_id"]})
            conn.execute(insert(records).values(kind="session", id=session["session_id"], payload=json.dumps(session)))

    def get_session(self, id): return self.get("session", id)

    def mutate_session(self, id, mutation):
        """Atomic session updates, transcript snapshots and a durable completion event."""
        with self.transaction() as conn:
            session = self._get(conn, "session", id)
            previous_result = session.get("result")
            mutation(session)
            self._put(conn, "session", id, session)
            if session.get("result") and session["result"] != previous_result:
                result = InterviewResult.model_validate(session["result"])
                if result.case_id != session["case_id"] or result.session_id != id:
                    raise AppError("SESSION_MISMATCH", "Result does not match session", 409)
                self._put(conn, "interview_session", id, result.model_dump())
                self._put(conn, "interview", result.case_id, result.model_dump())
                if not result.consent_confirmed or result.status == "declined":
                    conn.execute(delete(records).where(records.c.id == result.case_id,
                        records.c.kind.in_(["assessment", "report", "approval"])))
                    conn.execute(delete(records).where(records.c.kind == "report_version",
                        records.c.id.startswith(result.case_id + ":")))
                if session.get("state") in {"completed", "incomplete", "declined"}:
                    event = {"case_id": result.case_id, "session_id": id, "plan_version": session["frozen_plan"]["plan_version"], "status": "pending", "event": "interview_completed"}
                    conn.execute(insert(records).values(kind="workflow_event", id=id, payload=json.dumps(event)).on_conflict_do_nothing())
                    self._put(conn, "status", result.case_id, {"status": "interview_" + result.status, "failure": None})
            return session

    def list_sessions(self):
        with self.engine.connect() as conn:
            return [json.loads(raw) for raw in conn.execute(select(records.c.payload).where(records.c.kind == "session")).scalars()]

    def claim_voice_slot(self, session_id):
        with self.transaction() as conn:
            raw = conn.execute(select(records.c.payload).where(records.c.kind == "voice_slot", records.c.id == "singleton")).scalar_one_or_none()
            if raw and json.loads(raw).get("session_id"):
                raise AppError("VOICE_BUSY", "A voice session is reserved; reconcile it before starting another", 409)
            self._put(conn, "voice_slot", "singleton", {"session_id": session_id})

    def release_voice_slot(self, session_id):
        with self.transaction() as conn:
            raw = conn.execute(select(records.c.payload).where(records.c.kind == "voice_slot", records.c.id == "singleton")).scalar_one_or_none()
            if raw and json.loads(raw).get("session_id") == session_id:
                self._put(conn, "voice_slot", "singleton", {"session_id": None})

    def authenticate_session(self, id, token):
        import hmac
        try:
            session = self.get_session(id)
        except AppError:
            raise AppError("UNAUTHORIZED", "Invalid or expired candidate session", 401)
        if datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc) or not hmac.compare_digest(session["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise AppError("UNAUTHORIZED", "Invalid or expired candidate session", 401)
        return session

    def usage_records(self):
        with self.engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(select(usage))]

    def create_guest(self, token_hash, session, limit):
        with self.transaction() as conn:
            count = conn.execute(select(func.count()).select_from(records).where(records.c.kind == "guest")).scalar_one()
            if count >= limit:
                raise AppError("WORKSPACE_LIMIT", "Demo workspace capacity reached; contact the project owner", 429)
            self._put(conn, "guest", token_hash, session)

    def require_case_owner(self, case_id, workspace_id):
        with self.engine.connect() as conn:
            self._get(conn, "case", case_id)
            raw = conn.execute(select(records.c.payload).where(records.c.kind == "case_owner", records.c.id == case_id)).scalar_one_or_none()
            actual = json.loads(raw)["workspace_id"] if raw else None
            if actual != workspace_id:
                raise AppError("NOT_FOUND", "case not found", 404)

    def consume_workspace_operation(self, workspace_id, limit):
        if workspace_id is None: return
        with self.transaction() as conn:
            raw = conn.execute(select(records.c.payload).where(records.c.kind == "guest_operations", records.c.id == workspace_id)).scalar_one_or_none()
            count = json.loads(raw)["count"] if raw else 0
            if count >= limit:
                raise AppError("WORKSPACE_LIMIT", "Workspace processing allowance exhausted", 429)
            self._put(conn, "guest_operations", workspace_id, {"count": count + 1})

    def all_records(self, kind):
        with self.engine.connect() as conn:
            return [(row.id, json.loads(row.payload)) for row in conn.execute(select(records).where(records.c.kind == kind))]

    def put(self, kind, id, value):
        with self.transaction() as conn:
            # A worker may finish handling an event after its case was deleted.
            if kind == "workflow_event" and not conn.execute(select(records.c.id).where(records.c.kind == "case", records.c.id == value["case_id"])).first():
                return
            self._put(conn, kind, id, value)

    def save_stage_result(self, stage, value, receipt_id, fingerprint, expected_interview):
        with self.transaction() as conn:
            if expected_interview is not None:
                current = self._get(conn, "interview", value.case_id)
                if current != expected_interview or not current["consent_confirmed"]:
                    raise AppError("INPUT_CHANGED", "Interview changed or consent was withdrawn during processing", 409)
            kind = {"plan": "plan", "assess": "assessment", "report": "report"}[stage]
            self._save_artifact_in(conn, kind, value)
            self._put(conn, "stage_run", receipt_id, {"fingerprint": fingerprint, "status": "succeeded", "stage": stage})
