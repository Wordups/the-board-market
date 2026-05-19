"""
The Board: Markets — FOMC Calendar
P2.02

Static config: 8 FOMC meeting dates per year. Published a year out by the
Fed (federalreserve.gov/monetarypolicy/fomccalendars.htm). Meetings are
2-day events; the rate decision lands on the second day (a Wednesday).

We track meeting **end** dates because that's when the price reaction
happens. `is_fomc_week()` checks whether a given date falls in the same
ISO week as any meeting end date.

Schema decision: hardcoded list, no DB table. Brian extends the list
manually when the Fed publishes next year's schedule.

Public API:
    is_fomc_week(d) -> bool
    next_fomc(d) -> date | None
    days_to_next_fomc(d) -> int | None
"""

from datetime import date, datetime
from typing import Iterable


# Meeting end dates (the rate decision day). Source: Federal Reserve.
# Extend this list as new schedules are published.
FOMC_MEETING_DATES: list[date] = [
    # 2021
    date(2021, 1, 27),
    date(2021, 3, 17),
    date(2021, 4, 28),
    date(2021, 6, 16),
    date(2021, 7, 28),
    date(2021, 9, 22),
    date(2021, 11, 3),
    date(2021, 12, 15),
    # 2022
    date(2022, 1, 26),
    date(2022, 3, 16),
    date(2022, 5, 4),
    date(2022, 6, 15),
    date(2022, 7, 27),
    date(2022, 9, 21),
    date(2022, 11, 2),
    date(2022, 12, 14),
    # 2023
    date(2023, 2, 1),
    date(2023, 3, 22),
    date(2023, 5, 3),
    date(2023, 6, 14),
    date(2023, 7, 26),
    date(2023, 9, 20),
    date(2023, 11, 1),
    date(2023, 12, 13),
    # 2024
    date(2024, 1, 31),
    date(2024, 3, 20),
    date(2024, 5, 1),
    date(2024, 6, 12),
    date(2024, 7, 31),
    date(2024, 9, 18),
    date(2024, 11, 7),
    date(2024, 12, 18),
    # 2025
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 10, 29),
    date(2025, 12, 10),
    # 2026
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
]


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Cannot interpret {value!r} as date")


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])  # (year, week)


def is_fomc_week(d, meetings: Iterable[date] | None = None) -> bool:
    """
    True if `d` lands in the same ISO week as any FOMC meeting end date.
    Meeting day itself returns True. The downgrade rule in score.py also
    gates on weekday() in (Mon, Tue, Wed) — this function just answers
    the week-membership question.
    """
    target = _to_date(d)
    target_week = _iso_week(target)
    for m in (meetings if meetings is not None else FOMC_MEETING_DATES):
        if _iso_week(m) == target_week:
            return True
    return False


def next_fomc(d, meetings: Iterable[date] | None = None) -> date | None:
    """Next FOMC meeting on or after `d`. None if past the known schedule."""
    target = _to_date(d)
    pool = meetings if meetings is not None else FOMC_MEETING_DATES
    for m in pool:
        if m >= target:
            return m
    return None


def days_to_next_fomc(d, meetings: Iterable[date] | None = None) -> int | None:
    nxt = next_fomc(d, meetings)
    if nxt is None:
        return None
    return (nxt - _to_date(d)).days


if __name__ == "__main__":
    from datetime import timedelta

    today = date.today()
    print(f"Today: {today}")
    print(f"  is_fomc_week:       {is_fomc_week(today)}")
    print(f"  next_fomc:          {next_fomc(today)}")
    print(f"  days_to_next_fomc:  {days_to_next_fomc(today)}")

    # Sanity check: meeting day itself should be FOMC week
    for m in FOMC_MEETING_DATES[-3:]:
        print(f"  meeting {m} -> is_fomc_week({m})={is_fomc_week(m)}")
        # Same week, prior Monday should also be True
        monday = m - timedelta(days=m.weekday())
        print(f"    same-week Monday {monday}: is_fomc_week={is_fomc_week(monday)}")
        # Following Monday should be False
        next_monday = monday + timedelta(days=7)
        print(f"    next Monday {next_monday}:   is_fomc_week={is_fomc_week(next_monday)}")
