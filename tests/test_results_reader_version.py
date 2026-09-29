"""A verdict is only as good as the rule that produced it.

Stored verdicts keep the 6-K sweep from opening the same exhibit twice, which
also means a verdict OUTLIVES its rule. When the scheduling-notice fault was
fixed (2026-09-29, #118), VinFast's row did not move: the filing had already
been "checked", so nothing looked at it again — and the results row that the
wrong verdict had written was itself the second reason never to look.
"""
from alphadesk.ingest import edgar_releases as er


def test_a_verdict_from_an_older_rule_is_read_again(store):
    """The sweep skips what THIS reader decided, not what any reader decided."""
    store.mark_exhibit_checked("0001185185-26-004359", True, "6-K", reader=0)
    at_current = store.exhibit_checked(["0001185185-26-004359"], "6-K",
                                       reader=er.RESULTS_READER_VERSION)
    assert at_current == set(), "a verdict from an older rule must not silence a re-read"
    # Decided again by today's rule, it is skipped as before — the re-read
    # costs one fetch per candidate once, not on every pass afterwards.
    store.mark_exhibit_checked("0001185185-26-004359", False, "6-K",
                               reader=er.RESULTS_READER_VERSION)
    assert store.exhibit_checked(["0001185185-26-004359"], "6-K",
                                 reader=er.RESULTS_READER_VERSION) == {"0001185185-26-004359"}


def test_a_row_the_old_rule_wrote_is_taken_back(store):
    """Re-deciding a filing is worth nothing while the row it created stands:
    the calendar joins to the ROW, not to the verdict, so a corrected judgment
    that leaves the row behind never reaches a reader."""
    store.upsert_release("VFS", "0001185185-26-004359", "0001913510", "2026-09-28",
                         None, "VinFast Auto Ltd.", "2026-09-28", form="6-K")
    assert any(r["accession"] == "0001185185-26-004359"
               for r in store.releases_between("2026-09-28", "2026-09-28"))
    assert store.delete_release("0001185185-26-004359") == 1
    assert not any(r["accession"] == "0001185185-26-004359"
                   for r in store.releases_between("2026-09-28", "2026-09-28"))
    # Idempotent: a second sweep finding nothing to retract is not an error.
    assert store.delete_release("0001185185-26-004359") == 0


def test_the_version_is_bumped_when_the_rule_changes():
    """A guard, not a tautology: the constant exists so that editing
    is_results_release without bumping it is a visible omission rather than a
    silent one. Pinning the current value is what makes the next edit notice."""
    assert er.RESULTS_READER_VERSION == 1


def test_a_sweep_retracts_the_row_the_old_rule_left_behind(store, monkeypatch):
    """END TO END, because the two halves are useless apart: re-reading
    without retracting leaves the calendar citing the filing, and retracting
    without re-reading never happens. The state here is production's on
    2026-09-29 — a results row and a verdict, both from the cover-page fault."""
    acc, doc = "0001185185-26-004359", "vfs6k092826.htm"
    store.upsert_release("VFS", acc, "0001913510", "2026-09-28", None,
                         "VinFast Auto Ltd.", "2026-09-28", form="6-K")
    store.mark_exhibit_checked(acc, True, "6-K", reader=0)

    notice = (
        "REPORT OF FOREIGN PRIVATE ISSUER PURSUANT TO RULE 13a-16 OR 15d-16 "
        "OF THE SECURITIES EXCHANGE ACT OF 1934 VinFast Auto Ltd. INFORMATION "
        "CONTAINED IN THIS REPORT ON FORM 6-K VINFAST SETS DATE FOR THE RELEASE "
        "OF SECOND QUARTER 2026 RESULTS September 28, 2026 - VinFast announced "
        "that it will release its 2Q26 financial results on October 19, 2026.")
    hit = {"_id": f"{acc}:{doc}", "_source": {
        "adsh": acc, "file_type": "EX-99.1", "file_date": "2026-09-28",
        "display_names": ["VinFast Auto Ltd.  (VFS)  (CIK 0001913510)"]}}

    monkeypatch.setattr(er, "_search_text",
                        lambda day, phrase, forms, offset=0:
                        {"hits": {"hits": [hit] if offset == 0 else []}})
    monkeypatch.setattr(er.edgar, "fetch_filing_text", lambda url, max_chars=0: notice)
    monkeypatch.setattr(er, "_results_in_other_exhibits", lambda *a, **k: False)

    assert er.refresh_foreign_day("2026-09-28") == 0
    assert not any(r["accession"] == acc
                   for r in store.releases_between("2026-09-28", "2026-09-28"))
    # And the corrected verdict is stamped, so the next pass does not refetch.
    assert store.exhibit_checked([acc], "6-K",
                                 reader=er.RESULTS_READER_VERSION) == {acc}
