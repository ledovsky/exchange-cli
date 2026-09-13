"""Config loading and the exchangelib Account."""
import os
import subprocess
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

AUTH_TYPES = ("ntlm", "basic")


class ExchError(Exception):
    """An error with a message meant for the user; the CLI prints it and exits 1."""


def config_path() -> Path:
    return Path(os.environ.get("EXCH_CONFIG", "~/.config/exch/config.toml")).expanduser()


@dataclass
class Config:
    server: str = ""            # host name or full EWS URL
    email: str = ""             # primary SMTP address of the mailbox
    username: str = ""          # DOMAIN\user or UPN; empty = email
    auth_type: str = "ntlm"     # ntlm | basic
    timezone: str = ""          # IANA name for displayed times; empty = local zone
    password_env: str = "EXCH_PASSWORD"
    password_command: str = ""  # shell command printing the password; wins over password_env

    @property
    def ews_url(self) -> str:
        if self.server.startswith(("https://", "http://")):
            return self.server
        return f"https://{self.server}/EWS/Exchange.asmx"

    @property
    def login(self) -> str:
        return self.username or self.email


CONFIG_KEYS = tuple(f.name for f in fields(Config))


def load_config(env: bool = True) -> Config:
    """Config file values, overridden by EXCH_<KEY> env vars unless env=False."""
    values = {}
    path = config_path()
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ExchError(f"Bad config {path}: {e}")
        unknown = set(data) - set(CONFIG_KEYS)
        if unknown:
            raise ExchError(f"Unknown keys in {path}: {', '.join(sorted(unknown))}")
        values.update(data)
    for key in CONFIG_KEYS if env else ():
        value = os.environ.get(f"EXCH_{key.upper()}")
        if value:
            values[key] = value
    return Config(**values)


def save_config(config: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = Config()
    lines = []
    for key in CONFIG_KEYS:
        value = getattr(config, key)
        if value != getattr(defaults, key) or key in ("server", "email"):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    return path


def get_password(config: Config) -> str:
    if config.password_command:
        result = subprocess.run(config.password_command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise ExchError(f"password_command failed (exit {result.returncode}): "
                            f"{result.stderr.strip() or 'no output'}")
        password = result.stdout.rstrip("\r\n")
        if not password:
            raise ExchError("password_command printed nothing")
        return password
    password = os.environ.get(config.password_env)
    if not password:
        raise ExchError(f"No password: set ${config.password_env} or password_command in {config_path()}")
    return password


def get_account(config: Config | None = None):
    from exchangelib import BASIC, DELEGATE, NTLM, Account, Configuration, Credentials, EWSTimeZone
    from exchangelib.protocol import BaseProtocol

    config = config or load_config()
    missing = [k for k in ("server", "email") if not getattr(config, k)]
    if missing:
        raise ExchError(f"Not configured ({', '.join(missing)} missing). Run:\n"
                        "  exch configure --server mail.example.com --email you@example.com")
    if config.auth_type not in AUTH_TYPES:
        raise ExchError(f"auth_type must be one of {', '.join(AUTH_TYPES)}, got '{config.auth_type}'")

    BaseProtocol.TIMEOUT = 30
    ews_config = Configuration(
        service_endpoint=config.ews_url,
        credentials=Credentials(username=config.login, password=get_password(config)),
        auth_type={"ntlm": NTLM, "basic": BASIC}[config.auth_type],
        max_connections=4,
    )
    return Account(
        primary_smtp_address=config.email,
        config=ews_config,
        autodiscover=False,
        access_type=DELEGATE,
        default_timezone=EWSTimeZone(config.timezone) if config.timezone else None,
    )


def explain_error(exc: Exception, config: Config) -> str | None:
    """Turn connection/auth failures into a one-line hint, or None if unknown."""
    import requests
    from exchangelib.errors import TransportError, UnauthorizedError, UnknownTimeZone

    if isinstance(exc, UnknownTimeZone):
        return f"Unknown timezone '{config.timezone}': use an IANA name like Europe/London"
    if isinstance(exc, UnauthorizedError):
        return f"Authentication failed for {config.login} (check the password and username)"
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, TransportError)):
        return (f"Cannot reach {config.ews_url}: {exc.__class__.__name__}. "
                "Check the server name and the network (VPN, proxy, firewall)")
    return None
