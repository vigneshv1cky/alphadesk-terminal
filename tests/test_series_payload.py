"""build_series_payload is the seam every bar source passes through, so it
is where a bar that is not a bar gets dropped."""
import json
import math
from datetime import datetime, timedelta, timezone

from alphadesk.ingest.prices import build_series_payload


def _bars(n, first_nan=False):
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        px = 100.0 + i
        out.append({"ts": t0 + timedelta(days=i), "open": px, "high": px + 1,
                    "low": px - 1, "close": px + 0.5, "volume": 1000.0})
    if first_nan:
        nan = float("nan")
        out[0].update(open=nan, high=nan, low=nan, close=nan, volume=0.0)
    return out


def test_nan_bar_is_dropped_and_payload_serialises():
    payload = build_series_payload("NVDA", _bars(40, first_nan=True), "1d",
                                   range_key="3M", interval="1d", stats={"coverage": 1.0})
    assert payload is not None
    assert len(payload["bars"]) == 39
    assert not any(math.isnan(b["c"]) for b in payload["bars"])
    json.dumps(payload)          # the encoder that refused the NaN


def test_too_few_real_bars_is_no_chart():
    assert build_series_payload("X", _bars(2, first_nan=True), "1d") is None
