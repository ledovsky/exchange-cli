"""Calendar: read-only listing of events (recurring events expanded)."""
import datetime as dt

from .account import ExchError
from .mail import fmt_mailbox

EVENT_FIELDS = ("id", "subject", "start", "end", "location", "organizer", "is_all_day",
                "is_cancelled", "my_response_type")


def _parse_date(value: str, today: dt.date) -> dt.date:
    v = value.lower()
    if v == "today":
        return today
    if v == "tomorrow":
        return today + dt.timedelta(days=1)
    if v == "yesterday":
        return today - dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ExchError(f"Bad --date '{value}': use today, tomorrow, yesterday or YYYY-MM-DD")


def _fmt_time(account, value) -> str:
    return value.astimezone(account.default_timezone).strftime("%H:%M")


def calendar_list(account, date_str: str, days: int):
    from exchangelib import EWSDateTime

    if days < 1:
        raise ExchError("--days must be >= 1")
    tz = account.default_timezone
    first = _parse_date(date_str, EWSDateTime.now(tz).date())
    start = EWSDateTime(first.year, first.month, first.day, tzinfo=tz)
    end = start + dt.timedelta(days=days)

    events = account.calendar.view(start=start, end=end).only(*EVENT_FIELDS)
    events = sorted(events, key=lambda e: e.start if isinstance(e.start, dt.datetime)
                    else EWSDateTime(e.start.year, e.start.month, e.start.day, tzinfo=tz))
    if not events:
        span = first.isoformat() if days == 1 else f"{first} … {first + dt.timedelta(days=days - 1)}"
        print(f"No events on {span}.")
        return

    current_day = None
    for e in events:
        is_all_day = e.is_all_day or not isinstance(e.start, dt.datetime)
        day = e.start if not isinstance(e.start, dt.datetime) else e.start.astimezone(tz).date()
        if day != current_day:
            if current_day is not None:
                print()
            print(day.strftime("%Y-%m-%d %a"))
            current_day = day
        when = "all day    " if is_all_day else f"{_fmt_time(account, e.start)}-{_fmt_time(account, e.end)}"
        status = " [cancelled]" if e.is_cancelled else ""
        print(f"  {when}  {e.subject or '(no subject)'}{status}")
        details = []
        if e.location:
            details.append(f"Location: {e.location}")
        if e.organizer:
            details.append(f"Organizer: {fmt_mailbox(e.organizer)}")
        if e.my_response_type and e.my_response_type != "Organizer":
            details.append(f"Response: {e.my_response_type}")
        pad = " " * 15
        if details:
            print(f"{pad}{' | '.join(details)}")
        print(f"{pad}id: {e.id}")
