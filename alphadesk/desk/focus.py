"""Today's gainers (or losers) laid beside their own news, filings, volume and
the shape of the move (2026-10-03) — the evidence a reader weighs when asking
which might keep rising, and which look finished.

NO VERDICT and no ranking by likelihood. Each row carries FLAGS that are plain
facts about it; some are arguments for a move continuing (a story of its own,
volume well above usual, still near the high) and some against (an offering
filed, most of the swing given back, the last hour running down). Which way a
flag cuts depends on the case, and that is left to the reader.
"""

from __future__ import annotations

_OFFERING = ("424B1", "424B4", "424B5", "S-1", "F-1")   # not 424B2/3 (structured notes) or shelf S-3/F-3
_STAKE = ("SCHEDULE 13D", "SC 13D", "SCHEDULE 13G", "SC 13G", "SC TO")
#: A story naming this many tickers or more is a list ("12 Industrials Stocks
#: Moving…"), which mentions a name and says nothing of why it moved.
LIST_STORY_TICKERS = 8


def own_stories(articles: list[dict]) -> tuple[list[dict], int]:
    """(stories about the name itself, count of list-style mentions)."""
    own, lists = [], 0
    for a in articles:
        if len(a.get("tickers") or []) >= LIST_STORY_TICKERS:
            lists += 1
        else:
            own.append(a)
    return own, lists


def build_row(mover: dict, articles: list[dict], filings: list[dict], halted: bool, shape: dict | None) -> dict:
    own, lists = own_stories(articles)
    kinds: dict[str, int] = {}
    for a in own:
        k = a.get("kind") or "unlabelled"
        kinds[k] = kinds.get(k, 0) + 1
    forms = [str(f.get("form") or "") for f in filings]
    shape = shape or {}
    reliable = bool(shape.get("reliable"))
    given_back = shape.get("given_back_from_high_pct") if reliable else None
    hour_dir = (shape.get("direction") or {}).get("last_60min") if reliable else None
    vol_x = (shape.get("volume") or {}).get("vs_median_daily")
    flags = []
    flags.append("story_of_its_own" if own else "no_story_of_its_own")
    if lists:
        flags.append("named_in_list_stories")
    if kinds.get("offering"):
        flags.append("offering_story")
    if any(f.startswith(_OFFERING) for f in forms):
        flags.append("offering_filing")
    if any(f.startswith(_STAKE) for f in forms):
        flags.append("stake_filing")
    if any(f.startswith("8-K") for f in forms):
        flags.append("material_8k")
    if halted:
        flags.append("halted_today")
    if given_back is not None:
        if given_back >= 50:
            flags.append("given_back_over_half_of_swing")
        elif given_back <= 15:
            flags.append("still_near_the_high")
    if hour_dir in ("up", "down"):
        flags.append(f"last_hour_{hour_dir}")
    if vol_x is not None and vol_x >= 2:
        flags.append("volume_over_2x_usual")
    elif vol_x is not None and vol_x < 0.5:
        flags.append("volume_under_half_usual")
    return {
        "symbol": mover.get("symbol"), "name": mover.get("name"),
        "change_pct": mover.get("change_pct"), "price": mover.get("price"), "volume": mover.get("volume"),
        "flags": flags,
        "news": {"own": len(own), "named_in_lists": lists, "by_kind": kinds,
                 "newest": [{"published_at": a.get("published_at"), "title": a.get("title"), "kind": a.get("kind"),
                             "source": a.get("source")} for a in own[:3]]},
        "filings": [{"form": f.get("form"), "filed_at": f.get("filed_at"), "role": f.get("role")} for f in filings[:5]],
        "shape": ({k: shape.get(k) for k in ("session", "change_pct", "given_back_from_high_pct", "last_60min_change_pct",
                                              "minutes_since_high", "volume", "reliable")} if shape else None),
    }


def scan_news(articles: list[dict], kinds: set[str] | None = None, min_stories: int = 1) -> list[dict]:
    """Stories about a name itself, grouped by symbol across the whole window
    (list-style stories naming many tickers are left out: they mention, they do
    not explain). Ordered by how many distinct stories a name has, then how
    recent the newest is — an order of ATTENTION, not of likelihood to rise or
    fall. `kinds` keeps only stories of those publisher kinds."""
    by: dict[str, list[dict]] = {}
    for a in articles:
        tickers = [str(t).upper() for t in (a.get("tickers") or []) if t]
        if not tickers or len(tickers) >= LIST_STORY_TICKERS:
            continue
        if kinds and (a.get("kind") or "unlabelled") not in kinds:
            continue
        for sym in tickers:
            by.setdefault(sym, []).append(a)
    out = []
    for sym, stories in by.items():
        if len(stories) < max(1, min_stories):
            continue
        stories.sort(key=lambda s: s.get("published_at") or "", reverse=True)
        counts: dict[str, int] = {}
        for s in stories:
            k = s.get("kind") or "unlabelled"
            counts[k] = counts.get(k, 0) + 1
        out.append({"symbol": sym, "stories": len(stories), "by_kind": counts,
                    "first_story_at": stories[-1].get("published_at"),
                    "newest": [{"published_at": s.get("published_at"), "title": s.get("title"), "kind": s.get("kind"),
                                "source": s.get("source"), "article_id": s.get("article_id"),
                                "with_other_tickers": len(s.get("tickers") or []) - 1} for s in stories[:3]]})
    out.sort(key=lambda r: (r["stories"], r["newest"][0]["published_at"] or ""), reverse=True)
    return out
