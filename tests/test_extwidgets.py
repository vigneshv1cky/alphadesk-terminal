"""The external-widget seam's contract: descriptors validate hard (drop with
a logged reason, never render broken), parameters are whitelisted, and every
value the frontend will see has been coerced to a capped plain scalar."""

import pytest

from alphadesk import extwidgets


@pytest.fixture(autouse=True)
def _one_backend(monkeypatch):
    monkeypatch.setenv("ALPHADESK_WIDGET_BACKENDS", "http://widgets.test")
    extwidgets._desc_cache.clear()
    yield
    extwidgets._desc_cache.clear()


def _serve(monkeypatch, by_url):
    """Fake the HTTP layer: by_url maps url -> payload (or Exception)."""
    def fake(url):
        v = by_url[url]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(extwidgets, "_fetch_json", fake)


GOOD = {
    "id": "flows", "type": "table", "title": "Fund flows",
    "endpoint": "/flows", "params": ["symbol"], "refresh_s": 30, "span": 6,
    "columns": [{"key": "name", "label": "Name"},
                {"key": "usd", "label": "USD", "align": "right"}],
}


def test_valid_descriptor_survives_and_is_cleaned(monkeypatch):
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [GOOD]})
    (w,) = extwidgets.list_widgets()
    assert w["uid"] == "ext0-flows"
    assert w["type"] == "table"
    assert w["params"] == ["symbol"]
    assert [c["key"] for c in w["columns"]] == ["name", "usd"]
    assert w["columns"][1]["align"] == "right"


@pytest.mark.parametrize("broken", [
    {**GOOD, "type": "iframe"},              # only declarative types render
    {**GOOD, "endpoint": "flows"},           # endpoint must be a path
    {**GOOD, "endpoint": "/../secrets"},     # no traversal
    {**GOOD, "title": "  "},                 # a tile must be named
    {**GOOD, "columns": []},                 # a table declares its columns
    {k: v for k, v in GOOD.items() if k != "id"},
    "not-an-object",
])
def test_broken_descriptors_are_dropped(monkeypatch, broken):
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [broken]})
    assert extwidgets.list_widgets() == []


def test_unknown_params_are_stripped_not_fatal(monkeypatch):
    d = {**GOOD, "params": ["symbol", "api_key", "cookie"]}
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [d]})
    (w,) = extwidgets.list_widgets()
    assert w["params"] == ["symbol"]


def test_refresh_and_span_are_clamped(monkeypatch):
    d = {**GOOD, "refresh_s": 1, "span": 40}
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [d]})
    (w,) = extwidgets.list_widgets()
    assert w["refresh_s"] == 15
    assert w["span"] == 12


def test_dead_backend_serves_last_good_descriptors(monkeypatch):
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [GOOD]})
    assert len(extwidgets.list_widgets()) == 1
    _serve(monkeypatch, {"http://widgets.test/widgets.json": OSError("down")})
    assert len(extwidgets.list_widgets(refresh=True)) == 1


def test_table_rows_are_capped_and_coerced(monkeypatch):
    rows = [{"name": "<b>x</b>" * 200, "usd": 5, "extra": "never sent"}
            for _ in range(extwidgets._MAX_ROWS + 50)]
    _serve(monkeypatch, {
        "http://widgets.test/widgets.json": [GOOD],
        "http://widgets.test/flows?symbol=NVDA": {"rows": rows},
    })
    out = extwidgets.fetch_data("ext0-flows", "nvda")
    assert len(out["rows"]) == extwidgets._MAX_ROWS
    row = out["rows"][0]
    assert set(row) == {"name", "usd"}          # undeclared keys never leave
    assert len(row["name"]) == extwidgets._MAX_STR
    assert row["usd"] == 5                      # numbers stay numbers


def test_metrics_values_are_scalars(monkeypatch):
    desc = {"id": "kpi", "type": "metrics", "title": "KPIs", "endpoint": "/kpi"}
    _serve(monkeypatch, {
        "http://widgets.test/widgets.json": [desc],
        "http://widgets.test/kpi": {"metrics": [
            {"label": "AUM", "value": 12.5},
            {"label": "Nested", "value": {"a": 1}},   # structure flattens to text
            {"value": "unlabelled is dropped"},
        ]},
    })
    out = extwidgets.fetch_data("ext0-kpi")
    assert out["metrics"][0] == {"label": "AUM", "value": 12.5}
    assert isinstance(out["metrics"][1]["value"], str)   # structure flattens
    assert len(out["metrics"]) == 2


def test_unknown_uid_is_a_lookup_error(monkeypatch):
    _serve(monkeypatch, {"http://widgets.test/widgets.json": [GOOD]})
    with pytest.raises(LookupError):
        extwidgets.fetch_data("ext0-nope")


def test_no_backends_means_inert(monkeypatch):
    monkeypatch.setenv("ALPHADESK_WIDGET_BACKENDS", "")
    called = []
    monkeypatch.setattr(extwidgets, "_fetch_json", lambda u: called.append(u))
    assert extwidgets.list_widgets() == []
    assert called == []
