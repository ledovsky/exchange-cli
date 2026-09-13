"""Mail: folders, listing, reading, sending and item actions."""
import mimetypes
from html.parser import HTMLParser
from pathlib import Path

from .account import ExchError

# Aliases for well-known folders; real names depend on the mailbox language (e.g. "Входящие").
WELL_KNOWN = {
    "inbox": "inbox",
    "sent": "sent",
    "drafts": "drafts",
    "deleted": "trash",
    "trash": "trash",
    "junk": "junk",
    "outbox": "outbox",
}

LIST_FIELDS = ("id", "subject", "sender", "datetime_received", "is_read", "has_attachments")


# ── helpers ────────────────────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def fmt_dt(account, dt) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(account.default_timezone).strftime("%Y-%m-%d %H:%M")


def fmt_mailbox(mb) -> str:
    if mb is None:
        return "-"
    if mb.name and mb.email_address and mb.name != mb.email_address:
        return f"{mb.name} <{mb.email_address}>"
    return mb.email_address or mb.name or "-"


def _split_addrs(values: list[str] | None) -> list[str]:
    return [a.strip() for v in values or [] for a in v.split(",") if a.strip()]


def _read_body(body: str | None, body_file: str | None) -> str:
    if body_file:
        return Path(body_file).expanduser().read_text()
    return body or ""


def _make_body(text: str, html: bool):
    from exchangelib import Body, HTMLBody
    return HTMLBody(text) if html else Body(text)


def resolve_folder(account, name: str):
    """Alias (`inbox`), alias path (`inbox/Projects`), unique name, or path under the root."""
    parts = [p for p in name.strip("/").split("/") if p]
    if not parts:
        raise ExchError("Empty folder name")
    alias = WELL_KNOWN.get(parts[0].lower())
    if alias:
        start, rest = getattr(account, alias), parts[1:]
    else:
        start, rest = account.msg_folder_root, parts
    if not rest:
        return start

    if len(rest) == 1:
        target = rest[0].lower()
        matches = [f for f in start.walk() if (f.name or "").lower() == target]
        if len(matches) == 1:
            return matches[0]
        if matches:
            paths = "\n  ".join(folder_path(account, f) for f in matches)
            raise ExchError(f"Folder name '{rest[0]}' is ambiguous, use a path:\n  {paths}")
        raise ExchError(f"Folder not found: {name}")

    folder = start
    for part in rest:
        child = next((c for c in folder.children if (c.name or "").lower() == part.lower()), None)
        if child is None:
            raise ExchError(f"Folder not found: {name}")
        folder = child
    return folder


def folder_path(account, folder) -> str:
    root = account.msg_folder_root.absolute
    return folder.absolute.removeprefix(root).lstrip("/")


def get_item(account, item_id: str):
    items = list(account.fetch(ids=[(item_id, None)]))
    item = items[0] if items else None
    if item is None or isinstance(item, Exception):
        raise ExchError(f"Item not found: {item_id} ({item})")
    return item


def _print_items(account, items):
    count = 0
    for item in items:
        count += 1
        flags = ("" if item.is_read else "*") + ("@" if item.has_attachments else "")
        print(f"{fmt_dt(account, item.datetime_received)}  {flags:<2} {fmt_mailbox(item.sender)}")
        print(f"  {item.subject or '(no subject)'}")
        print(f"  id: {item.id}")
        print()
    if not count:
        print("No messages.")
    else:
        print("(* unread, @ has attachments)")


# ── commands ───────────────────────────────────────────────────────────────
def mail_folders(account):
    root = account.msg_folder_root
    for f in root.walk():
        if f.folder_class and not f.folder_class.startswith("IPF.Note"):
            continue
        path = folder_path(account, f)
        depth = path.count("/")
        unread = f" ({f.unread_count} unread)" if f.unread_count else ""
        print(f"{'  ' * depth}{f.name}  [{f.total_count}]{unread}")


def mail_list(account, folder: str, count: int, unread: bool):
    qs = resolve_folder(account, folder).all()
    if unread:
        qs = qs.filter(is_read=False)
    _print_items(account, qs.only(*LIST_FIELDS).order_by("-datetime_received")[:count])


def mail_search(account, query: str, folder: str, count: int):
    qs = resolve_folder(account, folder).filter(query)
    _print_items(account, qs.only(*LIST_FIELDS).order_by("-datetime_received")[:count])


def mail_read(account, item_id: str, html: bool):
    from exchangelib import FileAttachment

    item = get_item(account, item_id)
    print(f"From    : {fmt_mailbox(getattr(item, 'sender', None))}")
    print(f"To      : {', '.join(fmt_mailbox(r) for r in item.to_recipients or []) or '-'}")
    if getattr(item, "cc_recipients", None):
        print(f"Cc      : {', '.join(fmt_mailbox(r) for r in item.cc_recipients)}")
    print(f"Date    : {fmt_dt(account, item.datetime_received)}")
    print(f"Subject : {item.subject or '(no subject)'}")
    attachments = [a for a in item.attachments or [] if not getattr(a, "is_inline", False)]
    if attachments:
        print("Attachments:")
        for a in attachments:
            size = f", {a.size} bytes" if a.size else ""
            kind = "file" if isinstance(a, FileAttachment) else "item"
            print(f"  - {a.name} ({kind}{size})")
    print()
    body = item.body or ""
    if html:
        print(body)
    elif getattr(item, "text_body", None):
        print(item.text_body.strip())
    elif body.__class__.__name__ == "HTMLBody":
        print(html_to_text(body))
    else:
        print(body.strip())


def mail_send(account, to, cc, bcc, subject, body, body_file, attach, html, draft):
    from exchangelib import FileAttachment, Mailbox, Message

    to, cc, bcc = _split_addrs(to), _split_addrs(cc), _split_addrs(bcc)
    if not (to or cc or bcc) and not draft:
        raise ExchError("No recipients: pass --to, --cc or --bcc")
    msg = Message(
        account=account,
        folder=account.drafts if draft else account.sent,
        subject=subject,
        body=_make_body(_read_body(body, body_file), html),
        to_recipients=[Mailbox(email_address=a) for a in to],
        cc_recipients=[Mailbox(email_address=a) for a in cc],
        bcc_recipients=[Mailbox(email_address=a) for a in bcc],
    )
    for path in attach or []:
        p = Path(path).expanduser()
        if not p.is_file():
            raise ExchError(f"Attachment not found: {path}")
        content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        msg.attach(FileAttachment(name=p.name, content=p.read_bytes(), content_type=content_type))

    if draft:
        msg.save()
        print(f"Draft saved: {msg.subject}")
        print(f"id: {msg.id}")
    else:
        msg.send_and_save()
        print(f"Sent: {msg.subject} → {', '.join(to + cc + bcc)}")


def mail_reply(account, item_id, body, body_file, reply_all, html, draft):
    # Built by hand rather than item.create_reply(): exchangelib only has that on Message,
    # but meeting invites (MeetingRequest etc.) are repliable too.
    from exchangelib.items import ReplyAllToItem, ReplyToItem
    from exchangelib.properties import ReferenceItemId

    item = get_item(account, item_id)
    text = _read_body(body, body_file)
    subject = item.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"RE: {subject}"

    author = getattr(item, "author", None) or getattr(item, "sender", None)
    if author is None:
        raise ExchError("Message has no sender to reply to")
    me = account.primary_smtp_address.lower()
    to, cc = [author], []
    if reply_all:
        seen = {(author.email_address or "").lower(), me}
        for field, target in (("to_recipients", to), ("cc_recipients", cc)):
            for r in getattr(item, field, None) or []:
                addr = (r.email_address or "").lower()
                if addr and addr not in seen:
                    seen.add(addr)
                    target.append(r)

    cls = ReplyAllToItem if reply_all else ReplyToItem
    reply = cls(
        account=account,
        reference_item_id=ReferenceItemId(id=item.id, changekey=item.changekey),
        subject=subject,
        new_body=_make_body(text, html),
        to_recipients=to,
        cc_recipients=cc,
    )
    if draft:
        saved = reply.save(account.drafts)
        print(f"Reply draft saved: {subject}")
        if getattr(saved, "id", None):
            print(f"id: {saved.id}")
    else:
        reply.send()
        print(f"Replied{' to all' if reply_all else ''}: {subject}")


def mail_attachments(account, item_id, out):
    from exchangelib import FileAttachment

    item = get_item(account, item_id)
    out_dir = Path(out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for a in item.attachments or []:
        if not isinstance(a, FileAttachment):
            print(f"Skipped non-file attachment: {a.name}")
            continue
        target = out_dir / Path(a.name or "attachment").name
        stem, suffix, n = target.stem, target.suffix, 1
        while target.exists():
            target = out_dir / f"{stem} ({n}){suffix}"
            n += 1
        target.write_bytes(a.content)
        print(f"Saved {target} ({len(a.content)} bytes)")
        saved += 1
    if not saved:
        print("No file attachments.")


def mail_mark(account, item_id, read: bool):
    item = get_item(account, item_id)
    item.is_read = read
    item.save(update_fields=["is_read"])
    print(f"Marked {'read' if read else 'unread'}: {item.subject}")


def mail_move(account, item_id, folder):
    item = get_item(account, item_id)
    target = resolve_folder(account, folder)
    item.move(target)
    print(f"Moved to {folder_path(account, target)}: {item.subject}")
    print(f"id: {item.id}")


def mail_delete(account, item_id):
    item = get_item(account, item_id)
    item.move_to_trash()
    print(f"Moved to Deleted Items: {item.subject}")
