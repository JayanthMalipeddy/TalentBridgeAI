"""No-signup access with isolated server-owned workspaces."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from fastapi import Request
from .errors import AppError

COOKIE = "tb_guest"


def origins(settings):
    return [v.strip().rstrip('/') for v in settings.frontend_origin.split(',') if v.strip()]


def verify_origin(request):
    if request.headers.get("origin", "").rstrip('/') not in origins(request.app.state.ctx.settings):
        raise AppError("ORIGIN_FORBIDDEN", "Request must originate from the configured frontend", 403)


def cookie_secure(settings):
    if settings.app_env in {"development", "test", "fixture-demo"}:
        return not all(urlparse(o).hostname in {"localhost", "127.0.0.1", "::1"} for o in origins(settings))
    return True


def metadata(session):
    return {k: session[k] for k in ("workspace_id", "expires_at", "csrf_token")}


def get_guest(request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 200:
        raise AppError("UNAUTHORIZED", "Guest session is missing or expired", 401)
    try:
        session = request.app.state.ctx.repository.get("guest", hashlib.sha256(token.encode()).hexdigest())
    except AppError:
        raise AppError("UNAUTHORIZED", "Guest session is missing or expired", 401)
    if datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc):
        raise AppError("UNAUTHORIZED", "Guest session is missing or expired", 401)
    return session


def bootstrap(request, response):
    verify_origin(request)
    try: return metadata(get_guest(request))
    except AppError as exc:
        if exc.status != 401: raise
    ctx = request.app.state.ctx
    token = secrets.token_urlsafe(32)
    session = {"workspace_id": secrets.token_urlsafe(24), "csrf_token": secrets.token_urlsafe(32),
               "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ctx.settings.guest_ttl_seconds)).isoformat()}
    ctx.repository.create_guest(hashlib.sha256(token.encode()).hexdigest(), session, ctx.settings.guest_max_workspaces)
    response.set_cookie(COOKIE, token, max_age=ctx.settings.guest_ttl_seconds,
                        httponly=True, secure=cookie_secure(ctx.settings), samesite="lax", path="/")
    return metadata(session)


def owner(request: Request):
    authorization = request.headers.get("authorization")
    if authorization:
        from .auth import recruiter
        recruiter(request, authorization)
        return None  # Legacy cases only; guest workspaces stay private.
    session = get_guest(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        verify_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), session["csrf_token"].encode()):
            raise AppError("CSRF_INVALID", "Refresh the workspace session before retrying", 403)
    return session["workspace_id"]


def owned_case(request: Request):
    workspace = owner(request)
    request.app.state.ctx.repository.require_case_owner(request.path_params["case_id"], workspace)
    return workspace
