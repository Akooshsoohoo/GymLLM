"""Deleting your account from the app. Mirrors routes.account_delete."""

from __future__ import annotations

from flask import jsonify

from .. import account
from ..auth import current_user_email
from . import bp
from .errors import token_required


@bp.route("/account", methods=["DELETE"])
@token_required
def account_delete():
    """Everything stored for the signed-in email is removed, for good, and this
    token and every other one issued for it stop working."""
    account.delete(current_user_email())
    return jsonify(deleted=True)
