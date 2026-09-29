"""Locating a company's own guidance sentences — verbatim, never parsed."""
from alphadesk.ingest import guidance


def test_the_guidance_sentence_is_returned_whole():
    """MEASURED on NETSOL's call. The conditions travel with the figure: a
    bare "13%" in a revenue field would drop "to 16%", "approximately", and
    the fact that it is GROWTH rather than a level."""
    text = ("Thank you all for joining. For fiscal 2027, NETSOL expects net revenue growth "
            "of 13% to 16%, gross margins of approximately 50% or better, and consolidated "
            "Adjusted EBITDA growth of 15% to 25%. We are pleased with the quarter.")
    got = guidance.find(text)
    assert len(got) == 1
    assert got[0].startswith("For fiscal 2027, NETSOL expects net revenue growth of 13% to 16%")
    assert "approximately 50% or better" in got[0]
    assert guidance.verified(got, text) == got


def test_the_safe_harbour_paragraph_is_not_guidance():
    """Every release carries it and it names every guidance word there is. A
    naive search returned it above the real thing on Gray Media."""
    for s in [
        'These statements may be identified by words such as "estimates," "expect," '
        '"anticipate," "will" and similar expressions, and involve risks of 10% or more.',
        "As always, guidance may change in the future based on several factors and "
        "therefore may not reflect actual results, which could differ by $10 million.",
        "This release contains forward-looking statements within the meaning of the "
        "Private Securities Litigation Reform Act, including our $5 million estimate.",
    ]:
        assert guidance.find(s) == [], s


def test_a_diary_date_is_not_guidance():
    """"Expects to report its third quarter results on Friday, November 6" matches
    every guidance word and is a calendar entry (Gray Media, 2026-09-28) — the
    same trap the news Earnings scope hit with "to Report"."""
    s = ("Gray currently expects to report its third quarter 2026 financial results on "
         "Friday, November 6, 2026, and host its quarterly investor call at 11AM, "
         "covering $192 million of revenue.")
    assert guidance.find(s) == []


def test_a_sentence_with_no_figure_is_not_kept():
    """An outlook with nothing in it to act on is a sentiment, not guidance."""
    assert guidance.find("We remain confident in our outlook for the year ahead and "
                         "expect continued momentum across the business.") == []


def test_table_junk_and_links_are_not_sentences():
    """EDGAR tables arrive as runs of zero-width separators, and a transcript
    opens with a webcast URL whose query string carries digits — so it passes
    the figure test and drags the next clause in with it (both measured)."""
    table = ("​ ​ Quarter Ending September 30, 2026 ​ ​ ​ ​ "
             "​ 192 ​ 205 ​ guidance ​ ​ ​ 1.5% ​ ​.")
    assert guidance.find(table) == []
    link = ("Access the full call at https://viavid.webcasts.com/starthere.jsp?ei=1775840 "
            "Summary the company expects revenue of $74.4 million.")
    assert guidance.find(link) == []


def test_verified_drops_a_quote_the_document_does_not_contain():
    """`find` produces quotes from the text so they always verify. This is for
    the caller that stored one and shows it later, against a document that may
    have been refetched — the same check verify_guidance makes of a figure."""
    text = "For fiscal 2027 the company expects revenue of $84 million to $86 million."
    assert guidance.verified(["For fiscal 2027 the company expects revenue of $84 million"], text)
    assert guidance.verified(["The company expects revenue of $200 million"], text) == []
    # Whitespace is normalised on both sides, so a re-wrapped document still matches.
    assert guidance.verified(["expects revenue of $84 million"], "…\n  expects   revenue of $84 million …")


def test_the_document_order_is_kept_and_nothing_is_ranked():
    """Which sentence matters is the reader's judgment (invariant 3)."""
    text = ("The company sees full-year revenue of $100 million. Margins are expected to "
            "reach 20% next year. It reaffirms its outlook of $250 million for 2028.")
    got = guidance.find(text)
    assert len(got) == 3
    assert got[0].startswith("The company sees full-year")
    assert got[2].startswith("It reaffirms its outlook")
