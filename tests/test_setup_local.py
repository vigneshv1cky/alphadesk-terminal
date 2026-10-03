"""`alphadesk init`: the one-person setup writes a private settings file once and
never replaces it (the vault key in it cannot be remade)."""
import base64
import os
import stat

from alphadesk import config, setup_local


def test_init_writes_a_private_file_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert setup_local.run_init("me@example.com") == 0
    path = tmp_path / ".env"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lines = dict(l.split("=", 1) for l in path.read_text().splitlines() if "=" in l and not l.startswith("#"))
    assert len(base64.b64decode(lines["ALPHADESK_VAULT_KEY"])) == 32
    assert lines["SEC_USER_AGENT"] == "AlphaDesk (me@example.com)"
    assert lines["ALPHADESK_AUTH"] == "off" and lines["ALPHADESK_KEEP_DATA"] == "forever"
    before = path.read_text()
    assert setup_local.run_init("other@example.com", quiet=True) == 0      # a second run changes nothing
    assert path.read_text() == before


def test_init_refuses_something_that_is_not_an_email(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert setup_local.run_init("not-an-email") == 1
    assert not (tmp_path / ".env").exists()
