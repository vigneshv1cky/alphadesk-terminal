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

import re

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


# ── THE EVIDENCE LADDER (2026-10-27) ─────────────────────────────────────
#
# "How to explain every gainer and loser" (the owner). The answer here is
# never an explanation: it is every public record that bears on the move,
# each marked with the check that found it, or a plain statement of every
# check that ran and came back empty and every one that could not be read.
# The reader's agent draws the conclusion (invariant 1). Measured the day it
# was asked: of the day's top 15 gainers and top 15 losers, eleven had no
# story of their own, no filing and no list mention, and seven more were
# explained only inside a round-up's body — Boeing's 737 schedule and the
# refiners' fuel futures among them.
#
# The rungs, in roughly the order of how directly a record speaks for the
# company. ORDER IS NOT WEIGHT: nothing here scores a record or says which
# one moved the price.

RUNGS: tuple[str, ...] = ("company_word", "scheduled_report", "corporate_action", "third_party",
                          "roundup_passages", "group_move", "market_structure")

#: What no source in the catalogue covers, said rather than invented. A
#: biotech's FDA decision date or trial readout is the commonest reason a
#: small one moves on no filing and no story; no connected vendor carries it.
NOT_COVERED: tuple[str, ...] = (
    "FDA decision dates (PDUFA) and advisory-committee meetings: no source in the catalogue",
    "clinical-trial readout dates and registry changes: no source in the catalogue",
    "commodity futures and their moves: no source in the catalogue; a round-up passage is the only record",
    "social-media and forum attention: deliberately not read (removed 2026-09-23)",
)

#: The forms that register or list a security — a new listing, a spin-off's
#: Form 10, an IPO's final prospectus. Within NEW_LISTING_DAYS of the session
#: they mean the change may be measured against a base that is not a prior
#: session's close of the same security.
LISTING_FORMS: tuple[str, ...] = ("8-A12B", "8-A12G", "10-12B", "10-12B/A", "10-12G", "S-1", "F-1",
                                  "424B4", "S-4", "F-4", "25-NSE")
NEW_LISTING_DAYS = 30
#: Prior daily bars needed before a percentage change is a change from the
#: same security's own previous close.
MIN_PRIOR_SESSIONS = 1

_TENDER = ("SC TO", "SC 14D9")
_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited", "plc", "holdings",
             "holding", "group", "common", "stock", "class", "a", "b", "c", "ordinary", "shares", "share", "the",
             "nv", "sa", "ag", "se", "lp", "llc", "trust", "ads", "adr", "depositary", "units", "unit"}
#: First words too common to stand alone for a company in running text.
_GENERIC = {"national", "american", "united", "general", "first", "global", "international", "applied",
            "critical", "new", "great", "western", "eastern", "southern", "northern", "pacific", "atlantic",
            "energy", "digital", "advanced", "real", "health", "capital", "financial", "home", "better", "clear",
            "usa", "us", "mid", "midcap", "royal", "standard", "central", "north", "south", "east", "west",
            "world", "universal", "premier", "power", "data", "bio", "medical", "life", "smart", "big", "blue"}


def company_short_name(name: str | None) -> str | None:
    """The words a story uses for the company: "Boeing Company" -> "Boeing",
    "Par Pacific Holdings, Inc. Common Stock" -> "Par Pacific". The first
    word alone when it is distinctive; two words when it is short or common
    ("National Vision", "HF Sinclair"). None when nothing distinctive is left.
    A heuristic for FINDING sentences, never shown as a fact. Pure."""
    words = [w for w in re.split(r"[\s,]+", (name or "").strip()) if w]
    kept: list[str] = []
    for w in words:
        bare = re.sub(r"[^A-Za-z0-9&'-]", "", w)
        if bare.lower().strip(".") in _SUFFIXES:
            break
        if bare:
            kept.append(bare)
    if not kept:
        return None
    first = kept[0]
    if (len(first) < 4 or first.lower() in _GENERIC) and len(kept) > 1:
        return f"{first} {kept[1]}"
    return first if len(first) >= 3 else None


def _ticker_patterns(symbol: str) -> list[re.Pattern]:
    s = re.escape(symbol.upper())
    pats = [re.compile(rf"\(\s*(?:(?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX|OTC|CBOE)\s*:\s*)?{s}\s*\)"),
            re.compile(rf"\b(?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX|OTC)\s*:\s*{s}\b"),
            re.compile(rf"\${s}\b")]
    # A bare capitalised ticker only from three letters: "BA" or "DK" in
    # running text is too often something else.
    if len(symbol) >= 3:
        pats.append(re.compile(rf"(?<![A-Za-z$]){s}(?![A-Za-z])"))
    return pats


def names_company(text: str | None, symbol: str, short_name: str | None) -> bool:
    """Does `text` name the company, by its ticker in a ticker's usual dress
    or by its short name as a whole word? Pure."""
    if not text:
        return False
    if any(p.search(text) for p in _ticker_patterns(symbol)):
        return True
    return bool(short_name) and re.search(rf"(?<![A-Za-z]){re.escape(short_name)}(?![A-Za-z])", text, re.I) is not None


def plain_text(body: str | None) -> str:
    """A stored body as running text: tags dropped, entities decoded. Pure."""
    from html import unescape
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body or "", flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", ". ", text, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


#: A passage is quoted whole up to this length; a longer sentence is cut to
#: this many characters around the match, with an ellipsis marking each cut.
PASSAGE_MAX = 420


#: Words a full stop follows without ending the sentence: "Valero Energy
#: Corp. (NYSE:VLO) dropped 7%" is one sentence, and cutting it after "Corp"
#: quoted a company name with nothing it did (2026-10-27).
_ABBREV = ("Inc", "Corp", "Co", "Ltd", "Cos", "Bros", "Mr", "Mrs", "Ms", "Dr", "St", "Jr", "Sr", "vs", "No",
           "U.S", "U.K", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
           "approx", "est", "Hldgs", "Intl", "N.V", "S.A", "L.P", "plc")
_SPLIT = re.compile(
    "".join(rf"(?<!\b{re.escape(a)}\.)" for a in _ABBREV) + r"(?<=[.!?])\s+(?=[\"“(A-Z0-9$])"
    r"|\s*\n+\s*|\s+[•·]\s+|\.\s*\.\s+")
#: A "sentence" naming this many ticker-like capitalised words is a table row
#: (an options-activity grid), not prose about the company.
_TABLE_TOKENS = 10


def passages(text: str, symbol: str, short_name: str | None, limit: int = 2) -> list[str]:
    """The sentences of `text` that name the company, VERBATIM, in order,
    at most `limit`. A list item is a sentence here, so a movers round-up's
    "Boeing Co (NYSE:BA) shares fell 11% after …" is one passage. A line
    break ends a sentence too — headline, summary and body are kept as
    separate lines — and a table row is skipped. Pure."""
    out: list[str] = []
    for sentence in _SPLIT.split(text):
        sentence = sentence.strip(" .")
        if len(sentence) < 12 or not names_company(sentence, symbol, short_name):
            continue
        if len(re.findall(r"\b[A-Z]{2,5}\b", sentence)) >= _TABLE_TOKENS and len(sentence) > PASSAGE_MAX:
            continue
        if len(sentence) > PASSAGE_MAX:
            at = next((m.start() for p in _ticker_patterns(symbol) for m in [p.search(sentence)] if m), None)
            if at is None and short_name:
                m = re.search(re.escape(short_name), sentence, re.I)
                at = m.start() if m else 0
            lo = max(0, (at or 0) - PASSAGE_MAX // 3)
            cut = sentence[lo:lo + PASSAGE_MAX]
            sentence = ("…" if lo else "") + cut + ("…" if lo + PASSAGE_MAX < len(sentence) else "")
        if sentence not in out:
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


def _story_ref(a: dict) -> dict:
    return {"article_id": a.get("article_id"), "title": a.get("title"), "published_at": a.get("published_at"),
            "kind": a.get("kind"), "source": a.get("source")}


def sort_stories(symbol: str, short_name: str | None, articles: list[dict]) -> dict[str, list[dict]]:
    """A name's tagged stories split by what they are, without reading them:
    a wire release whose headline names the company is its own word; an
    analyst note is a third party; a story of eight tickers or more is a list;
    any other story whose headline names the company is a story of its own;
    the rest (a wire release about someone else, a market wrap tagged with
    it) can only bear on the move through a sentence inside them, so they go
    to the round-up check with the lists. Pure."""
    out: dict[str, list[dict]] = {"releases": [], "analyst_notes": [], "own": [], "read_for_passages": []}
    for a in articles:
        many = len(a.get("tickers") or []) >= LIST_STORY_TICKERS
        named = names_company(a.get("title"), symbol, short_name)
        if many:
            out["read_for_passages"].append(a)
        elif a.get("kind") == "release" and named:
            out["releases"].append(a)
        elif a.get("kind") == "rating":
            out["analyst_notes"].append(a)
        elif named:
            out["own"].append(a)
        else:
            out["read_for_passages"].append(a)
    return out


#: The calendar's after-the-close spellings; a report then bears on the next
#: session.
_AFTER_CLOSE = ("amc", "after", "after close", "after market close", "post-market")


def report_in_window(row: dict, symbol: str, day) -> bool:
    """Is this calendar row a report the session's move can follow? Either
    EDGAR's clock for its results filing falls between the previous close and
    the session's close, or the row is dated the session (and not after its
    close) or the previous session after its close. Pure."""
    from datetime import datetime
    from alphadesk.desk import sessions as cal
    if str(row.get("symbol") or "").upper() != symbol.upper():
        return False
    prev = cal.previous_session(day)
    released = row.get("released_at")
    if released:
        try:
            at = datetime.fromisoformat(str(released))
            at = at if at.tzinfo else at.replace(tzinfo=cal.NY)
            return datetime.combine(prev, cal.CLOSE, tzinfo=cal.NY) < at <= datetime.combine(day, cal.CLOSE, tzinfo=cal.NY)
        except ValueError:
            pass
    rep = str(row.get("report_date") or "")[:10]
    after = str(row.get("session") or "").strip().lower() in _AFTER_CLOSE
    return (rep == day.isoformat() and not after) or (rep == prev.isoformat() and after)


def report_ref(row: dict) -> dict:
    return {k: row.get(k) for k in ("report_date", "session", "released_at", "sources", "fiscal_period",
                                    "eps_actual", "eps_estimate", "form") if row.get(k) is not None}


def action_counts(event: dict, span: tuple[str, str]) -> bool:
    """A corporate action dated within the span. An ordinary cash dividend is
    left out — it cannot move a price this far — and a special one kept. Pure."""
    if not any(span[0] <= d <= span[1] for d in event.get("dates") or []):
        return False
    if event.get("type") == "cash_dividends":
        return bool((event.get("detail") or {}).get("special"))
    return True


def action_ref(event: dict) -> dict:
    return {"type": event.get("type"), "dates": event.get("dates"), "symbols": event.get("symbols"),
            "detail": event.get("detail")}



# ── WHEN THE MOVE BEGAN, AND WHICH RECORDS CAME BEFORE IT (2026-10-27) ──
#
# A record published BEFORE the price moved is a different fact from one
# published AFTER: "why is X trading higher" stories, movers lists and the
# halts a move trips are written about the move, while a filing or a release
# that came first is something the market could have read. The order is a
# MEASUREMENT of time, never a verdict on cause — a leak, a record no source
# carries or plain flow can still sit before either — and nothing here ranks
# a record by it.

#: The move "began" in the bar whose close first covered this share of the
#: change the list shows, counted bar by bar from the previous close. A
#: quarter of a 20% gain is 5%: well past a quiet day's noise for a name on
#: the movers list, and early enough that a story written about the move
#: lands after it.
MOVE_BEGAN_SHARE = 0.25
#: The same, for the half-way mark, given as context.
MOVE_HALF_SHARE = 0.5


def _when(stamp):
    from alphadesk.desk.movestate import _at
    return _at(stamp) if stamp else None


def _crossing(stamped: list, length, since, until, target: float, up: bool):
    """(began_after, began_by) of the first bar whose close reached `target`,
    or None. A bar is stamped at its START, so the price was short of the
    mark when the bar before it closed and reached it by this one's close."""
    prev_end = since
    for t, b in stamped:
        close = float(b["c"])
        if (close >= target) if up else (close <= target):
            end = t + length
            return prev_end, (min(end, until) if until else end)
        prev_end = t + length
    return None


def move_start(bars: list[dict], prev_close: float | None, change_pct: float | None, since,
               until=None) -> dict:
    """When the move began: the interval in which the price, read bar by bar
    from the previous close, first covered MOVE_BEGAN_SHARE of the change the
    list shows. Sparse bars give a WIDE interval rather than a guessed
    instant — a thin overnight tape can leave hours between two prints, and
    the interval says so. `found` false says why in `not_found_note`. Pure."""
    from datetime import timedelta
    from alphadesk.desk import sessions as cal
    if not prev_close or change_pct is None or change_pct == 0:
        return {"found": False, "not_found_note": "the previous close or the change is unknown"}
    stamped = sorted(((t, b) for b in bars or [] for t in [_when(b.get("t"))]
                      if t and b.get("c") is not None and t >= since and (until is None or t <= until)),
                     key=lambda x: x[0])
    if not stamped:
        return {"found": False, "not_found_note": "the reader's intraday bars hold no trade after the previous close"}
    gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(stamped, stamped[1:]) if b[0] > a[0]]
    # The bar length is the tightest spacing seen, held to half an hour so two
    # prints hours apart are not read as one long bar.
    length = timedelta(seconds=min(1800.0, max(60.0, min(gaps) if gaps else 60.0)))
    up = change_pct > 0
    hit = _crossing(stamped, length, since, until, prev_close * (1 + MOVE_BEGAN_SHARE * change_pct / 100), up)
    if not hit:
        return {"found": False, "not_found_note": f"no bar after the previous close had covered "
                                          f"{int(MOVE_BEGAN_SHARE * 100)}% of the move"}
    half = _crossing(stamped, length, since, until, prev_close * (1 + MOVE_HALF_SHARE * change_pct / 100), up)
    iso = lambda d: d.astimezone(cal.NY).isoformat(timespec="minutes")  # noqa: E731
    return {"found": True, "began_after": iso(hit[0]), "began_by": iso(hit[1]),
            "interval_minutes": round((hit[1] - hit[0]).total_seconds() / 60),
            "share_of_move": MOVE_BEGAN_SHARE,
            "price_at_that_share": round(prev_close * (1 + MOVE_BEGAN_SHARE * change_pct / 100), 4),
            "previous_close": round(prev_close, 4), "half_of_move_by": iso(half[1]) if half else None,
            "measured_from": iso(since), "bars_read": len(stamped), "first_bar_at": iso(stamped[0][0])}


#: A record's own clock, in the order a record carries one.
_STAMP_KEYS = ("filed_at", "published_at", "released_at", "halted_at")
TIME_ORDERS = ("before_move", "as_move_began", "after_move_began", "dated_by_day_only")


def time_order(record: dict, start: dict) -> dict | None:
    """Where one record sits against the move's start: "before_move" (at or
    before the interval opened), "as_move_began" (inside it, so it cannot be
    ordered either way), "after_move_began", or "dated_by_day_only" (a
    corporate action, a calendar row with no release clock, a filing known
    only by its date). `minutes_from_move_start` is negative before the
    interval, positive after it, 0 inside. None for a record that is not a
    publication (an industry group, the daily-bars count). Pure."""
    stamp = next((record.get(k) for k in _STAMP_KEYS if record.get(k)), None)
    if not stamp:
        return {"order": "dated_by_day_only"} if (record.get("report_date") or record.get("dates")) else None
    if len(str(stamp)) <= 10:
        return {"order": "dated_by_day_only"}
    at, after, by = _when(stamp), _when(start["began_after"]), _when(start["began_by"])
    if at is None:
        return None
    if at <= after:
        return {"order": "before_move", "minutes_from_move_start": round((at - after).total_seconds() / 60)}
    if at > by:
        return {"order": "after_move_began", "minutes_from_move_start": round((at - by).total_seconds() / 60)}
    return {"order": "as_move_began", "minutes_from_move_start": 0}


def mark_time_order(rungs: dict[str, dict], start: dict | None) -> dict | None:
    """Stamp every timed record in `rungs` with its `time_order`, in place,
    and count them by order. None when the start is unknown. Pure but for
    the stamping."""
    if not start or not start.get("found"):
        return None
    counts = {k: 0 for k in TIME_ORDERS}
    earliest = None
    for rung, r in rungs.items():
        for rec in r.get("records") or []:
            got = time_order(rec, start)
            if got is None:
                continue
            rec["time_order"] = got
            counts[got["order"]] += 1
            if got["order"] == "before_move":
                stamp = next(rec.get(k) for k in _STAMP_KEYS if rec.get(k))
                if earliest is None or _when(stamp) < _when(earliest["at"]):
                    earliest = {"rung": rung, "check": rec.get("check"), "at": stamp}
    return {**counts, "earliest_before_move": earliest}


def _filing_ref(f: dict) -> dict:
    return {"check": "sec_filing", "form": f.get("form"), "filed_at": f.get("filed_at"),
            "accession": f.get("accession"), "role": f.get("role"), "url": f.get("url"),
            "items": f.get("items") or []}


def _rung(status: str, records: list | None = None, **extra) -> dict:
    return {"status": status, "records": records or [], **extra}


def ladder(symbol: str, name: str | None, change_pct: float | None, window: dict, *,
           stories: dict[str, list[dict]] | None, passages_found: list[dict] | None,
           filings: list[dict] | None, earnings: list[dict] | None, actions: list[dict] | None,
           listing_filings: list[dict] | None, prior_sessions: int | None, halts: list[dict] | None,
           group: dict | None, unread: dict[str, str] | None = None, move: dict | None = None) -> dict:
    """One mover's evidence, rung by rung. Each input is what a check read;
    None means the check COULD NOT BE READ (its reason in `unread`), an empty
    list means it ran and found nothing — the two are never confused. Pure.

    Every rung answers {status: "records" | "empty" | "unread", records}.
    `checks_with_records`, `checks_empty` and `checks_unread` summarise them,
    and `nothing_found` is true only when no rung holds a record. `move` is
    move_start()'s answer: with it found, every timed record carries its
    `time_order` and `time_order` counts them; without it, `move_began` says
    why and no record is ordered."""
    unread = dict(unread or {})
    rungs: dict[str, dict] = {}

    def status(*inputs) -> str | None:
        return "unread" if any(i is None for i in inputs) else None

    # 1. The company's own word: its filings and its own wire releases.
    word: list[dict] = []
    for f in filings or []:
        word.append(_filing_ref(f))
    for a in (stories or {}).get("releases") or []:
        word.append({"check": "wire_release", **_story_ref(a)})
    rungs["company_word"] = _rung("records" if word else (status(filings, stories) or "empty"), word)

    # 2. A scheduled report: the calendar's row, and a results 8-K (Item 2.02).
    sched = [{"check": "earnings_calendar", **e} for e in earnings or []]
    for f in filings or []:
        if any(i.get("number") == "2.02" for i in f.get("items") or []):
            sched.append({"check": "results_filing", "form": f.get("form"), "filed_at": f.get("filed_at"),
                          "accession": f.get("accession"), "item": "2.02"})
    rungs["scheduled_report"] = _rung("records" if sched else (status(earnings) or "empty"), sched)

    # 3. Corporate actions, and whether the change has a prior close at all.
    corp = [{"check": "corporate_actions_feed", **a} for a in actions or []]
    corp += [{"check": "listing_filing", "form": f.get("form"), "filed_at": f.get("filed_at"),
              "accession": f.get("accession"), "url": f.get("url")} for f in listing_filings or []]
    base = None
    if prior_sessions is not None:
        base = {"prior_sessions_in_daily_bars": prior_sessions,
                "change_has_a_prior_close": prior_sessions >= MIN_PRIOR_SESSIONS}
        if prior_sessions < MIN_PRIOR_SESSIONS:
            corp.append({"check": "daily_bars", "prior_sessions_in_daily_bars": prior_sessions,
                         "note": "the reader's daily bars hold no session before this one, so the percentage "
                                 "is not a change from this security's own previous close"})
    rungs["corporate_action"] = _rung("records" if corp else (status(actions, listing_filings, prior_sessions) or "empty"),
                                      corp, change_base=base)

    # 4. Third parties on the company: analyst notes and stories of its own.
    third = [{"check": "analyst_note", **_story_ref(a)} for a in (stories or {}).get("analyst_notes") or []]
    third += [{"check": "story_of_its_own", **_story_ref(a)} for a in (stories or {}).get("own") or []]
    rungs["third_party"] = _rung("records" if third else (status(stories) or "empty"), third[:6],
                                 total=len(third))

    # 5. Sentences inside round-ups, lists and wraps that name the company.
    rungs["roundup_passages"] = _rung("records" if passages_found else (status(passages_found, stories) or "empty"),
                                      (passages_found or [])[:4], total=len(passages_found or []))

    # 6. Moving with a group: other movers in its SEC industry, its basket.
    g = group or {}
    grp_records = [r for r in (g.get("sec_industry"), g.get("vendor_industry"), g.get("basket"))
                   if r and r.get("moved_together")]
    grp_records += [{**p, "found_by": p.get("check"), "check": "group_member_passage"}
                    for p in g.get("member_passages") or []]
    rungs["group_move"] = _rung("records" if grp_records else (status(group) or "empty"), grp_records,
                                sector_fund=g.get("sector_fund"))

    # 7. Market structure: a halt during the session.
    rungs["market_structure"] = _rung("records" if halts else (status(halts) or "empty"),
                                      [{"check": "trading_halt", **h} for h in halts or []])

    for k, r in rungs.items():
        if r["status"] == "unread" and k not in unread:
            unread[k] = "a source this check reads could not be read"
    with_records = [k for k in RUNGS if rungs[k]["status"] == "records"]
    return {
        "symbol": symbol, "name": name, "change_pct": change_pct, "window": window,
        "rungs": rungs,
        "move_began": move or {"found": False, "not_found_note": "the reader's intraday bars were not read"},
        "time_order": mark_time_order(rungs, move),
        "checks_with_records": with_records,
        "checks_empty": [k for k in RUNGS if rungs[k]["status"] == "empty"],
        "checks_unread": {k: unread[k] for k in RUNGS if rungs[k]["status"] == "unread"},
        "nothing_found": not with_records,
    }


_TICKER_DRESS = re.compile(r"\(\s*(?:(?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX|OTC|CBOE)\s*:\s*)?([A-Z]{1,5}(?:\.[A-Z])?)\s*\)"
                           r"|\b(?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX|OTC)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b")


#: Other rows of the list that must share an industry before it holds a
#: record — the same two the basket rule asks for.
GROUP_PEERS = 2


def tickers_named(sentence: str) -> set[str]:
    """Tickers a sentence names in a ticker's dress — "(NYSE:VLO)",
    "Nasdaq: AEHR". Pure."""
    return {a or b for a, b in _TICKER_DRESS.findall(sentence or "")}


def group_records(rows: list[dict], industry_of: dict[str, dict | None], basket_of: dict[str, dict],
                  basket_moves: dict[str, float | None], passages_of: dict[str, list[dict]],
                  sector_of: dict[str, dict | None], vendor_industry_of: dict[str, str | None] | None = None
                  ) -> dict[str, dict]:
    """Each mover's group context. Pure.

    SEC INDUSTRY: the registrant's Standard Industrial Classification as the
    SEC records it. VENDOR INDUSTRY: the industry the reader's vendor files
    the company under — finer where the SEC's code is stale (on 2026-10-27
    the SEC filed HF Sinclair under pipelines and Par Pacific under crude
    production, while the vendor put all seven falling refiners under one
    industry). For each basis, the other rows of THIS list sharing it, with
    their moves; `moved_together` when at least one does, which on a
    one-direction list means they moved the same way.
    BASKET: the curated basket the symbol belongs to (each ticker has one
    home), every member's move, and how many moved the same way as this one;
    `moved_together` when at least two other members did.
    MEMBER PASSAGES: a round-up sentence found for another row sharing either
    industry, attached with `via` naming that row — ONLY when the sentence
    names at least one company besides that row by ticker. A sentence about
    one company's own news says nothing about its neighbours; a sentence
    naming several is about the group (the refiners' wrap named two of seven).
    SECTOR FUND: the vendor's sector and that sector fund's move, as context;
    it never makes the rung hold a record."""
    vendor_industry_of = vendor_industry_of or {}
    peers_by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        ind = industry_of.get(r["symbol"])
        if ind and ind.get("sic"):
            peers_by.setdefault(("sic", str(ind["sic"])), []).append(r)
        vi = vendor_industry_of.get(r["symbol"])
        if vi:
            peers_by.setdefault(("vendor", str(vi).strip().lower()), []).append(r)
    out: dict[str, dict] = {}
    for r in rows:
        sym, chg = r["symbol"], r.get("change_pct")
        g: dict = {}
        neighbours: dict[str, dict] = {}
        ind = industry_of.get(sym)
        if ind and ind.get("sic"):
            peers = [p for p in peers_by.get(("sic", str(ind["sic"])), []) if p["symbol"] != sym]
            g["sec_industry"] = {"check": "sec_industry", "sic": ind.get("sic"), "industry": ind.get("industry"),
                                 "others_in_this_list": [{"symbol": p["symbol"], "change_pct": p.get("change_pct")}
                                                         for p in peers],
                                 "moved_together": len(peers) >= GROUP_PEERS}
            neighbours.update({p["symbol"]: p for p in peers})
        vi = vendor_industry_of.get(sym)
        if vi:
            peers = [p for p in peers_by.get(("vendor", str(vi).strip().lower()), []) if p["symbol"] != sym]
            g["vendor_industry"] = {"check": "vendor_industry", "industry": vi,
                                    "others_in_this_list": [{"symbol": p["symbol"], "change_pct": p.get("change_pct")}
                                                            for p in peers],
                                    "moved_together": len(peers) >= GROUP_PEERS}
            neighbours.update({p["symbol"]: p for p in peers})
        shared: list[dict] = []
        for p in neighbours:
            for ps in passages_of.get(p) or []:
                if tickers_named(ps.get("passage") or "") - {p}:
                    shared.append({**ps, "via": p})
        if shared:
            g["member_passages"] = shared[:4]
        basket = basket_of.get(sym)
        if basket:
            members = [{"symbol": m, "change_pct": basket_moves.get(m)} for m in basket["symbols"] if m != sym]
            same = [m for m in members if m["change_pct"] is not None and chg is not None
                    and (m["change_pct"] > 0) == (chg > 0) and m["change_pct"] != 0]
            measured = [m for m in members if m["change_pct"] is not None]
            g["basket"] = {"check": "basket", "id": basket.get("id"), "label": basket.get("label"),
                           "members": members, "members_measured": len(measured),
                           "same_direction": len(same), "moved_together": len(same) >= 2}
        if sym in sector_of:
            g["sector_fund"] = sector_of[sym]
        out[sym] = g
    return out


def coverage(ladders: list[dict]) -> dict:
    """Counts across rows: how many have records at each rung, how many end
    with nothing, how many had a check unread. Counts only — never a share
    of the move a rung accounts for."""
    by = {k: sum(1 for x in ladders if k in x["checks_with_records"]) for k in RUNGS}
    ordered = [x for x in ladders if x.get("time_order")]
    return {"rows": len(ladders), "with_records_by_check": by,
            "move_start_found": len(ordered),
            "with_a_record_before_the_move": [x["symbol"] for x in ordered if x["time_order"]["before_move"]],
            "records_only_after_the_move_began": [
                x["symbol"] for x in ordered if not x["time_order"]["before_move"]
                and not x["time_order"]["as_move_began"] and x["time_order"]["after_move_began"]],
            "nothing_found": [x["symbol"] for x in ladders if x["nothing_found"]],
            "with_an_unread_check": [x["symbol"] for x in ladders if x["checks_unread"]]}
