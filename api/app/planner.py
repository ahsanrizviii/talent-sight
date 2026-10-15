"""Finds interview times for many candidates at once.

Plain code, no AI: the rules are exact, so the answer must be exact too.
A slot is only used when ALL of these hold:
- it is on a working day (Monday to Friday by default) and not on a saved holiday;
- it fits completely inside one of the interview windows (09:00-12:00 or 14:00-17:00 by default);
- it does not clash with any interview already booked, keeping the gap (15 minutes) on both sides;
- it starts no earlier than the time asked for.
Slots are handed out in order, so the best-ranked candidate gets the earliest time.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from app.settings import settings

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_DAYS_AHEAD = 366  # never look further than a year for free slots


class PlanError(ValueError):
    """The rules in .env cannot be used (for example a window like 12:00-09:00)."""


@dataclass(frozen=True)
class Rules:
    windows: tuple[tuple[time, time], ...]
    length: timedelta
    gap: timedelta
    work_days: frozenset[int]  # 0 = Monday ... 6 = Sunday
    zone: timezone

    def windows_text(self) -> str:
        return ",".join(f"{start:%H:%M}-{end:%H:%M}" for start, end in self.windows)

    def days_text(self) -> str:
        return ",".join(DAY_NAMES[d].title() for d in sorted(self.work_days))

    def describe(self) -> dict:
        return {
            "windows": [f"{start:%H:%M}-{end:%H:%M}" for start, end in self.windows],
            "interview_minutes": int(self.length.total_seconds() // 60),
            "gap_minutes": int(self.gap.total_seconds() // 60),
            "work_days": [DAY_NAMES[d].title() for d in sorted(self.work_days)],
            "slots_per_day": len(day_slots(date(2026, 1, 5), self)),  # 5 Jan 2026 is a Monday
        }


def _time(text: str) -> time:
    hours, minutes = text.strip().split(":")
    return time(int(hours), int(minutes))


def parse_windows(text: str) -> tuple[tuple[time, time], ...]:
    """'09:00-12:00,14:00-17:00' -> ((09:00, 12:00), (14:00, 17:00)). Raises PlanError."""
    windows = []
    try:
        for part in text.split(","):
            if not part.strip():
                continue
            start, end = (_time(t) for t in part.split("-"))
            windows.append((start, end))
    except (ValueError, IndexError) as error:
        raise PlanError("Write the interview hours like 09:00-12:00,14:00-17:00.") from error
    for start, end in windows:
        if end <= start:
            raise PlanError(f"The interview hours {start:%H:%M}-{end:%H:%M} end before they start.")
    ordered = sorted(windows)
    for (_, first_end), (second_start, _) in zip(ordered, ordered[1:]):
        if second_start < first_end:
            raise PlanError("Two blocks of interview hours overlap.")
    if not ordered:
        raise PlanError("Set at least one block of interview hours.")
    return tuple(ordered)


def parse_days(text: str) -> frozenset[int]:
    """'Mon,Tue,Wed' -> {0, 1, 2}. Raises PlanError."""
    try:
        days = frozenset(DAY_NAMES.index(d.strip().lower()[:3]) for d in text.split(",") if d.strip())
    except ValueError as error:
        raise PlanError("Working days must be written like Mon,Tue,Wed,Thu,Fri.") from error
    if not days:
        raise PlanError("Choose at least one working day.")
    return days


def make_rules(minutes: int, gap: int, windows: str, days: str) -> Rules:
    if not 10 <= minutes <= 240:
        raise PlanError("An interview must last between 10 and 240 minutes.")
    if not 0 <= gap <= 120:
        raise PlanError("The gap between interviews must be between 0 and 120 minutes.")
    rules = Rules(
        windows=parse_windows(windows),
        length=timedelta(minutes=minutes),
        gap=timedelta(minutes=gap),
        work_days=parse_days(days),
        zone=timezone(timedelta(minutes=settings.interview_utc_offset_minutes)),
    )
    if not day_slots(date(2026, 1, 5), rules):
        raise PlanError(f"No {minutes}-minute interview fits inside these hours.")
    return rules


def rules_from_settings() -> Rules:
    """The rules written in .env: used until someone saves them on the Settings page."""
    return make_rules(settings.interview_minutes, settings.interview_gap_minutes, settings.interview_windows, settings.work_days)


def with_length(rules: Rules, minutes: int) -> Rules:
    """The same rules for a different interview length (a batch may choose its own)."""
    return make_rules(minutes, int(rules.gap.total_seconds() // 60), rules.windows_text(), rules.days_text())


def day_slots(day: date, rules: Rules) -> list[datetime]:
    """Every possible start time on one day, ignoring other interviews: 09:00, 10:15, 14:00, 15:15 ..."""
    starts = []
    for window_start, window_end in rules.windows:
        moment = datetime.combine(day, window_start, rules.zone)
        last = datetime.combine(day, window_end, rules.zone)
        while moment + rules.length <= last:
            starts.append(moment)
            moment += rules.length + rules.gap
    return starts


def clashes(start: datetime, busy: list[tuple[datetime, datetime]], rules: Rules) -> datetime | None:
    """The end of the booked interview this slot would clash with, or None when it is free.
    The gap is kept on both sides, so nobody walks out of one interview straight into the next."""
    end = start + rules.length
    for other_start, other_end in busy:
        if start < other_end + rules.gap and other_start < end + rules.gap:
            return other_end
    return None


def plan(
    count: int,
    earliest: datetime,
    busy: list[tuple[datetime, datetime]],
    days_off: set[date],
    rules: Rules,
) -> list[datetime]:
    """`count` free start times, in order, from `earliest` on. Fewer if a year is not enough."""
    taken = list(busy)
    found: list[datetime] = []
    day = earliest.astimezone(rules.zone).date()
    for _ in range(MAX_DAYS_AHEAD):
        if len(found) >= count:
            break
        if day.weekday() in rules.work_days and day not in days_off:
            for window_start, window_end in rules.windows:
                moment = datetime.combine(day, window_start, rules.zone)
                last = datetime.combine(day, window_end, rules.zone)
                while len(found) < count and moment + rules.length <= last:
                    blocked_until = clashes(moment, taken, rules)
                    if moment < earliest:
                        moment += rules.length + rules.gap
                    elif blocked_until is not None:
                        moment = max(moment + timedelta(minutes=5), blocked_until + rules.gap)  # just after the other one
                    else:
                        found.append(moment)
                        taken.append((moment, moment + rules.length))
                        moment += rules.length + rules.gap
        day += timedelta(days=1)
    return found


def slot_problem(start: datetime, busy: list[tuple[datetime, datetime]], days_off: set[date], rules: Rules, now: datetime) -> str:
    """Why this exact time cannot be used, or "" when it can. Checked again just before sending,
    because the preview may be a few minutes old."""
    local = start.astimezone(rules.zone)
    if start <= now:
        return "The time has already passed."
    if local.weekday() not in rules.work_days:
        return "It is not a working day."
    if local.date() in days_off:
        return "It is a holiday."
    inside = any(
        datetime.combine(local.date(), a, rules.zone) <= local and local + rules.length <= datetime.combine(local.date(), b, rules.zone)
        for a, b in rules.windows
    )
    if not inside:
        return "It is outside the interview hours."
    if clashes(start, busy, rules) is not None:
        return "It clashes with another interview."
    return ""
