"""Earnings transcript providers — the seam for "what did the company say
about the quarter".

The FREE default reads no vendor at all: a results press release is filed
by the company as Exhibit 99.1 to its results 8-K (Item 2.02) the day it
reports, and EDGAR serves it without a key. It is the company's own
words, verbatim, and it carries the guidance paragraph. It is not the
call — the Q&A with analysts happens on the call and only a vendor that
records calls has that — so `kind` says "release", and the UI says so.

The keyed vendors (Finnhub, FMP) serve the recorded call. Neither is on a
free plan; a reader keys one on the Account page and it becomes THEIR
transcript source for the session.
"""

import logging
import re
from datetime import date, timedelta

from alphadesk.providers.base import EntitlementError, ProviderError
from alphadesk.providers.registry import register

log = logging.getLogger("alphadesk.providers.transcripts")


def quarter_end_before(day: str) -> date | None:
    """The calendar quarter that closed most recently before `day` — what
    a results release published on `day` reports on. Calendar, not fiscal:
    Apple reports its fiscal Q3 in late July; this says "quarter ended
    2026-06-30", which is true and needs no fiscal-year table."""
    try:
        d = date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return None
    first_of_quarter = date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)
    return first_of_quarter - timedelta(days=1)


def _period_title(period_end: str | None, kind: str) -> str:
    what = "Results release" if kind == "release" else "Earnings call"
    if not period_end:
        return what
    d = date.fromisoformat(period_end)
    return f"{what} · quarter ended {d.strftime('%b')} {d.year}"


class EdgarReleases:
    """The results press release from the company's 8-K on SEC EDGAR."""

    name = "edgar"
    kind = "release"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        pass                                            # keyless by design

    def list_transcripts(self, symbol: str) -> list[dict]:
        from alphadesk.ingest import edgar
        out = []
        for f in edgar.recent_filings(symbol, forms=("8-K",), limit=80):
            items = {i.strip() for i in (f.get("items") or "").split(",") if i.strip()}
            if "2.02" not in items:
                continue
            day = f.get("report_date") or f.get("filing_date")
            pe = quarter_end_before(day)
            pe_s = pe.isoformat() if pe else None
            out.append({"id": f["accession"], "date": f.get("filing_date"),
                        "title": _period_title(pe_s, self.kind), "period_end": pe_s,
                        "url": f["url"]})
            if len(out) >= 16:
                break
        return out

    @staticmethod
    def _exhibit_url(filing_url: str) -> str:
        """The press release is Exhibit 99.1, a separate document in the
        filing's folder whose FILE NAME is the filer's choice (Apple:
        "a8-kex991…", NVIDIA: "q2fy27pr.htm") — so the name proves nothing.
        The filing's index page lists every document with its TYPE, and
        EX-99.1 there is the release. Falls back to the 8-K body, which at
        least names the exhibit, when the page cannot be read."""
        from alphadesk.ingest import edgar
        folder, doc = filing_url.rsplit("/", 1)
        acc_nodash = folder.rsplit("/", 1)[-1]
        if len(acc_nodash) != 18 or not acc_nodash.isdigit():
            return filing_url
        acc = f"{acc_nodash[:10]}-{acc_nodash[10:12]}-{acc_nodash[12:]}"
        try:
            html = edgar._get(f"{folder}/{acc}-index.html").decode("utf-8", "replace")
        except Exception as exc:
            log.debug("filing index unavailable (%s): %s", folder, exc)
            return filing_url
        picked = exhibit_from_index(html)
        return f"{folder}/{picked}" if picked else filing_url

    def transcript(self, symbol: str, id: str) -> dict | None:
        from alphadesk.ingest import edgar
        from alphadesk.ledger import store
        meta = store.get_filing_meta(id)
        if meta is None:
            rows = [r for r in self.list_transcripts(symbol) if r["id"] == id]
            if not rows:
                return None
            url, day = rows[0]["url"], rows[0]["date"]
        else:
            url, day = meta["url"], meta.get("filing_date")
        exhibit = self._exhibit_url(url)
        text = edgar.fetch_filing_text(exhibit, max_chars=120_000)
        if not text:
            return None
        text = strip_exhibit_header(text)
        pe = quarter_end_before(day or "")
        pe_s = pe.isoformat() if pe else None
        return {"id": id, "symbol": symbol.upper(), "date": day, "period_end": pe_s,
                "title": _period_title(pe_s, self.kind), "url": exhibit, "text": text}


class FinnhubTranscripts:
    """Finnhub's recorded calls (premium on their side). Config:
    FINNHUB_API_KEY — the same key as the news and prices providers."""

    name = "finnhub"
    kind = "call"
    _BASE = "https://finnhub.io/api/v1"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _get(self, path: str):
        if not self.api_key:
            raise ProviderError("no Finnhub key")
        from alphadesk.providers.prices import _get_json
        return _get_json(f"{self._BASE}{path}", {"X-Finnhub-Token": self.api_key})

    def list_transcripts(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        data = self._get(f"/stock/transcripts/list?symbol={sym}") or {}
        out = []
        for t in data.get("transcripts") or []:
            if not t.get("id"):
                continue
            pe = _quarter_end(t.get("year"), t.get("quarter"))
            out.append({"id": str(t["id"]), "date": (t.get("time") or "")[:10] or None,
                        "title": t.get("title") or _period_title(pe, self.kind),
                        "period_end": pe, "url": None})
        out.sort(key=lambda r: r["date"] or "", reverse=True)
        return out

    def transcript(self, symbol: str, id: str) -> dict | None:
        data = self._get(f"/stock/transcripts?id={id}") or {}
        turns = data.get("transcript") or []
        if not turns:
            return None
        paras = []
        for turn in turns:
            speech = " ".join(s.strip() for s in (turn.get("speech") or []) if s and s.strip())
            if speech:
                paras.append(f"{turn.get('name') or 'Speaker'}: {speech}")
        pe = _quarter_end(data.get("year"), data.get("quarter"))
        return {"id": id, "symbol": symbol.upper(), "date": (data.get("time") or "")[:10] or None,
                "period_end": pe, "title": data.get("title") or _period_title(pe, self.kind),
                "url": None, "text": "\n\n".join(paras)}


class FmpTranscripts:
    """Financial Modeling Prep's recorded calls. Config: the user's Financial Modeling Prep key — the
    same key as the fmp news provider."""

    name = "fmp"
    kind = "call"
    _BASE = "https://financialmodelingprep.com/stable"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _get(self, path: str):
        if not self.api_key:
            raise ProviderError("no Financial Modeling Prep key")
        from alphadesk.providers.prices import _get_json
        sep = "&" if "?" in path else "?"
        data = _get_json(f"{self._BASE}{path}{sep}apikey={self.api_key}", {})
        if isinstance(data, dict) and data.get("Error Message"):
            msg = str(data["Error Message"])[:200]
            if "premium" in msg.lower() or "upgrade" in msg.lower():
                raise EntitlementError(f"FMP: {msg}")
            raise ProviderError(f"FMP: {msg}")
        return data

    def list_transcripts(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        rows = self._get(f"/earning-call-transcript-dates?symbol={sym}") or []
        out = []
        for r in rows:
            q, y, d = r.get("quarter"), r.get("fiscalYear") or r.get("year"), r.get("date")
            if not (q and y):
                continue
            pe = _quarter_end(y, q)
            out.append({"id": f"{y}Q{q}", "date": (d or "")[:10] or None,
                        "title": f"Earnings call · FY{y} Q{q}", "period_end": pe, "url": None})
        out.sort(key=lambda r: r["date"] or r["id"], reverse=True)
        return out

    def transcript(self, symbol: str, id: str) -> dict | None:
        m = re.fullmatch(r"(\d{4})Q([1-4])", id)
        if not m:
            return None
        y, q = m.group(1), m.group(2)
        rows = self._get(f"/earning-call-transcript?symbol={symbol.upper()}&year={y}&quarter={q}") or []
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row or not row.get("content"):
            return None
        # FMP separates speaker turns with single newlines; the panel breaks
        # paragraphs on blank lines, so each turn gets one.
        text = re.sub(r"(?:\r?\n)+", "\n\n", str(row["content"]).strip())
        return {"id": id, "symbol": symbol.upper(), "date": (row.get("date") or "")[:10] or None,
                "period_end": _quarter_end(y, q), "title": f"Earnings call · FY{y} Q{q}",
                "url": None, "text": text}


_EXHIBIT_HEADER = re.compile(r"^\s*EX-99(?:\.\d+)?\s+\d+\s+\S+\.(?:htm|html|txt)\s+EX-99(?:\.\d+)?\s+(?:Document\s+)?", re.I)


def strip_exhibit_header(text: str) -> str:
    """An exhibit page opens with EDGAR's own banner ("EX-99.1 2 q2fy27pr.htm
    EX-99.1 Document") before the company's first word; that is the
    viewer's chrome, not the release."""
    return _EXHIBIT_HEADER.sub("", text, count=1)


def exhibit_from_index(html: str) -> str | None:
    """The file name of the results exhibit on a filing index page: the row
    typed EX-99.1 first, then any EX-99.* HTML document. None when the page
    lists no such exhibit."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)
    found: list[tuple[str, str]] = []
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        href = re.search(r'href="([^"]+)"', row)
        if not href or len(cells) < 4:
            continue
        kind = next((c for c in cells if re.fullmatch(r"EX-99(?:\.\d+)?", c, re.I)), None)
        if not kind:
            continue
        name = href.group(1).rsplit("/", 1)[-1]
        if name.lower().endswith((".htm", ".html", ".txt")):
            found.append((kind.upper(), name))
    if not found:
        return None
    found.sort(key=lambda kn: (kn[0] != "EX-99.1", kn[0]))
    return found[0][1]


def _quarter_end(year, quarter) -> str | None:
    """A vendor's fiscal (year, quarter) is not a calendar date; the label
    is kept as they state it and this gives a sortable stand-in only."""
    try:
        y, q = int(year), int(quarter)
    except (TypeError, ValueError):
        return None
    if not 1 <= q <= 4:
        return None
    month = q * 3
    last = date(y, month, 28) + timedelta(days=4)
    return (last - timedelta(days=last.day)).isoformat()


register("transcripts", EdgarReleases.name, EdgarReleases)
register("transcripts", FinnhubTranscripts.name, FinnhubTranscripts)
register("transcripts", FmpTranscripts.name, FmpTranscripts)
