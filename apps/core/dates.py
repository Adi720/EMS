import calendar
from datetime import date


def add_months(day, months):
    """The same day ``months`` later (or earlier), clamped to the month's last day."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
