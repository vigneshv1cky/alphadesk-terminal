"""SEC EDGAR pacing (2026-09-14). SEC allows 10 requests a second per IP
address and blocks an address that goes over; every reader's EDGAR traffic
leaves from the server, so the pace is process-wide and a block pauses all
calls instead of retrying into it."""

import io
import threading
import time
import urllib.error

import pytest

from alphadesk.ingest import edgar


class _Resp:
    def __init__(self, body=b"{}"):
        self._b = body
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def fresh_pace(monkeypatch):
    monkeypatch.setattr(edgar, "_next_slot", 0.0)
    monkeypatch.setattr(edgar, "_blocked_until", 0.0)
    monkeypatch.setenv("SEC_USER_AGENT", "AlphaDesk tests (test@example.com)")
    yield


def test_concurrent_callers_are_spaced_by_the_interval(monkeypatch):
    """Twelve callers at once each reserve a send slot one interval after the
    last and wait until it. Asserted on the reserved slots and the requested
    waits, not on wall-clock send times: a thread that wakes a few
    milliseconds late on a busy machine made the old timing check fail
    (22ms against a 24ms floor) without the pacing being wrong."""
    interval = 0.03
    monkeypatch.setattr(edgar, "_MIN_INTERVAL_S", interval)
    slots, waits, sent = [], [], []
    lock = threading.Lock()
    reserve = edgar._reserve_slot

    def recording_reserve():
        slot = reserve()
        with lock:
            slots.append(slot)
        return slot
    monkeypatch.setattr(edgar, "_reserve_slot", recording_reserve)
    monkeypatch.setattr(edgar.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda req, timeout=15: sent.append(req.full_url) or _Resp())
    barrier = threading.Barrier(12)

    def call():
        barrier.wait()                                   # all twelve ask at the same instant
        edgar._get("https://data.sec.gov/x")
    started = time.monotonic()
    threads = [threading.Thread(target=call) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    slots.sort()
    gaps = [b - a for a, b in zip(slots, slots[1:])]
    assert len(sent) == 12 and len(slots) == 12
    assert all(g >= interval - 1e-9 for g in gaps)                 # no two slots inside one interval
    assert slots[0] >= started and slots[-1] - slots[0] >= 11 * interval - 1e-9
    # Every caller after the first had to wait for its slot, and none waited
    # past the last slot.
    assert len(waits) >= 11 and all(0 < w <= 11 * interval + 0.05 for w in waits)


def _refusal(code, body):
    return urllib.error.HTTPError("https://data.sec.gov/x", code, "Forbidden", {}, io.BytesIO(body))


def test_a_rate_limit_answer_pauses_every_call_until_the_cooldown_ends(monkeypatch):
    monkeypatch.setattr(edgar, "_MIN_INTERVAL_S", 0.0)
    calls = []

    def blocked(req, timeout=15):
        calls.append(req.full_url)
        raise _refusal(403, b"<html><h1>Request Rate Threshold Exceeded</h1></html>")
    monkeypatch.setattr(edgar.urllib.request, "urlopen", blocked)
    with pytest.raises(edgar.EdgarRateLimited):
        edgar._get("https://data.sec.gov/a")
    assert edgar.rate_limit_status()["blocked"] is True and edgar.rate_limit_status()["seconds_left"] > 500

    with pytest.raises(edgar.EdgarRateLimited):
        edgar._get("https://data.sec.gov/b")               # refused without reaching SEC
    assert calls == ["https://data.sec.gov/a"]

    monkeypatch.setattr(edgar, "_blocked_until", time.monotonic() - 1)
    monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda req, timeout=15: _Resp(b"ok"))
    assert edgar._get("https://data.sec.gov/c") == b"ok"     # the cooldown over, calls resume


def test_429_is_a_block_and_an_ordinary_403_or_404_is_not(monkeypatch):
    monkeypatch.setattr(edgar, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda req, timeout=15: (_ for _ in ()).throw(_refusal(404, b"Not Found")))
    with pytest.raises(urllib.error.HTTPError):
        edgar._get("https://www.sec.gov/missing")
    monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda req, timeout=15: (_ for _ in ()).throw(_refusal(403, b"Undeclared Automated Tool")))
    with pytest.raises(urllib.error.HTTPError) as exc:
        edgar._get("https://www.sec.gov/x")
    assert not isinstance(exc.value, edgar.EdgarRateLimited) and edgar.rate_limit_status()["blocked"] is False
    monkeypatch.setattr(edgar.urllib.request, "urlopen", lambda req, timeout=15: (_ for _ in ()).throw(_refusal(429, b"")))
    with pytest.raises(edgar.EdgarRateLimited):
        edgar._get("https://efts.sec.gov/LATEST/search-index")
    assert edgar.rate_limit_status()["blocked"] is True


def test_the_system_route_carries_no_operator_telemetry(client):
    """Reader-scoped since 2026-09-18: no EDGAR pacing, uptime, seams or
    counts of other readers' live connections."""
    body = client.get("/api/system").json()
    assert set(body) == {"market", "news", "providers"}
