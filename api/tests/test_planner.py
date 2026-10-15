"""Tests for the interview slot planner: working days, interview hours, holidays, no clashes."""

from datetime import date, datetime, time, timedelta, timezone

from app.planner import Rules, clashes, day_slots, plan, slot_problem

DHAKA = timezone(timedelta(hours=6))
RULES = Rules(
    windows=((time(9), time(12)), (time(14), time(17))),
    length=timedelta(minutes=60),
    gap=timedelta(minutes=15),
    work_days=frozenset({0, 1, 2, 3, 4}),  # Monday to Friday
    zone=DHAKA,
)
MONDAY = date(2026, 10, 19)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), DHAKA)


def test_one_day_has_four_slots_with_these_hours():
    assert [f"{s:%H:%M}" for s in day_slots(MONDAY, RULES)] == ["09:00", "10:15", "14:00", "15:15"]


def test_slots_fill_in_order_and_never_clash():
    starts = plan(6, at(MONDAY, 0), [], set(), RULES)
    assert [f"{s:%a %H:%M}" for s in starts] == ["Mon 09:00", "Mon 10:15", "Mon 14:00", "Mon 15:15", "Tue 09:00", "Tue 10:15"]
    for first, second in zip(starts, starts[1:]):
        assert second - first >= RULES.length + RULES.gap or second.date() != first.date()


def test_weekends_are_skipped():
    friday = date(2026, 10, 23)
    starts = plan(5, at(friday, 0), [], set(), RULES)
    assert [s.strftime("%a") for s in starts] == ["Fri", "Fri", "Fri", "Fri", "Mon"]


def test_holidays_are_skipped():
    tuesday = MONDAY + timedelta(days=1)
    starts = plan(5, at(MONDAY, 0), [], {MONDAY}, RULES)
    assert {s.date() for s in starts} == {tuesday, tuesday + timedelta(days=1)}


def test_existing_interviews_are_worked_around_with_the_gap():
    busy = [(at(MONDAY, 9, 30), at(MONDAY, 10, 30))]  # booked by hand at an odd time
    starts = plan(3, at(MONDAY, 0), busy, set(), RULES)
    assert [f"{s:%H:%M}" for s in starts] == ["10:45", "14:00", "15:15"]  # 10:45 = 10:30 + 15 min gap
    for start in starts:
        assert clashes(start, busy, RULES) is None


def test_nothing_before_the_earliest_time():
    starts = plan(2, at(MONDAY, 13), [], set(), RULES)
    assert [f"{s:%H:%M}" for s in starts] == ["14:00", "15:15"]


def test_every_slot_fits_inside_the_hours():
    for start in plan(40, at(MONDAY, 0), [], set(), RULES):
        assert slot_problem(start, [], set(), RULES, at(MONDAY, 0)) == ""
        assert start.astimezone(DHAKA).time() < time(12) or start.astimezone(DHAKA).time() >= time(14)


def test_slot_problem_names_the_reason():
    now = at(MONDAY, 0)
    saturday = date(2026, 10, 24)
    assert slot_problem(at(saturday, 9), [], set(), RULES, now) == "It is not a working day."
    assert slot_problem(at(MONDAY, 9), [], {MONDAY}, RULES, now) == "It is a holiday."
    assert slot_problem(at(MONDAY, 11, 30), [], set(), RULES, now) == "It is outside the interview hours."  # would end 12:30
    assert slot_problem(at(MONDAY, 9), [(at(MONDAY, 9), at(MONDAY, 10))], set(), RULES, now) == "It clashes with another interview."
    assert slot_problem(at(MONDAY, 9), [], set(), RULES, at(MONDAY, 10)) == "The time has already passed."
