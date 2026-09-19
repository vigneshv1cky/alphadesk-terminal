"""The analyst view is assembled section by section from the user's
vendors; a section no connected vendor serves carries its own key prompt,
and only a view with no section at all is a 428 (2026-09-13)."""

import pytest

from alphadesk.ingest import analysts
from alphadesk.providers.base import EntitlementError, NeedsKey
from alphadesk.providers.company_vendors import recommendation_summary


class _FinnhubFree:
    name = "finnhub"
    def analyst_ratings(self, s):
        return {"recommendation": recommendation_summary(2, 0, 17, 7, 2),
                "distribution": [{"period": "0m", "strong_buy": 2, "buy": 0, "hold": 17, "sell": 7, "strong_sell": 2}]}
    def price_targets(self, s): raise EntitlementError("HTTP 403")
    def rating_changes(self, s): raise EntitlementError("HTTP 403")
    def short_interest(self, s): raise EntitlementError("HTTP 403")


def test_recommendation_summary_scores_one_to_five():
    assert recommendation_summary(2, 0, 17, 7, 2) == {"mean": 3.25, "key": "hold", "analysts": 28}
    assert recommendation_summary(6, 19, 14, 3, 2)["key"] == "buy"
    assert recommendation_summary(0, 0, 0, 0, 0) == {"mean": None, "key": None, "analysts": 0}


def test_sections_the_plan_refuses_carry_their_prompts(vendors):
    vendors(finnhub=_FinnhubFree())
    out = analysts.analyst_view("khc")
    assert out["recommendation"]["key"] == "hold" and out["sources"] == {"analyst_ratings": "finnhub"}
    assert set(out["needs"]) == {"price_targets", "rating_changes", "short_interest"}
    assert out["needs"]["price_targets"]["refused"] == ["Finnhub"]
    assert out["targets"]["mean"] is None and out["changes"] == []


def test_no_section_at_all_is_a_key_prompt(vendors):
    vendors()
    with pytest.raises(NeedsKey):
        analysts.analyst_view("KHC")
