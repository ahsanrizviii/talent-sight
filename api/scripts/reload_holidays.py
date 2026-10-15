"""Reads every holiday calendar PDF in knowledge/holidays again, even ones read before.

docker compose exec api python -m scripts.reload_holidays
"""

from app.holiday_calendar import load_holiday_calendars

results = load_holiday_calendars(force=True)
print("\n".join(results) if results else "No PDF found in knowledge/holidays.")
