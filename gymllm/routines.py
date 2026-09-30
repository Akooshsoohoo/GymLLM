"""Routines: named templates of named blocks that pre-fill the recorder.

Every lookup is scoped by the owner's email, so another person's routine is simply
not found. Over-long names and bodies are cut to size rather than rejected (the
form's maxlength already stops them in a browser); only a blank routine name is an
error."""

from __future__ import annotations

from .extensions import db
from .models import Routine, RoutineBlock, _utcnow

NAME_MAX = 60
BLOCK_NAME_MAX = 40
BODY_MAX = 4000
MAX_BLOCKS = 20
COPY_SUFFIX = " (copy)"


def _one_line(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def clean_blocks(names: list[str], bodies: list[str]) -> list[dict]:
    """The editor's repeated block_name / block_body fields, paired in order. Blocks
    with neither a name nor a body are dropped; at most MAX_BLOCKS are kept."""
    blocks = []
    for i in range(max(len(names), len(bodies))):
        name = _one_line(names[i] if i < len(names) else "", BLOCK_NAME_MAX)
        body = (bodies[i] if i < len(bodies) else "").replace("\r\n", "\n").strip()[:BODY_MAX]
        if name or body:
            blocks.append({"name": name, "body": body})
    return blocks[:MAX_BLOCKS]


def validate(name: str | None) -> tuple[str, str | None]:
    """(cleaned name, error or None)."""
    name = _one_line(name, NAME_MAX)
    return name, None if name else "Give the routine a name."


def clean_title(name: str | None) -> str:
    """A routine name posted back from the recorder, for the day's title."""
    return _one_line(name, NAME_MAX)


def list_for(owner: str) -> list[dict]:
    """The owner's routines, most recently changed first, with their block counts."""
    counts = dict(
        db.session.query(RoutineBlock.routine_id, db.func.count(RoutineBlock.id))
        .join(Routine, Routine.id == RoutineBlock.routine_id)
        .filter(Routine.user_email == owner)
        .group_by(RoutineBlock.routine_id)
        .all()
    )
    rows = (
        Routine.query.filter_by(user_email=owner)
        .order_by(Routine.updated_at.desc(), Routine.id.desc())
        .all()
    )
    return [{"id": r.id, "name": r.name, "blocks": counts.get(r.id, 0)} for r in rows]


def get(owner: str, routine_id: int) -> Routine | None:
    return Routine.query.filter_by(id=routine_id, user_email=owner).first()


def blocks_of(routine: Routine) -> list[dict]:
    rows = RoutineBlock.query.filter_by(routine_id=routine.id).order_by(RoutineBlock.position).all()
    return [{"name": b.name or "", "body": b.body} for b in rows]


def _replace_blocks(routine: Routine, blocks: list[dict]) -> None:
    # Deleted by hand: SQLite doesn't enforce ON DELETE CASCADE by default.
    RoutineBlock.query.filter_by(routine_id=routine.id).delete()
    for i, b in enumerate(blocks):
        db.session.add(
            RoutineBlock(routine_id=routine.id, position=i, name=b["name"] or None, body=b["body"])
        )


def create(owner: str, name: str, blocks: list[dict]) -> Routine:
    """The caller commits."""
    routine = Routine(user_email=owner, name=name)
    db.session.add(routine)
    db.session.flush()
    _replace_blocks(routine, blocks)
    return routine


def update(routine: Routine, name: str, blocks: list[dict]) -> None:
    """Rename and replace the blocks wholesale. The caller commits."""
    routine.name = name
    routine.updated_at = _utcnow()  # onupdate alone misses a blocks-only change
    _replace_blocks(routine, blocks)


def delete(routine: Routine) -> None:
    """The caller commits."""
    RoutineBlock.query.filter_by(routine_id=routine.id).delete()
    db.session.delete(routine)


def duplicate(routine: Routine) -> Routine:
    """A copy named '<name> (copy)', cut to fit. The caller commits."""
    name = routine.name[: NAME_MAX - len(COPY_SUFFIX)] + COPY_SUFFIX
    return create(routine.user_email, name, blocks_of(routine))
