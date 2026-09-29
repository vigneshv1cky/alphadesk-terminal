"""WHAT THE COMPANY SAID ABOUT THE PERIOD AHEAD, IN ITS OWN WORDS
(2026-09-29, the owner: "verbatim quotes for guidance").

Guidance is frequently what actually moves a stock, and it lives in the press
release rather than in XBRL: Gray Media's whole 8-K on 2026-09-28 was a
guidance raise, and none of it appears in the filed figures.

SENTENCES, NEVER PARSED NUMBERS. This finds the company's own sentences and
hands them over whole. It does not read "$192 million" into a revenue field,
because the moment a figure is lifted out of its sentence it becomes OUR
reading of the document rather than the company's statement — and a guidance
figure carries conditions ("the midpoint of", "assumes", "plus or minus") that
a bare number silently drops. Every quote returned is a verbatim substring of
the text it came from, which `verified()` re-checks rather than trusts.

ONE RULE, NO MODEL — the same standing decision as the news search. What it
cannot do is judge whether guidance is good: it locates, it does not weigh.
"""
from __future__ import annotations

import re

# Sentences that TALK about guidance without being any: the safe-harbour
# paragraph every release carries, and the standing caveat. Measured on Gray
# Media, where a naive search returned both above the real thing.
_BOILERPLATE = re.compile(
    r"forward[- ]looking statements?|identified by words such as|within the meaning of"
    r"|Private Securities Litigation Reform|undue reliance|guidance may change in the future"
    r"|except as required by law|we undertake no (obligation|duty)", re.I)

# "expects to report its third quarter results on November 6" is a DIARY DATE,
# not guidance — and it matches every guidance word there is. Same trap the
# news Earnings scope hit with "to Report".
_REPORT_DATE = re.compile(
    r"\b(report|announce|release|host|hold)\b[^.]{0,60}\b(results|earnings|call|webcast)\b"
    r"[^.]{0,40}\bon\b\s+\w+day|\b(conference call|webcast)\b[^.]{0,40}\bat\b\s*\d", re.I)

# The company speaking about a period ahead.
_GUIDANCE = re.compile(
    r"\bguidance\b|\boutlook\b|\bforecasts?\b"
    # PARTICIPLES TOO. "Margins are expected to reach 20%" is guidance and
    # `expects?` does not match "expected" — caught by a test, not by reading.
    r"|\b(expects?|expected|anticipates?|anticipated|projects?|projected"
    r"|estimates?|estimated|targets?|targeted|sees|guiding)\b"
    r"|\b(raises?|raised|lowers?|lowered|reaffirms?|reiterates?|narrows?|updates?)\b"
    r"[^.]{0,40}\b(guidance|outlook|forecast|range|estimate)\b", re.I)

# A figure, so a sentence has something in it to act on. Currency, a percent,
# or a plain magnitude in words.
_FIGURE = re.compile(
    r"[$€£¥]\s?\d|\d[\d,.]*\s*(million|billion|trillion|bps|basis points)\b|\d[\d,.]*\s?%", re.I)

# Zero-width and non-breaking junk, which EDGAR's HTML tables are full of: a
# guidance table arrives as a sentence of separators and would otherwise be
# returned as a quote.
_JUNK = re.compile(r"[​‌‍﻿\xa0]")

# A LINK IS NOT A SENTENCE. Transcripts open with a webcast URL whose query
# string carries digits, so it satisfies the figure test and drags whatever
# follows it into the quote (measured on NETSOL's call).
_URL = re.compile(r"https?://|www\.\w|\.com/|\.jsp\b", re.I)

MIN_CHARS = 40
MAX_CHARS = 400
# A TABLE ROW IS NOT A SENTENCE, and a letter-share test does not catch one:
# EDGAR's zero-width separators BECOME SPACES when cleaned, so the row reads as
# mostly letters and passes (measured on Gray Media's guidance table). What
# distinguishes it is that bare numbers dominate its tokens — a guidance
# sentence carries a few figures among many words, a table row is figures with
# a label on the front.
MAX_NUMERIC_SHARE = 0.30


def _sentences(text: str) -> list[str]:
    clean = _JUNK.sub(" ", text or "")
    clean = re.sub(r"\s+", " ", clean)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]


def _is_prose(s: str) -> bool:
    tokens = [t for t in re.split(r"\s+", s.strip()) if t]
    if not tokens:
        return False
    numeric = sum(1 for t in tokens if not re.search(r"[A-Za-z]{2}", t))
    return numeric / len(tokens) <= MAX_NUMERIC_SHARE


def find(text: str, limit: int = 8) -> list[str]:
    """The guidance sentences in a document, in the order the company wrote
    them. Verbatim: each is a whitespace-normalised substring of `text`.

    Order is the document's own, never a ranking — which sentence matters is
    the reader's judgment (invariant 3).
    """
    out: list[str] = []
    seen: set[str] = set()
    for s in _sentences(text):
        if not (MIN_CHARS <= len(s) <= MAX_CHARS):
            continue
        if _BOILERPLATE.search(s) or _REPORT_DATE.search(s) or _URL.search(s):
            continue
        if not (_GUIDANCE.search(s) and _FIGURE.search(s)):
            continue
        if not _is_prose(s):
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def verified(quotes: list[str], text: str) -> list[str]:
    """Keep only quotes that really are in the document.

    `find` produces them from the text so they always are — this exists for
    the caller that stores a quote and shows it later, where the document may
    have been refetched. The same check `verify_guidance` makes of a figure,
    applied to a sentence.
    """
    norm = re.sub(r"\s+", " ", _JUNK.sub(" ", text or ""))
    return [q for q in quotes if q and re.sub(r"\s+", " ", q) in norm]
