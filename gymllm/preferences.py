"""The user's default weight unit for exercise weights that don't state one."""

from __future__ import annotations

from .extensions import db
from .models import UserPreference

UNITS = ("lbs", "kg")
DEFAULT_UNIT = "lbs"


def get_weight_unit(user_email: str) -> str:
    row = UserPreference.query.filter_by(user_email=user_email).first()
    return row.weight_unit if row and row.weight_unit in UNITS else DEFAULT_UNIT


def set_weight_unit(user_email: str, unit: str) -> str:
    unit = unit if unit in UNITS else DEFAULT_UNIT
    row = UserPreference.query.filter_by(user_email=user_email).first()
    if row is None:
        db.session.add(UserPreference(user_email=user_email, weight_unit=unit))
    else:
        row.weight_unit = unit
    db.session.commit()
    return unit
