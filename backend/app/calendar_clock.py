from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


SPAIN_TIME_ZONE = ZoneInfo("Europe/Madrid")


def spain_today() -> date:
    """Return the current civil date for MECORRESPONDE's Spanish jurisdiction."""
    return datetime.now(SPAIN_TIME_ZONE).date()
