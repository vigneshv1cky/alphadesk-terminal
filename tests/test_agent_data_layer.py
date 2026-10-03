"""2026-10-03: what an agent needs to answer "why did this stock move" in one pass —
press-release exhibits, holder notices, a share count for a foreign filer, the
price/news/filing join, and the repair of stories stored without their tickers."""
import json
import uuid

from alphadesk.desk import moves
from alphadesk.ingest import edgar, news


def test_a_holder_notice_gives_the_share_count_it_implies():
    text = ("Reporting Person beneficially owns 70,082 Shares, representing approximately 3.74% "
            "of the Issuer's outstanding common stock.")
    assert edgar.derive_shares(text) == 1_873_900
    assert edgar.derive_shares("nothing about holdings here") is None
    assert edgar.derive_shares("owns 5 shares, approximately 0% of the class") is None


def test_holder_notices_are_readable_under_their_current_names():
    for form in ("SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"):
        assert edgar.is_readable(form) and form in edgar.DEFAULT_FORMS
    assert not edgar.is_readable("4")


def test_a_filing_reads_with_its_press_release_exhibit(monkeypatch):
    base = "https://www.sec.gov/Archives/edgar/data/1/000000000026000001"
    pages = {
        f"{base}/main.htm": b"<html><body>Attached is a press release.</body></html>",
        f"{base}/ex99-1.htm": b"<html><body>OceanPal exits shipping and retires Series C.</body></html>",
        f"{base}/ex3-1.htm": b"<html><body>Articles of incorporation.</body></html>",
        f"{base}/index.json": json.dumps({"directory": {"item": [
            {"name": "main.htm"}, {"name": "ex99-1.htm"}, {"name": "ex3-1.htm"}, {"name": "image_001.jpg"}]}}).encode(),
    }
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: pages[url])
    assert edgar.exhibit_documents(f"{base}/main.htm") == [f"{base}/ex99-1.htm"]
    text = edgar.fetch_filing_with_exhibits(f"{base}/main.htm")
    assert "Attached is a press release." in text
    assert "[EXHIBIT ex99-1.htm]" in text and "retires Series C" in text
    assert "Articles of incorporation" not in text          # only press-release exhibits


def test_a_missing_folder_index_leaves_the_main_document(monkeypatch):
    def get(url, timeout=15.0):
        if url.endswith("index.json"):
            raise OSError("no index")
        return b"<html><body>Only the cover.</body></html>"
    monkeypatch.setattr(edgar, "_get", get)
    assert edgar.fetch_filing_with_exhibits("https://www.sec.gov/Archives/edgar/data/1/2/main.htm") == "Only the cover."


def _bars(closes, start="2026-09-01"):
    from datetime import date, timedelta
    d, out = date.fromisoformat(start), []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"t": d.isoformat(), "c": c, "v": 1000})
        d += timedelta(days=1)
    return out


def test_big_moves_are_matched_to_the_stories_and_filings_leading_into_them():
    bars = _bars([10, 10.2, 12.6, 12.5, 12.4])           # +23.5% on Sep 3
    articles = [
        {"published_at": "2026-09-02T22:00:00+00:00", "title": "after the close", "kind": "company", "tickers": ["X"]},
        {"published_at": "2026-09-03T13:00:00+00:00", "title": "pre-market", "kind": "movers", "tickers": ["A"] * 12},
        {"published_at": "2026-09-08T13:00:00+00:00", "title": "much later", "kind": None, "tickers": ["X"]},
    ]
    filings = [{"form": "6-K", "filing_date": "2026-09-02", "accession": "A-1", "readable": True,
                "accepted_at": "2026-09-02T17:30:00-04:00"}]
    got = moves.join_moves(bars, articles, filings, min_move_pct=10)
    (day,) = got["big_move_days"]
    assert day["date"] == "2026-09-03" and day["change_pct"] == 23.53
    assert [s["title"] for s in day["stories"]] == ["after the close", "pre-market"]
    assert day["stories"][1]["named_tickers"] == 12
    assert [f["accession"] for f in day["filings"]] == ["A-1"]
    assert not day["nothing_attached"]
    (reaction,) = got["filing_reactions"]                 # accepted after the close: the next session reacts
    assert reaction["reaction_session"] == "2026-09-03" and reaction["change_pct"] == 23.53


def test_a_move_with_nothing_around_it_says_so():
    got = moves.join_moves(_bars([10, 10.1, 13, 13]), [], [], min_move_pct=10)
    assert got["big_moves_with_nothing_attached"] == 1
    assert got["big_move_days"][0]["nothing_attached"] is True


def test_the_board_repair_asks_each_symbol_once(store, monkeypatch):
    uid = uuid.uuid4().hex
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    store.save_board(uid, ["SVRN", "NVDA", "MU", "AAPL"], "SVRN")
    asked = []
    monkeypatch.setattr(news, "symbol_articles", lambda u, s, b, n: asked.append(s) or [])
    assert news.repair_board_tickers(uid, max_symbols=3) == 3
    assert news.repair_board_tickers(uid, max_symbols=3) == 1      # the rest, nothing twice
    assert news.repair_board_tickers(uid, max_symbols=3) == 0
    assert sorted(asked) == ["AAPL", "MU", "NVDA", "SVRN"]
