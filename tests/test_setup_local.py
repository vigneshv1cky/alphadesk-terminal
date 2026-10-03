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


def test_a_python_with_no_root_certificates_falls_back_to_certifi(monkeypatch):
    """The python.org build on macOS ships no CA bundle, so every HTTPS call failed
    on a fresh clone; config points OpenSSL at certifi's bundle then (2026-10-03)."""
    import ssl
    from types import SimpleNamespace

    import certifi

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(ssl, "get_default_verify_paths",
                        lambda: SimpleNamespace(cafile="/nonexistent/cert.pem", capath="/nonexistent"))
    config._ensure_ca_bundle()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()
    monkeypatch.setenv("SSL_CERT_FILE", "/mine.pem")                 # an operator's own choice wins
    config._ensure_ca_bundle()
    assert os.environ["SSL_CERT_FILE"] == "/mine.pem"
