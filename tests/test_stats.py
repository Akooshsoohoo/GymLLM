from datetime import date

import pytest

from gymllm import stats

TODAY = date(2026, 3, 15)  # a Sunday


def row(**kw):
    base = {
        "id": 1,
        "date": "2026-03-10",
        "exercise": "barbell bench press",
        "weight": "185 lbs",
        "sets": "3",
        "reps": "5, 5, 5",
        "notes": "",
        "tags": "chest;push",
    }
    base.update(kw)
    return base


@pytest.mark.parametrize(
    "sets,reps,expected",
    [
        ("3", "5, 5, 5", 15),
        ("3", "12", 36),
        ("", "[15, 12, 14]", 41),
        ("", "", None),
        ("4", "", None),
    ],
)
def test_total_reps(sets, reps, expected):
    assert stats.total_reps(sets, reps) == expected


def test_entry_volume():
    assert stats.entry_volume(row()) == 185 * 15
    assert stats.entry_volume(row(weight="bodyweight")) is None
    assert stats.entry_volume(row(reps="")) is None
    assert stats.entry_volume(row(weight="80 kg", sets="3", reps="10")) == 2400


def test_range_and_grouping_validation():
    assert stats.clean_range("30d") == "30d"
    assert stats.clean_range("nope") == "all"
    assert stats.clean_grouping("week", "7d") == "week"
    assert stats.clean_grouping(None, "90d") == "week"
    assert stats.clean_grouping("bad", "1y") == "month"
    assert stats.range_start(TODAY, "7d") == date(2026, 3, 9)
    assert stats.range_start(TODAY, "all") is None


def test_filter_range_is_inclusive_of_start():
    rows = [row(date="2026-03-09"), row(date="2026-03-08"), row(date="2026-03-15")]
    assert [r["date"] for r in stats.filter_range(rows, TODAY, "7d")] == [
        "2026-03-09",
        "2026-03-15",
    ]
    assert len(stats.filter_range(rows, TODAY, "all")) == 3


def test_period_keys_and_labels():
    d = date(2026, 3, 11)  # Wednesday
    assert stats.period_key(d, "day") == "2026-03-11"
    assert stats.period_key(d, "week") == "2026-03-09"
    assert stats.period_key(d, "month") == "2026-03"
    assert stats.period_label("2026-03-11", "day") == "Wed 11 Mar 2026"
    assert stats.period_label("2026-03-09", "week") == "9–15 Mar 2026"
    assert stats.period_label("2026-03-30", "week") == "30 Mar – 5 Apr 2026"
    assert stats.period_label("2026-03", "month") == "March 2026"
    assert stats.period_keys(date(2025, 11, 20), date(2026, 2, 3), "month") == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]
    assert stats.period_keys(date(2026, 3, 10), date(2026, 3, 17), "week") == [
        "2026-03-09",
        "2026-03-16",
    ]


def test_group_rows_by_week_newest_first():
    rows = [
        row(id=1, date="2026-03-02"),
        row(id=2, date="2026-03-10", weight="bodyweight", exercise="pull up"),
        row(id=3, date="2026-03-12"),
    ]
    groups = stats.group_rows(rows, "week")
    assert [g["key"] for g in groups] == ["2026-03-09", "2026-03-02"]
    top = groups[0]
    assert top["label"] == "9–15 Mar 2026"
    assert top["sessions"] == 2 and top["entries"] == 2 and top["exercises"] == 2
    assert top["volume"] == 185 * 15
    assert [r["id"] for r in top["rows"]] == [3, 2]


def test_week_streak():
    assert stats.week_streak(set(), TODAY) == 0
    # This week and the two before it.
    assert stats.week_streak({"2026-03-10", "2026-03-04", "2026-02-24"}, TODAY) == 3
    # Nothing yet this week: the streak still counts from last week.
    assert stats.week_streak({"2026-03-04", "2026-02-24"}, TODAY) == 2
    # A gap two weeks ago breaks it.
    assert stats.week_streak({"2026-03-10", "2026-02-24"}, TODAY) == 1


def test_personal_records_need_an_earlier_entry_to_beat():
    rows = [
        row(id=1, date="2026-01-05", weight="185 lbs"),
        row(id=2, date="2026-02-05", weight="190 lbs"),
        row(id=3, date="2026-03-05", weight="190 lbs"),  # equal, not a record
        row(id=4, date="2026-03-12", weight="200 lbs"),
        row(id=5, date="2026-03-12", weight="bodyweight", exercise="pull up"),
    ]
    prs = stats.personal_records(rows, None)
    assert [(p["id"], p["previous"]) for p in prs] == [(4, 190.0), (2, 185.0)]
    assert [p["id"] for p in stats.personal_records(rows, date(2026, 3, 1))] == [4]


def test_overview_totals_deltas_and_series():
    rows = [
        row(id=1, date="2026-03-14"),
        row(id=2, date="2026-03-14", exercise="pull up", weight="bodyweight", tags="back;pull"),
        row(id=3, date="2026-03-10", weight="190 lbs"),
        row(id=4, date="2026-03-03"),  # previous window
        row(id=5, date="2026-01-01"),  # outside both
    ]
    data = stats.overview(rows, TODAY, "7d", "day")
    assert data["totals"] == {"entries": 3, "sessions": 2, "exercises": 2, "volume": 375 * 15}
    assert data["deltas"] == {"sessions": 1, "entries": 2, "volume": 190 * 15}
    assert [p["key"] for p in data["activity"]] == [f"2026-03-{d:02d}" for d in range(9, 16)]
    assert [p["entries"] for p in data["activity"]] == [0, 1, 0, 0, 0, 2, 0]
    assert data["activity"][1]["label"] == "10 Mar"
    # Heatmap starts on the Monday of the range and runs to today.
    assert (
        data["heatmap"][0]["date"] == "2026-03-09" and data["heatmap"][-1]["date"] == "2026-03-15"
    )
    assert {c["date"]: c["count"] for c in data["heatmap"] if c["count"]} == {
        "2026-03-14": 2,
        "2026-03-10": 1,
    }
    assert data["tags"][0] == {"tag": "chest", "count": 2}
    assert data["top_exercises"][0]["exercise"] == "barbell bench press"
    assert data["top_exercises"][0]["best"] == "190 lbs"
    assert [p["id"] for p in data["prs"]] == [3]
    assert data["streak"] == 2  # this week and last; nothing the week before


def test_overview_all_time_has_no_deltas_and_folds_tags():
    rows = [row(id=i, date="2026-03-01", tags=f"t{i}") for i in range(12)]
    data = stats.overview(rows, TODAY, "all", "month")
    assert data["deltas"] == {"sessions": None, "entries": None, "volume": None}
    assert [p["key"] for p in data["activity"]] == ["2026-03"]
    assert data["tags"][-1] == {"tag": "other", "count": 2} and len(data["tags"]) == 11


def test_overview_with_no_rows():
    data = stats.overview([], TODAY, "all", "month")
    assert data["totals"]["entries"] == 0 and data["activity"] == [] and data["streak"] == 0
    assert len(data["heatmap"]) == (TODAY - date(2026, 3, 9)).days + 1


def test_exercise_series():
    rows = [
        row(id=1, date="2026-03-10", weight="185 lbs"),
        row(id=2, date="2026-03-10", weight="190 lbs", reps="3"),
        row(id=3, date="2026-03-12", weight="bodyweight"),
    ]
    series = stats.exercise_series(rows)
    assert series == [
        {"date": "2026-03-10", "weight": 190.0, "volume": 185 * 15 + 190 * 9, "reps": 24},
        {"date": "2026-03-12", "weight": None, "volume": 0.0, "reps": 15},
    ]
