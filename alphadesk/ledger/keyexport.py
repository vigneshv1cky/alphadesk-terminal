"""A reader's vendor keys, sealed under a passphrase they choose (2026-10-02).

The vault never shows a key after entry. An export is the one deliberate
exception, so the file it produces has to be useless without the passphrase:
scrypt turns the passphrase into a 256-bit key, and AES-256-GCM seals the
keys under it. The file is plain JSON a person can read the shape of — a
format name, a version, the scrypt settings, a salt, a nonce and the sealed
contents — and nothing in it names a vendor or a key.

Two things are guarded on opening, because the file is attacker-controlled
input there:

  * The scrypt settings come from the file, so they are bounded. A hostile
    file asking for gigabytes of memory is refused, not obeyed — and a file
    whose work factor was lowered to make guessing cheap is refused too.
  * The header is authenticated (it is the GCM associated data), so editing
    any of it breaks the file rather than quietly changing how it opens.

Every failure speaks about the file, never about what was in it: a wrong
passphrase and a damaged file read the same, as in the vault itself.
"""

from __future__ import annotations

import base64
import json
import os
import unicodedata

FORMAT = "alphadesk-keys"
PLAIN_FORMAT = "alphadesk-keys-plain"
VERSION = 1
MIN_PASSPHRASE = 12

# 32 MiB of memory and about a tenth of a second per guess on a laptop. The
# bounds on opening keep a file from asking for more, or for less.
_N, _R, _P = 2 ** 15, 8, 1
_N_MIN, _N_MAX = 2 ** 14, 2 ** 17
_SALT_LEN, _NONCE_LEN = 16, 12


class KeyFileError(Exception):
    """The file cannot be made or opened. The message never contains key
    material."""


def _passphrase_bytes(passphrase: str) -> bytes:
    # NFKC so the same words typed on another keyboard or system open the file.
    return unicodedata.normalize("NFKC", passphrase).encode("utf-8")


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(_passphrase_bytes(passphrase))


def _header(kdf: dict) -> dict:
    return {"format": FORMAT, "version": VERSION, "cipher": "aes-256-gcm", "kdf": kdf}


def _aad(header: dict) -> bytes:
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode()


def seal(payload: dict, passphrase: str) -> str:
    """The file's text for one payload. Fresh salt and nonce every call."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(passphrase) < MIN_PASSPHRASE:
        raise KeyFileError(f"the passphrase must be at least {MIN_PASSPHRASE} characters")
    salt, nonce = os.urandom(_SALT_LEN), os.urandom(_NONCE_LEN)
    kdf = {"name": "scrypt", "n": _N, "r": _R, "p": _P, "salt": base64.b64encode(salt).decode()}
    header = _header(kdf)
    sealed = AESGCM(_derive(passphrase, salt, _N, _R, _P)).encrypt(
        nonce, json.dumps(payload).encode(), _aad(header))
    return json.dumps({**header, "nonce": base64.b64encode(nonce).decode(),
                       "ciphertext": base64.b64encode(sealed).decode()}, indent=2) + "\n"


def plain(payload: dict) -> str:
    """The file's text for one payload with NO passphrase (2026-10-02): the
    keys readable as they are, for a reader who would rather guard the file
    than a passphrase. Anyone holding the file holds the keys."""
    return json.dumps({"format": PLAIN_FORMAT, "version": VERSION, **payload}, indent=2) + "\n"


def read_plain(text: str) -> dict | None:
    """The payload of a plain file, or None when the text is not one (a sealed
    file, or something else — open_file says which)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if isinstance(doc, dict) and doc.get("format") == PLAIN_FORMAT and doc.get("version") == VERSION:
        return {k: v for k, v in doc.items() if k not in ("format", "version")}
    return None


def open_file(text: str, passphrase: str) -> dict:
    """The payload a file holds, or KeyFileError."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        doc = json.loads(text)
    except ValueError:
        raise KeyFileError("this is not an AlphaDesk keys file") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise KeyFileError("this is not an AlphaDesk keys file")
    if doc.get("version") != VERSION:
        raise KeyFileError(f"unsupported keys file version {doc.get('version')!r}")
    try:
        kdf = doc["kdf"]
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
        salt = base64.b64decode(kdf["salt"], validate=True)
        nonce = base64.b64decode(doc["nonce"], validate=True)
        sealed = base64.b64decode(doc["ciphertext"], validate=True)
    except (KeyError, TypeError, ValueError):
        raise KeyFileError("the keys file is damaged") from None
    if kdf.get("name") != "scrypt" or r != _R or p != _P or not (_N_MIN <= n <= _N_MAX) or n & (n - 1):
        raise KeyFileError("the keys file asks for a work factor this tool does not accept")
    if len(salt) != _SALT_LEN or len(nonce) != _NONCE_LEN:
        raise KeyFileError("the keys file is damaged")
    try:
        opened = AESGCM(_derive(passphrase, salt, n, r, p)).decrypt(
            nonce, sealed, _aad(_header({"name": "scrypt", "n": n, "r": r, "p": p,
                                         "salt": kdf["salt"]})))
        return json.loads(opened.decode())
    except Exception:
        raise KeyFileError("the keys file cannot be opened — wrong passphrase or damaged file") from None


def restore(user_id: str, payload: dict) -> tuple[list[str], list[str]]:
    """Put an opened file's keys into an account, sealed under THIS instance's
    own vault key. Returns (restored, skipped), each as "seam:provider".

    An entry is held to what entering a key by hand is held to — a known seam,
    a vendor this instance has registered, a key that looks like one — so a
    file cannot put in a row the Account page would have refused. A skipped
    entry is named, never the key.
    """
    from alphadesk.ledger import store, vault
    from alphadesk.providers import registry

    restored: list[str] = []
    skipped: list[str] = []
    for entry in payload.get("keys") or []:
        seam, provider = str(entry.get("seam", "")), str(entry.get("provider", ""))
        label = f"{seam}:{provider}"
        api_key = str(entry.get("api_key") or "").strip()
        if (seam not in ("news", "prices", "transcripts") or len(api_key) < 8
                or provider not in registry.available(seam)[seam]):
            skipped.append(label)
            continue
        sealed = vault.encrypt({"api_key": api_key,
                                "api_secret": str(entry.get("api_secret") or "").strip(),
                                "base_url": str(entry.get("base_url") or "").strip(),
                                "model": str(entry.get("model") or "").strip()})
        plan = "paid" if str(entry.get("plan") or "").strip().lower() == "paid" else "free"
        store.set_user_key(user_id, seam, provider, sealed, api_key[-4:], vendor_plan=plan)
        restored.append(label)
    if restored:
        registry.forget_user_keys(user_id)
    return restored, skipped


def run_cli(action: str, path: str) -> int:
    """`keys decrypt FILE` (print the keys) and `keys import-file FILE` (seal
    them into this instance's local account). The passphrase comes from the
    prompt only: an argument or an environment variable would sit in shell
    history and process listings. Returns the exit status."""
    import getpass
    import json
    import sys

    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    try:
        payload = read_plain(text)
        if payload is None:
            payload = open_file(text, getpass.getpass("passphrase for the keys file: "))
    except KeyFileError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if action == "decrypt":
        print("these are your keys in plain text — keep this output out of shared logs and history",
              file=sys.stderr)
        print(json.dumps(payload, indent=2))
        return 0
    from alphadesk.ledger import store
    store.init()
    restored, skipped = restore(store.ensure_local_user(), payload)
    print(f"sealed into the local account: {', '.join(restored) or 'nothing'}")
    if skipped:
        print(f"skipped (unknown vendor or not a usable key): {', '.join(skipped)}", file=sys.stderr)
    return 0 if restored else 1
