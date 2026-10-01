"""WHAT KIND OF POST A POST IS — the structural rule, mirrored in
`lib/postKind.ts` (2026-10-01).

THE SAME STANDING DECISION AS `newskind.py`: one rule, no model, and a kind is
a FACT ABOUT THE RECORD or it is not given. A story carries its publisher's
channel in its URL; a post carries nothing of the sort, so the only kinds that
exist are the ones its own shape states — was it a repost, did it have words,
was it only a link.

NO TOPIC IS READ OUT OF POST TEXT. "Tariffs", "markets" or "politics" would be
a keyword reading of text anyone may write, and it would route an unverified
assertion into a label that looks like ours — the same reason no ticker is
extracted (`providers/scraped.py`). A post that is none of the shapes below is
"text", which says only that it has words, and the words are handed over whole.

KEEPING THE TWO COPIES IN STEP IS A TEST: tests/test_postkind.py parses
lib/postKind.ts and fails when they diverge.
"""

from __future__ import annotations

import re

KIND_LABEL: dict[str, str] = {
    "repost": "Repost", "media": "Media only", "link": "Link only", "text": "Text",
}

# "RT @someone: …" / "RT: https://…" — a repost names itself at the front.
_REPOST = re.compile(r"^RT\b\s*[:@]", re.I)
# Nothing but one or more links.
_LINK_ONLY = re.compile(r"^(?:https?://\S+\s*)+$", re.I)


def post_kind(text: str | None, no_text: bool = False) -> str:
    """The kind of a post. Always one of KIND_LABEL: a post either has words
    or it does not, so unlike a story there is no "unlabelled"."""
    body = (text or "").strip()
    if no_text or not body:
        return "media"
    if _REPOST.search(body):
        return "repost"
    if _LINK_ONLY.match(body):
        return "link"
    return "text"


def of_post(post: dict) -> str:
    """The kind for a stored-shape post row."""
    return post_kind(post.get("text"), bool(post.get("no_text")))


__all__ = ["KIND_LABEL", "of_post", "post_kind"]
