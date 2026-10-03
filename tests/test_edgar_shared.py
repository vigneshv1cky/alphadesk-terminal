"""One copy of a registrant's SEC documents, shared by every module that reads them (2026-10-03)."""
import json
import threading

import pytest

from alphadesk.ingest import edgar


@pytest.fixture(autouse=True)
def _clean():
    edgar._json_cache.clear()
    edgar._json_locks.clear()
    yield
    edgar._json_cache.clear()


def test_a_document_is_downloaded_and_parsed_once(monkeypatch):
    calls = []
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: calls.append(url) or json.dumps({"a": 1}).encode())
    assert edgar.get_json("https://data.sec.gov/x") == {"a": 1}
    assert edgar.get_json("https://data.sec.gov/x") == {"a": 1}
    assert len(calls) == 1


def test_concurrent_askers_share_one_download(monkeypatch):
    calls, gate = [], threading.Event()

    def slow(url, timeout=15.0):
        calls.append(url)
        gate.wait(2)
        return b'{"ok": true}'

    monkeypatch.setattr(edgar, "_get", slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(edgar.get_json("https://data.sec.gov/y"))) for _ in range(4)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join()
    assert len(calls) == 1 and out == [{"ok": True}] * 4


def test_a_failure_is_not_remembered(monkeypatch):
    state = {"n": 0}

    def flaky(url, timeout=15.0):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("boom")
        return b'{"ok": 1}'

    monkeypatch.setattr(edgar, "_get", flaky)
    with pytest.raises(OSError):
        edgar.get_json("https://data.sec.gov/z")
    assert edgar.get_json("https://data.sec.gov/z") == {"ok": 1}


def test_the_big_facts_files_are_kept_few(monkeypatch):
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: b'{"f": 1}')
    for i in range(9):
        edgar.get_json(f"https://data.sec.gov/facts/{i}", "facts")
    assert sum(1 for v in edgar._json_cache.values() if v[1] == "facts") == edgar._JSON_MAX["facts"]


def test_a_failed_ticker_map_is_asked_again_not_remembered_for_ever(monkeypatch):
    edgar._ticker_cik_cache = None
    edgar._ticker_cik_retry_at = 0.0
    state = {"n": 0}

    def get(url, timeout=15.0):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("down")
        return json.dumps({"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple"}}).encode()

    monkeypatch.setattr(edgar, "_get", get)
    assert edgar._ticker_cik_map() == {}
    assert edgar._ticker_cik_map() == {}                       # inside the retry pause: no new request
    assert state["n"] == 1
    edgar._ticker_cik_retry_at = 0.0
    assert edgar._ticker_cik_map() == {"AAPL": "0000320193"}
    edgar._ticker_cik_cache = None
