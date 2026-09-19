"""The key vault's crypto: AES-256-GCM envelope encryption for user API keys.

The master key comes from ALPHADESK_VAULT_KEY — 32 bytes, base64. It is
REQUIRED to enable the vault and is never generated silently: losing it must
be a deliberate impossibility, not a restart surprise, because every stored
user key dies with it.

Each row encrypts a whole JSON config object (key, and for the LLM seam base
URL + model) under a fresh random 96-bit nonce; the stored value is
`nonce || ciphertext || tag`, base64. Encrypting the object rather than the
key field means no per-field decisions later when a provider needs more than
a bare key.

The decrypted value exists in memory for the duration of constructing a
provider, and is never put in an error message, a log line, or a prompt —
every exception below speaks about the vault, never about the plaintext.
"""

from __future__ import annotations

import base64
import json
import os

_ENV = "ALPHADESK_VAULT_KEY"
_NONCE_LEN = 12


class VaultError(Exception):
    """The vault cannot serve — wrong master key, missing key, or a corrupt
    row. The message never contains key material."""


def _master(env: str = _ENV) -> bytes:
    raw = (os.environ.get(env) or "").strip()
    if not raw:
        raise VaultError(
            f"{env} is not set — the vault is disabled until the operator "
            "provides a 32-byte base64 master key")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise VaultError(f"{env} is not valid base64") from exc
    if len(key) != 32:
        raise VaultError(f"{env} must decode to exactly 32 bytes (got {len(key)})")
    return key


def enabled() -> bool:
    """Whether the vault can serve. False surfaces as an honest 'not
    configured' in the API rather than a crash on first use."""
    try:
        _master()
        return True
    except VaultError:
        return False


def encrypt(config: dict, *, env: str = _ENV) -> str:
    """Seal one config object. Fresh nonce per call — never reused."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(_NONCE_LEN)
    sealed = AESGCM(_master(env)).encrypt(nonce, json.dumps(config).encode(), None)
    return base64.b64encode(nonce + sealed).decode()


def decrypt(blob: str, *, env: str = _ENV) -> dict:
    """Open one sealed config. A wrong master key and a tampered row fail the
    same way — GCM's tag check — and both surface as the same VaultError."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        raw = base64.b64decode(blob)
        opened = AESGCM(_master(env)).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], None)
        return json.loads(opened.decode())
    except VaultError:
        raise
    except Exception as exc:
        raise VaultError(
            "stored key cannot be opened — wrong master key or corrupt row"
        ) from exc
