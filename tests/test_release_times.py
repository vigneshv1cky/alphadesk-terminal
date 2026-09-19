"""When US agencies publish, against what the vendor says (2026-09-15).

Measured twice, a day apart: the vendor lists retail sales and the
Employment Cost Index at 09:30 New York time; Census and the BLS release
both at 08:30. Everything else US matched.
"""

from alphadesk.ingest.release_times import agency_time, correct_times


def _row(event, iso, country="US"):
    return {"event": event, "time": iso, "country": country}


def test_the_two_the_vendor_lists_late_are_moved():
    rows = [_row("Retail Sales MoM (Sep)", "2026-10-15T13:30:00Z"),
            _row("Employment Cost Index QoQ (Q3)", "2026-10-30T13:30:00Z")]
    assert correct_times(rows) == 2
    assert rows[0]["time"] == "2026-10-15T12:30:00Z"      # 08:30 ET
    assert rows[1]["time"] == "2026-10-30T12:30:00Z"
    assert rows[0]["vendor_time"] == "2026-10-15T13:30:00Z"
    assert rows[0]["time_agency"] == "Census Bureau"


def test_a_row_already_on_the_agency_clock_is_untouched():
    rows = [_row("Inflation Rate YoY (Sep)", "2026-10-14T12:30:00Z")]
    assert correct_times(rows) == 0
    assert "vendor_time" not in rows[0] and rows[0]["time"] == "2026-10-14T12:30:00Z"


def test_only_us_rows_are_corrected():
    rows = [_row("Retail Sales MoM", "2026-10-15T13:30:00Z", country="UK")]
    assert correct_times(rows) == 0


def test_the_date_is_never_changed():
    rows = [_row("Retail Sales MoM (Sep)", "2026-10-15T23:00:00Z")]
    correct_times(rows)
    assert rows[0]["time"].startswith("2026-10-15")


def test_a_release_the_table_does_not_know_is_left_alone():
    assert agency_time("NOPA Crush Report") is None
    rows = [_row("NOPA Crush Report", "2026-09-15T20:00:00Z")]
    assert correct_times(rows) == 0


def test_the_survey_houses_publish_at_ten():
    assert agency_time("ISM Manufacturing PMI (Sep)")[:2] == (10, 0)
    assert agency_time("Michigan Consumer Sentiment Prel (Oct)")[:2] == (10, 0)
    assert agency_time("Fed Interest Rate Decision")[:2] == (14, 0)
