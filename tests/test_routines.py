"""The routines module: validation, ordering, scoping and copies."""

from gymllm import routines
from gymllm.extensions import db
from gymllm.models import RoutineBlock

from .conftest import OTHER, USER


def test_validate_requires_a_name_and_trims_it():
    assert routines.validate("  ") == ("", "Give the routine a name.")
    assert routines.validate(None)[1] is not None
    assert routines.validate("  Push   day ") == ("Push day", None)
    name, error = routines.validate("x" * 80)
    assert error is None and len(name) == routines.NAME_MAX


def test_clean_blocks_pairs_fields_drops_empties_and_truncates():
    blocks = routines.clean_blocks(
        ["Warm-up", "", "  ", "y" * 50],
        ["Row 5 min", "Bench 185, 3 sets of ___\r\n", "", "z" * 5000],
    )
    assert blocks == [
        {"name": "Warm-up", "body": "Row 5 min"},
        {"name": "", "body": "Bench 185, 3 sets of ___"},
        {"name": "y" * routines.BLOCK_NAME_MAX, "body": "z" * routines.BODY_MAX},
    ]
    # Uneven lists still pair up in order.
    assert routines.clean_blocks(["Only a name"], []) == [{"name": "Only a name", "body": ""}]


def test_clean_blocks_caps_the_count():
    many = routines.clean_blocks([], [f"line {i}" for i in range(30)])
    assert len(many) == routines.MAX_BLOCKS and many[-1]["body"] == "line 19"


def test_create_update_keep_order_and_scope(app):
    with app.app_context():
        r = routines.create(
            USER, "Push", [{"name": "Chest", "body": "bench"}, {"name": "", "body": "dips"}]
        )
        db.session.commit()
        assert routines.blocks_of(r) == [
            {"name": "Chest", "body": "bench"},
            {"name": "", "body": "dips"},
        ]
        assert routines.get(OTHER, r.id) is None
        assert routines.list_for(OTHER) == []
        assert routines.list_for(USER) == [{"id": r.id, "name": "Push", "blocks": 2}]

        routines.update(r, "Push A", [{"name": "Shoulders", "body": "press"}])
        db.session.commit()
        assert routines.get(USER, r.id).name == "Push A"
        assert routines.blocks_of(r) == [{"name": "Shoulders", "body": "press"}]
        assert RoutineBlock.query.count() == 1  # the old blocks are gone, not orphaned


def test_duplicate_and_delete(app):
    with app.app_context():
        r = routines.create(USER, "L" * 60, [{"name": "Legs", "body": "squat"}])
        db.session.commit()
        copy = routines.duplicate(r)
        db.session.commit()
        assert copy.id != r.id and copy.name.endswith(" (copy)") and len(copy.name) == 60
        assert routines.blocks_of(copy) == routines.blocks_of(r)

        routines.delete(r)
        db.session.commit()
        assert routines.get(USER, r.id) is None
        assert [x["id"] for x in routines.list_for(USER)] == [copy.id]
        assert RoutineBlock.query.count() == 1
