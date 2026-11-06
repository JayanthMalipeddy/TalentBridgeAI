import hmac
from fastapi import Request, Header
from .errors import AppError

def recruiter(request: Request, authorization: str | None = Header(default=None)):
    expected = request.app.state.ctx.settings.recruiter_api_token.get_secret_value()
    if not expected:
        raise AppError("AUTH_NOT_CONFIGURED", "Set RECRUITER_API_TOKEN on the server", 503)
    supplied = (authorization or "").removeprefix("Bearer ")
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise AppError("UNAUTHORIZED", "Valid recruiter bearer token required", 401)

def candidate(request: Request, session_id: str, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("UNAUTHORIZED", "Candidate bearer token required", 401)
    return request.app.state.ctx.repository.authenticate_session(session_id, authorization[7:])
