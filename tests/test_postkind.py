"""The post kind, and the two copies of the rule that must not drift
(the same arrangement as tests/test_newskind.py)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from alphadesk import postkind
from alphadesk.postkind import of_post, post_kind

TS = Path(__file__).resolve().parents[1] / "alphadesk" / "ui" / "src" / "lib" / "postKind.ts"


def _ts_source() -> str:
    if not TS.exists():          # a backend-only checkout
        pytest.skip("the app's copy of the rule is not in this checkout")
    return TS.read_text(encoding="utf-8")


def test_the_kinds_and_labels_match_the_app() -> None:
    src = _ts_source()
    union = re.search(r"export type PostKind =(.*?)\n\n", src, re.S)
    assert union
    assert set(re.findall(r'"([a-z]+)"', union.group(1))) == set(postkind.KIND_LABEL)
    labels = re.search(r"POST_KIND_LABEL: Record<PostKind, string> = \{(.*?)\n\}", src, re.S)
    assert labels
    assert dict(re.findall(r'(\w+): "([^"]+)"', labels.group(1))) == postkind.KIND_LABEL


def test_the_patterns_match_the_app() -> None:
    src = _ts_source()
    assert re.search(r"const REPOST = /\^RT\\b\\s\*\[:@\]/i", src)
    assert re.search(r"const LINK_ONLY = /\^\(\?:https\?:\\/\\/\\S\+\\s\*\)\+\$/i", src)


@pytest.mark.parametrize("text,no_text,kind", [
    ("", True, "media"),
    ("   ", False, "media"),
    ("RT @someone: look at this", False, "repost"),
    ("RT: https://truthsocial.com/@x/1", False, "repost"),
    ("https://example.com/a https://example.com/b", False, "link"),
    ("Read this https://example.com/a", False, "text"),
    ("Tariffs are working. (NASDAQ: FAKE) merger!", False, "text"),
    ("Retweet if you agree", False, "text"),          # "RT" must be a prefix, not a prefix of a word
])
def test_the_rule(text, no_text, kind) -> None:
    assert post_kind(text, no_text) == kind
    assert kind in postkind.KIND_LABEL


def test_no_topic_is_ever_a_kind() -> None:
    assert set(postkind.KIND_LABEL) == {"repost", "media", "link", "text"}


def test_of_post_reads_a_stored_row() -> None:
    assert of_post({"text": "", "no_text": True}) == "media"
    assert of_post({"text": "hello"}) == "text"
