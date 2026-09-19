

# ── the 52-week range from the reader's own bars ─────────────────────────
#
# Alpaca's quote carries no range at all, so the column was empty on the
# Portfolio page (2026-09-16). One batch of daily bars fills it.

def test_the_range_is_the_high_and_low_of_the_year():
    from alphadesk.ingest.prices import week52_from_bars
    bars = [{"high": 120, "low": 90, "close": 100}, {"high": 150, "low": 110, "close": 140},
            {"high": 130, "low": 80, "close": 95}]
    assert week52_from_bars(bars) == (80, 150)


def test_a_bar_without_a_high_falls_back_to_its_close():
    from alphadesk.ingest.prices import week52_from_bars
    bars = [{"close": 100}, {"high": None, "low": None, "close": 140}, {"close": 85}]
    assert week52_from_bars(bars) == (85, 140)


def test_no_bars_no_range():
    from alphadesk.ingest.prices import week52_from_bars
    assert week52_from_bars([]) == (None, None)
