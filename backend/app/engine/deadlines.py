from __future__ import annotations
from datetime import date, timedelta


def add_business_days(start: date, days: int, holidays: set[date] | None = None) -> date:
    holidays = holidays or set()
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays:
            added += 1
    return current
