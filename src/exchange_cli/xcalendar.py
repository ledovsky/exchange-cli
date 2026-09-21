"""Calendar: read-only listing of events (recurring events expanded), own or other people's."""
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


def _as_datetime(value, tz):
    """All-day events can come with plain dates; make them sortable with datetimes."""
    from exchangelib import EWSDateTime

    if isinstance(value, dt.datetime):
        return value
    return EWSDateTime(value.year, value.month, value.day, tzinfo=tz)


def _print_events(account, events, show_ids: bool = True):
    """events: dicts with start, end, all_day, title and optional details, id."""
    tz = account.default_timezone
    current_day = None
    for e in sorted(events, key=lambda e: _as_datetime(e["start"], tz)):
        day = _as_datetime(e["start"], tz).astimezone(tz).date()
        if day != current_day:
            if current_day is not None:
                print()
            print(day.strftime("%Y-%m-%d %a"))
            current_day = day
        when = "all day    " if e["all_day"] else f"{_fmt_time(account, e['start'])}-{_fmt_time(account, e['end'])}"
        print(f"  {when}  {e['title']}")
        pad = " " * 15
        if e.get("details"):
            print(f"{pad}{' | '.join(e['details'])}")
        if show_ids and e.get("id"):
            print(f"{pad}id: {e['id']}")


def _folder_events(folder, start, end) -> list[dict]:
    events = []
    for e in folder.view(start=start, end=end).only(*EVENT_FIELDS):
        details = []
        if e.location:
            details.append(f"Location: {e.location}")
        if e.organizer:
            details.append(f"Organizer: {fmt_mailbox(e.organizer)}")
        if e.my_response_type and e.my_response_type != "Organizer":
            details.append(f"Response: {e.my_response_type}")
        events.append({
            "start": e.start, "end": e.end,
            "all_day": e.is_all_day or not isinstance(e.start, dt.datetime),
            "title": f"{e.subject or '(no subject)'}{' [cancelled]' if e.is_cancelled else ''}",
            "details": details, "id": e.id,
        })
    return events


# ── other people's calendars ───────────────────────────────────────────────
def _resolve_user(account, user: str):
    """An address is used as is; anything else is looked up in the directory."""
    from exchangelib.properties import Mailbox

    if "@" in user:
        return Mailbox(email_address=user)
    found = []
    for result in account.protocol.resolve_names([user], return_full_contact_data=True):
        if isinstance(result, Exception):
            continue
        mailbox, contact = result
        if mailbox is None or not mailbox.email_address:
            continue
        if contact is not None and contact.display_name:  # the mailbox name is often just the login
            mailbox.name = contact.display_name
        found.append(mailbox)
    if not found:
        raise ExchError(f"Nobody found for '{user}'")
    if len(found) > 1:
        shown = "\n".join(f"  {fmt_mailbox(m)}" for m in found[:10])
        more = f"\n  … and {len(found) - 10} more" if len(found) > 10 else ""
        raise ExchError(f"'{user}' matches {len(found)} people, use the address:\n{shown}{more}")
    return found[0]


def _no_access_errors() -> tuple:
    from exchangelib.errors import (ErrorAccessDenied, ErrorFolderNotFound, ErrorItemNotFound,
                                    ErrorNonExistentMailbox)
    return ErrorAccessDenied, ErrorFolderNotFound, ErrorItemNotFound, ErrorNonExistentMailbox


def _shared_calendar(account, email: str):
    """The user's calendar folder if we may read its items, else None."""
    from exchangelib.folders import Calendar, SingleFolderQuerySet
    from exchangelib.properties import DistinguishedFolderId, Mailbox

    no_access = _no_access_errors()
    shared = Calendar(root=account.root, _distinguished_id=DistinguishedFolderId(
        id=Calendar.DISTINGUISHED_FOLDER_ID, mailbox=Mailbox(email_address=email)))
    try:
        folder = SingleFolderQuerySet(account=account, folder=shared).resolve()
    except no_access:
        return None
    if isinstance(folder, no_access):
        return None
    if isinstance(folder, Exception):
        raise folder
    # Free/busy-only permissions let us see the folder but not its items
    rights = folder.effective_rights
    if rights is None or not rights.read:
        return None
    # Not the resolved folder: exchangelib points its distinguished id back at our own mailbox
    return shared


def _free_busy_events(account, email: str, start, end) -> tuple[list[dict], str]:
    """Events from GetUserAvailability: what the scheduling assistant in Outlook shows."""
    from exchangelib.errors import ErrorMailRecipientNotFound, ResponseMessageError

    try:
        view = next(iter(account.protocol.get_free_busy_info(
            accounts=[(email, "Required", False)], start=start, end=end)))
        if isinstance(view, Exception):
            raise view
    except ErrorMailRecipientNotFound:
        raise ExchError(f"No such mailbox: {email}")
    except ResponseMessageError as e:
        raise ExchError(f"Cannot get free/busy of {email}: {e}")

    day = dt.timedelta(days=1)
    midnight = dt.time(0, 0)
    events = []
    for e in view.calendar_events or []:
        d = e.details
        if d is not None and d.subject:
            title = d.subject if e.busy_type == "Busy" else f"{d.subject} [{e.busy_type.lower()}]"
        else:
            title = f"{e.busy_type}{' (private)' if d is not None and d.is_private else ''}"
        local_start, local_end = (v.astimezone(account.default_timezone) for v in (e.start, e.end))
        events.append({
            "start": e.start, "end": e.end,
            "all_day": local_start.time() == local_end.time() == midnight and e.end - e.start >= day,
            "title": title,
            "details": [f"Location: {d.location}"] if d is not None and d.location else [],
        })
    return events, view.view_type


def _span(first: dt.date, days: int) -> str:
    return first.isoformat() if days == 1 else f"{first} … {first + dt.timedelta(days=days - 1)}"


def calendar_list(account, date_str: str, days: int, users: list[str] | None = None):
    from exchangelib import EWSDateTime

    if days < 1:
        raise ExchError("--days must be >= 1")
    tz = account.default_timezone
    first = _parse_date(date_str, EWSDateTime.now(tz).date())
    start = EWSDateTime(first.year, first.month, first.day, tzinfo=tz)
    end = start + dt.timedelta(days=days)

    if not users:
        events = _folder_events(account.calendar, start, end)
        if not events:
            print(f"No events on {_span(first, days)}.")
            return
        _print_events(account, events)
        return

    account.protocol.version  # name lookup and free/busy need the server version, guessed on first access
    for i, user in enumerate(users):
        if i:
            print()
        mailbox = _resolve_user(account, user)
        folder = _shared_calendar(account, mailbox.email_address)
        events = None
        if folder is not None:
            try:
                events, source = _folder_events(folder, start, end), "shared calendar"
            except _no_access_errors():
                pass
        if events is None:
            events, view_type = _free_busy_events(account, mailbox.email_address, start, end)
            source = "free/busy only" if view_type in ("FreeBusy", "FreeBusyMerged", "MergedOnly") \
                else "free/busy with details"
        print(f"== {fmt_mailbox(mailbox)} ({source})")
        if not events:
            print(f"No events on {_span(first, days)}.")
            continue
        _print_events(account, events, show_ids=False)
