"""A feed whose terms forbid keeping what it sends (2026-09-26, #85).

Tiingo's Terms of Use: "If you use a Starter Plan or any free or paid trial
plan, you may not write, save, archive, back up, or otherwise retain Tiingo
Data in any persistent or durable storage."

Tiingo publishes no endpoint that reports a token's plan, so the account
holder declares it and an undeclared key is read the restrictive way. These
tests pin that the default is the safe one, because the failure mode is
silent: everything keeps working and the terms are being broken.
"""

from alphadesk.ingest import news


def _key(provider, plan=None):
    return {"provider": provider, "vendor_plan": plan}


def _story(article_id, feeds):
    return {"id": article_id, "title": f"story {article_id}", "feeds": list(feeds)}


def test_an_undeclared_tiingo_key_stores_nothing():
    # The default matters more than any other case here: a reader who
    # connected Tiingo before this existed has no declaration at all.
    kept = news.drop_unstorable([_story("a", ["tiingo"])], [_key("tiingo")])
    assert kept == []


def test_a_free_declaration_stores_nothing():
    kept = news.drop_unstorable([_story("a", ["tiingo"])], [_key("tiingo", "free")])
    assert kept == []


def test_a_paid_declaration_stores_normally():
    kept = news.drop_unstorable([_story("a", ["tiingo"])], [_key("tiingo", "paid")])
    assert len(kept) == 1 and kept[0]["feeds"] == ["tiingo"]


def test_only_the_word_paid_counts():
    for claim in ("Paid", "PAID", " paid "):
        # The route normalises before storing, so anything reaching here that
        # is not exactly "paid" was not normalised and must not be trusted.
        assert news.drop_unstorable([_story("a", ["tiingo"])], [_key("tiingo", claim.strip().lower())])
    for claim in ("premium", "power", "yes", "true", "", "trial"):
        assert news.drop_unstorable([_story("a", ["tiingo"])], [_key("tiingo", claim)]) == []


def test_a_story_another_feed_also_carried_survives_without_the_gated_name():
    # The same rule store.purge_vendor_data follows: the row is kept on the
    # other feed's authority, and the gated feed's name comes off it.
    kept = news.drop_unstorable([_story("a", ["tiingo", "fmp"])], [_key("tiingo")])
    assert len(kept) == 1
    assert kept[0]["feeds"] == ["fmp"]


def test_other_feeds_are_untouched():
    rows = [_story("a", ["alpaca"]), _story("b", ["fmp"]), _story("c", ["tiingo"])]
    kept = news.drop_unstorable(rows, [_key("tiingo"), _key("alpaca"), _key("fmp")])
    assert sorted(s["id"] for s in kept) == ["a", "b"]


def test_a_reader_with_no_tiingo_key_is_not_filtered_at_all():
    rows = [_story("a", ["alpaca"])]
    assert news.drop_unstorable(rows, [_key("alpaca")]) is rows


def test_the_gate_names_only_feeds_whose_terms_require_it():
    # Adding a feed here restricts what readers keep, so it should be a
    # deliberate act with a terms citation, not a default.
    assert news._PLAN_GATED == {"tiingo"}
