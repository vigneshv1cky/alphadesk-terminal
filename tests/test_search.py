"""Symbol search ranking.

The picker is how a symbol gets onto the board, so a bad first result is not a
cosmetic problem — it is the difference between typing a company name and
getting the company, or getting an ETF that merely mentions it.
"""

from alphadesk.config import _norm, _rank


def rank(sym, name, query):
    q = query.strip().upper()
    q_norm = _norm(q)
    return _rank(sym, name, q, q_norm, [t for t in q_norm.split() if t])


def better(a, b):
    """a outranks b — lower score wins, None means no match at all."""
    assert a is not None, "expected a match"
    return b is None or a < b


class TestNormalisation:
    def test_punctuation_becomes_space(self):
        """This is the whole reason "coca cola" used to miss Coca-Cola: the old
        search asked whether the raw query was a substring of the raw name, so
        a hyphen and a space never met and KO was unreachable by name."""
        assert _norm("Coca-Cola Company") == "COCA COLA COMPANY"
        assert _norm("Berkshire Hathaway Inc.  Class B") == "BERKSHIRE HATHAWAY INC. CLASS B"

    def test_the_dot_survives_because_tickers_use_it(self):
        """Everything else collapses to a space, but a full stop does not —
        BRK.B is a ticker, and stripping the dot would make it unmatchable by
        the exact-symbol tier. The cost is a trailing "CO." left in some
        company names, which changes no prefix or substring match."""
        assert _norm("JPMorgan Chase & Co.") == "JPMORGAN CHASE CO."
        assert rank("BRK.B", "Berkshire Hathaway Inc. Class B", "BRK.B") == 0

    def test_coca_cola_now_matches(self):
        assert rank("KO", "Coca-Cola Company", "coca cola") is not None


class TestTiers:
    def test_exact_ticker_beats_everything(self):
        exact = rank("VG", "Venture Global, Inc.", "VG")
        prefix = rank("VGT", "Vanguard Information Technology ETF", "VG")
        assert exact == 0
        assert better(exact, prefix)

    def test_ticker_prefix_beats_a_name_match(self):
        pref = rank("NVDA", "NVIDIA Corporation Common Stock", "NVD")
        name = rank("XYZ", "Something about NVD Holdings", "NVD")
        assert better(pref, name)

    def test_name_prefix_beats_a_name_substring(self):
        head = rank("MU", "Micron Technology, Inc. Common Stock", "micro")
        mid = rank("ZZZZ", "Acme Microelectronics Holdings", "micro")
        assert better(head, mid)

    def test_tokens_match_in_any_order(self):
        """"global venture" should still find Venture Global."""
        assert rank("VG", "Venture Global, Inc.", "global venture") is not None

    def test_no_match_returns_none(self):
        assert rank("AAPL", "Apple Inc. Common Stock", "zzzzz") is None


class TestDerivativesAreDemoted:
    def test_company_outranks_the_etf_named_after_it(self):
        """The failure that prompted this: "jpmorgan" answered JIG, a JPMorgan
        ETF, ahead of JPMorgan itself, because both merely contained the word
        and the tie fell to dictionary order."""
        company = rank("JPM", "JPMorgan Chase & Co.", "jpmorgan")
        etf = rank("JIG", "JPMorgan International Growth ETF", "jpmorgan")
        assert better(company, etf)

    def test_leveraged_notes_are_demoted(self):
        company = rank("MU", "Micron Technology, Inc. Common Stock", "micro")
        etn = rank("BNKU", "MicroSectors U.S. Big Banks 3x Leveraged ETNs due 2045", "micro")
        assert better(company, etn)

    def test_shorter_ticker_wins_within_a_tier(self):
        """Favours the primary listing over its derivatives, which are almost
        always longer symbols built off the parent."""
        short = rank("TSLA", "Tesla, Inc. Common Stock", "tesla")
        long_ = rank("TSLAX", "Tesla 2X Long Fund", "tesla")
        assert better(short, long_)


class TestSymbolSubstring:
    """Typing part of a ticker should reach tickers containing it.

    "fd" matched only the 41 symbols starting FD; the 28 that merely contain it
    — CLFD, BZFD, DFDV, MFDX — had no tier at all and were unreachable however
    far you scrolled.
    """

    def test_a_ticker_containing_the_query_matches(self):
        assert rank("CLFD", "Clearfield, Inc.", "FD") is not None
        assert rank("BZFD", "BuzzFeed, Inc.", "FD") is not None

    def test_prefix_still_outranks_containment(self):
        pref = rank("FDX", "FedEx Corporation", "FD")
        mid = rank("CLFD", "Clearfield, Inc.", "FD")
        assert better(pref, mid)

    def test_a_name_prefix_still_outranks_a_buried_ticker(self):
        """Two letters sit inside an enormous number of tickers. For "co" the
        company whose NAME starts with it is far likelier to be the one meant
        than an arbitrary symbol with CO in the middle."""
        by_name = rank("KO", "Coca-Cola Company", "CO")
        by_ticker = rank("DOCO", "Some Other Holdings", "CO")
        assert better(by_name, by_ticker)

    def test_single_character_does_not_trigger_containment(self):
        """One letter is in half the market; it would return noise, not a
        search. Prefix and exact still work at one character."""
        assert rank("CLFD", "Clearfield, Inc.", "F") is None
        assert rank("F", "Ford Motor Company", "F") == 0


class TestMetadataSelfHeal:
    """The symbol list comes from the SEC's ticker file (keyless). A failed
    fetch must not go to the SEC again on every keystroke."""

    def test_a_missing_cache_triggers_one_fetch_not_one_per_call(self, monkeypatch, tmp_path):
        import alphadesk.config as cfg

        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            raise RuntimeError("SEC unreachable")

        monkeypatch.setattr(cfg, "_NAMES_CACHE", tmp_path / "absent.json")
        monkeypatch.setattr(cfg, "_fetch_sec_names", fake_fetch)
        monkeypatch.setattr(cfg, "_names", None)
        monkeypatch.setattr(cfg, "_names_fetch_tried", False)

        assert cfg.search_symbols("AAPL") == []
        assert cfg.search_symbols("NVDA") == []
        assert cfg.search_symbols("MSFT") == []
        assert calls["n"] == 1

    def test_the_sec_file_maps_tickers_names_and_exchanges(self, monkeypatch, tmp_path):
        import json
        import alphadesk.config as cfg
        from alphadesk.ingest import edgar
        payload = {"fields": ["cik", "name", "ticker", "exchange"],
                   "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"], [1, "Apple iSports Group, Inc.", "AAPI", "OTC"]]}
        monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: json.dumps(payload).encode())
        monkeypatch.setattr(cfg, "_NAMES_CACHE", tmp_path / "names.json")
        monkeypatch.setattr(cfg, "_names", None)
        monkeypatch.setattr(cfg, "_names_fetch_tried", False)
        hits = cfg.search_symbols("apple", limit=5)
        assert [h["symbol"] for h in hits][:2] == ["AAPL", "AAPI"]           # an exchange listing before OTC
        assert hits[0] == {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "Nasdaq", "asset_class": "Equity"}
        assert cfg.symbol_meta("BTC-USD")["asset_class"] == "Cryptocurrency"


class TestNamesTheMarketUses:
    """A company is typed as the market says it, not as it files (2026-09-18,
    the reader searched TSMC and got nothing back)."""

    def test_initials_reach_a_name_that_contains_neither_the_query_nor_the_ticker(self):
        """TSMC appears nowhere: the ticker is TSM and the registered name is
        Taiwan Semiconductor Manufacturing Co Ltd. Its initials are TSMCL."""
        tsm = rank("TSM", "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "tsmc")
        assert tsm is not None
        # Last tier: anything that genuinely matched by name or ticker wins.
        assert better(rank("TSM", "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "taiwan"), tsm)
        assert better(rank("TSMC", "Some Other Corp", "tsmc"), tsm)      # an exact ticker

    def test_initials_need_four_characters_because_shorter_is_noise(self):
        """Measured over 10,449 listings: "TSMC" matched 2 by initials, "BAC"
        32 and "GE" 30. A short query is a ticker hunt, not an acronym."""
        assert rank("GE", "GENERAL ELECTRIC CO", "ge") is not None       # the ticker itself
        assert rank("GFL", "GFL ENVIRONMENTAL INC", "ge") is None        # not by initials
        assert rank("BRT", "BOSTON ACQUISITION CORP", "bac") is None

    def test_an_alias_leads_where_no_registered_name_can_be_reached(self, monkeypatch):
        """Initials cannot help a company renamed since the market learned it:
        nothing about "Alphabet Inc" spells Google."""
        from alphadesk import config
        monkeypatch.setattr(config, "_names", {
            "GOOGL": {"name": "Alphabet Inc. Class A", "exchange": "Nasdaq"},
            "GOOG": {"name": "Alphabet Inc. Class C", "exchange": "Nasdaq"},
            "META": {"name": "Meta Platforms, Inc.", "exchange": "Nasdaq"},
            "BAC": {"name": "BANK OF AMERICA CORP", "exchange": "NYSE"},
            "GOGL": {"name": "Golden Ocean Group Ltd", "exchange": "Nasdaq"},
        })
        assert [r["symbol"] for r in config.search_symbols("google", limit=2)] == ["GOOGL", "GOOG"]
        assert config.search_symbols("facebook", limit=1)[0]["symbol"] == "META"
        assert config.search_symbols("bofa", limit=1)[0]["symbol"] == "BAC"
        # An alias leads, it does not replace: the ranking still fills the list.
        assert config.search_symbols("bank of america", limit=1)[0]["symbol"] == "BAC"


class TestCoinNames:
    """2026-10-04: "bitcoin" answered a shell company and Bitcoin Cash before Bitcoin."""

    def test_a_name_that_is_the_query_beats_a_longer_name_with_a_shorter_ticker(self):
        coin = rank("BTC-USD", "Bitcoin", "bitcoin")
        shell = rank("BIXI", "Bitcoin Infrastructure Acquisition Corp", "bitcoin")
        cash = rank("BCH-USD", "Bitcoin Cash", "bitcoin")
        assert better(coin, shell) and better(coin, cash)

    def test_shell_company_and_warrant_are_demoted(self):
        plain = rank("BIXX", "Bitcoin Mining Holdings", "bitcoin")
        shell = rank("BIXI", "Bitcoin Infrastructure Acquisition Corp", "bitcoin")
        warrant = rank("BIXIW", "Bitcoin Mining Holdings", "bitcoin")
        assert better(plain, shell) and better(plain, warrant)

    def test_search_leads_with_the_coin_then_the_bitcoin_stocks(self, monkeypatch):
        from alphadesk import config as cfg
        names = {"BTC-USD": "Bitcoin", "BCH-USD": "Bitcoin Cash", "BIXI": "Bitcoin Infrastructure Acquisition Corp",
                 "MSTR": "Strategy Inc", "MARA": "MARA Holdings"}
        monkeypatch.setattr(cfg, "_names", {k: {"name": v} for k, v in names.items()}, raising=False)
        monkeypatch.setattr(cfg, "_ensure_names", lambda: None, raising=False)
        out = cfg.search_symbols("bitcoin", limit=5)
        syms = [r["symbol"] if isinstance(r, dict) else r for r in out]
        assert syms[0] == "BTC-USD"
        assert syms.index("MSTR") < syms.index("BIXI")


class TestEveryAlpacaCoinIsSearchable:
    """2026-10-04: the crypto movers listed coins that searching by name could not find."""

    def test_the_movers_coins_are_in_the_coin_list(self):
        from alphadesk.config import _COINS
        alpaca = "AAVE ADA ARB AVAX BAT BCH BONK BTC CRV DOGE DOT ETH FIL GRT HYPE LDO LINK LTC ONDO PAXG PEPE POL RENDER SHIB SKY SOL SUSHI TRUMP UNI USDC USDG USDT WIF XRP XTZ YFI".split()
        assert [c for c in alpaca if c not in _COINS] == []

    def test_a_cache_written_before_a_coin_was_added_still_finds_it(self):
        from alphadesk.config import _with_coins
        names = _with_coins({"AAPL": {"name": "Apple Inc.", "exchange": "Nasdaq", "class": "us_equity"}})
        assert names["BONK-USD"]["class"] == "crypto" and "AAPL" in names

    def test_market_names_lead_to_the_coin(self, monkeypatch):
        from alphadesk import config as cfg
        monkeypatch.setattr(cfg, "_names", cfg._with_coins({}), raising=False)
        monkeypatch.setattr(cfg, "_load_names", lambda: None, raising=False)
        for word, sym in (("ripple", "XRP-USD"), ("tether", "USDT-USD"), ("matic", "POL-USD")):
            assert [r["symbol"] for r in cfg.search_symbols(word, limit=3)][:1] == [sym]


class TestCoinTickers:
    def test_a_coin_typed_by_its_ticker_beats_stocks_that_only_start_with_it(self):
        coin = rank("BAT-USD", "Basic Attention Token", "bat")
        stock = rank("BATL", "Battalion Oil Corp", "bat")
        assert better(coin, stock)

    def test_an_exact_stock_ticker_still_comes_first(self):
        assert better(rank("BTC", "Grayscale Bitcoin Mini Trust", "btc"), rank("BTC-USD", "Bitcoin", "btc"))


class TestAlpacaStablecoinPairs:
    def test_every_pair_the_account_trades_becomes_findable(self, monkeypatch):
        from alphadesk import config as cfg
        monkeypatch.setattr(cfg, "_names", cfg._with_coins({}), raising=False)
        monkeypatch.setattr(cfg, "_load_names", lambda: None, raising=False)
        assert cfg.register_coin_pairs(["BAT/USDC", "BTC/USDT", "BAT/USD", "NEWCOIN/USD"]) == 3
        meta = cfg._names["BAT-USDC"]
        assert meta["name"] == "Basic Attention Token / USD Coin" and meta["class"] == "crypto"
        assert "NEWCOIN-USD" in cfg._names
        assert "BAT-USDC" in [r["symbol"] for r in cfg.search_symbols("bat", limit=10)]
        assert cfg.register_coin_pairs(["BAT/USDC"]) == 0                        # idempotent

    def test_a_stale_stablecoin_pair_does_not_show_a_false_move(self):
        from alphadesk.providers.alpaca import stale_pair_changes_blanked
        rows = [{"symbol": "BAT-USD", "price": 0.1046, "change_pct": 9.0},
                {"symbol": "BAT-USDC", "price": 0.0682, "change_pct": -34.2},
                {"symbol": "ETH-USDC", "price": 2726.0, "change_pct": 1.3},
                {"symbol": "ETH-USD", "price": 2725.0, "change_pct": 1.4}]
        got = {r["symbol"]: r["change_pct"] for r in stale_pair_changes_blanked(rows)}
        assert got == {"BAT-USD": 9.0, "BAT-USDC": None, "ETH-USDC": 1.3, "ETH-USD": 1.4}


def test_stablecoin_pairs_follow_the_dollar_pair_ahead_of_stocks():
    usd = rank("BAT-USD", "Basic Attention Token", "bat")
    usdc = rank("BAT-USDC", "Basic Attention Token / USD Coin", "bat")
    usdt = rank("BAT-USDT", "Basic Attention Token / Tether", "bat")
    stock = rank("BATL", "Battalion Oil Corp", "bat")
    assert usd < usdc < usdt < stock


def test_renamed_companies_are_found_by_their_old_names(monkeypatch):
    from alphadesk import config as cfg
    names = {s: {"name": n, "exchange": "Nasdaq", "class": "us_equity"} for s, n in
             {"MSTR": "Strategy Inc", "XYZ": "Block, Inc.", "MARA": "MARA Holdings, Inc.", "PSKY": "Paramount Skydance Corp",
              "PARA": "Banzai International, Inc.", "ZM": "Zoom Communications, Inc."}.items()}
    monkeypatch.setattr(cfg, "_names", names, raising=False)
    monkeypatch.setattr(cfg, "_load_names", lambda: None, raising=False)
    for word, sym in (("microstrategy", "MSTR"), ("square", "XYZ"), ("marathon digital", "MARA"),
                      ("viacom", "PSKY"), ("zoom video", "ZM")):
        assert cfg.search_symbols(word, limit=3)[0]["symbol"] == sym, word
    assert "PARA" not in [r["symbol"] for r in cfg.search_symbols("viacom", limit=3)][:1]
