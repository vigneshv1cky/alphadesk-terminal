"""WHAT KIND OF NEWS A STORY IS — the server's half of the rule (2026-09-30).

ONE RULE, NO MODEL, MIRRORED IN TWO LANGUAGES, which is the standing shape for
this kind of decision here: `newsquery.py` / `lib/newsMatch.ts` for the search,
and now this / `lib/newsKind.ts` for the kind. The app computed the kind in the
browser, so the chip existed on screen and an agent asking over MCP got
nothing — the app knew what a story was about and the reader's agent did not.

THE PUBLISHER'S OWN CLASSIFICATION, NOT OURS. Benzinga files every article
under a channel and that channel is in the URL path, so the kind is a FACT
about the record, on the same footing as the wire-host rule below and the SEC
item numbers behind the filing feed. Nothing here reads the story and nothing
infers a topic: an unrecognised channel stays UNLABELLED rather than guessed
at, and `story_kind` returns None for it.

Measured before it was built, on 45 stories sampled by ticker across sectors:
73% carried a specific channel, and three mechanical title patterns claimed
nine of the twelve that did not, leaving under 7% unlabelled. A keyword sample
would have lied — an earlier earnings-flavoured one put the generic share at
55%, nearly double the truth, because transcripts flood the generic channel.

ONE PUBLISHER. Every story in that sample came from Benzinga, the only feed
delivering on the instance measured. Another feed brings its own paths, so this
is a PER-PUBLISHER mapping like WIRE_HOSTS: extend it, never generalise it.

KEEPING THE TWO COPIES IN STEP IS A TEST, NOT A COMMENT. The comment asking
for it already existed on the TypeScript side and the two had drifted anyway —
the Python wire list was missing a host the app had, and the Python wire test
read only the URL where the app reads the URL or the named source.
tests/test_newskind.py parses lib/newsKind.ts and fails when they diverge.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── the company's own statement ──────────────────────────────────────────
#
# The newswires a company distributes its OWN statement through. A wire host is
# a FACT about the URL, not a reading of the story, which is what lets "press
# release" be a record rather than a judgement: a reporter's article about a
# company is not the company's word, however well sourced.
#
# CANONICAL HERE. `ingest/earnings_announcements` reads this list rather than
# keeping its own, because it kept its own and the two fell out of step.
WIRE_HOSTS: tuple[str, ...] = (
    "globenewswire.com", "prnewswire.com", "prnewswire.co.uk", "newswire.ca",
    "businesswire.com", "newsfilecorp.com", "accessnewswire.com", "accesswire.com",
    "thenewswire.com",
)


def _host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_wire_host(host: str) -> bool:
    return bool(host) and any(host == w or host.endswith(f".{w}") for w in WIRE_HOSTS)


def is_wire_release(url: str | None, source: str | None = None) -> bool:
    """EITHER the link or the named source, not the link falling back to it.

    A feed may hand over a canonical publisher URL on its own host while naming
    the wire that distributed it, and that is still the company's own
    statement — requiring the URL to be the wire would drop it.
    """
    return _is_wire_host(_host_of(url)) or _is_wire_host((source or "").strip().lower())


# ── what the story is about ──────────────────────────────────────────────

KIND_LABEL: dict[str, str] = {
    "earnings": "Earnings", "transcript": "Transcript", "rating": "Analyst",
    "movers": "Movers", "why": "Why it moved", "offering": "Offering",
    "ma": "M&A", "ipo": "IPO", "fund": "Funds", "macro": "Macro",
    "crypto": "Crypto", "legal": "Legal", "opinion": "Opinion",
    "pickup": "Press pickup", "release": "Press release", "company": "Company",
}

#: Channel path → kind. LONGEST PREFIX WINS, so a narrower channel beats the
#: section it sits in: "markets/earnings" is earnings, while "markets/tech" is
#: not a kind at all and falls through to the title rules.
CHANNELS: tuple[tuple[str, str], ...] = (
    ("wiim", "why"),
    ("news/earnings", "earnings"),
    ("markets/earnings", "earnings"),
    ("trading-ideas/movers", "movers"),
    ("trading-ideas/previews", "earnings"),
    ("trading-ideas/long-ideas", "opinion"),
    ("analyst-stock-ratings", "rating"),
    ("markets/offerings", "offering"),
    ("markets/ipos", "ipo"),
    ("etfs", "fund"),
    ("economics", "macro"),
    ("crypto", "crypto"),
    ("m-a", "ma"),
    ("m", "ma"),
)

# Titles that name their own kind, for stories the channel left generic.
# DELIBERATELY NARROW AND ANCHORED: an analyst note is formulaic ("HSBC
# Maintains Hold on JPMorgan Chase, Raises Price Target to $377") and a
# third-party pickup is quoted with its publication trailing. A loose rule here
# would mislabel a company announcement, which is the one thing the generic
# bucket is genuinely full of.
_RATING = re.compile(
    r"\b(maintains|reiterates|upgrades|downgrades|initiates|assumes)\b[^.]{0,80}"
    r"\b(buy|sell|hold|neutral|outperform|underperform|overweight|underweight|price target)\b",
    re.I)
_PRICE_TARGET = re.compile(r"\b(raises|lowers|cuts|boosts)\b[^.]{0,40}\bprice target\b", re.I)
_TRANSCRIPT = re.compile(r"\btranscript\b|\bearnings (conference )?call\b", re.I)
# "'JPMorgan Tweaks Data-Sharing Notices in Battle With Fintechs' - Bloomberg"
_PICKUP = re.compile(r"^['\"“].{10,}['\"”]\s*[-–—]\s*\S")


def channel_of(url: str | None) -> str:
    """The channel a Benzinga URL files the story under: the path before the
    date segments. "/markets/tech/26/09/62057613/slug" -> "markets/tech"."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not (parsed.hostname or "").lower().endswith("benzinga.com"):
            return ""
        path = parsed.path
    except ValueError:
        return ""
    out: list[str] = []
    for part in [p for p in path.split("/") if p]:
        # The two-digit year starts the article's own identifiers; everything
        # before it is the channel.
        if part.isdigit():
            break
        out.append(part.lower())
    return "/".join(out)


def story_kind(url: str | None, source: str | None, title: str | None) -> str | None:
    """The kind, or None where the record does not say — never a guess."""
    if is_wire_release(url, source):
        return "release"
    text = (title or "").strip()
    # The title rules go FIRST for the two kinds the channel scatters: an
    # analyst note appears both under its own channel and under the generic
    # one, and a transcript is always generic. Reading the title first means
    # one kind rather than two names for the same thing.
    if _TRANSCRIPT.search(text):
        return "transcript"
    if _RATING.search(text) or _PRICE_TARGET.search(text):
        return "rating"
    channel = channel_of(url)
    if channel:
        best, best_len = None, -1
        for prefix, kind in CHANNELS:
            if (channel == prefix or channel.startswith(f"{prefix}/")) and len(prefix) > best_len:
                best, best_len = kind, len(prefix)
        if best:
            return best
    if _PICKUP.search(text):
        return "pickup"
    return "company" if channel else None


def of_article(article: dict) -> str | None:
    """The kind for a stored-shape article row."""
    return story_kind(article.get("url"), article.get("source"), article.get("title"))


__all__ = ["CHANNELS", "KIND_LABEL", "WIRE_HOSTS", "channel_of", "is_wire_release",
           "of_article", "story_kind"]
