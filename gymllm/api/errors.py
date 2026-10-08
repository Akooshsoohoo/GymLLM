"""JSON errors: {"error": {"code": "quota_exceeded", "message": "..."}}."""

from __future__ import annotations

from functools import wraps

from flask import current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from .. import auth
from ..extensions import db


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str):
    return jsonify(error={"code": code, "message": message}), status


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def register(bp) -> None:
    @bp.errorhandler(ApiError)
    def api_error(e: ApiError):
        return error_response(e.status, e.code, e.message)

    @bp.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        code = (e.name or "error").lower().replace(" ", "_")
        return error_response(e.code or 500, code, e.description or e.name)

    @bp.errorhandler(Exception)
    def unexpected(e: Exception):
        db.session.rollback()
        current_app.logger.exception("Unhandled API error: %s", e)
        return error_response(500, "server_error", "Something went wrong. Please try again.")


TOKEN_ERRORS = {
    auth.TOKEN_MISSING: ("unauthorized", "Sign in to continue."),
    auth.TOKEN_EXPIRED: ("token_expired", "Your sign-in has expired. Sign in again."),
    auth.TOKEN_INVALID: ("invalid_token", "Sign in again."),
}


def token_required(view):
    """A valid bearer token, or 401. The cookie session never counts here: the
    blueprint is exempt from CSRF, so it must not act on a browser's cookies."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        claims, why = auth.api_token_claims()
        if claims is None:
            raise ApiError(401, *TOKEN_ERRORS[why])
        return view(*args, **kwargs)

    return wrapped


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "bad_request", "Send a JSON object.")
    return data
