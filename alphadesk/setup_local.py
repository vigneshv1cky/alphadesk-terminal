"""First-time setup for one person running their own server (2026-10-03).

Writes a settings file beside the data (config.DATA_DIR/.env) holding the three
things a fresh install cannot guess: a vault key to seal vendor keys, the
contact address the SEC wants in every request, and sign-in switched off for
a single-person instance.

`--like-cloud` makes the settings the live server runs on instead: Postgres, a
login (an email and a password hash) in place of "no sign-in", and the longer
retention — so what runs on a laptop is what runs in the cloud, differing only
in where it is.

The vault key is made here, once, on purpose and in view — never silently at
start (alphadesk/ledger/vault.py): losing it makes every stored key
unreadable, so an existing file is never overwritten, and the key is the
reason the file is created with owner-only permissions.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from urllib.parse import urlparse

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


DEFAULT_DATABASE_URL = "postgresql://localhost:5432/alphadesk"
_DB_NAME = re.compile(r"[A-Za-z0-9_]{1,63}")


def ensure_database(database_url: str) -> str:
    """Make sure the Postgres database named by the URL exists, making it if the
    server is reachable and it is not. Returns a sentence about what happened;
    never raises (the settings are written either way, and the sentence says
    what to start)."""
    u = urlparse(database_url)
    name = (u.path or "/").lstrip("/")
    if not _DB_NAME.fullmatch(name):
        return f"the database name {name!r} is not a plain name; create it yourself"
    try:
        import pg8000.dbapi
        conn = pg8000.dbapi.connect(user=u.username or os.environ.get("USER", "postgres"), password=u.password,
                                    host=u.hostname or "localhost", port=u.port or 5432, database="postgres")
    except Exception as exc:                                     # noqa: BLE001
        return (f"Postgres is not reachable at {u.hostname or 'localhost'}:{u.port or 5432} ({type(exc).__name__}): start it "
                "(for example `brew services start postgresql@16`), then run the dashboard; "
                f"the database {name!r} is made on first start if you create it with `createdb {name}`")
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cur.fetchone():
            return f"database {name!r} already exists"
        cur.execute(f'CREATE DATABASE "{name}"')                 # the name is checked above
        return f"database {name!r} created"
    except Exception as exc:                                     # noqa: BLE001
        return f"could not make the database {name!r} ({type(exc).__name__}); create it with `createdb {name}`"
    finally:
        conn.close()


def run_init(email: str, quiet: bool = False, like_cloud: bool = False, login_email: str | None = None,
             password_hash: str | None = None, database_url: str | None = None) -> int:
    from alphadesk.config import DATA_DIR
    path = DATA_DIR / ".env"
    if path.exists():
        if not quiet:
            print(f"already set up: {path} exists and was left as it is")
        return 0
    if not _EMAIL.fullmatch(email or ""):
        print("--email must be a real address, such as you@example.com", file=sys.stderr)
        return 1
    key = base64.b64encode(os.urandom(32)).decode()
    lines = [
        "# Written by `python -m alphadesk.main init`. Keep a copy of the vault key:",
        "# without it the vendor keys stored here cannot be opened.",
        f"ALPHADESK_VAULT_KEY={key}",
        f"SEC_USER_AGENT=AlphaDesk ({email})",
    ]
    note = ""
    if like_cloud:
        login = (login_email or email).strip().lower()
        if not _EMAIL.fullmatch(login):
            print("the login must be a real email address", file=sys.stderr)
            return 1
        if not password_hash or not password_hash.startswith("scrypt$"):
            print("a login needs a password hash (made by `hash-password`)", file=sys.stderr)
            return 1
        db_url = database_url or DEFAULT_DATABASE_URL
        lines += [
            "# The same settings the cloud runs on: Postgres, and a login of your own.",
            f"ALPHADESK_DATABASE_URL={db_url}",
            f"ALPHADESK_LOGIN_EMAIL={login}",
            f"ALPHADESK_LOGIN_PASSWORD_HASH='{password_hash}'",
        ]
        note = ensure_database(db_url)
    else:
        lines += [
            "# One person, no sign-in. Keep DASHBOARD_HOST on 127.0.0.1 unless something",
            "# else in front of the server asks for a password.",
            "ALPHADESK_AUTH=off",
        ]
        if database_url:
            lines.append(f"ALPHADESK_DATABASE_URL={database_url}")
    lines += [
        "# Keep what the server fetches (stories, the forecast log, scraped pages) instead of the",
        "# short defaults, and reach further back when it has less. A vendor's terms about",
        "# storing its data still apply to you.",
        "ALPHADESK_KEEP_DATA=forever",
    ]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    if not quiet:
        print(f"set up: {path}")
        if note:
            print(f"database: {note}")
        print("next:   python -m alphadesk.main dashboard   (then open http://127.0.0.1:8000"
              + (f" and sign in as {(login_email or email).strip().lower()})" if like_cloud else ")"))
    return 0
