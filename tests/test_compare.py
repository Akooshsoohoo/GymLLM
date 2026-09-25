from datetime import date

from gymllm import compare


def row(d, exercise, weight="", sets="3", reps="10", tags="", id=1):
    return {"id": id, "date": d, "exercise": exercise, "weight": weight, "sets": sets,
            "reps": reps, "notes": "", "tags": tags}  # fmt: skip


TODAY = date(2026, 9, 10)


def test_weight_in_unit_uses_default_for_bare_numbers():
    assert compare.weight_in_unit("80", "kg") == (80.0, "kg")
    assert compare.weight_in_unit("185 lb", "kg") == (185.0, "lbs")
    assert compare.weight_in_unit("bodyweight", "lbs") is None


def test_shared_lift_leader_and_gap():
    mine = [
        row("2026-09-01", "Bench Press", "185 lbs"),
        row("2026-09-03", "bench press", "190 lbs"),
    ]
    theirs = [row("2026-09-02", "bench press", "200")]
    data = compare.compare((mine, []), (theirs, []), TODAY, "all", "lbs", "lbs")
    (s,) = data["shared"]
    assert s["lead"] == "theirs"
    assert s["diff"] == 10
    assert s["mine"]["sessions"] == 2


def test_no_leader_when_units_differ():
    mine = [row("2026-09-01", "squat", "100 kg")]
    theirs = [row("2026-09-02", "squat", "200 lbs")]
    (s,) = compare.compare((mine, []), (theirs, []), TODAY, "all", "kg", "lbs")["shared"]
    assert s["lead"] is None and s["diff"] is None
    assert s["mine"]["text"] == "100 kg"


def test_only_common_exercises_are_shared():
    mine = [row("2026-09-01", "squat", "100 kg")]
    theirs = [row("2026-09-02", "deadlift", "140 kg")]
    assert compare.compare((mine, []), (theirs, []), TODAY, "all")["shared"] == []


def test_favourites_flag_overlap():
    mine = [row("2026-09-01", "squat"), row("2026-09-02", "curl")]
    theirs = [row("2026-09-01", "Squat"), row("2026-09-02", "row")]
    favs = compare.compare((mine, []), (theirs, []), TODAY, "all")["favourites"]
    assert {f["exercise"]: f["shared"] for f in favs["mine"]} == {"squat": True, "curl": False}


def test_totals_and_leads():
    mine = [row("2026-09-01", "squat", sets="5"), row("2026-09-02", "squat", sets="5")]
    theirs = [row("2026-09-01", "squat", sets="3")]
    cardio = [
        {
            "id": 1,
            "date": "2026-09-03",
            "activity": "run",
            "distance": "",
            "duration": "30 min",
            "notes": "",
        }
    ]
    totals = {
        t["label"]: t for t in compare.compare((mine, []), (theirs, cardio), TODAY, "all")["totals"]
    }
    assert totals["Sessions"]["mine"] == 2 and totals["Sessions"]["theirs"] == 2
    assert totals["Sessions"]["lead"] is None
    assert totals["Sets"]["lead"] == "mine"
    assert totals["Cardio minutes"]["lead"] == "theirs"


def test_volume_has_no_leader_across_units():
    mine = [row("2026-09-01", "squat", "100")]
    theirs = [row("2026-09-01", "squat", "100")]
    totals = compare.compare((mine, []), (theirs, []), TODAY, "all", "kg", "lbs")["totals"]
    vol = next(t for t in totals if t["label"].startswith("Volume"))
    assert vol["lead"] is None and vol["units"] == ("kg", "lbs")


def test_empty_when_nothing_in_range():
    mine = [row("2026-01-01", "squat")]
    data = compare.compare((mine, []), ([], []), TODAY, "30d")
    assert data["empty"]


def test_muscle_split_is_share_of_each_person():
    mine = [
        row("2026-09-01", "squat", tags="quads;compound"),
        row("2026-09-02", "curl", tags="biceps"),
    ]
    theirs = [row("2026-09-01", "squat", tags="quads")] * 3
    split = {
        m["tag"]: m for m in compare.compare((mine, []), (theirs, []), TODAY, "all")["muscles"]
    }
    assert split["quads"] == {"tag": "quads", "mine": 50, "theirs": 100}
    assert "compound" not in split


def test_weekly_sessions_twelve_weeks():
    weekly = compare.weekly_sessions({"2026-09-08", "2026-09-09"}, {"2026-09-01"}, TODAY)
    assert len(weekly) == 12
    assert weekly[-1]["mine"] == 2 and weekly[-1]["theirs"] == 0
    assert weekly[-2]["theirs"] == 1
