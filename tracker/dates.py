"""Deadline resolution.

The whole point of running daily is that these values change every day:
a window that was "opens in 12 days" yesterday is "OPEN NOW" today, and an
annual deadline that just passed rolls forward to next year automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

URGENT_DAYS = 7
SOON_DAYS = 30


@dataclass
class Resolved:
    """Everything the site needs to render one deadline."""

    state: str          # open | urgent | soon | upcoming | rolling | unknown
    label: str          # short badge text, e.g. "Closes in 13 days"
    detail: str         # human sentence under the badge
    target: str         # ISO date the countdown points at, or ""
    days: int | None    # days to that target (negative never happens; we roll)
    opens_on: str       # ISO date the window opens, or ""
    closes_on: str      # ISO date the window closes, or ""
    confidence: str     # confirmed | typical | estimate | ""
    note: str
    # Can you actually submit an application today? False only when we are
    # confident applications are not open yet (a window ahead of its opening
    # date) or definitely closed (a fixed date already passed). Anything
    # ambiguous defaults to True, so the "hide what's not open" filter only
    # ever hides entries we are sure about rather than guessing people away
    # from something that might still be live.
    is_open: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def _md(value: str) -> tuple[int, int]:
    month, day = value.split("-")
    return int(month), int(day)


def _next_occurrence(month_day: str, today: date) -> date:
    """The next time MM-DD comes around, counting today as still valid."""
    month, day = _md(month_day)
    for year in (today.year, today.year + 1, today.year + 2):
        try:
            candidate = date(year, month, day)
        except ValueError:  # 29 Feb in a non-leap year
            candidate = date(year, month, day - 1)
        if candidate >= today:
            return candidate
    return date(today.year + 1, month, day)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _countdown(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 45:
        return f"in {_plural(days, 'day')}"
    if days < 365:
        return f"in about {_plural(round(days / 30.4), 'month')}"
    return f"in about {_plural(round(days / 365), 'year')}"


def _grade(days: int) -> str:
    if days <= URGENT_DAYS:
        return "urgent"
    if days <= SOON_DAYS:
        return "soon"
    return "upcoming"


def resolve(deadline: dict | None, today: date | None = None) -> Resolved:
    today = today or date.today()
    deadline = deadline or {}
    kind = deadline.get("kind", "unknown")
    confidence = deadline.get("confidence", "")
    note = deadline.get("note", "")
    time_of_day = deadline.get("time", "")

    if kind == "fixed":
        try:
            target = date.fromisoformat(deadline["date"])
        except (KeyError, ValueError):
            return Resolved("unknown", "Date unclear", "No usable date on file.",
                            "", None, "", "", confidence, note, True)
        days = (target - today).days
        if days < 0:
            return Resolved("unknown", "Passed",
                            f"Closed on {target:%d %b %Y}. Waiting for the next call.",
                            target.isoformat(), None, "", target.isoformat(), confidence, note, False)
        suffix = f" at {time_of_day}" if time_of_day else ""
        return Resolved(_grade(days), f"Closes {_countdown(days)}",
                        f"Deadline {target:%d %B %Y}{suffix}.",
                        target.isoformat(), days, "", target.isoformat(), confidence, note, True)

    if kind == "annual":
        target = _next_occurrence(deadline.get("month_day", "12-31"), today)
        days = (target - today).days
        suffix = f" at {time_of_day}" if time_of_day else ""
        return Resolved(_grade(days), f"Closes {_countdown(days)}",
                        f"Next deadline {target:%d %B %Y}{suffix}.",
                        target.isoformat(), days, "", target.isoformat(), confidence, note, True)

    if kind == "window":
        opens = _next_occurrence(deadline.get("from_month_day", "01-01"), today)
        closes = _next_occurrence(deadline.get("to_month_day", "12-31"), today)
        # If the closing date comes round before the opening one, we are inside
        # the window right now.
        if closes < opens:
            days = (closes - today).days
            return Resolved("urgent" if days <= URGENT_DAYS else "open",
                            f"OPEN NOW - closes {_countdown(days)}",
                            f"Applications are open and close on {closes:%d %B %Y}.",
                            closes.isoformat(), days,
                            "", closes.isoformat(), confidence, note, True)
        days = (opens - today).days
        return Resolved(_grade(days) if days <= SOON_DAYS else "upcoming",
                        f"Opens {_countdown(days)}",
                        f"Window runs {opens:%d %B %Y} to {closes:%d %B %Y}.",
                        opens.isoformat(), days,
                        opens.isoformat(), closes.isoformat(), confidence, note, False)

    if kind == "rolling":
        return Resolved("rolling", "Rolling", "No fixed deadline - applications are handled continuously.",
                        "", None, "", "", confidence, note, True)

    return Resolved("unknown", "Date varies", "No single published date - check the official links.",
                    "", None, "", "", confidence, note, True)


def upcoming_sort_key(resolved: Resolved) -> tuple[int, int]:
    """Sort so live and imminent things float to the top."""
    order = {"urgent": 0, "open": 1, "soon": 2, "upcoming": 3, "rolling": 4, "unknown": 5}
    return (order.get(resolved.state, 9), resolved.days if resolved.days is not None else 99999)


def stale_days(iso: str, today: date | None = None) -> int | None:
    today = today or date.today()
    try:
        return (today - date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def add_days(today: date, n: int) -> date:
    return today + timedelta(days=n)
