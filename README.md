# exch — Exchange mailbox CLI

Command-line client for an on-premises Microsoft Exchange mailbox over EWS (Exchange Web
Services): mail and a read-only calendar. Built on
[exchangelib](https://github.com/ecederstrand/exchangelib); authenticates with NTLM or Basic.
Plain-text output, usable by humans and agents.

Tested against Exchange Server 2019. Exchange Online (Microsoft 365) needs OAuth and is not
supported.

## Install

Requires Python 3.11+. [uv](https://docs.astral.sh/uv/) is the recommended installer.

```bash
# run without installing
uvx --from git+https://github.com/ledovsky/exchange-cli exch --version

# install the `exch` command into ~/.local/bin
uv tool install git+https://github.com/ledovsky/exchange-cli
uv tool upgrade exchange-cli        # later

# pin a release
uv tool install "git+https://github.com/ledovsky/exchange-cli@v0.1.0"

# hack on it
git clone git@github.com:ledovsky/exchange-cli.git ~/projects/exchange-cli
uv tool install --editable ~/projects/exchange-cli
```

Private repository over SSH (for example on a server with a deploy key):
`uv tool install git+ssh://git@github.com/ledovsky/exchange-cli.git@v0.1.0`.

## Configuration

Nothing is built in: every machine that runs `exch` has its own config. Create it with
`exch configure`:

```bash
exch configure --server mail.example.com --email jane.doe@example.com \
  --username 'EXAMPLE\jdoe' --timezone Europe/London \
  --password-command 'pass show work/exchange'
exch whoami
```

`exch configure` writes `~/.config/exch/config.toml` (mode 0600). Run it again with any subset of
options to change only those. The file can also be edited by hand:

```toml
server = "mail.example.com"          # host (EWS at https://<host>/EWS/Exchange.asmx) or full EWS URL
email = "jane.doe@example.com"       # mailbox address
username = "EXAMPLE\\jdoe"           # DOMAIN\user or user@domain; default: email
auth_type = "ntlm"                   # ntlm (default) or basic
timezone = "Europe/London"           # IANA zone for displayed times; default: this machine's zone
password_command = "pass show work/exchange"
# password_env = "EXCH_PASSWORD"     # used when password_command is not set (default name)
```

Every key can be overridden by an environment variable `EXCH_<KEY>`: `EXCH_SERVER`,
`EXCH_EMAIL`, `EXCH_USERNAME`, `EXCH_AUTH_TYPE`, `EXCH_TIMEZONE`, `EXCH_PASSWORD_ENV`,
`EXCH_PASSWORD_COMMAND`. `EXCH_CONFIG` points at a different config file.

### Password

The password is never written to the config. `exch` gets it on every run from:

1. `password_command` — a shell command whose stdout is the password, e.g.
   `pass show work/exchange`, `security find-generic-password -s exchange -w` (macOS Keychain),
   `cat ~/.config/exch/password` (a 0600 file on a server);
2. otherwise the environment variable named by `password_env` (default `EXCH_PASSWORD`).

## Network access

The EWS endpoint must be reachable over HTTPS. Corporate servers are often reachable only from
the office network or a corporate VPN, and full-tunnel VPNs can block them. A connection problem
shows up after the 30 s timeout as:

```
Error: Cannot reach https://mail.example.com/EWS/Exchange.asmx: TransportError. Check the server name and the network (VPN, proxy, firewall)
```

`exch whoami` is the quickest check.

## Commands

Every message and event has an EWS id (a long base64 string) printed as `id: ...`; pass it to
`read`, `reply`, `attachments`, `mark`, `move`, `delete`. Ids change when an item is moved —
`move` prints the new one.

### configure / whoami

```bash
exch configure --server mail.example.com --email jane.doe@example.com
exch whoami
```

`whoami` connects, authenticates and prints the mailbox, EWS URL, server build, timezone and
inbox counts.

### folders

```bash
exch folders
```

Mail folder tree with total and unread counts.

**Folder arguments** (`--folder` in `list`, `search`, `move`) accept:

- a well-known alias: `inbox`, `sent`, `drafts`, `deleted` (or `trash`), `junk`, `outbox` —
  works whatever the mailbox language is;
- an alias path: `inbox/Projects`;
- a folder name found anywhere in the tree: `Archive` (the error lists paths if it is ambiguous);
- a path from the top of the mailbox: `Inbox/Projects/2026`.

Matching is case-insensitive.

### list

```bash
exch list                          # 20 newest in Inbox
exch list --unread --count 50
exch list --folder sent --count 5
```

Newest first. Flags: `*` unread, `@` has attachments.

### search

```bash
exch search "subject:report"
exch search "from:smith budget" --folder Archive --count 10
```

The query is AQS (Advanced Query Syntax), as in Outlook search: `from:`, `to:`, `subject:`,
`body:`, `hasattachment:true`, free text. Dates follow the server's locale, e.g.
`received:01.09.2026..05.09.2026` on a server with `dd.mm.yyyy` dates; a format the server does
not expect gives wrong or empty results.

### read

```bash
exch read <id>
exch read <id> --html     # raw HTML body
```

Headers, attachment list and the body as text. Does **not** mark the message read.

### send

```bash
exch send --to alice@example.com,bob@example.com --cc carol@example.com --subject "Hi" --body "Text"
exch send --to alice@example.com --subject "Report" --body-file report.html --html --attach report.pdf
exch send --to alice@example.com --subject "Later" --body "..." --draft     # save to Drafts only
```

`--to`/`--cc`/`--bcc` are repeatable and accept comma-separated lists. `--attach` is repeatable.
A sent message is saved to Sent Items.

### reply

```bash
exch reply <id> --body "Thanks!"
exch reply <id> --all --body-file answer.txt
exch reply <id> --body "..." --draft
```

Replies to the original author (the real sender even when a delegate sent it). `--all` adds
the other To/Cc recipients, excluding you. Exchange appends the quoted original. Works on
meeting invites too. Exchange marks the original message read, even for `--draft`.

### attachments

```bash
exch attachments <id> --out ~/Downloads
```

Saves file attachments; existing files are not overwritten (`name (1).ext`).

### mark / move / delete

```bash
exch mark <id> --read
exch mark <id> --unread
exch move <id> --folder Archive
exch delete <id>            # moves to Deleted Items (not a permanent delete)
```

### calendar

```bash
exch calendar                          # today
exch calendar --date tomorrow
exch calendar --date 2026-09-14 --days 7
exch calendar --user jane.doe@example.com      # someone else's calendar
```

Read-only. Recurring meetings are expanded. Shows time, subject, location, organizer, your
response and `[cancelled]` for cancelled meetings. `--date` takes `today`, `tomorrow`,
`yesterday` or `YYYY-MM-DD`.

**Other people's calendars** — `--user`, repeatable, takes an address or a name to look up in
the directory (an ambiguous name lists the matches):

```bash
exch calendar --user jane.doe@example.com
exch calendar --user "Jane Doe" --user bob@example.com --date tomorrow --days 3
```

What you see depends on what the person shares with you, as in Outlook; the header line of each
calendar says which one it was:

- `shared calendar` — you have read access to their calendar folder: same details as your own;
- `free/busy with details` — the organization default on many servers: time, subject, location,
  and the status when it is not Busy (`[tentative]`, `[oof]`, …); private events show as
  `Busy (private)`;
- `free/busy only` — time and status.

Free/busy requests are limited by the server to a window of about two months (`--days`).

## Errors

Exit code 1 with a one-line `Error: ...` for: missing config or password, auth failure,
unreachable server, unknown folder, item, person or timezone.

## Development

```bash
git clone git@github.com:ledovsky/exchange-cli.git && cd exchange-cli
uv sync
uv run exch --version
```

Everything that talks to Exchange is verified by hand against a real mailbox.

Layout: `src/exchange_cli/` — `account.py` (config, password, EWS account), `mail.py`,
`xcalendar.py`, `cli.py` (argparse wiring).

## License

MIT, see `LICENSE`.
