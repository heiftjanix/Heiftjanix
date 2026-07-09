"""Werktags- und Feiertagslogik (Deutschland / Bayern) — reine Stdlib.

Wird von forecast/revenue_aggregate genutzt, damit die Monatsend-Prognose auf
Werktagen (Mo–Fr abzüglich Feiertage) statt Kalendertagen basiert.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Ostersonntag nach der anonymen gregorianischen Formel (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def german_holidays(year: int, region: str = "BY") -> set[date]:
    """Gesetzliche Feiertage. Bundesweit + regionale (Standard: Bayern).

    Für Bayern inkl. Heilige Drei Könige, Fronleichnam, Allerheiligen und
    Mariä Himmelfahrt (in weiten Teilen Bayerns Feiertag).
    """
    easter = easter_sunday(year)
    days: set[date] = {
        date(year, 1, 1),          # Neujahr
        easter - timedelta(days=2),  # Karfreitag
        easter + timedelta(days=1),  # Ostermontag
        date(year, 5, 1),          # Tag der Arbeit
        easter + timedelta(days=39),  # Christi Himmelfahrt
        easter + timedelta(days=50),  # Pfingstmontag
        date(year, 10, 3),         # Tag der Deutschen Einheit
        date(year, 12, 25),        # 1. Weihnachtstag
        date(year, 12, 26),        # 2. Weihnachtstag
    }
    if region == "BY":
        days |= {
            date(year, 1, 6),                 # Heilige Drei Könige
            easter + timedelta(days=60),      # Fronleichnam
            date(year, 8, 15),                # Mariä Himmelfahrt
            date(year, 11, 1),                # Allerheiligen
        }
    return days


def _holiday_set(year: int, month: int, region: str, extra: list[str] | None) -> set[date]:
    days = german_holidays(year, region)
    # Jahresübergreifende Sicherheit (z. B. Prognose im Dezember referenziert Vorjahr).
    days |= german_holidays(year - 1, region)
    days |= german_holidays(year + 1, region)
    for iso in extra or []:
        try:
            days.add(date.fromisoformat(iso))
        except ValueError:
            continue
    return days


def is_business_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def business_days_in_month(year: int, month: int, region: str = "BY",
                           extra: list[str] | None = None) -> int:
    """Anzahl Werktage im gesamten Monat."""
    holidays = _holiday_set(year, month, region, extra)
    _, last = calendar.monthrange(year, month)
    return sum(
        1 for day in range(1, last + 1)
        if is_business_day(date(year, month, day), holidays)
    )


def business_days_elapsed(today: date, region: str = "BY",
                          extra: list[str] | None = None) -> int:
    """Verstrichene Werktage vom Monatsersten bis heute (inklusive)."""
    holidays = _holiday_set(today.year, today.month, region, extra)
    return sum(
        1 for day in range(1, today.day + 1)
        if is_business_day(date(today.year, today.month, day), holidays)
    )


def business_days_between(start: date, end: date, region: str = "BY",
                          extra: list[str] | None = None) -> int:
    """Werktage von start bis end (inklusive beider Ränder), 0 wenn end < start."""
    if end < start:
        return 0
    holidays = _holiday_set(start.year, start.month, region, extra)
    holidays |= _holiday_set(end.year, end.month, region, extra)
    count = 0
    d = start
    while d <= end:
        if is_business_day(d, holidays):
            count += 1
        d += timedelta(days=1)
    return count


def add_business_days(start: date, n: int, region: str = "BY",
                      extra: list[str] | None = None) -> date:
    """start + n Werktage (für den UPS-Fallback: Versanddatum + Transittage)."""
    holidays = _holiday_set(start.year, start.month, region, extra)
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        # Feiertagsset ggf. für ein neues Jahr nachladen
        if d.year not in {start.year}:
            holidays |= _holiday_set(d.year, d.month, region, extra)
        if is_business_day(d, holidays):
            added += 1
    return d
