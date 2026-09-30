"""The story kind, and the two copies of the rule that must not drift.

A COMMENT ASKING FOR TWO FILES TO BE KEPT IN STEP DOES NOT KEEP THEM IN STEP
(2026-09-30). Both the wire list and the channel map existed twice — once in
Python, once in `lib/newsKind.ts` — each carrying a note saying to mirror the
other, and they had drifted anyway: Python was missing `thenewswire.com`, so a
company statement distributed through it was not read as the company's word
here while the app read it as exactly that. These tests parse the TypeScript
and fail when the two disagree, which is the only version of "keep them in
step" that survives a busy afternoon.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from alphadesk import newskind

TS = Path(__file__).resolve().parents[1] / "alphadesk" / "ui" / "src" / "lib" / "newsKind.ts"


def _ts_source() -> str:
    if not TS.exists():          # a backend-only checkout
        pytest.skip("the app's copy of the rule is not in this checkout")
    return TS.read_text(encoding="utf-8")


def test_the_wire_list_matches_the_app() -> None:
    block = re.search(r"const WIRE_HOSTS = \[(.*?)\]", _ts_source(), re.S)
    assert block, "WIRE_HOSTS not found in lib/newsKind.ts — has it been renamed?"
    theirs = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert theirs == set(newskind.WIRE_HOSTS), (
        "the wire hosts have drifted:\n"
        f"  only in the app:    {sorted(theirs - set(newskind.WIRE_HOSTS))}\n"
        f"  only in the server: {sorted(set(newskind.WIRE_HOSTS) - theirs)}")


def test_the_channel_map_matches_the_app() -> None:
    block = re.search(r"const CHANNELS: \[string, StoryKind\]\[\] = \[(.*?)\n\]", _ts_source(), re.S)
    assert block, "CHANNELS not found in lib/newsKind.ts — has it been renamed?"
    theirs = dict(re.findall(r'\["([^"]+)",\s*"([^"]+)"\]', block.group(1)))
    assert theirs == dict(newskind.CHANNELS), (
        "the channel map has drifted:\n"
        f"  only in the app:    {sorted(set(theirs) - set(dict(newskind.CHANNELS)))}\n"
        f"  only in the server: {sorted(set(dict(newskind.CHANNELS)) - set(theirs))}")


def test_every_kind_the_app_names_has_a_label_here() -> None:
    # The union has no trailing semicolon; it ends at the blank line before
    # KIND_LABEL. Anchoring on ";" swallowed half the file and passed junk.
    block = re.search(r"export type StoryKind =(.*?)\n\n", _ts_source(), re.S)
    assert block
    theirs = set(re.findall(r'"([a-z]+)"', block.group(1)))
    assert theirs == set(newskind.KIND_LABEL)


# ── the rule itself ──────────────────────────────────────────────────────

BZ = "https://www.benzinga.com"


@pytest.mark.parametrize("url,source,title,want", [
    # The channel decides it, and the LONGEST PREFIX WINS: a narrower channel
    # beats the section it sits in.
    (f"{BZ}/markets/earnings/26/09/1234/slug", "Benzinga", "Acme beats", "earnings"),
    (f"{BZ}/wiim/26/09/1234/slug", "Benzinga", "Why Acme is moving", "why"),
    (f"{BZ}/etfs/26/09/1234/slug", "Benzinga", "A fund launch", "fund"),
    (f"{BZ}/trading-ideas/movers/26/09/1/s", "Benzinga", "Movers", "movers"),
    # A channel that is not a kind falls through to the generic bucket rather
    # than being invented into one.
    (f"{BZ}/markets/tech/26/09/1234/slug", "Benzinga", "Acme ships a thing", "company"),
    # The title rules go FIRST for the two kinds the channel scatters.
    (f"{BZ}/markets/tech/26/09/1/s", "Benzinga", "Acme Corp Earnings Call Transcript", "transcript"),
    (f"{BZ}/markets/tech/26/09/1/s", "Benzinga",
     "HSBC Maintains Hold on JPMorgan Chase, Raises Price Target to $377", "rating"),
    (f"{BZ}/markets/tech/26/09/1/s", "Benzinga", "Goldman Raises Price Target To $50", "rating"),
    # A quoted headline with its publication trailing is somebody else's story.
    (f"{BZ}/markets/tech/26/09/1/s", "Benzinga",
     "'JPMorgan Tweaks Data-Sharing Notices In Battle With Fintechs' - Bloomberg", "pickup"),
    # The company's own statement, by URL and by named source alike.
    ("https://www.globenewswire.com/news/2026/x", "GlobeNewswire", "Acme Announces", "release"),
    ("https://acme.com/investors/pr", "businesswire.com", "Acme Announces", "release"),
    # THE SOURCE MUST BE HOST-SHAPED, as it is in the app: a feed naming the
    # wire as "GlobeNewswire" rather than "globenewswire.com" does NOT count,
    # and reading that as a company statement would be the server inventing a
    # record the app does not see.
    ("https://acme.com/investors/pr", "GlobeNewswire", "Acme Announces", None),
    # NOT A GUESS: a publisher with no channel scheme stays unlabelled.
    ("https://www.zacks.com/stock/news/1/acme", "Zacks", "Acme Is A Buy", None),
    ("", "", "", None),
])
def test_the_kind_is_read_from_the_record(url, source, title, want) -> None:
    assert newskind.story_kind(url, source, title) == want


def test_a_wire_named_as_the_source_counts_even_when_the_link_does_not() -> None:
    """The app reads the URL OR the named source; the server's older
    press-release check read only the URL. A feed may hand over a canonical
    publisher URL while naming the wire that distributed it, and that is still
    the company's own statement."""
    assert newskind.is_wire_release("https://acme.com/pr", "globenewswire.com")
    assert newskind.is_wire_release("https://ir.globenewswire.com/x", None)
    assert not newskind.is_wire_release("https://reuters.com/x", "Reuters")
    # And a display name is not a host, here or in the app.
    assert not newskind.is_wire_release("https://acme.com/pr", "GlobeNewswire")


def test_the_channel_stops_at_the_article_identifiers() -> None:
    assert newskind.channel_of(f"{BZ}/markets/tech/26/09/62057613/slug") == "markets/tech"
    assert newskind.channel_of(f"{BZ}/26/09/1/slug") == ""
    # Another publisher's path is not a Benzinga channel.
    assert newskind.channel_of("https://www.reuters.com/markets/earnings/x") == ""


def test_a_malformed_url_is_not_an_exception() -> None:
    """These rows come from a feed, and a feed is not obliged to be tidy."""
    for bad in (None, "", "not a url", "http://", "https://[oops"):
        assert newskind.story_kind(bad, None, "") in (None, "company")
