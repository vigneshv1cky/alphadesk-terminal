"""The per-user earnings calendar (2026-09-13): the user's calendar vendors
unioned, EDGAR-listed companies named, results 8-Ks joined from the keyless
release table, volatility and liquidity from the user's own daily bars,
each day ordered largest company first, then most traded."""

from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.ingest import earnings_calendar as uc
from alphadesk.ingest import edgar, edgar_releases
from alphadesk.providers.base import EntitlementError, NeedsKey


def test_parse_hits_keeps_item_202_once_per_ticker_and_filing():
    hits = [
        {"_id": "0000796343-26-000147:adbe-20260910.htm", "_source": {"adsh": "0000796343-26-000147", "items": ["2.02", "9.01"],
         "file_date": "2026-09-10", "display_names": ["ADOBE INC.  (ADBE)  (CIK 0000796343)"]}},
        {"_id": "0000796343-26-000147:ex99.htm", "_source": {"adsh": "0000796343-26-000147", "items": ["2.02", "9.01"],
         "file_date": "2026-09-10", "display_names": ["ADOBE INC.  (ADBE)  (CIK 0000796343)"]}},
        {"_id": "x:y", "_source": {"adsh": "0002082866-26-000085", "items": ["5.02"], "file_date": "2026-09-10",
         "display_names": ["Pinnacle Financial Partners, Inc.  (PNFP, PNFP-PA)  (CIK 0002082866)"]}},
        {"_id": "z:w", "_source": {"adsh": "0001341439-26-000030", "items": ["2.02"], "file_date": "2026-09-10",
         "display_names": ["ORACLE CORP  (ORCL, ORCL-PD)  (CIK 0001341439)"]}},
    ]
    rows = edgar_releases.parse_hits(hits)
    assert sorted((r["symbol"], r["accession"]) for r in rows) == [
        ("ADBE", "0000796343-26-000147"), ("ORCL", "0001341439-26-000030"), ("ORCL-PD", "0001341439-26-000030")]
    adbe = next(r for r in rows if r["symbol"] == "ADBE")
    assert adbe["cik"] == "0000796343" and adbe["company"] == "ADOBE INC." and adbe["file_date"] == "2026-09-10"


def test_combine_unions_vendors_and_collapses_a_moved_report():
    fin = [{"symbol": "KR", "report_date": "2026-09-11", "session": "BMO", "confirmed": True, "eps_estimate": 1.0, "eps_actual": None}]
    av = [{"symbol": "KR", "report_date": "2026-09-11", "session": "DAY", "confirmed": False, "eps_estimate": None, "eps_actual": None},
          {"symbol": "ORCL", "report_date": "2026-09-10", "session": "AMC", "confirmed": True, "eps_estimate": 1.5, "eps_actual": None}]
    rows = {r["symbol"]: r for r in uc.combine([("finnhub", fin), ("alphavantage", av)])}
    assert rows["KR"]["sources"] == "alphavantage,finnhub" and rows["KR"]["session"] == "BMO"
    assert rows["ORCL"]["sources"] == "alphavantage"


def test_a_vendor_date_off_by_days_moves_to_the_filing_day():
    rows = [{"symbol": "KR", "report_date": "2026-09-09"}]
    uc.join_releases(rows, {"KR": [{"file_date": "2026-09-11", "accepted_at": "2026-09-11T06:59:48-04:00", "accession": "k"}]})
    assert rows[0]["report_date"] == "2026-09-11" and rows[0]["vendor_date"] == "2026-09-09"
    assert rows[0]["date_from_edgar"] is True and rows[0]["released_at"].endswith("06:59:48-04:00")


def test_two_vendor_rows_moved_onto_one_release_become_one_row():
    rows = [{"symbol": "RFIL", "report_date": "2026-09-09", "session": "BMO", "confirmed": True, "eps_estimate": None,
             "sources": "finnhub"},
            {"symbol": "RFIL", "report_date": "2026-09-14", "session": "DAY", "confirmed": False, "eps_estimate": 0.2,
             "sources": "fmp"}]
    uc.join_releases(rows, {"RFIL": [{"file_date": "2026-09-14", "accepted_at": "2026-09-14T08:08:16-04:00", "accession": "r"}]})
    got = uc.merge_same_release(rows)
    assert len(got) == 1 and got[0]["report_date"] == "2026-09-14" and got[0]["eps_estimate"] == 0.2
    assert got[0]["sources"] == "finnhub,fmp" and got[0]["vendor_date"] == "2026-09-09" and got[0]["confirmed"] is True


def test_join_releases_takes_the_nearest_filing_within_a_week():
    rows = [{"symbol": "ADBE", "report_date": "2026-09-10"}, {"symbol": "KR", "report_date": "2026-09-11"},
            {"symbol": "GME", "report_date": "2026-09-07"}]
    rel = {"ADBE": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:06:14-04:00", "accession": "a"}],
           "KR": [{"file_date": "2026-08-20", "accepted_at": "2026-08-20T07:00:00-04:00", "accession": "old"}],
           "GME": [{"file_date": "2026-09-08", "accepted_at": "2026-09-08T09:02:00-04:00", "accession": "g"}]}
    uc.join_releases(rows, rel)
    assert rows[0]["released_at"] == "2026-09-10T16:06:14-04:00" and "vendor_date" not in rows[0]
    assert "released_at" not in rows[1]                                   # a filing weeks earlier is another quarter
    assert rows[2]["report_date"] == "2026-09-08" and rows[2]["vendor_date"] == "2026-09-07"


def test_a_vendor_date_two_weeks_early_still_joins_but_an_earlier_filing_does_not():
    # Finnhub listed Macy's on 09-01; its results 8-K was filed 09-10.
    rows = [{"symbol": "M", "report_date": "2026-09-01"}, {"symbol": "PRE", "report_date": "2026-09-20"}]
    rel = {"M": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T06:45:00-04:00", "accession": "m"}],
           "PRE": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T07:00:00-04:00", "accession": "p"}]}
    uc.join_releases(rows, rel)
    assert rows[0]["report_date"] == "2026-09-10" and rows[0]["vendor_date"] == "2026-09-01"
    assert "released_at" not in rows[1]                                   # ten days earlier: a pre-announcement, not this date


def test_edgar_only_rows_add_unlisted_filers_once_per_company():
    listed = {"APMD": "1", "ORCL": "2", "ORCL-PD": "2", "KR": "3"}
    rel = {"APMD": [{"file_date": "2026-09-08", "accepted_at": "2026-09-08T07:05:00-04:00", "accession": "a", "cik": "1"}],
           "ORCL": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:05:00-04:00", "accession": "o", "cik": "2"}],
           "ORCL-PD": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:05:00-04:00", "accession": "o", "cik": "2"}],
           "KR": [{"file_date": "2026-09-11", "accepted_at": None, "accession": "k2", "cik": "3"}],
           "NOTSEC": [{"file_date": "2026-09-09", "accepted_at": None, "accession": "n", "cik": "9"}],
           "LATE": [{"file_date": "2026-09-14", "accepted_at": None, "accession": "l", "cik": "4"}]}
    vendor_rows = [{"symbol": "KR", "report_date": "2026-09-11", "released_on": "2026-09-11"}]
    got = {r["symbol"]: r for r in uc.edgar_only_rows(vendor_rows, rel, "2026-09-07", "2026-09-11", listed)}
    assert sorted(got) == ["APMD", "ORCL"]                                # KR has a vendor row; ORCL-PD is ORCL; NOTSEC unlisted
    assert got["APMD"]["session"] == "BMO" and got["ORCL"]["session"] == "AMC"
    assert got["APMD"]["edgar_only"] is True and got["APMD"]["released_at"].startswith("2026-09-08T07:05")


def test_a_mid_quarter_item_202_is_not_a_quarter_release():
    f = lambda form, d, items="": {"form": form, "filing_date": d, "items": items}   # noqa: E731
    # Group 1 Automotive: results on 07-30, another Item 2.02 on 09-08.
    assert not uc.is_quarter_release("2026-09-08", [f("8-K", "2026-09-08", "2.02,8.01"), f("8-K", "2026-07-30", "2.02"), f("10-Q", "2026-07-30")])
    # Plains All American: 10-Q on 08-10, Item 2.02 on 09-09.
    assert not uc.is_quarter_release("2026-09-09", [f("10-Q", "2026-08-10"), f("8-K", "2026-05-08", "2.02")])
    # BNC: the 10-Q beside the release is the same event; the last quarter was 80 days back.
    assert uc.is_quarter_release("2026-09-11", [f("10-Q", "2026-09-11"), f("8-K", "2026-09-11", "2.02"), f("8-K", "2026-06-23", "2.02")])
    # A new registrant's first release.
    assert uc.is_quarter_release("2026-09-08", [f("10-Q", "2026-09-08")])


class _Cal:
    name = "finnhub"
    def earnings_calendar(self, start, end, symbol=None):
        return [{"symbol": "ADBE", "report_date": "2026-09-10", "session": "AMC", "confirmed": True, "eps_estimate": 5.0, "eps_actual": 5.3},
                {"symbol": "TINY", "report_date": "2026-09-10", "session": "DAY", "confirmed": False, "eps_estimate": None, "eps_actual": None},
                {"symbol": "NOTSEC", "report_date": "2026-09-10", "session": "DAY", "confirmed": False, "eps_estimate": None, "eps_actual": None}]


class _Bars:
    name = "alpaca"
    def daily_history(self, symbols, sessions=21):
        t0 = datetime(2026, 8, 12, tzinfo=timezone.utc)
        big = [{"ts": t0 + timedelta(days=i), "close": 500 + (i % 3), "volume": 3_000_000} for i in range(21)]
        small = [{"ts": t0 + timedelta(days=i), "close": 2 + (i % 2) * 0.1, "volume": 100_000} for i in range(21)]
        return {"ADBE": big, "TINY": small}


def test_rows_between_names_joins_and_orders_by_liquidity(vendors, monkeypatch):
    vendors(finnhub=_Cal(), alpaca=_Bars())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"ADBE": "0000796343", "TINY": "0000000001"})
    monkeypatch.setattr(edgar, "company_title", lambda s: {"ADBE": "Adobe Inc.", "TINY": "Tiny Corp"}.get(s))
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {
        "ADBE": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:06:14-04:00", "accession": "a"}],
        "REF": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:30:00-04:00", "accession": "r", "cik": "0000000002"}]})
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"ADBE": "0000796343", "TINY": "0000000001", "REF": "0000000002"})
    monkeypatch.setattr(uc, "quarter_release", lambda sym, d: True)
    rows = uc.rows_between("2026-09-10", "2026-09-10")
    assert [r["symbol"] for r in rows] == ["ADBE", "TINY", "REF"]     # NOTSEC is not an SEC filer; most traded first, REF has no bars
    assert rows[2]["edgar_only"] is True and rows[2]["session"] == "AMC" and rows[2]["confirmed"] is True
    adbe, tiny, _ = rows
    assert adbe["company_name"] == "Adobe Inc." and adbe["surprise_pct"] == 6.0 and adbe["released_at"].startswith("2026-09-10T16:06")
    assert adbe["liquidity"] > 1e9 and adbe["low_liquidity"] is False and adbe["volatility"] is not None
    assert tiny["low_liquidity"] is True and tiny["released_at"] is None


def test_pick_report_takes_the_nearest_and_the_upcoming_on_a_tie():
    reps = [{"report_date": "2026-06-10"}, {"report_date": "2026-09-09"}, {"report_date": "2026-09-18"}, {"report_date": "2026-12-09"}]
    assert uc.pick_report(reps, "2026-09-13")["report_date"] == "2026-09-09"          # four days back beats five ahead
    assert uc.pick_report([{"report_date": "2026-09-09"}, {"report_date": "2026-09-17"}], "2026-09-13")["report_date"] == "2026-09-17"
    assert uc.pick_report([], "2026-09-13") is None


def test_find_asks_for_one_symbol_and_dates_it_like_the_week(vendors, monkeypatch):
    asked = []

    class _One:
        name = "finnhub"
        def earnings_calendar(self, start, end, symbol=None):
            asked.append(symbol)
            return [{"symbol": "NB", "report_date": "2026-09-01", "session": "AMC", "confirmed": False, "eps_estimate": -0.04, "eps_actual": None},
                    {"symbol": "OTHER", "report_date": "2026-09-01", "session": "AMC", "confirmed": False, "eps_estimate": None, "eps_actual": None},
                    {"symbol": "NB", "report_date": "2026-12-09", "session": "DAY", "confirmed": False, "eps_estimate": None, "eps_actual": None}]
    vendors(finnhub=_One())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"NB": "0001512228", "OTHER": "1"})
    monkeypatch.setattr(edgar, "company_title", lambda s: "NIOCORP DEVELOPMENTS LTD")
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {
        "NB": [{"file_date": "2026-09-10", "accepted_at": "2026-09-10T16:30:00-04:00", "accession": "n", "cik": "0001512228"}]})
    got = uc.find("nb", today="2026-09-13")
    assert asked == ["NB"] and got["company_name"] == "NIOCORP DEVELOPMENTS LTD"
    assert [r["report_date"] for r in got["reports"]] == ["2026-09-10", "2026-12-09"]
    assert got["reports"][0]["vendor_date"] == "2026-09-01" and got["pick"] == "2026-09-10"
    assert uc.find("ZZZZ", today="2026-09-13")["listed"] is False


def test_no_calendar_vendor_is_a_key_prompt_and_a_refusal_is_named(vendors):
    vendors(alpaca=_Bars())
    with pytest.raises(NeedsKey):
        uc.rows_between("2026-09-10", "2026-09-10")

    class _Refuses:
        name = "fmp"
        def earnings_calendar(self, s, e, symbol=None):
            raise EntitlementError("HTTP 402")
    vendors(fmp=_Refuses())
    with pytest.raises(NeedsKey) as exc:
        uc.rows_between("2026-09-10", "2026-09-10")
    assert exc.value.prompt()["refused"] == ["Financial Modeling Prep"]
    assert uc.upcoming(7) == [] and uc.report_row("ADBE", "2026-09-10") is None
    with pytest.raises(NeedsKey):
        uc.find("ADBE")


def test_previous_weekday_skips_the_weekend():
    from alphadesk.ingest import earnings
    assert earnings.previous_weekday("2026-09-14") == "2026-09-11"     # Monday -> Friday
    assert earnings.previous_weekday("2026-09-11") == "2026-09-10"


def test_a_late_filed_8k_dates_the_report_by_its_release_not_its_filing():
    """2026-09-14: Optical Cable released on the 9th (both vendors said so)
    and filed the 8-K on the 11th at 4:15 PM. The report stays on the 9th,
    with no release time — the 4:15 PM is the filing's."""
    rows = [{"symbol": "OCC", "report_date": "2026-09-09", "session": "BMO"}]
    rel = {"OCC": [{"file_date": "2026-09-11", "event_date": "2026-09-09",
                    "accepted_at": "2026-09-11T16:15:22-04:00", "accession": "0001437749-26-030174"}]}
    uc.join_releases(rows, rel)
    r = rows[0]
    assert r["report_date"] == "2026-09-09" and "vendor_date" not in r
    assert r["released_at"] is None and r["released_on"] == "2026-09-09"
    assert r["filed_on"] == "2026-09-11" and r["filed_at"].startswith("2026-09-11T16:15")


def test_a_same_day_filing_keeps_its_clock_and_moves_a_wrong_vendor_date():
    rows = [{"symbol": "KR", "report_date": "2026-09-09"}]
    rel = {"KR": [{"file_date": "2026-09-11", "event_date": "2026-09-11",
                   "accepted_at": "2026-09-11T06:59:48-04:00", "accession": "k"}]}
    uc.join_releases(rows, rel)
    assert rows[0]["report_date"] == "2026-09-11" and rows[0]["vendor_date"] == "2026-09-09"
    assert rows[0]["released_at"].endswith("06:59:48-04:00")


def test_parse_hits_settles_the_release_day_only_for_a_same_day_filing():
    mk = lambda adsh, fd, pe, name: {"_id": adsh + ":x", "_source": {"adsh": adsh, "items": ["2.02", "9.01"], "file_date": fd,  # noqa: E731
                                     "period_ending": pe, "display_names": [name]}}
    rows = {r["symbol"]: r for r in edgar_releases.parse_hits([
        mk("1", "2026-09-11", "2026-09-09", "OPTICAL CABLE CORP  (OCC)  (CIK 0001000230)"),
        mk("2", "2026-09-10", "2026-09-10", "ADOBE INC.  (ADBE)  (CIK 0000796343)")])}
    assert rows["OCC"]["event_date"] is None                    # read from the 8-K's text later
    assert rows["ADBE"]["event_date"] == "2026-09-10"


def test_the_release_day_comes_from_the_item_202_sentence_not_the_date_of_report():
    """Measured 2026-09-14: the date of report is the earliest event in the
    whole 8-K — Casey's shareholder vote on the 2nd, results on the 8th."""
    casey = ("Item 2.02. Results of Operations and Financial Condition . On September 8, 2026, Casey's General Stores, "
             "Inc. (the \"Company\") issued a press release announcing its financial results")
    assert edgar_releases.press_release_date(casey) == "2026-09-08"
    assert edgar_releases.resolve_release_day("2026-09-08", "2026-09-02", "2.02,5.07,9.01", casey) == "2026-09-08"
    occ = "Item 2.02 Results of Operations and Financial Condition On September 9, 2026, Optical Cable Corporation issued a press release"
    assert edgar_releases.resolve_release_day("2026-09-11", "2026-09-09", "2.02,9.01", occ) == "2026-09-09"
    # no sentence: a results-only filing trusts its date of report, a mixed one its filing day
    assert edgar_releases.resolve_release_day("2026-09-11", "2026-09-09", "2.02,9.01", "") == "2026-09-09"
    assert edgar_releases.resolve_release_day("2026-09-09", "2026-09-04", "1.01,2.02,9.01", "") == "2026-09-09"
    # a same-day filing never reads the text; a sentence dated outside the window is ignored
    assert edgar_releases.resolve_release_day("2026-09-10", "2026-09-10", "2.02", "On August 1, 2026") == "2026-09-10"
    assert edgar_releases.resolve_release_day("2026-09-11", "2026-09-09", "2.02,9.01",
                                              "Item 2.02 On August 1, 2026, the quarter ended") == "2026-09-09"


def test_an_edgar_only_row_from_a_late_filing_sits_on_its_release_day():
    listed = {"LATE": "9"}
    rel = {"LATE": [{"file_date": "2026-09-14", "event_date": "2026-09-10", "accepted_at": "2026-09-14T17:00:00-04:00",
                     "accession": "l", "cik": "9"}]}
    [row] = uc.edgar_only_rows([], rel, "2026-09-07", "2026-09-11", listed)
    assert row["report_date"] == "2026-09-10" and row["released_at"] is None and row["session"] is None


def test_the_filing_clock_corrects_a_vendor_session_only_when_the_vendor_claims_later():
    f = uc.session_after_release
    assert f("AMC", True, "2026-09-11T06:59:48-04:00") == "BMO"      # said after the close, filed before the open
    assert f("BMO", True, "2026-09-09T14:53:00-04:00") == "BMO"      # Car-Mart: filed hours after a pre-market release
    assert f("BMO", True, "2026-09-10T16:06:00-04:00") == "BMO"
    assert f("DAY", False, "2026-09-10T16:06:00-04:00") == "AMC"     # no session named: the filing's
    assert f(None, False, "2026-09-10T07:00:00-04:00") == "BMO"
    assert f("AMC", True, None) == "AMC"                              # no clock of its own


def test_a_same_day_release_sets_the_session_from_its_clock_and_a_late_one_keeps_the_vendors():
    rows = [{"symbol": "KR", "report_date": "2026-09-11", "session": "AMC", "confirmed": True},
            {"symbol": "OCC", "report_date": "2026-09-09", "session": "BMO", "confirmed": True},
            {"symbol": "CRMT", "report_date": "2026-09-09", "session": "BMO", "confirmed": True}]
    rel = {"KR": [{"file_date": "2026-09-11", "event_date": "2026-09-11", "accepted_at": "2026-09-11T06:59:48-04:00", "accession": "k"}],
           "OCC": [{"file_date": "2026-09-11", "event_date": "2026-09-09", "accepted_at": "2026-09-11T16:15:22-04:00", "accession": "o"}],
           "CRMT": [{"file_date": "2026-09-09", "event_date": "2026-09-09", "accepted_at": "2026-09-09T14:53:00-04:00", "accession": "c"}]}
    uc.join_releases(rows, rel)
    kr, occ, crmt = rows
    assert kr["session"] == "BMO" and kr["vendor_session"] == "AMC"
    assert occ["session"] == "BMO" and "vendor_session" not in occ
    assert crmt["session"] == "BMO" and "vendor_session" not in crmt


def test_one_vendors_actual_counts_unless_it_is_its_estimate_with_no_filing_behind_it():
    """2026-09-14: one vendor's actual counts, as the consumer calendars show
    it (the owner's call) — but FMP gave NioCorp an actual equal to its
    estimate with no SEC filing since July, and that stays a placeholder."""
    fmp = [{"symbol": "NB", "report_date": "2026-09-09", "session": "DAY", "confirmed": False, "eps_estimate": -0.035, "eps_actual": -0.035},
           {"symbol": "KR", "report_date": "2026-09-11", "session": "DAY", "confirmed": False, "eps_estimate": 1.0, "eps_actual": 1.05},
           {"symbol": "CAN", "report_date": "2026-09-08", "session": "DAY", "confirmed": False, "eps_estimate": -0.1, "eps_actual": -0.08},
           {"symbol": "ABAT", "report_date": "2026-09-14", "session": "AMC", "confirmed": False, "eps_estimate": -0.05, "eps_actual": -0.15},
           {"symbol": "CSHR", "report_date": "2026-09-14", "session": "BMO", "confirmed": False, "eps_estimate": 0.1, "eps_actual": 0.1}]
    fin = [{"symbol": "NB", "report_date": "2026-09-09", "session": "AMC", "confirmed": True, "eps_estimate": -0.0378, "eps_actual": None},
           {"symbol": "CAN", "report_date": "2026-09-08", "session": "BMO", "confirmed": True, "eps_estimate": -0.1, "eps_actual": -0.08}]
    rows = {r["symbol"]: r for r in uc.combine([("fmp", fmp), ("finnhub", fin)])}
    uc.join_releases(list(rows.values()), {"KR": [{"file_date": "2026-09-11", "event_date": "2026-09-11",
                                                   "accepted_at": "2026-09-11T06:59:48-04:00", "accession": "k"}]})
    asked = []
    uc.settle_actuals(list(rows.values()), lambda sym: (asked.append(sym), sym == "CSHR")[1])
    nb, kr, can, abat, cshr = (rows[s] for s in ("NB", "KR", "CAN", "ABAT", "CSHR"))
    assert nb["eps_actual"] is None and nb["placeholder_actual"] == -0.035 and nb["placeholder_source"] == "fmp"
    assert abat["eps_actual"] == -0.15 and abat["actual_basis"] == "single_vendor" and abat["actual_source"] == "fmp"
    assert cshr["eps_actual"] == 0.1 and "placeholder_actual" not in cshr        # equal to the estimate, but it filed
    assert kr["eps_actual"] == 1.05 and "actual_basis" not in kr                  # one vendor, but EDGAR has the 8-K
    assert can["eps_actual"] == -0.08 and "actual_basis" not in can               # two vendors carry it
    assert sorted(asked) == ["CSHR", "NB"]                                        # evidence asked only for placeholders


def test_filing_evidence_is_a_filing_on_the_day_or_the_next_or_a_foreign_issuer_a_day_later(monkeypatch):
    filings = {
        "ABAT": [{"form": "10-K", "filing_date": "2026-09-14"}, {"form": "8-K", "filing_date": "2026-08-20"}],
        "NB": [{"form": "10-K", "filing_date": "2026-07-30"}],
        "KEN": [{"form": "20-F", "filing_date": "2026-04-01"}, {"form": "6-K", "filing_date": "2026-08-01"}],
    }
    monkeypatch.setattr(edgar, "recent_filings", lambda sym, forms=None, limit=40: filings[sym])
    assert uc._evidence_lookup("ABAT", "2026-09-14", "2026-09-14") is True
    assert uc._evidence_lookup("NB", "2026-09-09", "2026-09-14") is False
    assert uc._evidence_lookup("KEN", "2026-09-14", "2026-09-14") is False       # a foreign issuer, same day: not yet
    assert uc._evidence_lookup("KEN", "2026-09-12", "2026-09-14") is True
    rows = [{"symbol": "NB", "report_date": "2026-09-09", "eps_estimate": -0.035, "eps_actual": -0.035, "sources": "fmp"},
            {"symbol": "ABAT", "report_date": "2026-09-14", "eps_estimate": -0.05, "eps_actual": -0.15, "sources": "fmp"}]
    assert uc.actual_evidence(rows, "2026-09-14") == {"NB": False}                # only the placeholder is looked up


def test_fmp_fetches_a_long_range_a_week_at_a_time_and_splits_a_capped_week():
    from alphadesk.providers.company_vendors import FmpPrices
    f = FmpPrices(api_key="k")
    f._RANGE_CAP = 3
    asked = []

    def fake(path, **p):
        asked.append((p["from"], p["to"]))
        if p["from"] == "2026-09-07" and p["to"] == "2026-09-13":
            return [{"symbol": s, "date": "2026-09-09"} for s in "ABC"]     # the cap: split into days
        return [{"symbol": "NB", "date": p["from"], "epsActual": None, "epsEstimated": -0.04}]
    f._get = fake
    rows = f.earnings_calendar("2026-09-07", "2026-09-20")
    days = [f"2026-09-{d:02d}" for d in range(7, 14)]
    assert sorted(asked) == sorted([("2026-09-07", "2026-09-13"), *[(d, d) for d in days], ("2026-09-14", "2026-09-20")])
    assert len(rows) == 8 and {r["report_date"] for r in rows} == {*days, "2026-09-14"}


def test_fmp_answers_one_symbol_from_its_own_record():
    from alphadesk.providers.company_vendors import FmpPrices
    f = FmpPrices(api_key="k")
    f._get = lambda path, **p: ([{"symbol": "NB", "date": "2026-11-12", "epsActual": None, "epsEstimated": -0.04},
                                 {"symbol": "NB", "date": "2026-09-09", "epsActual": -0.035, "epsEstimated": -0.035},
                                 {"symbol": "NB", "date": "2026-03-01", "epsActual": -0.02, "epsEstimated": -0.03}]
                                if path == "earnings" and p.get("symbol") == "NB" else pytest.fail(f"unexpected {path}"))
    rows = f.earnings_calendar("2026-05-17", "2027-01-12", symbol="nb")
    assert sorted(r["report_date"] for r in rows) == ["2026-09-09", "2026-11-12"]


def test_filer_classification_reads_form_types():
    from alphadesk.ingest import edgar
    assert edgar.classify_filer(["6-K", "6-K", "20-F"]) is True
    assert edgar.classify_filer(["40-F", "6-K"]) is True
    assert edgar.classify_filer(["8-K", "10-Q", "10-K"]) is False
    assert edgar.classify_filer(["6-K", "10-Q"]) is False                      # files 10-Qs: domestic
    assert edgar.classify_filer([]) is None


def test_the_release_clock_comes_from_the_filing_index_header():
    """2026-09-14: the submissions record wrote Hain Celestial's same-day
    06:54 New York acceptance as 06:54 UTC; the index header is New York time."""
    hdr = "<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20260914065422\n<ACCESSION-NUMBER>0000910406-26-000123"
    assert edgar.index_accepted_at(hdr) == "2026-09-14T06:54:22-04:00"
    assert edgar.index_accepted_at("<ACCEPTANCE-DATETIME>20261214170000") == "2026-12-14T17:00:00-05:00"   # EST in winter
    assert edgar.index_accepted_at("no header") is None


def test_fill_times_stores_the_index_clock_and_marks_it(store, monkeypatch):
    store.upsert_release("HAIN", "a-1", "0000910406", "2026-09-14", "2026-09-14T02:54:22-04:00", "Hain", "2026-09-14")
    monkeypatch.setattr(edgar, "recent_filings", lambda sym, forms=None, limit=20: [
        {"accession": "a-1", "cik": "0000910406", "report_date": "2026-09-14", "items": "2.02,9.01",
         "accepted_at": "2026-09-14T02:54:22-04:00", "url": "u"}])
    monkeypatch.setattr(edgar, "accepted_at_from_index", lambda cik, acc: "2026-09-14T06:54:22-04:00")
    assert edgar_releases.fill_times("2026-09-01") == 1
    [row] = store.releases_between("2026-09-14", "2026-09-14")
    assert row["accepted_at"] == "2026-09-14T06:54:22-04:00"
    assert store.releases_missing_time("2026-09-01") == []            # verified once, not asked again


def test_listing_kind_keeps_one_exchange_listing_per_company():
    cik = {"OCCI": "1", "OCCIM": "1", "OCCIN": "1", "LEN": "2", "LEN-B": "2", "BBBMF": "3", "AAPL": "4"}
    by = {}
    for t, c in cik.items():
        by.setdefault(c, []).append(t)
    assert uc.listing_kind("OCCI", cik, by, "Nasdaq") == "primary"
    assert uc.listing_kind("OCCIM", cik, by, "Nasdaq") == "secondary"
    assert uc.listing_kind("LEN-B", cik, by, "NYSE") == "secondary"
    assert uc.listing_kind("BBBMF", cik, by, "OTC") == "otc"
    assert uc.listing_kind("AAPL", cik, by, "Nasdaq") == "primary"
    assert uc.listing_kind("NEWCO", cik, by, None) == "otc"                 # no exchange on record


def test_an_estimate_on_the_old_share_count_is_rescaled_for_a_recent_split():
    rows = [{"symbol": "OPTT", "report_date": "2026-09-14", "eps_estimate": -0.03, "eps_actual": None},
            {"symbol": "NVDA", "report_date": "2026-09-14", "eps_estimate": 8.0, "eps_actual": None},
            {"symbol": "OLD", "report_date": "2026-09-14", "eps_estimate": 1.0, "eps_actual": None}]
    splits = [{"symbol": "OPTT", "date": "2026-09-14", "to": 1.0, "from": 30.0},
              {"symbol": "NVDA", "date": "2026-09-01", "to": 10.0, "from": 1.0},
              {"symbol": "OLD", "date": "2026-07-01", "to": 2.0, "from": 1.0}]
    uc.adjust_for_splits(rows, splits)
    optt, nvda, old = rows
    assert optt["eps_estimate"] == -0.9 and optt["eps_estimate_unadjusted"] == -0.03 and "1-for-30" in optt["split_note"]
    assert nvda["eps_estimate"] == 0.8
    assert old["eps_estimate"] == 1.0 and "split_note" not in old             # months before: already in the estimate


def test_timing_needs_a_clear_habit():
    f = uc.timing_from_history
    assert f(["BMO", "BMO", "BMO", "BMO"]) == "BMO"
    assert f(["AMC", "AMC", "DAY", "AMC"]) == "AMC"                          # one late-day filing does not break a habit
    assert f(["BMO", "AMC", "BMO", "BMO"]) == "BMO"                         # three of four
    assert f(["BMO", "AMC", "AMC", "BMO"]) is None                          # split: no call
    assert f(["BMO", "BMO"]) == "BMO"                                        # both of two, all there is
    assert f(["BMO"]) is None
    assert f(["DAY", "DAY", "DAY", "BMO"]) is None


def test_predictions_fill_only_open_upcoming_primary_rows():
    rows = [{"symbol": "PLCE", "report_date": "2026-09-15", "session": "DAY", "confirmed": False, "listing": "primary"},
            {"symbol": "CBRL", "report_date": "2026-09-15", "session": "BMO", "confirmed": True, "listing": "primary"},
            {"symbol": "OCCIM", "report_date": "2026-09-15", "session": "DAY", "confirmed": False, "listing": "secondary"},
            {"symbol": "PAST", "report_date": "2026-09-11", "session": "DAY", "confirmed": False, "listing": "primary"},
            {"symbol": "OUT", "report_date": "2026-09-14", "session": "DAY", "confirmed": True, "released_on": "2026-09-14", "listing": "primary"}]
    asked = []
    uc.predict_sessions(rows, habit=lambda s: (asked.append(s), ("AMC", 4))[1], today="2026-09-14")
    assert asked == ["PLCE"] and rows[0]["session_predicted"] == "AMC" and rows[0]["session_basis"] == 4
    assert all("session_predicted" not in r for r in rows[1:])


def test_a_foreign_filers_habit_comes_from_its_6ks_on_past_report_dates():
    filings = [{"form": "6-K", "filing_date": "2026-06-10", "accepted_at": "2026-06-10T16:30:00-04:00"},
               {"form": "6-K", "filing_date": "2026-06-10", "accepted_at": "2026-06-10T18:02:00-04:00"},
               {"form": "6-K", "filing_date": "2026-03-11", "accepted_at": "2026-03-11T16:05:00-04:00"},
               {"form": "6-K", "filing_date": "2026-02-02", "accepted_at": "2026-02-02T08:00:00-05:00"},    # not a report day
               {"form": "6-K", "filing_date": "2025-12-09", "accepted_at": "2025-12-09T16:10:00-05:00"}]
    sessions = uc.foreign_release_sessions(filings, ["2026-06-10", "2026-03-11", "2025-12-09", "2025-09-10"])
    assert sessions == ["AMC", "AMC", "AMC"]                   # the earliest 6-K on each report day; no 6-K on the fourth
    assert uc.timing_from_history(sessions) == "AMC"


def test_an_estimate_is_rescaled_only_for_a_split_both_split_vendors_list(vendors, monkeypatch):
    class _FmpCal:
        name = "fmp"
        def earnings_calendar(self, start, end, symbol=None):
            return [{"symbol": s, "report_date": "2026-09-17", "session": "DAY", "confirmed": False, "eps_estimate": -0.03, "eps_actual": None}
                    for s in ("OPTT", "VMRK")]
        def split_calendar(self, s, e):
            return [{"symbol": "OPTT", "date": "2026-09-15", "to": 1.0, "from": 30.0, "kind": None},
                    {"symbol": "VMRK", "date": "2026-09-15", "to": 2.0, "from": 1.0, "kind": None}]      # never took effect

    class _AlpacaSplits:
        name = "alpaca"
        def split_calendar(self, s, e):
            return [{"symbol": "OPTT", "date": "2026-09-15", "to": 1.0, "from": 30.0, "kind": "reverse"}]

    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"OPTT": "1", "VMRK": "2"})
    monkeypatch.setattr(edgar, "company_title", lambda s: s)
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {})
    monkeypatch.setattr(uc, "_release_habit", lambda sym, dates: (None, None))
    vendors(fmp=_FmpCal(), alpaca=_AlpacaSplits())
    rows = {r["symbol"]: r for r in uc.rows_between("2026-09-13", "2026-09-19", stats=False)}
    assert rows["OPTT"]["eps_estimate"] == -0.9 and rows["VMRK"]["eps_estimate"] == -0.03
    vendors(fmp=_FmpCal())                          # one split vendor: nothing to check against, its splits stand
    rows = {r["symbol"]: r for r in uc.rows_between("2026-09-13", "2026-09-19", stats=False)}
    assert rows["VMRK"]["eps_estimate"] == -0.015


def test_release_habits_are_read_back_for_the_reader_and_a_failed_lookup_is_not_stored(store, monkeypatch):
    from alphadesk.providers import registry
    asked = []

    def habit(sym, dates):
        asked.append(sym)
        if sym == "DOWN":
            raise RuntimeError("EDGAR paused")
        return ("AMC", 4) if sym == "ADBE" else (None, 0)
    monkeypatch.setattr(uc, "_today_et", lambda: "2026-09-14")
    monkeypatch.setattr(uc, "_release_habit", habit)
    router = registry.DataRouter("reader-1", {})
    rows = [{"symbol": s, "report_date": "2026-09-16", "session": "DAY"} for s in ("ADBE", "TINY", "DOWN")]
    rows.append({"symbol": "PAST", "report_date": "2026-09-01", "session": "DAY"})          # a passed date is not asked
    got = uc.release_habits_for(router, rows, None)
    assert sorted(asked) == ["ADBE", "DOWN", "TINY"] and got == {"ADBE": ("AMC", 4), "TINY": (None, 0)}
    asked.clear()
    got = uc.release_habits_for(router, rows, None)                     # a fresh build: stored ones are not asked again
    assert asked == [] and got["ADBE"] == ("AMC", 4) and got["TINY"] == (None, 0)   # DOWN failed: retried later
    from alphadesk.ingest import background_fill
    background_fill._failed.clear()
    uc.release_habits_for(router, rows, None)
    assert asked == ["DOWN"]
    asked.clear()
    uc.release_habits_for(registry.DataRouter("reader-2", {}), rows, None)       # another reader's store is their own
    assert sorted(asked) == ["ADBE", "DOWN", "TINY"]


def test_each_day_lists_the_largest_company_first_and_companies_without_a_value_after(vendors, monkeypatch):
    class _Caps:
        name = "fmp"
        def market_caps(self, symbols):
            return {"TINY": 5e11}                                   # a big company that trades little
    vendors(finnhub=_Cal(), alpaca=_Bars(), fmp=_Caps())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"ADBE": "0000796343", "TINY": "0000000001"})
    monkeypatch.setattr(edgar, "company_title", lambda s: s)
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {})
    rows = uc.rows_between("2026-09-10", "2026-09-10")
    assert [(r["symbol"], r["market_cap"]) for r in rows] == [("TINY", 5e11), ("ADBE", None)]   # ADBE has no value: after, though most traded


def test_a_week_with_many_timing_lookups_returns_at_once_and_fills_them_in_the_background(store, monkeypatch):
    from alphadesk.ingest import background_fill
    from alphadesk.providers import registry
    queued = []
    monkeypatch.setattr(background_fill, "submit", lambda kind, owner, syms, job: queued.append((kind, list(syms), job)) or 1)
    monkeypatch.setattr(uc, "_today_et", lambda: "2026-09-14")
    monkeypatch.setattr(uc, "HABIT_BLOCK_LIMIT", 2)
    monkeypatch.setattr(uc, "_release_habit", lambda sym, dates: ("BMO", 3))
    router = registry.DataRouter("reader-1", {})
    rows = [{"symbol": s, "report_date": "2026-10-20", "session": "DAY"} for s in ("A", "B", "C")]
    pending = {}
    assert uc.release_habits_for(router, rows, None, pending) == {} and pending == {"timing": 3}
    kind, syms, job = queued[0]
    assert kind == "timing" and syms == ["A", "B", "C"]
    job(syms)                                                           # the background run stores them
    assert uc.release_habits_for(router, rows, None, {}) == {s: ("BMO", 3) for s in "ABC"}


# A FOREIGN PRIVATE ISSUER'S RESULTS (2026-09-16). ZTO Express announced its
# second quarter on a 6-K; the 8-K sweep is blind to those, so the company
# appeared nowhere in the calendar week the reader was looking at and nothing
# could confirm the date a vendor gave.

def test_a_6k_exhibit_is_a_results_release_only_with_a_period_named():
    zto = ("Exhibit 99.1 ZTO Reports Second Quarter 2026 Unaudited Financial Results "
           "10.5 Billion Parcels Expanded Market Share to 19.9% SHANGHAI, August 19, 2026 /PRNewswire/ - ZTO")
    assert edgar_releases.is_results_release(zto)
    assert edgar_releases.is_results_release(
        "Interim Results Announcement for the Six Months Ended June 30, 2026")
    assert edgar_releases.is_results_release(
        "TOP WEALTH GROUP HOLDING LIMITED ANNOUNCES FINANCIAL RESULTS for the fiscal year ended March 31, 2026")
    # Results mentioned in passing, with no period: not an announcement.
    assert not edgar_releases.is_results_release(
        "The board has appointed a new auditor to review the financial results going forward.")
    assert not edgar_releases.is_results_release(
        "Next Day Disclosure Return dated September 14, 2026 in respect of share buy-backs")
    assert not edgar_releases.is_results_release("")


def test_the_release_day_of_a_6k_comes_from_the_dateline():
    assert edgar_releases.dateline_day(
        "ZTO Reports Second Quarter 2026 Unaudited Financial Results SHANGHAI, August 19, 2026 "
        "/PRNewswire/ - ZTO Express (Cayman) Inc.") == "2026-08-19"
    assert edgar_releases.dateline_day(
        "BEIJING, Aug. 18, 2026 (GLOBE NEWSWIRE) - iQIYI, Inc. today announced") == "2026-08-18"
    assert edgar_releases.dateline_day("No dateline at all in this document.") is None


def test_a_6k_keeps_a_vendor_date_a_day_away_and_still_records_the_filing():
    """The dateline is the issuer's own calendar: ZTO announced on the evening
    of August 18 in New York and datelined the release Shanghai, August 19.
    The filing confirms the report; it does not move it onto the other day,
    and its morning clock never becomes the release time."""
    rows = [{"symbol": "ZTO", "report_date": "2026-08-18", "session": "AMC", "confirmed": True,
             "eps_actual": 0.56}]
    rel = {"ZTO": [{"symbol": "ZTO", "accession": "a1", "file_date": "2026-08-19",
                    "event_date": "2026-08-19", "accepted_at": "2026-08-19T06:05:00-04:00", "form": "6-K"}]}
    uc.join_releases(rows, rel, today="2026-09-16")
    r = rows[0]
    assert r["report_date"] == "2026-08-18" and not r.get("date_from_edgar")
    assert r["session"] == "AMC" and r.get("vendor_session") is None
    assert r["released_at"] is None                    # a morning filing is not an evening release
    assert r["released_on"] == "2026-08-19" and r["filed_on"] == "2026-08-19"
    assert r["release_accession"] == "a1"


def test_a_6k_a_week_from_the_vendor_date_still_moves_the_report():
    rows = [{"symbol": "XYZ", "report_date": "2026-08-12", "session": None, "confirmed": False,
             "eps_actual": 1.0}]
    rel = {"XYZ": [{"symbol": "XYZ", "accession": "b1", "file_date": "2026-08-19",
                    "event_date": "2026-08-19", "accepted_at": "2026-08-19T06:00:00-04:00", "form": "6-K"}]}
    uc.join_releases(rows, rel, today="2026-09-16")
    assert rows[0]["report_date"] == "2026-08-19" and rows[0]["date_from_edgar"]


def test_a_domestic_filing_is_unaffected_by_the_foreign_tolerance():
    """Kroger's 8-K a day from Finnhub's date must still move the report —
    the tolerance belongs to the dateline of an issuer abroad, not to 8-Ks."""
    rows = [{"symbol": "KR", "report_date": "2026-09-10", "session": None, "confirmed": False,
             "eps_actual": 1.0}]
    rel = {"KR": [{"symbol": "KR", "accession": "c1", "file_date": "2026-09-11",
                   "event_date": "2026-09-11", "accepted_at": "2026-09-11T08:30:00-04:00", "form": "8-K"}]}
    uc.join_releases(rows, rel, today="2026-09-16")
    assert rows[0]["report_date"] == "2026-09-11" and rows[0]["date_from_edgar"]
    assert rows[0]["released_at"] == "2026-09-11T08:30:00-04:00"


def test_foreign_candidates_keep_the_exhibit_over_the_cover_page():
    hits = [
        {"_id": "0001104659-26-098506:tm2623526d1_6k.htm",
         "_source": {"adsh": "0001104659-26-098506", "file_date": "2026-08-19", "file_type": "6-K",
                     "display_names": ["ZTO Express (Cayman) Inc.  (ZTO, ZTOEF)  (CIK 0001677250)"]}},
        {"_id": "0001104659-26-098506:tm2623526d1_ex99-1.htm",
         "_source": {"adsh": "0001104659-26-098506", "file_date": "2026-08-19", "file_type": "EX-99.1",
                     "display_names": ["ZTO Express (Cayman) Inc.  (ZTO, ZTOEF)  (CIK 0001677250)"]}},
    ]
    rows = {r["symbol"]: r for r in edgar_releases.foreign_candidates(hits)}
    assert set(rows) == {"ZTO", "ZTOEF"}              # both listings of one filer
    assert rows["ZTO"]["document"] == "tm2623526d1_ex99-1.htm" and rows["ZTO"]["is_exhibit"]
    assert rows["ZTO"]["cik"] == "0001677250"
