"""The US equity exchanges' trading days (2026-10-03), for questions about a
session that has not happened: "what might move Monday" asked on a Friday
evening or a Saturday, or "tomorrow" asked on a Monday.

Full-day closures only (the nine NYSE holidays, with the observed-day rule);
the early 1pm closes the day after Thanksgiving, on Christmas Eve and on July 3
do not change which days trade. A one-off closure (a national day of mourning)
is not in a calendar computed in advance.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> date | None:
    """A holiday on a Saturday is kept on the Friday, one on a Sunday on the
    Monday. (A New Year's Day on a Saturday is not moved: the exchange stays
    open that Friday, which the caller handles.)"""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def holidays(year: int) -> set[date]:
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 12, 25)]
    out = {_nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2),
           _last_weekday(year, 5, 0), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4)}
    for d in fixed:
        if d == date(year, 1, 1) and d.weekday() == 5:
            continue                      # Saturday New Year's: no weekday holiday
        out.add(_observed(d))
    # A New Year's Day that falls on a Sunday is observed on the Monday of the
    # same year; one on Saturday closes nothing. Next year's Saturday Jan 1 never
    # reaches back to Dec 31 here, as the exchange does not close it.
    return out


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def next_session(after: date) -> date:
    """The first trading day strictly after `after`."""
    d = after + timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d


def previous_session(before: date) -> date:
    """The last trading day strictly before `before`."""
    d = before - timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def on_or_next_session(d: date) -> date:
    return d if is_session(d) else next_session(d)


def upcoming_session(now: datetime) -> date:
    """The next session that has not opened yet: today when it is a trading day
    and the open is still ahead, otherwise the next trading day."""
    now = now.astimezone(NY)
    today = now.date()
    if is_session(today) and now.time() < OPEN:
        return today
    return next_session(today)


def last_close(now: datetime) -> datetime:
    """The most recent regular close at or before `now`."""
    now = now.astimezone(NY)
    day = now.date()
    if is_session(day) and now.time() >= CLOSE:
        return datetime.combine(day, CLOSE, tzinfo=NY)
    return datetime.combine(previous_session(day), CLOSE, tzinfo=NY)


def sessions_from(start: date, count: int) -> list[date]:
    out, d = [], start
    for _ in range(max(1, count)):
        out.append(d)
        d = next_session(d)
    return out
