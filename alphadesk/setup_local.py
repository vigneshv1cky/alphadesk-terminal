"""First-time setup for one person running their own server (2026-10-03).

Writes a settings file beside the data (config.DATA_DIR/.env) holding the three
things a fresh install cannot guess: a vault key to seal vendor keys, the
contact address the SEC wants in every request, and sign-in switched off for
a single-person instance.

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

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def run_init(email: str, quiet: bool = False) -> int:
    from alphadesk.config import DATA_DIR
    path = DATA_DIR / ".env"
    if path.exists():
        if not quiet:
            print(f"already set up: {path} exists and was left as it is")
        return 0
    if not _EMAIL.match(email or ""):
        print("--email must be a real address, such as you@example.com", file=sys.stderr)
        return 1
    key = base64.b64encode(os.urandom(32)).decode()
    text = (
        "# Written by `python -m alphadesk.main init`. Keep a copy of the vault key:\n"
        "# without it the vendor keys stored here cannot be opened.\n"
        f"ALPHADESK_VAULT_KEY={key}\n"
        f"SEC_USER_AGENT=AlphaDesk ({email})\n"
        "# One person, no sign-in. Keep DASHBOARD_HOST on 127.0.0.1 unless something\n"
        "# else in front of the server asks for a password.\n"
        "ALPHADESK_AUTH=off\n"
        "# Keep what the server fetches (stories, the forecast log, scraped pages) instead of the\n"
        "# short defaults, and reach further back when it has less. A vendor's terms about\n"
        "# storing its data still apply to you.\n"
        "ALPHADESK_KEEP_DATA=forever\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    if not quiet:
        print(f"set up: {path}")
        print("next:   python -m alphadesk.main dashboard   (then open http://127.0.0.1:8000)")
    return 0
