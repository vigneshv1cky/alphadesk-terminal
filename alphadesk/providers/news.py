"""News providers.

Eight implementations, because one implementation never proves an interface.
All return the same `Article` shape, so switching feeds is keying another
one on the Account page and nothing else — every feed is a user's own key. Polygon and Alpaca ride their existing SDKs; Finnhub, Benzinga, Tiingo,
Alpha Vantage, Marketaux and FMP are plain urllib against their REST
endpoints — the LLM
seam's no-vendor-SDK rule, applied here because none needs more than one
GET. Bloomberg and Reuters are deliberately absent: neither sells
self-serve API access, and their wire stories reach the window through the
feeds that license them.

Both are FIREHOSE feeds: one request returns everything since a timestamp,
already tagged with the symbols each article is about. That shape is what the
screener needs — it groups the whole window by ticker. A per-symbol-only feed
cannot back this interface without N requests per
poll and would silently lose discovery, since you can only ask about symbols
you already know.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from alphadesk.net import bound_timeout
from alphadesk.providers.base import Article, ProviderError
from alphadesk.providers.registry import register

log = logging.getLogger("alphadesk.providers.news")

# Cap on RAW items paged through per call, distinct from the caller's `limit`
# on USABLE ones. Without it a wide window on a busy day pages forever.
_MAX_SCAN = int(os.environ.get("NEWS_MAX_SCAN", "400"))

# Storage bound on a full article body — generous for prose, a guard against
# a feed shipping a novel.
_BODY_CHARS = 20_000


def _strip_html(html: str) -> str:
    """Publisher HTML → plain text with paragraph breaks.

    The body field is rendered verbatim in the reader, so the sanitation
    happens HERE, at ingestion, not in the browser: nothing executable and no
    markup survives, and the stored record is safe however it is later
    displayed (the web reader, the MCP tools, an agent's context). Block-level
    closers become paragraph breaks so the text keeps its shape.
    """
    import re
    from html import unescape

    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", html)
    s = re.sub(r"(?i)</(p|div|h[1-6]|li|blockquote|tr)>", "\n\n", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[:_BODY_CHARS]


class PolygonNews:
    """Polygon.io ticker news. Config: the user's Polygon key."""

    name = "polygon"
    # Verified against the live payload: description (~400 chars), image_url
    # and author ship; no body field exists at any tier.
    capabilities = ("summaries", "images", "bylines")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        # Explicit config wins — the key vault builds per-user instances this
        # way; the environment stays the operator path. api_secret is accepted
        # for interface symmetry and unused: Polygon auths with one key.
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Polygon key")
        try:
            import polygon
        except ImportError as exc:                    # pragma: no cover
            raise ProviderError("polygon-api-client is not installed") from exc

        client = polygon.RESTClient(api_key=self.api_key)
        out: list[Article] = []
        scanned = 0
        try:
            for art in client.list_ticker_news(
                published_utc_gte=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                limit=min(limit, 1000), sort="published_utc", order="desc",
            ):
                scanned += 1
                if scanned > _MAX_SCAN:
                    log.warning("polygon scan cap (%d) hit at %d usable", _MAX_SCAN, len(out))
                    break
                symbols = [t for t in (getattr(art, "tickers", None) or []) if t]
                title = getattr(art, "title", "") or ""
                art_id = str(getattr(art, "id", "") or getattr(art, "article_url", ""))
                if not (art_id and title and symbols):
                    continue
                pub = getattr(art, "publisher", None)
                out.append(Article(
                    id=art_id,
                    title=title,
                    url=getattr(art, "article_url", "") or "",
                    published_at=str(getattr(art, "published_utc", "")
                                     or datetime.now(timezone.utc).isoformat()),
                    symbols=symbols[:8],
                    # The FULL description — the feed's summary is the one
                    # piece of article text the subscription delivers, and
                    # truncating it at 400 was showing less than is paid for.
                    # 4000 is a storage bound, not a reading one.
                    summary=(getattr(art, "description", "") or "")[:4000],
                    source=pub.name if pub is not None and hasattr(pub, "name") else "Polygon",
                    image_url=getattr(art, "image_url", "") or "",
                    author=getattr(art, "author", "") or "",
                ))
                if len(out) >= limit:
                    break
        except Exception as exc:
            raise ProviderError(f"polygon fetch failed: {exc}") from exc
        return out


def alpaca_story_body(key: str, secret: str, article_id: str, symbol: str, published_at: str) -> Article | None:
    """One stored Alpaca story fetched again with its text: Alpaca has no
    lookup by id, so the story's first ticker is asked for the minutes around
    its publication and the id matched. None when it is not found."""
    from datetime import timedelta
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    client = bound_timeout(NewsClient(key, secret))
    page = client.get_news(NewsRequest(symbols=symbol, start=at - timedelta(minutes=5), end=at + timedelta(minutes=5),
                                       limit=50, include_content=True))
    items = getattr(page, "data", {}).get("news", []) if hasattr(page, "data") else []
    for item in items:
        if str(getattr(item, "id", "")) == str(article_id):
            return alpaca_article(item)
    return None


class AlpacaNews:
    """Alpaca market-data news (Benzinga-sourced).

    Config: the user's Alpaca key / ALPACA_SECRET_KEY — the same credentials the
    price provider already uses, so this costs nothing extra to enable.

    Narrower publisher mix than Polygon; the trade is that it is bundled with
    market data rather than separately billed.
    """

    name = "alpaca"
    # Benzinga articles arrive with full HTML content; stripped to plain
    # text at ingestion (see _strip_html).
    capabilities = ("summaries", "full_bodies", "images", "bylines")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.key = (api_key or "").strip()
        self.secret = (api_secret or "").strip()

    def fetch(self, since: datetime, limit: int = 200, until: datetime | None = None) -> list[Article]:
        """Articles from `since`, newest first; with `until`, only those
        published before it (a page of older news)."""
        if not (self.key and self.secret):
            raise ProviderError("no Alpaca key and secret")
        try:
            from alpaca.data.historical.news import NewsClient
            from alpaca.data.requests import NewsRequest
        except ImportError as exc:                    # pragma: no cover
            raise ProviderError("alpaca-py is not installed") from exc

        client = bound_timeout(NewsClient(self.key, self.secret))
        out: list[Article] = []
        try:
            # Alpaca caps a page at 50; page until the caller's limit or the
            # raw-scan cap, whichever comes first.
            token, scanned = None, 0
            while len(out) < limit and scanned < _MAX_SCAN:
                # include_content: Alpaca sends the article's text only when
                # asked (2026-09-15). Unasked, every Benzinga story arrived
                # without it and the reader showed the summary with a link
                # out, though the feed delivers the full story on this key.
                req = NewsRequest(start=since, end=until, limit=50, sort="desc",
                                  include_content=True, exclude_contentless=True, page_token=token)
                page = client.get_news(req)
                items = getattr(page, "data", {}).get("news", []) if hasattr(page, "data") else []
                if not items:
                    break
                for a in items:
                    scanned += 1
                    art = alpaca_article(a)
                    if art is None:
                        continue
                    out.append(art)
                    if len(out) >= limit:
                        break
                token = getattr(page, "next_page_token", None)
                if not token:
                    break
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"alpaca news fetch failed: {exc}") from exc
        return out


def alpaca_article(a) -> Article | None:
    """One Alpaca (Benzinga) news item as an Article, from the REST client's
    model or the real-time stream's — both carry the same fields. None for an
    item without an id, a headline or a ticker: the window groups by ticker."""
    from html import unescape
    symbols = [s for s in (getattr(a, "symbols", None) or []) if s]
    # Headlines and summaries arrive HTML-escaped ("maker&#39;s"); decoded
    # here so the stored text reads as written.
    title = unescape(getattr(a, "headline", "") or "")
    art_id = str(getattr(a, "id", "") or getattr(a, "url", ""))
    if not (art_id and title and symbols):
        return None
    ts = getattr(a, "created_at", None)
    published = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
    first_image = ""
    for img in getattr(a, "images", None) or []:
        first_image = str(getattr(img, "url", "") or (img.get("url", "") if isinstance(img, dict) else ""))
        if first_image:
            break
    return Article(
        id=art_id,
        title=title,
        url=getattr(a, "url", "") or "",
        published_at=published,
        symbols=symbols[:8],
        summary=unescape(getattr(a, "summary", "") or "")[:4000],
        source=getattr(a, "source", "") or "Alpaca",
        image_url=first_image,
        author=getattr(a, "author", "") or "",
        body=_strip_html(getattr(a, "content", "") or ""),
    )


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0):
    """One bounded GET returning parsed JSON. Errors surface as ProviderError
    WITHOUT the URL — query strings can carry a key, and provider errors end
    up in logs."""
    import json as _json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "AlphaDesk/1.0",
                                "Accept": "application/json", **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ProviderError(f"unreachable: {exc.reason}") from exc
    except ValueError as exc:
        raise ProviderError("response was not JSON") from exc


class FinnhubNews:
    """Finnhub general market news. Config: the user's Finnhub key.

    The `/news?category=general` firehose tags articles sparsely — `related`
    carries tickers only when Finnhub links the story to companies, and
    untagged items are DROPPED here because the screener groups the window by
    symbol. A Finnhub-only window is therefore thinner than a Polygon one;
    as a second feed merged alongside another it earns its place. The token
    travels as a header, never in the URL.
    """

    name = "finnhub"
    capabilities = ("summaries", "images")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Finnhub key")
        try:
            items = _get_json("https://finnhub.io/api/v1/news?category=general",
                              headers={"X-Finnhub-Token": self.api_key})
        except ProviderError as exc:
            raise ProviderError(f"finnhub fetch failed: {exc}") from exc
        if not isinstance(items, list):
            raise ProviderError("finnhub fetch failed: unexpected payload shape")

        floor = since.timestamp()
        out: list[Article] = []
        for a in items[:_MAX_SCAN]:
            ts = a.get("datetime") or 0
            if not isinstance(ts, (int, float)) or ts < floor:
                continue
            symbols = [t.strip().upper() for t in str(a.get("related") or "").split(",") if t.strip()]
            title = (a.get("headline") or "").strip()
            art_id = str(a.get("id") or "")
            if not (art_id and title and symbols):
                continue
            out.append(Article(
                id=f"finnhub-{art_id}",
                title=title,
                url=a.get("url") or "",
                published_at=datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                symbols=symbols[:8],
                summary=(a.get("summary") or "")[:4000],
                source=a.get("source") or "Finnhub",
                image_url=a.get("image") or "",
            ))
            if len(out) >= limit:
                break
        return out


class BenzingaNews:
    """Benzinga newsfeed, direct. Config: the user's Benzinga key.

    The same wire Alpaca resells — going direct is for readers who hold a
    Benzinga license without an Alpaca account. Full HTML bodies ship and are
    stripped to plain text at ingestion, same as the Alpaca path.
    """

    name = "benzinga"
    capabilities = ("summaries", "full_bodies", "images", "bylines")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Benzinga key")
        from email.utils import parsedate_to_datetime
        from urllib.parse import urlencode

        out: list[Article] = []
        page, scanned = 0, 0
        while len(out) < limit and scanned < _MAX_SCAN:
            qs = urlencode({
                "token": self.api_key, "pageSize": 100, "page": page,
                "displayOutput": "full", "sort": "created:desc",
                "dateFrom": since.strftime("%Y-%m-%d"),
            })
            try:
                items = _get_json(f"https://api.benzinga.com/api/v2/news?{qs}")
            except ProviderError as exc:
                raise ProviderError(f"benzinga fetch failed: {exc}") from exc
            if not isinstance(items, list) or not items:
                break
            aged_out = False
            for a in items:
                scanned += 1
                try:
                    created = parsedate_to_datetime(a.get("created") or "")
                except (TypeError, ValueError):
                    continue
                if created.timestamp() < since.timestamp():
                    aged_out = True       # sorted desc: everything after is older
                    break
                symbols = [str(t.get("name") or "").strip().upper()
                           for t in (a.get("stocks") or []) if isinstance(t, dict)]
                symbols = [t for t in symbols if t]
                title = (a.get("title") or "").strip()
                art_id = str(a.get("id") or "")
                if not (art_id and title and symbols):
                    continue
                images = a.get("image") or []
                first_image = ""
                for img in images:
                    first_image = str(img.get("url") or "") if isinstance(img, dict) else ""
                    if first_image:
                        break
                out.append(Article(
                    id=f"benzinga-{art_id}",
                    title=title,
                    url=a.get("url") or "",
                    published_at=created.astimezone(timezone.utc).isoformat(),
                    symbols=symbols[:8],
                    summary=_strip_html(a.get("teaser") or "")[:4000],
                    source="Benzinga",
                    image_url=first_image,
                    author=(a.get("author") or "").strip(),
                    body=_strip_html(a.get("body") or ""),
                ))
                if len(out) >= limit:
                    break
            if aged_out:
                break
            page += 1
        return out


class TiingoNews:
    """Tiingo's news feed. Config: the user's Tiingo key.

    Ticker-tagged at the source — the `tickers` array is Tiingo's own, so
    every article lands in the window under symbols the FEED asserted, not
    ones we guessed. Access to this endpoint depends on the reader's Tiingo
    plan; a plan without it surfaces as a logged provider error and an
    intact window, like every other dead feed. Token in the Authorization
    header, never the URL.
    """

    name = "tiingo"
    capabilities = ("summaries",)

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Tiingo key")
        url = (f"https://api.tiingo.com/tiingo/news"
               f"?startDate={since.strftime('%Y-%m-%d')}&limit={min(_MAX_SCAN, 1000)}")
        try:
            items = _get_json(url, headers={"Authorization": f"Token {self.api_key}"})
        except ProviderError as exc:
            raise ProviderError(f"tiingo fetch failed: {exc}") from exc
        if not isinstance(items, list):
            raise ProviderError("tiingo fetch failed: unexpected payload shape")

        floor = since.isoformat()
        out: list[Article] = []
        for a in items:
            if not isinstance(a, dict):
                continue
            published = str(a.get("publishedDate") or "")
            # startDate is day-granular upstream; the real cut happens here.
            if published and published < floor:
                continue
            symbols = [str(t).strip().upper() for t in (a.get("tickers") or []) if t]
            title = (a.get("title") or "").strip()
            art_id = str(a.get("id") or "")
            if not (art_id and title and symbols):
                continue
            out.append(Article(
                id=f"tiingo-{art_id}",
                title=title,
                url=a.get("url") or "",
                published_at=published or datetime.now(timezone.utc).isoformat(),
                symbols=symbols[:8],
                summary=(a.get("description") or "")[:4000],
                source=a.get("source") or "Tiingo",
            ))
            if len(out) >= limit:
                break
        return out


class AlphaVantageNews:
    """Alpha Vantage NEWS_SENTIMENT. Config: the user's Alpha Vantage key.

    Ticker-tagged at the source, with a RELEVANCE score per tag — tags below
    the floor are dropped, because Alpha Vantage marks passing mentions too
    and a 0.02-relevance tag would put an article under a symbol it is
    barely about. Its own sentiment fields are ignored: enrichment is one
    pipeline for every feed, or the window's labels mean different things
    per source.

    TWO exceptions to house rules, both theirs: the key rides the URL
    because query-param auth is the only kind the API offers (_get_json
    already keeps URLs out of error text), and throttling arrives as an
    HTTP 200 carrying a Note/Information body — surfaced here as the error
    it is. The free tier's 25 requests/day cannot cover the default
    20-minute poll; this feed suits a keyed reader more than an operator.
    """

    name = "alphavantage"
    capabilities = ("summaries", "images")

    _MIN_RELEVANCE = 0.15

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Alpha Vantage key")
        url = ("https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
               f"&time_from={since.strftime('%Y%m%dT%H%M')}&sort=LATEST"
               f"&limit={min(_MAX_SCAN, 1000)}&apikey={self.api_key}")
        try:
            data = _get_json(url)
        except ProviderError as exc:
            raise ProviderError(f"alphavantage fetch failed: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("alphavantage fetch failed: unexpected payload shape")
        throttle = data.get("Note") or data.get("Information")
        if throttle and not data.get("feed"):
            raise ProviderError(f"alphavantage refused: {str(throttle)[:200]}")

        out: list[Article] = []
        for a in (data.get("feed") or [])[:_MAX_SCAN]:
            if not isinstance(a, dict):
                continue
            tags = sorted((a.get("ticker_sentiment") or []),
                          key=lambda t: -float(t.get("relevance_score") or 0))
            symbols = []
            for t in tags:
                tick = str(t.get("ticker") or "").strip().upper()
                # Prefixed instruments (CRYPTO:BTC, FOREX:USD) aren't equities
                # this terminal renders.
                if not tick or ":" in tick:
                    continue
                if float(t.get("relevance_score") or 0) < self._MIN_RELEVANCE:
                    continue
                symbols.append(tick)
            title = (a.get("title") or "").strip()
            art_url = a.get("url") or ""
            if not (art_url and title and symbols):
                continue
            raw_ts = str(a.get("time_published") or "")
            try:
                published = datetime.strptime(raw_ts, "%Y%m%dT%H%M%S").replace(
                    tzinfo=timezone.utc)
            except ValueError:
                continue
            if published < since:
                continue
            out.append(Article(
                id=f"alphavantage-{art_url}",
                title=title,
                url=art_url,
                published_at=published.isoformat(),
                symbols=symbols[:8],
                summary=(a.get("summary") or "")[:4000],
                source=a.get("source") or "Alpha Vantage",
                image_url=a.get("banner_image") or "",
                author=", ".join(a.get("authors") or [])[:200],
            ))
            if len(out) >= limit:
                break
        return out


class MarketauxNews:
    """Marketaux news. Config: the user's Marketaux key.

    Entity-tagged at the source: each article carries the instruments it
    matched, typed — only equity entities become window symbols, ordered by
    the feed's own match score. Query-param auth is the only kind offered
    (the Alpha Vantage exception again; error text stays URL-free). The free
    tier returns THREE articles per request — fine for trying the seam,
    thin for a window; the docstring is the warning label.
    """

    name = "marketaux"
    capabilities = ("summaries", "images")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Marketaux key")
        url = ("https://api.marketaux.com/v1/news/all"
               f"?published_after={since.strftime('%Y-%m-%dT%H:%M')}"
               f"&limit={min(limit, 100)}&api_token={self.api_key}")
        try:
            data = _get_json(url)
        except ProviderError as exc:
            raise ProviderError(f"marketaux fetch failed: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("marketaux fetch failed: unexpected payload shape")

        out: list[Article] = []
        for a in (data.get("data") or [])[:_MAX_SCAN]:
            if not isinstance(a, dict):
                continue
            entities = sorted(
                (e for e in (a.get("entities") or [])
                 if isinstance(e, dict) and e.get("type") == "equity" and e.get("symbol")),
                key=lambda e: -float(e.get("match_score") or 0))
            symbols = [str(e["symbol"]).strip().upper() for e in entities]
            symbols = [t for t in symbols if t and ":" not in t]
            title = (a.get("title") or "").strip()
            art_id = str(a.get("uuid") or "")
            if not (art_id and title and symbols):
                continue
            out.append(Article(
                id=f"marketaux-{art_id}",
                title=title,
                url=a.get("url") or "",
                published_at=str(a.get("published_at") or "")
                             or datetime.now(timezone.utc).isoformat(),
                symbols=symbols[:8],
                summary=(a.get("description") or a.get("snippet") or "")[:4000],
                source=a.get("source") or "Marketaux",
                image_url=a.get("image_url") or "",
            ))
            if len(out) >= limit:
                break
        return out


class FMPNews:
    """Financial Modeling Prep stock news. Config: the user's Financial Modeling Prep key.

    A firehose of single-symbol articles — FMP tags each item with exactly
    one ticker, so a story about two companies arrives as two items; the
    URL-keyed cross-feed dedupe collapses those when another feed carries
    the combined story. Timestamps arrive as naive US/Eastern and are
    restated in UTC here, because a naive string would sort wrongly against
    every other feed's articles. Query-param auth is the only kind offered.
    """

    name = "fmp"
    capabilities = ("summaries", "images")

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        if not self.api_key:
            raise ProviderError("no Financial Modeling Prep key")
        from alphadesk.config import ET
        # The stable API: /api/v3/stock_news answers 403 "Legacy Endpoint"
        # to accounts opened after FMP's change (measured 2026-09-14).
        url = ("https://financialmodelingprep.com/stable/news/stock-latest"
               f"?page=0&limit={min(_MAX_SCAN, 250)}&apikey={self.api_key}")
        try:
            items = _get_json(url)
        except ProviderError as exc:
            raise ProviderError(f"fmp fetch failed: {exc}") from exc
        if not isinstance(items, list):
            raise ProviderError("fmp fetch failed: unexpected payload shape")
        # Companies' own press releases ride with the stock news (2026-09-14):
        # the primary source for results, and where a company announces when
        # it will report — which the earnings calendar reads from the window.
        try:
            releases = _get_json("https://financialmodelingprep.com/stable/news/press-releases-latest"
                                 f"?page=0&limit=100&apikey={self.api_key}")
            if isinstance(releases, list):
                items = items + releases
        except ProviderError as exc:
            log.debug("fmp press releases unavailable: %s", exc)

        out: list[Article] = []
        seen: set[tuple[str, str]] = set()
        for a in items:
            if not isinstance(a, dict):
                continue
            raw_ts = str(a.get("publishedDate") or "")
            try:
                published = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ET).astimezone(timezone.utc)
            except ValueError:
                continue
            if published < since:
                continue
            symbol = str(a.get("symbol") or "").strip().upper()
            title = (a.get("title") or "").strip()
            art_url = a.get("url") or ""
            # A release can arrive on both lists.
            if not (art_url and title and symbol) or (art_url, symbol) in seen:
                continue
            seen.add((art_url, symbol))
            out.append(Article(
                id=f"fmp-{art_url}",
                title=title,
                url=art_url,
                published_at=published.isoformat(),
                symbols=[symbol],
                summary=(a.get("text") or "")[:4000],
                source=a.get("site") or "FMP",
                image_url=a.get("image") or "",
            ))
            if len(out) >= limit:
                break
        return out


register("news", PolygonNews.name, PolygonNews)
register("news", AlpacaNews.name, AlpacaNews)
register("news", FinnhubNews.name, FinnhubNews)
register("news", BenzingaNews.name, BenzingaNews)
register("news", TiingoNews.name, TiingoNews)
register("news", AlphaVantageNews.name, AlphaVantageNews)
register("news", MarketauxNews.name, MarketauxNews)
register("news", FMPNews.name, FMPNews)
