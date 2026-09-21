import argparse
import sys

from . import __version__
from .account import (AUTH_TYPES, ExchError, explain_error, get_account, load_config,
                      save_config)


# ── subcommand handlers ────────────────────────────────────────────────────
def cmd_configure(args):
    config = load_config(env=False)
    for key in ("server", "email", "username", "auth_type", "timezone"):
        value = getattr(args, key)
        if value is not None:
            setattr(config, key, value)
    if args.password_env is not None:
        config.password_env, config.password_command = args.password_env, ""
    if args.password_command is not None:
        config.password_command = args.password_command
    if not (config.server and config.email):
        raise ExchError("--server and --email are required for a new config")
    path = save_config(config)
    print(f"Saved {path}")
    print(path.read_text().rstrip())
    print("Check it with: exch whoami")


def cmd_whoami(args, account):
    config = load_config()
    inbox = account.inbox
    print(f"Email    : {account.primary_smtp_address}")
    print(f"Username : {config.login}")
    print(f"Server   : {config.ews_url} (build {account.version.build})")
    print(f"Timezone : {account.default_timezone.key}")
    print(f"Inbox    : {inbox.total_count} messages, {inbox.unread_count} unread")


# Mail
def cmd_folders(args, account):
    from .mail import mail_folders
    mail_folders(account)


def cmd_list(args, account):
    from .mail import mail_list
    mail_list(account, args.folder, args.count, args.unread)


def cmd_search(args, account):
    from .mail import mail_search
    mail_search(account, args.query, args.folder, args.count)


def cmd_read(args, account):
    from .mail import mail_read
    mail_read(account, args.id, args.html)


def cmd_send(args, account):
    from .mail import mail_send
    mail_send(account, args.to, args.cc, args.bcc, args.subject, args.body, args.body_file,
              args.attach, args.html, args.draft)


def cmd_reply(args, account):
    from .mail import mail_reply
    mail_reply(account, args.id, args.body, args.body_file, args.all, args.html, args.draft)


def cmd_attachments(args, account):
    from .mail import mail_attachments
    mail_attachments(account, args.id, args.out)


def cmd_mark(args, account):
    from .mail import mail_mark
    mail_mark(account, args.id, read=args.read)


def cmd_move(args, account):
    from .mail import mail_move
    mail_move(account, args.id, args.folder)


def cmd_delete(args, account):
    from .mail import mail_delete
    mail_delete(account, args.id)


# Calendar
def cmd_calendar(args, account):
    from .xcalendar import calendar_list
    calendar_list(account, args.date, args.days, args.user)


# ── parser ─────────────────────────────────────────────────────────────────
def _body_args(p: argparse.ArgumentParser):
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body", help="Message body text")
    g.add_argument("--body-file", help="Read the body from a file")
    p.add_argument("--html", action="store_true", help="Treat the body as HTML")
    p.add_argument("--draft", action="store_true", help="Save to Drafts instead of sending")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exch",
        description="Exchange (EWS) mailbox CLI: mail and calendar",
    )
    parser.add_argument("--version", action="version", version=f"exch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("configure", help="Write ~/.config/exch/config.toml",
                       description="Create or update the config file. Only the given options change.")
    p.add_argument("--server", help="Exchange host (mail.example.com) or full EWS URL")
    p.add_argument("--email", help="Mailbox address")
    p.add_argument("--username", help="Login: DOMAIN\\user or user@domain (default: email)")
    p.add_argument("--auth-type", choices=AUTH_TYPES, help="Default: ntlm")
    p.add_argument("--timezone", help="IANA timezone for displayed times (default: local)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--password-env", help="Env var holding the password (default: EXCH_PASSWORD)")
    g.add_argument("--password-command", help="Shell command that prints the password")
    p.set_defaults(func=cmd_configure, needs_account=False)

    p = sub.add_parser("whoami", help="Check the connection and show the mailbox")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("folders", help="Mail folder tree with message counts")
    p.set_defaults(func=cmd_folders)

    p = sub.add_parser("list", help="List messages, newest first")
    p.add_argument("--folder", default="inbox",
                   help="inbox|sent|drafts|deleted|junk, a folder name or a path (default: inbox)")
    p.add_argument("--count", type=int, default=20, help="Max messages (default: 20)")
    p.add_argument("--unread", action="store_true", help="Only unread messages")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="Search messages with an AQS query")
    p.add_argument("query", help='e.g. "from:ivanov subject:report", "invoice"')
    p.add_argument("--folder", default="inbox", help="Folder to search (default: inbox)")
    p.add_argument("--count", type=int, default=20, help="Max messages (default: 20)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("read", help="Show a message (does not mark it read)")
    p.add_argument("id", help="Item id from list/search")
    p.add_argument("--html", action="store_true", help="Print the raw HTML body")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("send", help="Send a message")
    p.add_argument("--to", action="append", help="Recipient(s), repeat or comma-separate")
    p.add_argument("--cc", action="append", help="Cc recipient(s)")
    p.add_argument("--bcc", action="append", help="Bcc recipient(s)")
    p.add_argument("--subject", required=True)
    p.add_argument("--attach", action="append", metavar="PATH", help="Attach a file, repeatable")
    _body_args(p)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("reply", help="Reply to a message")
    p.add_argument("id", help="Item id to reply to")
    p.add_argument("--all", action="store_true", help="Reply to all")
    _body_args(p)
    p.set_defaults(func=cmd_reply)

    p = sub.add_parser("attachments", help="Save a message's file attachments")
    p.add_argument("id", help="Item id")
    p.add_argument("--out", default=".", help="Output directory (default: current)")
    p.set_defaults(func=cmd_attachments)

    p = sub.add_parser("mark", help="Mark a message read or unread")
    p.add_argument("id", help="Item id")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--read", dest="read", action="store_true")
    g.add_argument("--unread", dest="read", action="store_false")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("move", help="Move a message to another folder")
    p.add_argument("id", help="Item id")
    p.add_argument("--folder", required=True, help="Target folder")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("delete", help="Move a message to Deleted Items")
    p.add_argument("id", help="Item id")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("calendar", help="List calendar events")
    p.add_argument("--date", default="today", help="today|tomorrow|yesterday|YYYY-MM-DD (default: today)")
    p.add_argument("--days", type=int, default=1, help="Number of days from --date (default: 1)")
    p.add_argument("--user", action="append", metavar="WHO",
                   help="Show this person's calendar instead of yours: an address or a name "
                        "to look up, repeatable")
    p.set_defaults(func=cmd_calendar)

    return parser


def main():
    args = build_parser().parse_args()
    config = None
    try:
        if not getattr(args, "needs_account", True):
            args.func(args)
            return
        config = load_config()
        args.func(args, get_account(config))
    except ExchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        hint = explain_error(e, config) if config else None
        if hint is None:
            raise
        print(f"Error: {hint}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
