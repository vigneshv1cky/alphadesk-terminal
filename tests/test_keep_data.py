"""ALPHADESK_KEEP_DATA (2026-10-03): a longer retention for the records, never a shorter one."""
import importlib

import pytest


@pytest.fixture
def cfg(monkeypatch):
    import alphadesk.config as config

    def load(value=None):
        if value is None:
            monkeypatch.delenv("ALPHADESK_KEEP_DATA", raising=False)
        else:
            monkeypatch.setenv("ALPHADESK_KEEP_DATA", value)
        return importlib.reload(config)

    yield load
    monkeypatch.delenv("ALPHADESK_KEEP_DATA", raising=False)
    importlib.reload(config)


def test_unset_keeps_the_defaults(cfg):
    c = cfg()
    assert (c.NEWS_KEEP_DAYS, c.ANNOUNCEMENT_KEEP_DAYS, c.FORECAST_KEEP_DAYS, c.NEWS_BODY_KEEP_HOURS) == (7.0, 30, 120, 72.0)
    assert (c.NEWS_OLDER_PAGE_DAYS, c.SYMBOL_NEWS_LOOKBACK_DAYS, c.NEWS_BACKFILL_DAYS) == (7, 30, 7.0)


def test_forever_lengthens_every_record_and_widens_the_reach(cfg):
    c = cfg("forever")
    assert c.NEWS_KEEP_DAYS == c.ANNOUNCEMENT_KEEP_DAYS == c.FORECAST_KEEP_DAYS == c.SCRAPED_KEEP_DAYS == c.FOREVER_DAYS
    assert c.NEWS_BODY_KEEP_HOURS == c.NEWS_OLDER_PAGE_KEEP_HOURS == c.FOREVER_DAYS * 24
    assert (c.NEWS_OLDER_PAGE_DAYS, c.SYMBOL_NEWS_LOOKBACK_DAYS, c.NEWS_BACKFILL_DAYS) == (30, 365, 30.0)


def test_a_number_never_shortens_a_default(cfg):
    c = cfg("30")
    assert c.NEWS_KEEP_DAYS == 30.0 and c.FORECAST_KEEP_DAYS == 120 and c.ANNOUNCEMENT_KEEP_DAYS == 30
    assert cfg("3").NEWS_KEEP_DAYS == 7.0


def test_a_bad_value_is_ignored(cfg):
    assert cfg("lots").NEWS_KEEP_DAYS == 7.0
