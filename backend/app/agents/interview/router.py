from fastapi import APIRouter, Depends, Request
from ...auth import candidate
from ...errors import AppError, unavailable

router = APIRouter()

@router.get("/{session_id}")
def get_session(request: Request, session: dict = Depends(candidate)):
    return {k: v for k, v in session.items() if k != "token_hash"}

@router.get("/{session_id}/report")
def get_owned_report(request: Request, session: dict = Depends(candidate)):
    repo = request.app.state.ctx.repository
    case = repo.get_case(session["case_id"])
    if case.mode != "mock" or repo.get("mock_owner", case.case_id)["session_id"] != session["session_id"]:
        raise AppError("FORBIDDEN", "Only the owning mock session may read this report", 403)
    return repo.get_report(case.case_id)

@router.post("/{session_id}/start")
def start(session: dict = Depends(candidate)):
    unavailable("Interview interaction (Gana)")
