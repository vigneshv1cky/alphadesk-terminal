"""The option-chain join.

The fetch is two upstream calls that know different halves — the contracts
endpoint knows strike, side and open interest; the chain snapshot knows the
quote. `_merge` is where they meet, and the rules it enforces are the ones a
reader would be misled by if they broke.
"""

from types import SimpleNamespace

from alphadesk.ingest import options


def contract(sym, strike, side, oi=0):
    return SimpleNamespace(symbol=sym, strike_price=strike, type=side, open_interest=oi)


def snap(bid=None, ask=None, last=None, **extra):
    """Alpaca's REST snapshot shape."""
    q = {k: v for k, v in (("bp", bid), ("ap", ask)) if v is not None}
    return {"latestQuote": q or None, "latestTrade": {"p": last} if last else None, **extra}


class TestMerge:
    def test_sides_split_and_each_is_strike_ordered(self):
        cs = [contract("C3", 30, "call"), contract("P1", 10, "put"),
              contract("C1", 10, "call"), contract("P2", 20, "put"),
              contract("C2", 20, "call")]
        calls, puts = options._merge(cs, {})
        # A chain is a price ladder; any order but ascending strike destroys the
        # only structure it has.
        assert [r["strike"] for r in calls] == [10, 20, 30]
        assert [r["strike"] for r in puts] == [10, 20]

    def test_mid_needs_both_sides(self):
        cs = [contract("A", 10, "call"), contract("B", 20, "call"), contract("C", 30, "call")]
        snaps = {"A": snap(bid=1.0, ask=1.4), "B": snap(bid=2.0), "C": snap(ask=3.0)}
        calls, _ = options._merge(cs, snaps)
        by = {r["strike"]: r for r in calls}
        assert by[10]["mid"] == 1.2
        # One-sided books are normal far from the money. A mid off a single side
        # is an invented price, not a wide one, so it stays null.
        assert by[20]["mid"] is None and by[20]["bid"] == 2.0
        assert by[30]["mid"] is None and by[30]["ask"] == 3.0

    def test_a_contract_with_no_snapshot_still_renders(self):
        """Open interest and strike come from the contract, not the quote — a
        contract nobody is quoting is a real row, not a dropped one."""
        calls, _ = options._merge([contract("X", 50, "call", oi=1234)], {})
        assert len(calls) == 1
        row = calls[0]
        assert row["open_interest"] == 1234 and row["strike"] == 50.0
        assert row["bid"] is None and row["ask"] is None and row["mid"] is None

    def test_open_interest_missing_is_zero_not_none(self):
        """The column is a count. None would render as a dash and read as
        'unknown' when the feed's own answer is 'none outstanding'."""
        calls, _ = options._merge([contract("Y", 5, "call", oi=None)], {})
        assert calls[0]["open_interest"] == 0

    def test_volume_counts_only_from_the_chains_latest_session_and_greeks_come_through(self):
        """A contract that last traded days ago carries that day's bar: its
        volume is not today's (2026-09-14, NVDA's deep strikes)."""
        cs = [contract("A", 205, "put"), contract("B", 20, "put")]
        snaps = {"A": snap(bid=1.26, ask=1.3, last=1.27, dailyBar={"t": "2026-09-14T04:00:00Z", "v": 18384},
                           prevDailyBar={"c": 1.0}, impliedVolatility=0.4405, quoteSizes=None,
                           greeks={"delta": -0.2224, "gamma": 0.0305, "theta": -0.3591, "vega": 0.0661, "rho": -0.0053}),
                 "B": snap(last=203.3, dailyBar={"t": "2026-09-09T04:00:00Z", "v": 50})}
        snaps["A"]["latestQuote"].update({"bs": 49, "as": 41})
        _, puts = options._merge(cs, snaps)
        stale, live = puts
        assert live["volume"] == 18384 and stale["volume"] == 0
        assert live["implied_volatility"] == 44.0 and live["delta"] == -0.2224 and live["theta"] == -0.3591
        assert live["bid_size"] == 49 and live["ask_size"] == 41 and live["change_pct"] == 27.0
        assert stale["delta"] is None and stale["implied_volatility"] is None

    def test_contract_type_enum_repr_is_handled(self):
        """alpaca-py hands back ContractType.CALL, not the string 'call'."""
        cs = [contract("Z", 5, "ContractType.CALL"), contract("W", 5, "ContractType.PUT")]
        calls, puts = options._merge(cs, {})
        assert len(calls) == 1 and len(puts) == 1


class TestFlow:
    """The flow screener's capture (2026-09-14): a trade's side is known only
    when it is seen close to its quote."""

    def test_occ_symbols_parse_and_fills_classify_against_the_spread(self):
        from alphadesk.ingest import options_flow as of
        assert of.parse_occ("NVDA260918P00205000") == {"underlying": "NVDA", "expiry": "2026-09-18", "type": "put", "strike": 205.0}
        assert of.parse_occ("SPXW260915C07660000")["strike"] == 7660.0 and of.parse_occ("junk") is None
        assert of.classify(1.30, 1.26, 1.30) == ("ask", 1.0)
        assert of.classify(1.26, 1.26, 1.30) == ("bid", 0.0)
        assert of.classify(1.28, 1.26, 1.30)[0] == "mid"
        assert of.classify(1.28, None, 1.30) == (None, None)

    def test_old_trades_keep_an_unknown_side_and_new_ones_are_classified_then_remembered(self):
        from datetime import datetime, timezone
        from alphadesk.ingest import options_flow as of
        of._states.clear()
        occ = "NVDA260918C00210000"

        class _V:
            def __init__(self):
                self.trades = [{"symbol": occ, "t": "2026-09-14T14:00:00.123456789Z", "price": 2.0, "size": 500, "exchange": "X"},
                               {"symbol": occ, "t": "2026-09-14T15:00:00Z", "price": 0.05, "size": 10, "exchange": "X"}]
                self.quote = {"bid": 1.9, "ask": 2.0}
                self.asked_since = []
            def option_active_contracts(self, symbol, top=40):
                return {"feed": "opra", "session": "2026-09-14", "contracts": [{"symbol": occ, "volume": 9000, "open_interest": 1200}]}
            def option_trades(self, symbols, start):
                self.asked_since.append(start)
                return [t for t in self.trades if t["t"] >= start[:19]]
            def option_latest_quotes(self, symbols):
                return {occ: self.quote}

        v = _V()
        first = of.flow(v, "reader-1", "nvda", min_premium=25_000, now=datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc))
        assert v.asked_since[0] == "2026-09-14T13:30:00Z"                      # the session's open
        assert [(r["premium"], r["side"]) for r in first["trades"]] == [(100_000.0, None)]   # seen late: side unknown
        assert first["trades"][0]["strike"] == 210.0 and first["trades"][0]["open_interest"] == 1200
        assert first["trades"][0]["dte"] == 4
        of._states.clear()
        late = of.flow(v, "reader-1", "NVDA", now=datetime(2026, 9, 15, 0, 30, tzinfo=timezone.utc))   # 20:30 New York, Monday
        assert late["trades"][-1]["dte"] == 4
        of._states.clear()
        first = of.flow(v, "reader-1", "nvda", min_premium=25_000, now=datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc))

        v.trades.append({"symbol": occ, "t": "2026-09-14T15:30:05Z", "price": 1.9, "size": 300, "exchange": "C"})
        second = of.flow(v, "reader-1", "NVDA", min_premium=25_000, now=datetime(2026, 9, 14, 15, 30, 10, tzinfo=timezone.utc))
        assert [(r["t"], r["side"]) for r in second["trades"]] == [("2026-09-14T15:30:05Z", "bid"), ("2026-09-14T14:00:00.123456Z", None)]
        v.quote = {"bid": 1.0, "ask": 1.1}
        third = of.flow(v, "reader-1", "NVDA", min_premium=25_000, now=datetime(2026, 9, 14, 15, 31, tzinfo=timezone.utc))
        assert third["trades"][0]["side"] == "bid" and third["trades"][0]["bid"] == 1.9      # remembered, not re-read
        assert of.flow(v, "reader-2", "NVDA", now=datetime(2026, 9, 14, 15, 31, tzinfo=timezone.utc))["trades"][0]["side"] is None


def test_a_new_session_starts_a_new_capture():
    from datetime import datetime, timezone
    from alphadesk.ingest import options_flow as of
    of._states.clear()
    occ = "NVDA260918C00210000"

    class _V:
        tape = [{"symbol": occ, "t": "2026-09-14T14:00:00Z", "price": 2.0, "size": 500}]
        def option_active_contracts(self, symbol, top=40):
            return {"contracts": [{"symbol": occ, "volume": 1, "open_interest": 1}]}
        def option_trades(self, symbols, start):
            return [t for t in self.tape if t["t"] >= start[:19]]
        def option_latest_quotes(self, symbols):
            return {}
    v = _V()
    monday = of.flow(v, "r", "NVDA", now=datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc))
    assert [r["t"][:10] for r in monday["trades"]] == ["2026-09-14"]
    v.tape = v.tape + [{"symbol": occ, "t": "2026-09-15T14:00:00Z", "price": 3.0, "size": 500}]
    tuesday = of.flow(v, "r", "NVDA", now=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc))
    assert [r["t"][:10] for r in tuesday["trades"]] == ["2026-09-15"]


def test_prints_in_one_millisecond_are_one_order_and_conditions_name_it():
    from alphadesk.ingest import options_flow as of
    occ = "NVDA260918C00212500"
    prints = [{"symbol": occ, "t": "2026-09-14T13:31:58.895001Z", "price": 2.00, "size": 10, "exchange": "C", "condition": "S"},
              {"symbol": occ, "t": "2026-09-14T13:31:58.895420Z", "price": 2.02, "size": 30, "exchange": "X", "condition": "I"},
              {"symbol": occ, "t": "2026-09-14T13:31:59.000000Z", "price": 2.10, "size": 5, "exchange": "C", "condition": "f"},
              {"symbol": occ, "t": "2026-09-14T13:32:00.000000Z", "price": 9.99, "size": 5, "exchange": "C", "condition": "A"}]   # cancelled
    orders = sorted(of.group_orders(prints), key=lambda o: o["t"])
    assert len(orders) == 2
    sweep, leg = orders
    assert sweep["size"] == 40 and sweep["price"] == 2.015 and sweep["premium"] == 8060.0 and sweep["exchanges"] == ["C", "X"]
    assert of.flags_for(set(sweep["conditions"]), len(sweep["exchanges"]), 40, 500) == ["sweep"]
    assert of.flags_for(set(leg["conditions"]), 1, 900, 500) == ["multi-leg", "size>OI"]
    assert of.flags_for({"e"}, 1, None, None) == ["floor"] and of.flags_for({"n"}, 1, None, None) == ["stock-tied"]


def test_several_symbols_carry_the_stock_price_and_the_live_ask_share():
    from datetime import datetime, timezone
    from alphadesk.ingest import options_flow as of
    of._states.clear()

    class _V:
        def __init__(self):
            self.tape = {"NVDA": [], "AAPL": []}
            self.quote = {"bid": 1.9, "ask": 2.0}
        def option_active_contracts(self, symbol, top=40):
            occ = f"{symbol}260918C00210000"
            return {"feed": "opra", "contracts": [{"symbol": occ, "volume": 900, "open_interest": 1000}]}
        def option_trades(self, symbols, start):
            return [t for s in symbols for t in self.tape[s[:4]] if t["symbol"] == s and t["t"] >= start[:19]]
        def option_latest_quotes(self, symbols):
            return {s: self.quote for s in symbols}
        def stock_minute_closes(self, symbol, start):
            return {"2026-09-14T15:30": 212.4 if symbol == "NVDA" else 332.1}

    v = _V()
    now = datetime(2026, 9, 14, 15, 30, 10, tzinfo=timezone.utc)
    of.flow(v, "r", ["NVDA", "AAPL"], now=now)                                      # capture starts
    v.tape["NVDA"] = [{"symbol": "NVDA260918C00210000", "t": "2026-09-14T15:30:15Z", "price": 2.0, "size": 200, "exchange": "C", "condition": "I"},
                      {"symbol": "NVDA260918C00210000", "t": "2026-09-14T15:30:16Z", "price": 1.9, "size": 100, "exchange": "C", "condition": "I"}]
    v.tape["AAPL"] = [{"symbol": "AAPL260918C00210000", "t": "2026-09-14T15:30:17Z", "price": 3.0, "size": 300, "exchange": "X", "condition": "I"}]
    out = of.flow(v, "r", ["nvda", "AAPL", "nvda"], min_premium=10_000, now=datetime(2026, 9, 14, 15, 30, 20, tzinfo=timezone.utc))
    assert out["symbols"] == ["NVDA", "AAPL"] and out["errors"] == {}
    by = {(r["ticker"], r["t"]): r for r in out["trades"]}
    nvda = by[("NVDA", "2026-09-14T15:30:15Z")]
    assert nvda["stock"] == 212.4 and nvda["side"] == "ask" and nvda["ask_share"] == round(200 / 300, 3) and nvda["share_contracts"] == 300
    assert by[("AAPL", "2026-09-14T15:30:17Z")]["stock"] == 332.1
    assert ("NVDA", "2026-09-14T15:30:16Z") in by                                    # $19K: over the $10K floor
