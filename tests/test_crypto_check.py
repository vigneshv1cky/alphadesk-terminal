from alphadesk import cryptocheck


def test_the_report_names_each_kind_of_problem():
    search = lambda text: {"BAT": ["BAT-USD", "BATL"], "USDG": ["USDG-USD"]}.get(text, [])   # noqa: E731
    bars = {"BAT-USD": [1, 2], "BAT-USDC": [1]}
    got = cryptocheck.report(["BAT/USD", "BAT/USDC", "USDG/USD"], search, bars, {"BAT-USD", "USDG-USD"})
    assert got["pairs"] == 3
    assert got["problems"] == {"not_searchable": ["BAT-USDC"], "no_bars": ["USDG-USD"],
                               "not_in_movers": ["BAT-USDC"]}
    assert [r["symbol"] for r in got["rows"]] == ["BAT-USD", "BAT-USDC", "USDG-USD"]
