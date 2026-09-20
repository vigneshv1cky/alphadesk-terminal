"""The data store — SQLite (WAL) by default, Postgres by connection string.

Everything the terminal caches or accumulates: news articles and their
enrichment, SEC filings with their text and Q&A caches, research answers, the
earnings calendar, accounts, and token spend.

The SQL here is written in the dialect BOTH engines share (ON CONFLICT
upserts, parameterized everything, time windows computed in Python); the
thin adapter in ledger/db.py handles the remainder — placeholder style, two
DDL spellings, dict rows, and one shared schema-error type. Self-hosting is
unchanged: no setting means the SQLite file below, exactly as always.

There is no trading ledger here. The picks/runs/funnel/skips tables that used
to live in this file were dropped on 2026-08-18 along with the execution layer,
and `init()` removes them from pre-existing databases.
"""

import json
from html import unescape
from datetime import datetime, timedelta, timezone

from alphadesk.config import DATA_DIR
from alphadesk.ledger import db

_DB = DATA_DIR / "ledger.db"
_lock = db.lock

_SCHEMA = """
-- Earnings calendar: who reported (with the EPS surprise) and who's about to.
-- Drives "be ready" (upcoming) + post-earnings-drift candidates (recently reported).
CREATE TABLE IF NOT EXISTS earnings (
    symbol       TEXT NOT NULL,
    report_date  TEXT NOT NULL,     -- report date, YYYY-MM-DD (date-only, stable key)
    session      TEXT,              -- BMO (pre-open) | AMC (post-close) | DAY
    eps_estimate REAL,
    eps_actual   REAL,              -- NULL until reported
    surprise_pct REAL,              -- NULL until reported
    market_cap   REAL,              -- for ranking big names in the reporting-soon view
    company_name TEXT,              -- Nasdaq supplies it; a calendar of bare tickers is unreadable
    fetched_at   TEXT,
    -- Plain UNIQUE: the conflict POLICY lives at the insert site
    -- (upsert_earnings' explicit ON CONFLICT), where both engines agree —
    -- the old constraint-level REPLACE clause was SQLite-only, and its bare
    -- replace semantics silently wiped the pre-armed columns anyway.
    UNIQUE(symbol, report_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_date ON earnings (report_date);

-- Results releases as filed on SEC EDGAR: every 8-K carrying Item 2.02
-- (Results of Operations and Financial Condition), stamped with EDGAR's
-- acceptance instant. Public government data, gathered by a keyless loop
-- and shared by everyone; each user's calendar joins it to the reports
-- their own vendors list (2026-09-13).
CREATE TABLE IF NOT EXISTS earnings_releases (
    symbol      TEXT NOT NULL,
    accession   TEXT NOT NULL,
    cik         TEXT,
    file_date   TEXT NOT NULL,      -- YYYY-MM-DD
    event_date  TEXT,               -- the 8-K's date of report: the day the results were released
    accepted_source TEXT,           -- 'index': accepted_at read from the filing's own index header
    accepted_at TEXT,               -- EDGAR's acceptance, ISO with the New York offset
    company     TEXT,
    PRIMARY KEY (symbol, accession)
);
CREATE INDEX IF NOT EXISTS idx_releases_date ON earnings_releases (file_date);

-- What each of a reader's calendar vendors said AHEAD of a report, one row per
-- vendor, company and day it was seen (2026-09-14). Scored against EDGAR's
-- release days once the reports are out, it answers how right a vendor's date
-- and session are a day, three days, a week in advance — the number that
-- decides whether a paid calendar is worth buying. Owned by the reader whose
-- keys fetched it, like their news; vendor "calendar" is what their merged
-- calendar showed.
-- A company's own announcement of when it will report (2026-09-14), read
-- from a press release in the reader's feeds. Owned by that reader, like the
-- article it came from.
CREATE TABLE IF NOT EXISTS earnings_announcements (
    owner        TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    url          TEXT NOT NULL,
    published_at TEXT NOT NULL,
    report_date  TEXT NOT NULL,
    session      TEXT,              -- BMO / AMC when stated or implied by the call time
    basis        TEXT,              -- 'stated' | 'call time'
    source       TEXT,              -- the wire or publisher
    sentence     TEXT,
    PRIMARY KEY (owner, symbol, url)
);
CREATE INDEX IF NOT EXISTS idx_announcements_report ON earnings_announcements (owner, report_date);

CREATE TABLE IF NOT EXISTS release_habits (
    owner       TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    session     TEXT,               -- BMO / AMC the company usually reports in, or NULL
    basis       INTEGER,            -- how many past releases it rests on
    PRIMARY KEY (owner, symbol)
);

CREATE TABLE IF NOT EXISTS press_release_checks (
    owner      TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (owner, symbol)
);

CREATE TABLE IF NOT EXISTS earnings_forecasts (
    owner       TEXT NOT NULL,
    vendor      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    captured_on TEXT NOT NULL,      -- YYYY-MM-DD, New York
    report_date TEXT NOT NULL,
    session     TEXT,
    confirmed   INTEGER,
    PRIMARY KEY (owner, vendor, symbol, captured_on)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_report ON earnings_forecasts (owner, report_date);

-- Raw ticker-tagged articles (ingest/news.py): the article itself
-- (title/url/tickers/body) so the window has something to render and a
-- reader has something to click through to.
-- owner '' is the SHARED feed (the operator's poll); a user_id owns the rows
-- that user's own news key fetched (phase 3). One story can exist once per
-- owner — the composite key — but is ENRICHED once for everyone, because
CREATE TABLE IF NOT EXISTS news_articles (
    owner        TEXT NOT NULL DEFAULT '',
    article_id   TEXT NOT NULL,
    title        TEXT,
    summary      TEXT,
    source       TEXT,
    url          TEXT,
    published_at TEXT,
    tickers      TEXT,      -- JSON list, e.g. ["AAPL","NVDA"]
    ingested_at  TEXT,
    image_url    TEXT,      -- the feed's article image, when it carries one
    author       TEXT,
    body         TEXT,      -- full article text, PLAIN (sanitized at ingest),
                            -- only from feeds licensed to deliver it
    feeds        TEXT,      -- which of the reader's feeds delivered it, "alpaca,polygon";
                            -- NULL on rows stored before 2026-09-14
    PRIMARY KEY (owner, article_id)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles (published_at);

-- The read requests an OWNER made, kept so the server can replay them and
-- keep those panels warm (alphadesk/prewarm.py, 2026-09-19): the request,
-- never its answer. Deleted with the account.
CREATE TABLE IF NOT EXISTS warm_paths (
    user_id      TEXT NOT NULL,
    path         TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    PRIMARY KEY (user_id, path)
);

-- The Business and Properties sections read out of an annual report
-- (ingest/company.py), by the filing's accession: a filed 10-K/20-F never
-- changes, and reading the sections took 2–3.6s on EVERY profile view
-- (measured 2026-09-19). Public SEC data, so one row serves everyone.
CREATE TABLE IF NOT EXISTS annual_report_sections (
    accession    TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);

-- Each stored story's MEANING, for search by meaning (alphadesk/semantic.py,
-- 2026-09-19): a normalised float16 vector from the self-hosted embedding
-- model, base64 text so SQLite and Postgres read it alike. One per story per
-- owner, and it goes when the story goes (prune, purge, account delete).
CREATE TABLE IF NOT EXISTS news_vectors (
    owner       TEXT NOT NULL,
    article_id  TEXT NOT NULL,
    model       TEXT NOT NULL,
    vec         TEXT NOT NULL,
    embedded_at TEXT NOT NULL,
    PRIMARY KEY (owner, article_id)
);
CREATE INDEX IF NOT EXISTS idx_news_vectors_at ON news_vectors (embedded_at);

-- What a FUND's own name says it is (fundclass.py): "single" for a product
-- built on one company, "sector" for a basket that merely shares a word with
-- it. Public data — a fund name means the same for every reader — so this is
-- one shared table. A row with verdict NULL is queued for the idle worker.
-- `vec` is the name's own numbers, kept so building the two reference points
-- is arithmetic over stored rows instead of reading four hundred names
-- through the model again every time the known set grows.
CREATE TABLE IF NOT EXISTS fund_name_verdicts (
    name       TEXT PRIMARY KEY,
    verdict    TEXT,
    margin     REAL,
    model      TEXT,
    vec        TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fund_verdicts_pending ON fund_name_verdicts (verdict);

-- SEC EDGAR filing metadata (ingest/edgar.py). accession is SEC's own globally
-- unique id for one filing — the natural key, not an autoincrement.
CREATE TABLE IF NOT EXISTS filings (
    accession    TEXT PRIMARY KEY,
    symbol       TEXT NOT NULL,
    cik          TEXT NOT NULL,
    form         TEXT,            -- 10-K, 10-Q, 8-K, ...
    filing_date  TEXT,
    report_date  TEXT,
    primary_doc  TEXT,            -- filename within the accession's archive dir
    url          TEXT,            -- resolved sec.gov/Archives/... document URL
    ingested_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_filings_symbol ON filings (symbol, filing_date);

-- Extracted plain text per filing — parsing a multi-MB iXBRL document is
-- expensive (network + BeautifulSoup), so this is fetched once and reused for
-- every question asked against that filing afterward.
CREATE TABLE IF NOT EXISTS filing_text_cache (
    accession    TEXT PRIMARY KEY,
    text         TEXT,
    char_count   INTEGER,
    extracted_at TEXT
);

-- Accounts, for HOSTED MODE (app/auth.py) — present but empty on a
-- self-hosted instance, where auth stays off and nothing reads it. The
-- password is an scrypt hash (n=2^14, r=8, p=1, 32-byte salt), never the
-- password; there is deliberately no email verification or reset flow in
-- phase 1 — the operator manages accounts from the CLI, which is what an
-- allowlist means. Phase 2 hangs the key vault off user_id.
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,       -- scrypt$<salt-b64>$<hash-b64>
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT,
    last_seen_at  TEXT,                -- activity gate for per-user polling
    -- Stamped into every session cookie at issue; a cookie whose stamp
    -- trails the row is dead. Bumping this is "sign out everywhere".
    session_version INTEGER NOT NULL DEFAULT 1,
    -- Access (2026-09-18): the free trial's end, and the subscription as the
    -- payment processor last reported it. alphadesk/billing.py reads these;
    -- nothing here decides access on its own.
    trial_ends_at       TEXT,
    plan_status         TEXT,   -- the processor's word: active, past_due, canceled...
    plan_provider       TEXT,
    plan_customer_id    TEXT,
    plan_subscription_id TEXT,
    plan_period_end     TEXT    -- paid through; a canceled plan runs to here
);

-- How each account has signed in (2026-09-18): one row per method used —
-- google, github, microsoft, password — with the first and latest time. The
-- Account page's Security panel showed every method the SERVER offers as
-- "Active" for everyone; a reader who only ever used GitHub saw Google
-- active too. Recorded from this date on; earlier sign-ins are not known.
CREATE TABLE IF NOT EXISTS user_sign_ins (
    user_id   TEXT NOT NULL REFERENCES users(user_id),
    method    TEXT NOT NULL,
    first_at  TEXT,
    last_at   TEXT,
    PRIMARY KEY (user_id, method)
);

-- The key vault (phase 2): each user's news and LLM keys. config is a whole
-- JSON object sealed with AES-256-GCM under ALPHADESK_VAULT_KEY
-- (ledger/vault.py) — key_hint is the ONLY thing any API response carries.
-- The primary key allows one active key per PROVIDER per seam (2026-09-03,
-- "we are not just accepting one news api at a time"): a reader can hold
-- Polygon AND Alpaca news keys and their feed merges both. The llm seam
-- stays one-active-key by code (set_user_key clears siblings) — two model
-- keys would just be ambiguity about which one answers.
CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    seam         TEXT NOT NULL,  -- 'news' | 'llm' | 'prices' — validated at the API, not here: a CHECK cannot be ALTERed and cost a rebuild once already
    provider     TEXT NOT NULL,      -- registry name: polygon, anthropic, openai-compatible…
    config       TEXT NOT NULL,      -- vault envelope: base64(nonce || ciphertext || tag)
    key_hint     TEXT NOT NULL,      -- last 4 characters, for display ONLY
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    PRIMARY KEY (user_id, seam, provider)
);

-- Reader-created views (My Views): a named board per user, its composition
-- the same `id:span,id` string the ?tiles= URL form carries. The browser
-- keeps a working copy; THIS is the durable one that follows the account.
CREATE TABLE IF NOT EXISTS user_views (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    view_id    TEXT NOT NULL,
    name       TEXT NOT NULL,
    layout     TEXT NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (user_id, view_id)
);

-- Reader-made baskets (2026-09-18): a name, a line on what moves it and its
-- symbols (a JSON list), beside the curated ones in config. Per reader, like
-- views; the reader's agent reads them through the baskets tool.
CREATE TABLE IF NOT EXISTS user_baskets (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    basket_id  TEXT NOT NULL,
    label      TEXT NOT NULL,
    why        TEXT NOT NULL DEFAULT '',
    symbols    TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT,
    PRIMARY KEY (user_id, basket_id)
);

-- The reader's board — the symbol strip — mirrored from their browser so
-- their own agent can see which names they follow (2026-09-17). The browser
-- stays the source of truth; this is its last-written copy.
CREATE TABLE IF NOT EXISTS user_boards (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    symbols    TEXT NOT NULL,
    active     TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

-- The dollar-volume pool (providers/alpaca.py): every listed stock
-- averaging $10M+ a day over five sessions, derived from ONE reader's own
-- daily bars and rebuilt daily. Kept so a restart or a new server instance
-- does not show thin gainers and losers while it rebuilds (2026-09-17).
CREATE TABLE IF NOT EXISTS reader_dollar_pools (
    owner      TEXT NOT NULL,
    vendor     TEXT NOT NULL,
    symbols    TEXT NOT NULL,
    built_at   BIGINT NOT NULL,
    PRIMARY KEY (owner, vendor)
);

-- Access tokens a reader issues so THEIR OWN agent (Claude, Cursor,
-- opencode, …) can call AlphaDesk's tools as them. Only the SHA-256 of the
-- token is stored; the token itself is shown once, at creation.
CREATE TABLE IF NOT EXISTS agent_access_tokens (
    token_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    hint         TEXT NOT NULL,
    created_at   TEXT,
    last_used_at TEXT,
    revoked_at   TEXT
);

-- OAuth for agent apps that connect by sign-in rather than a pasted token
-- (Claude.ai and ChatGPT connectors; app/agent_oauth.py). Clients register
-- themselves (RFC 7591); their record, secret included, is vault-sealed.
-- Codes and tokens are stored only as SHA-256; expiries are unix seconds.
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id   TEXT PRIMARY KEY,
    info        TEXT NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash   TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    payload     TEXT NOT NULL,
    expires_at  BIGINT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS oauth_grants (
    grant_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    client_id       TEXT NOT NULL,
    client_name     TEXT NOT NULL,
    scopes          TEXT NOT NULL DEFAULT '',
    resource        TEXT,
    access_hash     TEXT NOT NULL UNIQUE,
    access_expires  BIGINT NOT NULL,
    refresh_hash    TEXT NOT NULL UNIQUE,
    refresh_expires BIGINT NOT NULL,
    created_at      TEXT,
    last_used_at    TEXT,
    revoked_at      TEXT
);

-- Chart state that follows the account (2026-09-05, "let's build our own
-- TradingView"): 'prefs' is the reading setup (interval, type, scale,
-- indicators), plus the workspace's cells, layouts and templates. Drawings
-- were saved here as 'drawings:SYM' until 2026-09-18; they are no longer
-- saved at all, and init() deletes the old rows.
CREATE TABLE IF NOT EXISTS user_chart_state (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    key        TEXT NOT NULL,
    state      TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (user_id, key)
);

"""


def _connect():
    return db.connect(_DB)


def _key_table_needs_rebuild(conn) -> bool:
    """Does user_api_keys predate the current shape? Two generations trigger
    the same rebuild: the pre-multi-feed primary key (no provider column in
    it), and the seam CHECK that named only news/llm before the prices seam
    (2026-09-03). Engine-specific introspection, because neither engine can
    ALTER a key or a CHECK in place and only one of them has sqlite_master."""
    if db.backend() == "postgres":
        rows = conn.execute(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc"
            " JOIN information_schema.key_column_usage kcu"
            "   ON kcu.constraint_name = tc.constraint_name"
            "  AND kcu.table_name = tc.table_name"
            " WHERE tc.table_name = 'user_api_keys'"
            "   AND tc.constraint_type = 'PRIMARY KEY'").fetchall()
        cols = {r["column_name"] for r in rows}
        if not cols:
            return False
        if "provider" not in cols:
            return True
        checks = conn.execute(
            "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c"
            " JOIN pg_class t ON t.oid = c.conrelid"
            " WHERE t.relname = 'user_api_keys' AND c.contype = 'c'").fetchall()
        return any("seam" in (r["def"] or "") and "prices" not in (r["def"] or "")
                   for r in checks)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='user_api_keys'").fetchone()
    if row is None or not row["sql"]:
        return False
    if "provider" not in (row["sql"].rsplit("PRIMARY KEY", 1)[-1]):
        return True
    return "CHECK" in row["sql"] and "'prices'" not in row["sql"]


def init() -> None:
    with _lock, _connect() as conn:
        # One-time removal of the trading ledger (2026-08-18). AlphaDesk stopped
        # booking, holding and grading positions, and these tables outlived the
        # code that wrote them. This is DESTRUCTIVE and deliberate: an existing
        # database loses its decision history the first time this runs. Back up
        # ledger.db first if that history matters.
        for dead in ("picks", "runs", "funnel", "relationships", "relation_facts",
                     "skips", "earnings_reads", "price_daily", "ingest_stats",
                     "earnings_reactions"):
            conn.execute(f"DROP TABLE IF EXISTS {dead}")

        # One-time removal of the in-app agent's tables (2026-09-17, the
        # owner's call after #175 removed the agent). DESTRUCTIVE and
        # deliberate: saved conversations, custom modes and commands,
        # reader-registered MCP servers (their vault-sealed tokens included)
        # and uploaded documents are deleted the first time this runs.
        for dead in ("agent_threads", "user_modes", "user_commands",
                     "user_mcp_servers", "user_documents",
                     # The in-app model went the same way (2026-09-17): its
                     # caches and its token meter go with it.
                     "token_usage", "enrichment_cache", "symbol_digests",
                     "filing_qa_cache", "research_cache"):
            conn.execute(f"DROP TABLE IF EXISTS {dead}")

        # news_articles' primary key changed shape (article_id alone ->
        # (owner, article_id)) when feeds became per-user (phase 3). A key
        # can't be ALTERed on either engine, and this table is real data, not
        # a cache — so it is REBUILT, with every existing row landing in the
        # shared feed (owner ''), which is exactly what it was.
        cols = db.table_columns(conn, "news_articles")
        if cols and "owner" not in cols:
            conn.execute("ALTER TABLE news_articles RENAME TO news_articles_old")
            conn.execute("DROP INDEX IF EXISTS idx_news_published")

        # user_api_keys' primary key changed shape ((user_id, seam) ->
        # (user_id, seam, provider)) when a reader gained multiple news
        # feeds at once. Same rebuild as news_articles — a key cannot be
        # ALTERed on either engine and these rows are real data.
        keys_rebuild = _key_table_needs_rebuild(conn)
        if keys_rebuild:
            conn.execute("ALTER TABLE user_api_keys RENAME TO user_api_keys_old")

        db.exec_script(conn, _SCHEMA)

        # Chart drawings are no longer saved (2026-09-18, the owner's call):
        # they live for one visit to /chart, so a line drawn and forgotten
        # does not come back. The copies saved before then are deleted on
        # every start — DESTRUCTIVE and deliberate, and idempotent.
        conn.execute("DELETE FROM user_chart_state WHERE key LIKE 'drawings:%'")

        if keys_rebuild:
            conn.execute(
                "INSERT INTO user_api_keys"
                " (user_id, seam, provider, config, key_hint, created_at, last_used_at)"
                " SELECT user_id, seam, provider, config, key_hint, created_at, last_used_at"
                " FROM user_api_keys_old WHERE true"
                " ON CONFLICT (user_id, seam, provider) DO NOTHING")
            conn.execute("DROP TABLE user_api_keys_old")

        if cols and "owner" not in cols:
            old = db.table_columns(conn, "news_articles_old")
            carried = [c for c in ("article_id", "title", "summary", "source", "url",
                                   "published_at", "tickers", "ingested_at",
                                   "image_url", "author", "body") if c in old]
            names = ", ".join(carried)
            conn.execute(
                # WHERE true is load-bearing: SQLite refuses an upsert
                # clause directly after INSERT..SELECT without it.
                f"INSERT INTO news_articles (owner, {names})"
                f" SELECT '', {names} FROM news_articles_old WHERE true"
                " ON CONFLICT (owner, article_id) DO NOTHING")
            conn.execute("DROP TABLE news_articles_old")

    # Idempotent column migrations for pre-existing databases — no-ops once
    # the column exists. Only the surviving tables are covered; the picks
    # migrations went with the table. Each in its OWN transaction: a failed
    # ALTER aborts a Postgres transaction, and one already-migrated column
    # must not roll back the migration after it.
    for ddl in (
        "ALTER TABLE earnings ADD COLUMN market_cap REAL",
        "ALTER TABLE earnings ADD COLUMN pre_report_close REAL",   # pre-armed reporter context
        "ALTER TABLE earnings ADD COLUMN implied_move_pct REAL",
        "ALTER TABLE earnings ADD COLUMN low_liquidity INTEGER",
        "ALTER TABLE earnings ADD COLUMN company_name TEXT",
        "ALTER TABLE earnings ADD COLUMN confirmed INTEGER",       # the company named the time
        "ALTER TABLE earnings ADD COLUMN estimate_count INTEGER",  # analysts behind the EPS estimate
        "ALTER TABLE earnings ADD COLUMN sources TEXT",            # retired 2026-09-13: the calendar is built per user
        "ALTER TABLE earnings ADD COLUMN actual_at TEXT",          # when the actual EPS was FIRST seen here — its age
        "ALTER TABLE earnings ADD COLUMN released_at TEXT",        # EDGAR's acceptance of the earnings 8-K
        "ALTER TABLE users ADD COLUMN last_seen_at TEXT",          # activity gate for per-user polling
        "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN trial_ends_at TEXT",          # access: the free trial's end
        "ALTER TABLE users ADD COLUMN plan_status TEXT",            # access: the processor's subscription status
        "ALTER TABLE users ADD COLUMN plan_provider TEXT",
        "ALTER TABLE users ADD COLUMN plan_customer_id TEXT",
        "ALTER TABLE users ADD COLUMN plan_subscription_id TEXT",
        "ALTER TABLE users ADD COLUMN plan_period_end TEXT",
        "ALTER TABLE news_articles ADD COLUMN image_url TEXT",     # the reader's article extras
        "ALTER TABLE news_articles ADD COLUMN author TEXT",
        "ALTER TABLE news_articles ADD COLUMN body TEXT",
        "ALTER TABLE news_articles ADD COLUMN feeds TEXT",
        "ALTER TABLE earnings_releases ADD COLUMN event_date TEXT",  # the release day an 8-K reports
        "ALTER TABLE earnings_releases ADD COLUMN accepted_source TEXT",  # 'index' once read from the filing index          # which reader feeds delivered it
        "ALTER TABLE earnings_releases ADD COLUMN form TEXT",  # 8-K, or 6-K for a foreign private issuer
        "ALTER TABLE fund_name_verdicts ADD COLUMN vec TEXT",  # the name's numbers, kept for the reference points
    ):
        try:
            with _lock, _connect() as conn:
                conn.execute(ddl)
        except db.schema_errors():
            pass  # already migrated

    # An account from before trials existed starts one NOW (2026-09-18), so
    # switching the access gate on can never lock out a reader who signed
    # up before there was a trial to count. Idempotent: only empty rows.
    from alphadesk import billing
    with _lock, _connect() as conn:
        conn.execute("UPDATE users SET trial_ends_at=? WHERE trial_ends_at IS NULL",
                     (billing.trial_end_from_now(),))

    # The CoinGecko key moved from its own "crypto" seam into market data
    # (2026-09-13), where every data vendor now lives. Idempotent: once the
    # rows are moved there is nothing left to move.
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, seam, provider, config, key_hint, created_at, last_used_at)"
            " SELECT user_id, 'prices', provider, config, key_hint, created_at, last_used_at"
            " FROM user_api_keys WHERE seam = 'crypto'"
            " ON CONFLICT (user_id, seam, provider) DO NOTHING")
        conn.execute("DELETE FROM user_api_keys WHERE seam = 'crypto'")


LOCAL_USER_ID = "local"


def ensure_local_user() -> str:
    """The one account an OPEN instance (ALPHADESK_AUTH=off: development,
    a single-person self-host) acts as, so the key vault and every keyed
    surface work there exactly as they do for a signed-in user. Its password
    hash is not a valid scrypt string, so it can never be logged into."""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, created_at) VALUES (?,?,?,?)"
            " ON CONFLICT (user_id) DO NOTHING",
            (LOCAL_USER_ID, "local@alphadesk.invalid", "!", _now()))
    return LOCAL_USER_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _et_date(offset_days: int = 0) -> str:
    """Today's ET calendar date (± offset) as YYYY-MM-DD. The market clock and every
    stored report_date are ET, so date-window comparisons must key on the ET day — SQLite
    date('now') is UTC and shifts the window a day in the evening ET (dropping the oldest
    drift day / pulling in tomorrow's reporters)."""
    from alphadesk.config import now_et
    return (now_et().date() + timedelta(days=offset_days)).isoformat()


def _et_day_start_utc() -> str:
    """UTC ISO timestamp of ET midnight today — for comparing full-timestamp
    columns (news_articles.ingested_at) against 'start of today' on the ET
    clock, which is the clock every stored report_date already uses."""
    from alphadesk.config import now_et
    return now_et().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc).isoformat()


def article_url_key(url: str | None) -> str:
    """The cross-feed identity of a story: its URL without the query string
    or a trailing slash. Two feeds give one press release different ids and
    the same address."""
    return (url or "").split("?", 1)[0].rstrip("/")


def _feed_list(v: str | None) -> list[str]:
    return sorted({f for f in (v or "").split(",") if f})


def save_articles(articles: list[dict], owner: str = "") -> list[str]:
    """Persist raw articles (news_articles) — the record a human clicks through
    to, not the AI's opinion of it. An article's own facts (title/url/tickers)
    never change once published, so a re-delivered one is not rewritten; only
    its FEEDS grow (2026-09-14): which of the reader's feeds delivered it.

    One story is one row per owner. The same URL arriving later under another
    feed's id is not stored again — its feed joins the existing row. Returns
    the ids that were folded into an existing story that way, so the caller
    does not spend a model call enriching a row that does not exist.
    `owner` is whose window the rows belong to."""
    articles = [a for a in (articles or []) if a.get("id")]
    if not articles:
        return []
    folded: list[str] = []
    with _lock, _connect() as conn:
        ids = [a["id"] for a in articles]
        # Earlier copies: the same ids, or any story of this owner published
        # within two days of the batch — a feed re-delivers inside its poll
        # window, never weeks later — matched on the normalised URL below
        # (a stored "…/a?utm=1" is the same story as an incoming "…/a/").
        dates = sorted(a.get("published_at") or "" for a in articles if a.get("published_at"))
        floor = ""
        if dates:
            try:
                floor = (datetime.fromisoformat(dates[0].replace("Z", "+00:00")) - timedelta(days=2)).isoformat()
            except ValueError:
                floor = ""
        existing: list[dict] = []
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            existing += [dict(r) for r in conn.execute(
                f"SELECT article_id, url, feeds, coalesce(length(body), 0) AS body_len FROM news_articles"
                f" WHERE owner = ? AND article_id IN ({','.join('?' * len(chunk))})",
                [owner, *chunk]).fetchall()]
        if floor:
            existing += [dict(r) for r in conn.execute(
                "SELECT article_id, url, feeds, coalesce(length(body), 0) AS body_len FROM news_articles"
                " WHERE owner = ? AND published_at >= ?",
                (owner, floor)).fetchall()]
        by_id = {r["article_id"]: r for r in existing}
        by_url = {article_url_key(r["url"]): r for r in existing if article_url_key(r["url"])}
        inserts, feed_updates, body_updates = [], {}, {}
        for a in articles:
            feeds = _feed_list(",".join(a.get("feeds") or []))
            hit = by_id.get(a["id"]) or by_url.get(article_url_key(a.get("url")))
            if hit is not None:
                if hit["article_id"] != a["id"]:
                    folded.append(a["id"])
                # The one fact that may arrive later: the story's text, stored
                # before the feed was asked for it (2026-09-15).
                if a.get("body") and not hit.get("body_len"):
                    hit["body_len"] = len(a["body"])
                    body_updates[hit["article_id"]] = a["body"]
                merged = _feed_list(",".join([hit.get("feeds") or "", *feeds]))
                if merged != _feed_list(hit.get("feeds")):
                    hit["feeds"] = ",".join(merged)
                    feed_updates[hit["article_id"]] = hit["feeds"]
                continue
            row = {"article_id": a["id"], "url": a.get("url"), "feeds": ",".join(feeds) or None}
            by_id[a["id"]] = row
            if article_url_key(a.get("url")):
                by_url[article_url_key(a.get("url"))] = row
            inserts.append((owner, a["id"], a.get("title"), a.get("summary"), a.get("source"), a.get("url"),
                            a.get("published_at"), json.dumps(a.get("tickers") or []), _now(),
                            a.get("image_url"), a.get("author"), a.get("body"), row["feeds"]))
        if inserts:
            conn.executemany(
                "INSERT INTO news_articles"
                " (owner, article_id, title, summary, source, url, published_at, tickers, ingested_at,"
                "  image_url, author, body, feeds)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT (owner, article_id) DO NOTHING", inserts)
        for aid, feeds in feed_updates.items():
            conn.execute("UPDATE news_articles SET feeds = ? WHERE owner = ? AND article_id = ?", (feeds, owner, aid))
        for aid, body in body_updates.items():
            conn.execute("UPDATE news_articles SET body = ? WHERE owner = ? AND article_id = ?", (body, owner, aid))
    return folded


def feed_counts(owner: str, since_iso: str) -> dict[str, int]:
    """Stories each of the reader's feeds delivered since `since_iso`, a story
    delivered by two feeds counting for both — how the Account page shows
    what a subscription actually brings."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT feeds FROM news_articles WHERE owner = ? AND ingested_at >= ? AND feeds IS NOT NULL",
            (owner, since_iso)).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        for f in _feed_list(dict(r)["feeds"]):
            out[f] = out.get(f, 0) + 1
    return out


def recent_articles(since_iso: str, limit: int = 400, owner: str = "") -> list[dict]:
    """The window's articles as ARTICLES — one row per story, newest first,
    with the full ticker list decoded. The per-ticker view below fans a story
    out under every symbol it names, which is right for the screener's context
    window and wrong for a reading list: there, a six-ticker story is one
    story. Capped, and the cap is visible to the caller via len()."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT article_id, title, summary, source, url, published_at, tickers,"
            "  image_url, author, body, feeds"
            " FROM news_articles WHERE owner = ? AND published_at >= ?"
            " ORDER BY published_at DESC LIMIT ?",
            (owner, since_iso, int(limit))
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # Stories stored before headlines were decoded at ingest read "&#39;".
        d["title"], d["summary"] = unescape(d.get("title") or ""), unescape(d.get("summary") or "")
        d["tickers"] = sorted({str(t).upper() for t in json.loads(d.pop("tickers") or "[]")})
        d["feeds"] = _feed_list(d.get("feeds"))
        out.append(d)
    return out


def article(owner: str, article_id: str) -> dict | None:
    """One of `owner`'s stored stories, in recent_articles' shape."""
    with _connect() as conn:
        r = conn.execute(
            "SELECT article_id, title, summary, source, url, published_at, tickers,"
            "  image_url, author, body, feeds FROM news_articles WHERE owner = ? AND article_id = ?",
            (owner, article_id)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["title"], d["summary"] = unescape(d.get("title") or ""), unescape(d.get("summary") or "")
    d["tickers"] = sorted({str(t).upper() for t in json.loads(d.pop("tickers") or "[]")})
    d["feeds"] = _feed_list(d.get("feeds"))
    return d


#: What a search word may be followed by inside the text it matched. A query
#: matches at the START of a word and may stop part-way through it — "benz"
#: finds Benzinga — but never begins mid-word, which is what made "hood"
#: return a neighbourhood store network and the likelihood of lung cancer
#: (2026-09-17, the reader's report).
def _words(text: str) -> str:
    """`text` reduced to its words, space-separated and lower case, with a
    leading space so a phrase can be anchored to a word start."""
    out = []
    word = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return " " + " ".join(out)


def matches_query(query: str, *fields: str | None) -> bool:
    """Does any field match `query`? The rule — whole words in order, word
    forms, a capitalised ticker exact, the last word of five or more as a
    prefix — lives in alphadesk/newsquery.py, shared with the app."""
    from alphadesk.newsquery import matches
    return matches(query, *fields)


def articles_before(owner: str, before_iso: str, limit: int = 100, query: str = "") -> list[dict]:
    """A page of `owner`'s stories published before `before_iso`, newest
    first, in recent_articles' shape; with `query`, only those matching it
    word by word (see matches_query) in headline, summary, tickers or source.

    The SQL narrows with a plain LIKE on the query's FIRST word (its stem,
    less a letter, so "companies" still reaches "company") OR on the tickers
    and names the query resolves to (newsquery.expand: "robinhood" reaches
    stories tagged HOOD). LIKE can only over-match; the word test is applied
    to the rows that come back.
    Doing it in SQL would need a regular expression, which SQLite and
    Postgres spell differently; this store speaks the dialect they share."""
    sql = ("SELECT article_id, title, summary, source, url, published_at, tickers,"
           "  image_url, author, body, feeds"
           " FROM news_articles WHERE owner = ? AND published_at < ?")
    from alphadesk.newsquery import expand, matches, stem
    q = (query or "").strip()
    first = _words(q).strip().split(" ")[0] if q else ""
    exp = expand(q) if first else {"tickers": [], "names": []}
    extra: list[str] = []
    if first:
        root = stem(first)
        like = f"%{root[:-1] if len(root) > 4 else root}%"
        cond = ("lower(title) LIKE ? OR lower(coalesce(summary, '')) LIKE ?"
                " OR lower(tickers) LIKE ? OR lower(coalesce(source, '')) LIKE ?")
        for t in exp["tickers"]:
            cond += " OR tickers LIKE ?"
            extra.append(f'%"{t}"%')
        for n in exp["names"]:
            cond += " OR lower(title) LIKE ?"
            extra.append(f"%{n}%")
        sql += f" AND ({cond})"
    sql += " ORDER BY published_at DESC LIMIT ?"

    want = int(limit)
    out: list[dict] = []
    edge = before_iso
    # Each pass reads a wider slice than it needs, because the word test drops
    # some of what LIKE returned; three passes is plenty on a reader's window
    # and bounds the work when a common fragment matches almost nothing.
    for _ in range(3 if first else 1):
        args: list = [owner, edge]
        if first:
            args += [like, like, like, like, *extra]
        args.append(max(want * 10, 200) if first else want)
        with _connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        if not rows:
            break
        for r in rows:
            d = dict(r)
            # Stories stored before headlines were decoded at ingest read "&#39;".
            d["title"], d["summary"] = unescape(d.get("title") or ""), unescape(d.get("summary") or "")
            d["tickers"] = sorted({str(t).upper() for t in json.loads(d.pop("tickers") or "[]")})
            d["feeds"] = _feed_list(d.get("feeds"))
            if first and not matches(q, d["title"], d.get("summary"), " ".join(d["tickers"]),
                                     d.get("source"), tickers=tuple(exp["tickers"]),
                                     names=tuple(exp["names"]), tags=d["tickers"]):
                continue
            out.append(d)
            if len(out) >= want:
                return out
        edge = rows[-1]["published_at"]
        if len(rows) < (max(want * 10, 200) if first else want):
            break
    return out


def articles_for_symbol(owner: str, symbol: str, before_iso: str | None = None,
                        limit: int = 10) -> list[dict]:
    """One symbol's stored stories, newest first, in recent_articles' shape —
    only those whose ticker list names it, optionally published before
    `before_iso` (the next page). The ticker match is done in SQL for the
    candidates and re-checked on the decoded list, so a symbol that is a
    substring of another (F in FORD) never slips in."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return []
    pattern = '%"' + sym.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + '"%'
    sql = ("SELECT article_id, title, summary, source, url, published_at, tickers,"
           "  image_url, author, body, feeds"
           " FROM news_articles WHERE owner = ? AND upper(tickers) LIKE ? ESCAPE '\\'")
    args: list = [owner, pattern]
    if before_iso:
        sql += " AND published_at < ?"
        args.append(before_iso)
    sql += " ORDER BY published_at DESC LIMIT ?"
    args.append(int(limit) * 2 + 10)
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        tickers = sorted({str(t).upper() for t in json.loads(d.pop("tickers") or "[]")})
        if sym not in tickers:
            continue
        d["tickers"] = tickers
        d["title"], d["summary"] = unescape(d.get("title") or ""), unescape(d.get("summary") or "")
        d["feeds"] = _feed_list(d.get("feeds"))
        out.append(d)
        if len(out) >= limit:
            break
    return out


def recent_articles_by_ticker(since_iso: str, limit_per_symbol: int = 12,
                              owner: str = "") -> dict[str, list[dict]]:
    """Recent articles grouped by ticker, newest first, capped per symbol so
    one chatty name (dozens of press-release wires) can't crowd out everyone
    else in the screener's context window."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT article_id, title, summary, source, url, published_at, tickers"
            " FROM news_articles WHERE owner = ? AND published_at >= ?"
            " ORDER BY published_at DESC",
            (owner, since_iso)
        ).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        for t in json.loads(d["tickers"] or "[]"):
            bucket = out.setdefault(t.upper(), [])
            if len(bucket) < limit_per_symbol:
                bucket.append(d)
    return out


def save_filings(rows: list[dict]) -> None:
    """Persist filing metadata. Each: {accession, symbol, cik, form,
    filing_date, report_date, primary_doc, url}. INSERT OR IGNORE: a filing's
    own facts never change once accepted by EDGAR."""
    data = [(r["accession"], r["symbol"].upper(), r["cik"], r.get("form"),
             r.get("filing_date"), r.get("report_date"), r.get("primary_doc"),
             r.get("url"), _now()) for r in (rows or [])]
    if not data:
        return
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO filings"
            " (accession, symbol, cik, form, filing_date, report_date, primary_doc, url, ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (accession) DO NOTHING", data)


def get_filings(symbol: str, forms: list[str] | None = None, limit: int = 20) -> list[dict]:
    """A symbol's filings, newest first. forms=None returns every form type
    ever ingested for it — since 2026-09-11 that includes the ownership
    forms (3/4/144), which for a large registrant arrive weekly, so the
    limit is what keeps a 10-Q on the page."""
    with _connect() as conn:
        if forms:
            ph = ",".join("?" * len(forms))
            rows = conn.execute(
                f"SELECT accession, symbol, cik, form, filing_date, report_date, primary_doc, url"
                f" FROM filings WHERE symbol=? AND form IN ({ph})"
                f" ORDER BY filing_date DESC LIMIT ?",
                (symbol.upper(), *forms, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT accession, symbol, cik, form, filing_date, report_date, primary_doc, url"
                " FROM filings WHERE symbol=? ORDER BY filing_date DESC LIMIT ?",
                (symbol.upper(), limit)).fetchall()
    return [dict(r) for r in rows]


def get_filing_meta(accession: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT accession, symbol, cik, form, filing_date, report_date, primary_doc, url"
            " FROM filings WHERE accession=?", (accession,)).fetchone()
    return dict(row) if row else None


def get_filing_text(accession: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT text FROM filing_text_cache WHERE accession=?", (accession,)).fetchone()
    return row["text"] if row else None


def save_filing_text(accession: str, text: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO filing_text_cache (accession, text, char_count, extracted_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT (accession) DO UPDATE SET text=excluded.text,"
            " char_count=excluded.char_count, extracted_at=excluded.extracted_at", (accession, text, len(text), _now()))


def create_user(user_id: str, email: str, password_hash: str) -> None:
    """A new account starts its free trial now (alphadesk/billing.py)."""
    from alphadesk import billing
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, created_at, trial_ends_at)"
            " VALUES (?,?,?,?,?)",
            (user_id, email.lower().strip(), password_hash, _now(), billing.trial_end_from_now()))


_ACCESS_COLS = ("trial_ends_at, plan_status, plan_provider, plan_customer_id,"
                " plan_subscription_id, plan_period_end")


def user_access_row(user_id: str) -> dict | None:
    """The facts access is decided from: email, disabled, trial, plan."""
    with _connect() as conn:
        row = conn.execute(
            f"SELECT user_id, email, disabled, {_ACCESS_COLS} FROM users WHERE user_id=?",
            (user_id,)).fetchone()
    return dict(row) if row else None


def admin_list_users() -> list[dict]:
    """Every account for the owner's admin page, newest first — never the
    password hash. Each carries the sign-in methods it has used."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT user_id, email, disabled, created_at, last_seen_at, {_ACCESS_COLS}"
            " FROM users ORDER BY created_at DESC").fetchall()
        methods = conn.execute("SELECT user_id, method FROM user_sign_ins").fetchall()
        # What each account holds, for the admin page's detail: one grouped
        # count per table rather than a query per account.
        counts: dict[str, dict[str, int]] = {}
        for kind, sql in (
            ("keys", "SELECT user_id, COUNT(*) AS n FROM user_api_keys GROUP BY user_id"),
            ("views", "SELECT user_id, COUNT(*) AS n FROM user_views GROUP BY user_id"),
            ("baskets", "SELECT user_id, COUNT(*) AS n FROM user_baskets GROUP BY user_id"),
            ("agent_tokens", "SELECT user_id, COUNT(*) AS n FROM agent_access_tokens"
                             " WHERE revoked_at IS NULL GROUP BY user_id"),
            ("agent_apps", "SELECT user_id, COUNT(*) AS n FROM oauth_grants"
                           " WHERE revoked_at IS NULL GROUP BY user_id"),
        ):
            for c in conn.execute(sql).fetchall():
                counts.setdefault(c["user_id"], {})[kind] = c["n"]
    by_user: dict[str, list[str]] = {}
    for m in methods:
        by_user.setdefault(m["user_id"], []).append(m["method"])
    out = []
    for r in rows:
        d = dict(r)
        d["sign_ins"] = sorted(by_user.get(d["user_id"], []))
        held = counts.get(d["user_id"], {})
        d["counts"] = {k: held.get(k, 0) for k in ("keys", "views", "baskets", "agent_tokens", "agent_apps")}
        out.append(d)
    return out


def set_user_disabled(user_id: str, disabled: bool) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE users SET disabled=? WHERE user_id=?", (1 if disabled else 0, user_id))
    return cur.rowcount > 0


def set_trial_end(user_id: str, iso: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE users SET trial_ends_at=? WHERE user_id=?", (iso, user_id))
    return cur.rowcount > 0


def set_plan(user_id: str, *, provider: str, status: str | None, customer_id: str | None = None,
             subscription_id: str | None = None, period_end: str | None = None) -> bool:
    """Record the subscription as the payment processor reported it."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET plan_provider=?, plan_status=?, plan_customer_id=COALESCE(?, plan_customer_id),"
            " plan_subscription_id=COALESCE(?, plan_subscription_id), plan_period_end=? WHERE user_id=?",
            (provider, status, customer_id, subscription_id, period_end, user_id))
    return cur.rowcount > 0


def user_by_plan_customer(provider: str, customer_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT user_id, email FROM users WHERE plan_provider=? AND plan_customer_id=?",
                           (provider, customer_id)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, email, password_hash, disabled, created_at, session_version"
            " FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    return dict(row) if row else None


def user_session_state(user_id: str) -> dict | None:
    """The two facts a presented cookie is re-validated against on every
    request: the row's current session_version and its disabled flag. None
    for a deleted account — which reads as signed out, exactly right."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT session_version, disabled FROM users WHERE user_id=?",
            (user_id,)).fetchone()
    return dict(row) if row else None


def bump_session_version(user_id: str) -> bool:
    """Invalidate EVERY outstanding session for one account — theirs is the
    'sign out everywhere' button, the operator's is revocation."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET session_version = session_version + 1 WHERE user_id=?",
            (user_id,))
    return cur.rowcount > 0


def list_users() -> list[dict]:
    """Everything EXCEPT the hash — a listing is for the operator's eyes and
    a hash in terminal scrollback is a hash leaked."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, email, disabled, created_at FROM users ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def set_user_password(email: str, password_hash: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE users SET password_hash=? WHERE email=?",
                           (password_hash, email.lower().strip()))
    return cur.rowcount > 0


def remove_user(email: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE email=?", (email.lower().strip(),))
    return cur.rowcount > 0


def set_user_key(user_id: str, seam: str, provider: str, config_sealed: str,
                 key_hint: str) -> None:
    """Store (or replace) one user's key for one seam+provider. `config_sealed`
    is the vault envelope — this function never sees plaintext. Keys
    ACCUMULATE across providers on every seam: the news feed merges every one,
    and no one market-data vendor carries every surface."""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, seam, provider, config, key_hint, created_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT (user_id, seam, provider) DO UPDATE SET"
            " config=excluded.config, key_hint=excluded.key_hint, created_at=excluded.created_at,"
            " last_used_at=NULL",
            (user_id, seam, provider, config_sealed, key_hint, _now()))


def get_user_key(user_id: str, seam: str) -> dict | None:
    """The full row, sealed config included — for the provider-construction
    path only. API handlers use list_user_keys, which never carries config."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, seam, provider, config, key_hint, created_at, last_used_at"
            " FROM user_api_keys WHERE user_id=? AND seam=?"
            " ORDER BY created_at DESC, provider LIMIT 1", (user_id, seam)).fetchone()
    return dict(row) if row else None


def get_user_keys(user_id: str, seam: str) -> list[dict]:
    """EVERY row for one seam, sealed config included — the multi-feed poll
    builds one provider per row."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, seam, provider, config, key_hint, created_at, last_used_at"
            " FROM user_api_keys WHERE user_id=? AND seam=? ORDER BY provider",
            (user_id, seam)).fetchall()
    return [dict(r) for r in rows]


def list_user_keys(user_id: str) -> list[dict]:
    """Everything EXCEPT the sealed config — same rule as list_users: what a
    listing carries is what ends up on screens and in scrollback."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT seam, provider, key_hint, created_at, last_used_at"
            " FROM user_api_keys WHERE user_id=? ORDER BY seam", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_user_key(user_id: str, seam: str, provider: str | None = None) -> bool:
    """Without `provider`, the whole seam goes (the llm route's semantics);
    with it, just that feed."""
    with _lock, _connect() as conn:
        if provider is None:
            cur = conn.execute("DELETE FROM user_api_keys WHERE user_id=? AND seam=?",
                               (user_id, seam))
        else:
            cur = conn.execute(
                "DELETE FROM user_api_keys WHERE user_id=? AND seam=? AND provider=?",
                (user_id, seam, provider))
    return cur.rowcount > 0


def touch_user_seen(user_id: str) -> None:
    """Stamp the user's last activity — the gate per-user polling runs on.
    Called throttled from the request middleware, so one active reader costs
    a handful of writes an hour, not one per request."""
    with _lock, _connect() as conn:
        conn.execute("UPDATE users SET last_seen_at=? WHERE user_id=?", (_now(), user_id))


def news_poll_users(active_hours: float = 48.0) -> list[str]:
    """Who gets their own feed polled this cycle: users with a vaulted news
    key, not disabled, seen within the activity window. The gate is the cost
    control the design demands — enrichment is the one unattended LLM call,
    and it must never spend a sleeping user's tokens."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=active_hours)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT u.user_id FROM users u"
            " JOIN user_api_keys k ON k.user_id = u.user_id AND k.seam = 'news'"
            " WHERE u.disabled = 0 AND u.last_seen_at IS NOT NULL AND u.last_seen_at >= ?"
            " ORDER BY u.user_id", (cutoff,)).fetchall()
    return [r["user_id"] for r in rows]


CALENDAR_VENDORS = ("fmp", "finnhub", "alphavantage")


def forecast_capture_users(active_hours: float = 168.0) -> list[str]:
    """Whose earnings calendar is captured today: users with a market-data key
    from a vendor that carries a calendar, not disabled, seen within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=active_hours)).isoformat()
    marks = ",".join("?" * len(CALENDAR_VENDORS))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT u.user_id FROM users u"
            f" JOIN user_api_keys k ON k.user_id = u.user_id AND k.seam = 'prices' AND k.provider IN ({marks})"
            " WHERE u.disabled = 0 AND u.last_seen_at IS NOT NULL AND u.last_seen_at >= ?"
            " ORDER BY u.user_id", (*CALENDAR_VENDORS, cutoff)).fetchall()
    return [r["user_id"] for r in rows]


def touch_user_key(user_id: str, seam: str) -> None:
    """Stamp last_used_at — the honest 'is this key actually serving' signal
    the Account page shows."""
    with _lock, _connect() as conn:
        conn.execute("UPDATE user_api_keys SET last_used_at=? WHERE user_id=? AND seam=?",
                     (_now(), user_id, seam))


def touch_user_key_provider(user_id: str, seam: str, provider: str) -> None:
    """The per-feed stamp — with several news keys, 'is this one serving'
    must be answerable per provider."""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE user_api_keys SET last_used_at=?"
            " WHERE user_id=? AND seam=? AND provider=?",
            (_now(), user_id, seam, provider))


def list_user_views(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT view_id, name, layout, position FROM user_views"
            " WHERE user_id=? ORDER BY position, view_id", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def upsert_user_view(user_id: str, view_id: str, name: str, layout: str,
                     position: int = 0) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_views (user_id, view_id, name, layout, position, updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT (user_id, view_id) DO UPDATE SET name=excluded.name,"
            " layout=excluded.layout, position=excluded.position, updated_at=excluded.updated_at",
            (user_id, view_id, name, layout, int(position), _now()))


def delete_user_view(user_id: str, view_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM user_views WHERE user_id=? AND view_id=?",
                           (user_id, view_id))
    return cur.rowcount > 0


def record_sign_in(user_id: str, method: str) -> None:
    """Stamp that `user_id` signed in with `method` (a provider id, or
    "password") — the first time and the latest."""
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_sign_ins (user_id, method, first_at, last_at) VALUES (?,?,?,?)"
            " ON CONFLICT (user_id, method) DO UPDATE SET last_at=excluded.last_at",
            (user_id, method, now, now))


def list_sign_ins(user_id: str) -> list[dict]:
    """The methods `user_id` has signed in with, latest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT method, first_at, last_at FROM user_sign_ins WHERE user_id=?"
            " ORDER BY last_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def list_user_baskets(user_id: str) -> list[dict]:
    """The reader's own baskets, by name — a stable order that does not move
    one when it is edited."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT basket_id, label, why, symbols FROM user_baskets"
            " WHERE user_id=? ORDER BY label, basket_id", (user_id,)).fetchall()
    out = []
    for r in rows:
        try:
            syms = [str(s) for s in json.loads(r["symbols"] or "[]")]
        except (ValueError, TypeError):
            syms = []
        out.append({"id": r["basket_id"], "label": r["label"], "why": r["why"] or None,
                    "symbols": syms, "mine": True})
    return out


def upsert_user_basket(user_id: str, basket_id: str, label: str, why: str,
                       symbols: list[str]) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_baskets (user_id, basket_id, label, why, symbols, updated_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT (user_id, basket_id) DO UPDATE SET label=excluded.label,"
            " why=excluded.why, symbols=excluded.symbols, updated_at=excluded.updated_at",
            (user_id, basket_id, label, why, json.dumps(symbols), _now()))


def delete_user_basket(user_id: str, basket_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM user_baskets WHERE user_id=? AND basket_id=?",
                           (user_id, basket_id))
    return cur.rowcount > 0


def save_board(user_id: str, symbols: list[str], active: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_boards (user_id, symbols, active, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT (user_id) DO UPDATE SET symbols=excluded.symbols, active=excluded.active,"
            " updated_at=excluded.updated_at",
            (user_id, json.dumps(symbols), active, _now()))


def get_board(user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT symbols, active, updated_at FROM user_boards WHERE user_id=?",
                           (user_id,)).fetchone()
    if not row:
        return None
    try:
        symbols = list(json.loads(row["symbols"]))
    except (TypeError, ValueError):
        symbols = []
    return {"symbols": symbols, "active": row["active"], "updated_at": row["updated_at"]}


def save_dollar_pool(owner: str, vendor: str, symbols: list[str], built_at: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO reader_dollar_pools (owner, vendor, symbols, built_at) VALUES (?,?,?,?)"
            " ON CONFLICT (owner, vendor) DO UPDATE SET symbols=excluded.symbols, built_at=excluded.built_at",
            (owner, vendor, json.dumps(symbols), int(built_at)))


def get_dollar_pool(owner: str, vendor: str) -> tuple[int, list[str]] | None:
    """(built_at, symbols) for this reader's saved pool, or None."""
    with _connect() as conn:
        row = conn.execute("SELECT symbols, built_at FROM reader_dollar_pools WHERE owner=? AND vendor=?",
                           (owner, vendor)).fetchone()
    if not row:
        return None
    try:
        return int(row["built_at"]), list(json.loads(row["symbols"]))
    except (TypeError, ValueError):
        return None


def create_agent_access_token(user_id: str, token_id: str, name: str, token_hash: str,
                              hint: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO agent_access_tokens (token_id, user_id, name, token_hash, hint, created_at)"
            " VALUES (?,?,?,?,?,?)", (token_id, user_id, name, token_hash, hint, _now()))


def list_agent_access_tokens(user_id: str) -> list[dict]:
    """A reader's live tokens, newest first. Never carries the hash."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT token_id, name, hint, created_at, last_used_at FROM agent_access_tokens"
            " WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC, token_id",
            (user_id,)).fetchall()
    return [dict(r) for r in rows]


def agent_access_token_by_hash(token_hash: str) -> dict | None:
    """The live token with this hash, or None (unknown or revoked)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT token_id, user_id, last_used_at FROM agent_access_tokens"
            " WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)).fetchone()
    return dict(row) if row else None


def touch_agent_access_token(token_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE agent_access_tokens SET last_used_at=? WHERE token_id=?",
                     (_now(), token_id))


def revoke_agent_access_token(user_id: str, token_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE agent_access_tokens SET revoked_at=? WHERE user_id=? AND token_id=?"
            " AND revoked_at IS NULL", (_now(), user_id, token_id))
    return cur.rowcount > 0


def save_oauth_client(client_id: str, info_sealed: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("INSERT INTO oauth_clients (client_id, info, created_at) VALUES (?,?,?)",
                     (client_id, info_sealed, _now()))


def get_oauth_client(client_id: str) -> str | None:
    """The sealed client record, or None."""
    with _connect() as conn:
        row = conn.execute("SELECT info FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
    return row["info"] if row else None


def save_oauth_code(code_hash: str, client_id: str, user_id: str, payload: str,
                    expires_at: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO oauth_codes (code_hash, client_id, user_id, payload, expires_at)"
            " VALUES (?,?,?,?,?)", (code_hash, client_id, user_id, payload, expires_at))


def get_oauth_code(code_hash: str) -> dict | None:
    """An unused code's row (expired ones included; the caller checks)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT code_hash, client_id, user_id, payload, expires_at FROM oauth_codes"
            " WHERE code_hash=? AND used=0", (code_hash,)).fetchone()
    return dict(row) if row else None


def spend_oauth_code(code_hash: str) -> bool:
    """Mark a code used. True for exactly one caller, however many race."""
    with _lock, _connect() as conn:
        cur = conn.execute("UPDATE oauth_codes SET used=1 WHERE code_hash=? AND used=0", (code_hash,))
    return cur.rowcount == 1


def create_oauth_grant(grant: dict) -> None:
    cols = ("grant_id", "user_id", "client_id", "client_name", "scopes", "resource",
            "access_hash", "access_expires", "refresh_hash", "refresh_expires")
    with _lock, _connect() as conn:
        conn.execute(
            f"INSERT INTO oauth_grants ({', '.join(cols)}, created_at) VALUES ({','.join('?' * len(cols))},?)",
            (*(grant[c] for c in cols), _now()))


def oauth_grant_by(column: str, token_hash: str) -> dict | None:
    """A live grant by its access or refresh hash."""
    if column not in ("access_hash", "refresh_hash"):
        raise ValueError(column)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT grant_id, user_id, client_id, client_name, scopes, resource, access_expires,"
            f" refresh_expires, last_used_at FROM oauth_grants WHERE {column}=? AND revoked_at IS NULL",
            (token_hash,)).fetchone()
    return dict(row) if row else None


def rotate_oauth_grant(grant_id: str, old_refresh_hash: str, access_hash: str, access_expires: int,
                       refresh_hash: str, refresh_expires: int) -> bool:
    """Swap in new tokens, only if the refresh token presented is still the
    current one — a replayed refresh token rotates nothing."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE oauth_grants SET access_hash=?, access_expires=?, refresh_hash=?, refresh_expires=?"
            " WHERE grant_id=? AND refresh_hash=? AND revoked_at IS NULL",
            (access_hash, access_expires, refresh_hash, refresh_expires, grant_id, old_refresh_hash))
    return cur.rowcount == 1


def touch_oauth_grant(grant_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE oauth_grants SET last_used_at=? WHERE grant_id=?", (_now(), grant_id))


def prune_oauth(now_s: int, client_idle_s: int = 7 * 24 * 3600) -> int:
    """Drop what can never be used again: codes a day past expiry, and client
    registrations older than `client_idle_s` that never got a grant (an app
    that registered and was never allowed in). Returns rows removed."""
    cutoff = datetime.fromtimestamp(now_s - client_idle_s, timezone.utc).isoformat()
    with _lock, _connect() as conn:
        codes = conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (now_s - 86_400,)).rowcount
        clients = conn.execute(
            "DELETE FROM oauth_clients WHERE created_at < ? AND client_id NOT IN"
            " (SELECT client_id FROM oauth_grants)", (cutoff,)).rowcount
    return max(0, codes) + max(0, clients)


def list_oauth_grants(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT grant_id, client_name, created_at, last_used_at FROM oauth_grants"
            " WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC, grant_id",
            (user_id,)).fetchall()
    return [dict(r) for r in rows]


def supersede_oauth_grants(user_id: str, client_id: str, keep_grant_id: str) -> int:
    """Revoke this reader's earlier live grants to the SAME registered app
    (2026-09-17). A grant is created on every completed consent and nothing
    collapsed them, so re-allowing an app already connected left the old
    grant live beside the new one — four "Claude" rows came from four
    approvals in one afternoon of connector testing, each still holding a
    90-day refresh token. The app just re-consented, so the grant it replaced
    can only be a leftover. Returns the number revoked.

    This matches on the CLIENT ID, which is the same app registration
    consenting twice. It cannot merge rows from an app that registers afresh
    each time it is added (Claude.ai does): to the server those are different
    clients, and the Account page groups them by name instead."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE oauth_grants SET revoked_at=?"
            " WHERE user_id=? AND client_id=? AND grant_id<>? AND revoked_at IS NULL",
            (_now(), user_id, client_id, keep_grant_id))
    return max(0, cur.rowcount)


def revoke_oauth_grant(grant_id: str, user_id: str | None = None) -> bool:
    sql = "UPDATE oauth_grants SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL"
    args: tuple = (_now(), grant_id)
    if user_id is not None:
        sql += " AND user_id=?"
        args += (user_id,)
    with _lock, _connect() as conn:
        cur = conn.execute(sql, args)
    return cur.rowcount > 0


def get_chart_state(user_id: str, key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT state FROM user_chart_state WHERE user_id=? AND key=?",
                           (user_id, key)).fetchone()
    return row["state"] if row else None


def set_chart_state(user_id: str, key: str, state: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_chart_state (user_id, key, state, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT (user_id, key) DO UPDATE SET state=excluded.state,"
            " updated_at=excluded.updated_at",
            (user_id, key, state, _now()))


def delete_chart_state(user_id: str, key: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM user_chart_state WHERE user_id=? AND key=?",
                           (user_id, key))
    return cur.rowcount > 0


def upsert_release(symbol: str, accession: str, cik: str | None, file_date: str,
                   accepted_at: str | None, company: str | None, event_date: str | None = None,
                   accepted_source: str | None = None, form: str | None = None) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO earnings_releases (symbol, accession, cik, file_date, accepted_at, company, event_date, accepted_source, form)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (symbol, accession) DO UPDATE SET"
            " accepted_at=COALESCE(excluded.accepted_at, earnings_releases.accepted_at),"
            " company=COALESCE(excluded.company, earnings_releases.company),"
            " event_date=COALESCE(excluded.event_date, earnings_releases.event_date),"
            " accepted_source=COALESCE(excluded.accepted_source, earnings_releases.accepted_source),"
            " form=COALESCE(excluded.form, earnings_releases.form)",
            (symbol.upper(), accession, cik, file_date, accepted_at, company, event_date, accepted_source, form))


def save_announcements(owner: str, rows: list[dict]) -> int:
    vals = [(owner, r["symbol"].upper(), r["url"], r["published_at"], r["report_date"], r.get("session"),
             r.get("basis"), r.get("source"), (r.get("sentence") or "")[:300]) for r in rows if r.get("url")]
    if not vals:
        return 0
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO earnings_announcements (owner, symbol, url, published_at, report_date, session, basis, source, sentence)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (owner, symbol, url) DO UPDATE SET report_date=excluded.report_date, session=excluded.session,"
            " basis=excluded.basis, sentence=excluded.sentence", vals)
    return len(vals)


def replace_announcements(owner: str, symbols: list[str], rows: list[dict]) -> int:
    """The announcements these companies have now, replacing what they had.

    Rows written by an earlier, looser reader are otherwise permanent: the
    press-release check re-reads every company within hours, so the table
    should say what the current reader makes of them (2026-09-15)."""
    syms = sorted({s.upper() for s in symbols})
    with _lock, _connect() as conn:
        for i in range(0, len(syms), 200):
            chunk = syms[i:i + 200]
            conn.execute(f"DELETE FROM earnings_announcements WHERE owner = ?"
                         f" AND symbol IN ({','.join('?' * len(chunk))})", [owner, *chunk])
    return save_announcements(owner, rows)


def save_release_habits(owner: str, habits: dict[str, tuple[str | None, int | None]], computed_at: str) -> int:
    """Each company's usual release session as computed now, replacing the last."""
    vals = [(owner, sym.upper(), computed_at, h[0], h[1]) for sym, h in habits.items()]
    if not vals:
        return 0
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO release_habits (owner, symbol, computed_at, session, basis) VALUES (?,?,?,?,?)"
            " ON CONFLICT (owner, symbol) DO UPDATE SET computed_at=excluded.computed_at, session=excluded.session,"
            " basis=excluded.basis", vals)
    return len(vals)


def release_habits(owner: str, symbols: list[str], since: str) -> dict[str, tuple[str | None, int]]:
    """The reader's stored habits for `symbols` computed at or after `since`."""
    out: dict[str, tuple[str | None, int]] = {}
    syms = sorted({s.upper() for s in symbols})
    with _connect() as conn:
        for i in range(0, len(syms), 200):
            chunk = syms[i:i + 200]
            for r in conn.execute(
                    f"SELECT symbol, session, basis FROM release_habits WHERE owner = ? AND computed_at >= ?"
                    f" AND symbol IN ({','.join('?' * len(chunk))})", [owner, since, *chunk]).fetchall():
                out[r["symbol"]] = (r["session"], r["basis"] or 0)
    return out


def mark_press_releases_checked(owner: str, symbols: list[str], checked_at: str) -> None:
    vals = [(owner, s.upper(), checked_at) for s in symbols]
    if not vals:
        return
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO press_release_checks (owner, symbol, checked_at) VALUES (?,?,?)"
            " ON CONFLICT (owner, symbol) DO UPDATE SET checked_at=excluded.checked_at", vals)


def press_releases_checked_since(owner: str, symbols: list[str], since: str) -> set[str]:
    """The symbols whose press releases were read for this reader at or after `since`."""
    syms = sorted({s.upper() for s in symbols})
    out: set[str] = set()
    with _connect() as conn:
        for i in range(0, len(syms), 200):
            chunk = syms[i:i + 200]
            out |= {r["symbol"] for r in conn.execute(
                f"SELECT symbol FROM press_release_checks WHERE owner = ? AND checked_at >= ?"
                f" AND symbol IN ({','.join('?' * len(chunk))})", [owner, since, *chunk]).fetchall()}
    return out


def announcements_between(owner: str, start: str, end: str) -> list[dict]:
    """A reader's stored announcements for reports dated in [start, end], newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol, url, published_at, report_date, session, basis, source, sentence FROM earnings_announcements"
            " WHERE owner = ? AND report_date >= ? AND report_date <= ? ORDER BY published_at DESC",
            (owner, start, end)).fetchall()
    return [dict(r) for r in rows]


def save_forecasts(owner: str, vendor: str, captured_on: str, rows: list[dict]) -> int:
    """One vendor's upcoming reports as seen on `captured_on`. A later sighting
    the same day replaces the earlier one (the vendor's latest word that day)."""
    vals = [(owner, vendor, r["symbol"], captured_on, r["report_date"][:10], r.get("session"),
             1 if r.get("confirmed") else 0) for r in rows]
    if not vals:
        return 0
    with _lock, _connect() as conn:
        conn.executemany(
            "INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date, session, confirmed)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT (owner, vendor, symbol, captured_on) DO UPDATE SET"
            " report_date=excluded.report_date, session=excluded.session, confirmed=excluded.confirmed", vals)
    return len(vals)


def forecasts_for(owner: str, report_from: str, report_to: str) -> list[dict]:
    """Every capture of a reader's vendors for reports dated within a span
    wide enough to include dates that later moved."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT vendor, symbol, captured_on, report_date, session, confirmed FROM earnings_forecasts"
            " WHERE owner = ? AND report_date >= ? AND report_date <= ?", (owner, report_from, report_to)).fetchall()
    return [dict(r) for r in rows]


def forecast_capture_days(owner: str) -> dict[str, list[str]]:
    """The days each vendor was captured for a reader, sorted."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT vendor, captured_on FROM earnings_forecasts WHERE owner = ?", (owner,)).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        d = dict(r)
        out.setdefault(d["vendor"], []).append(d["captured_on"])
    return {k: sorted(v) for k, v in out.items()}


def releases_between(start: str, end: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol, accession, cik, file_date, accepted_at, company, event_date, form FROM earnings_releases"
            " WHERE file_date >= ? AND file_date <= ? ORDER BY file_date, symbol", (start, end)).fetchall()
    return [dict(r) for r in rows]


def set_release_clock(symbol: str, accession: str, accepted_at: str | None, source: str | None) -> None:
    """Replace a release's acceptance instant — unlike upsert_release, which
    never overwrites a known one — and record where it was read."""
    with _lock, _connect() as conn:
        conn.execute("UPDATE earnings_releases SET accepted_at = ?, accepted_source = ? WHERE symbol = ? AND accession = ?",
                     (accepted_at, source, symbol.upper(), accession))


def releases_missing_time(since: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol, accession, cik, file_date, form FROM earnings_releases"
            " WHERE (accepted_at IS NULL OR event_date IS NULL OR accepted_source IS NULL) AND file_date >= ?",
            (since,)).fetchall()
    return [dict(r) for r in rows]


def news_health(owner: str = "") -> dict:
    """Is the news pipeline alive for `owner`? Their last article ingested,
    how many today, and today's AI spend — the one thing here that runs
    unattended and can fail silently (a dead feed or a dead model endpoint).

    Per reader (2026-09-15). It read the shared feed's rows (owner ''), which
    stopped arriving when that feed was removed on 2026-09-13, so the header's
    "News · 41h ago" stayed amber for every reader while their own feeds were
    current."""
    with _connect() as conn:
        last_at = conn.execute(
            "SELECT max(ingested_at) AS m FROM news_articles WHERE owner = ?", (owner,)).fetchone()["m"]
        today = int(conn.execute(
            "SELECT count(*) AS n FROM news_articles WHERE owner = ? AND ingested_at >= ?",
            (owner, _et_day_start_utc())).fetchone()["n"])
    return {"last_article_at": last_at, "articles_today": today}


init()


def prune_vendor_data(now: datetime | None = None) -> dict[str, int]:
    """Delete each reader's vendor data once no feature reads it
    (2026-09-18, the owner's "store less"). The retention for each kind is in
    config.py; the rule is that a vendor's data is held only as long as the
    feature it serves needs it, never as an archive. Returns rows touched
    per kind, for the log. Idempotent and cheap: run hourly and on start.

    Also clears the old Nasdaq `earnings` table, which no code reads since
    the unofficial sources were removed (2026-09-13)."""
    from alphadesk import config as cfg
    now = now or datetime.now(timezone.utc)

    def ago(**kw) -> str:
        return (now - timedelta(**kw)).isoformat()

    day = now.date()
    out: dict[str, int] = {}
    with _lock, _connect() as conn:
        def run(kind: str, sql: str, args: tuple = ()) -> None:
            out[kind] = conn.execute(sql, args).rowcount or 0

        # Older than the keep window, and not fetched in the last day (a
        # story fetched for an older page gets a day from its fetch, so a
        # reader paging back does not lose it mid-scroll).
        run("news", "DELETE FROM news_articles WHERE published_at < ?"
            " AND (ingested_at IS NULL OR ingested_at < ?)",
            (ago(days=cfg.NEWS_KEEP_DAYS), ago(hours=cfg.NEWS_OLDER_PAGE_KEEP_HOURS)))
        run("news_bodies", "UPDATE news_articles SET body=NULL"
            " WHERE body IS NOT NULL AND published_at < ?", (ago(hours=cfg.NEWS_BODY_KEEP_HOURS),))
        run("announcements", "DELETE FROM earnings_announcements WHERE report_date < ?",
            ((day - timedelta(days=cfg.ANNOUNCEMENT_KEEP_DAYS)).isoformat(),))
        run("forecasts", "DELETE FROM earnings_forecasts WHERE report_date < ?",
            ((day - timedelta(days=cfg.FORECAST_KEEP_DAYS)).isoformat(),))
        run("release_habits", "DELETE FROM release_habits WHERE computed_at < ?",
            (ago(days=cfg.HABIT_KEEP_DAYS),))
        run("press_checks", "DELETE FROM press_release_checks WHERE checked_at < ?",
            (ago(hours=cfg.PRESS_CHECK_KEEP_HOURS),))
        run("dollar_pools", "DELETE FROM reader_dollar_pools WHERE built_at < ?",
            (int((now - timedelta(days=cfg.POOL_KEEP_DAYS)).timestamp()),))
        run("nasdaq_earnings", "DELETE FROM earnings")
        run("news_vectors", _ORPHAN_VECTORS)
    return out


#: A story's vector is deleted with the story, whatever deleted it.
_ORPHAN_VECTORS = ("DELETE FROM news_vectors WHERE NOT EXISTS (SELECT 1 FROM news_articles a"
                   " WHERE a.owner = news_vectors.owner AND a.article_id = news_vectors.article_id)")


def note_warm_path(user_id: str, path: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM warm_paths WHERE user_id=? AND path=?", (user_id, path))
        conn.execute("INSERT INTO warm_paths (user_id, path, last_used_at) VALUES (?,?,?)",
                     (user_id, path[:600], datetime.now(timezone.utc).isoformat()))


def warm_paths(user_id: str, since_iso: str) -> list[dict]:
    """The owner's kept requests used since `since_iso`; older ones are
    deleted on the way."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM warm_paths WHERE user_id=? AND last_used_at < ?", (user_id, since_iso))
        rows = conn.execute("SELECT path, last_used_at FROM warm_paths WHERE user_id=?", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def active_users(active_hours: float) -> list[dict]:
    """(user_id, email) of accounts not disabled and seen within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=active_hours)).isoformat()
    with _connect() as conn:
        rows = conn.execute("SELECT user_id, email FROM users WHERE disabled = 0"
                            " AND last_seen_at IS NOT NULL AND last_seen_at >= ?", (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def get_annual_report_sections(accession: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM annual_report_sections WHERE accession=?", (accession,)).fetchone()
    return json.loads(row["payload"]) if row else None


def save_annual_report_sections(accession: str, payload: dict) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM annual_report_sections WHERE accession=?", (accession,))
        conn.execute("INSERT INTO annual_report_sections (accession, payload, extracted_at) VALUES (?,?,?)",
                     (accession, json.dumps(payload), datetime.now(timezone.utc).isoformat()))


def unembedded_articles(model: str, limit: int = 64) -> list[dict]:
    """Stored stories with no vector from `model` yet, newest first, across
    owners — the embedding worker's queue."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT a.owner, a.article_id, a.title, a.summary FROM news_articles a"
            " LEFT JOIN news_vectors v ON v.owner = a.owner AND v.article_id = a.article_id AND v.model = ?"
            " WHERE v.article_id IS NULL AND a.owner != '' ORDER BY a.published_at DESC LIMIT ?",
            (model, int(limit))).fetchall()
    return [dict(r) for r in rows]



# ── what a fund's name says it is (fundclass.py) ────────────────────────────

def queue_fund_names(names: list[str], verdict: str | None = None, model: str | None = None) -> None:
    """Remember fund names to classify. With `verdict` the answer is already
    known — ticker-matched funds are single-stock by construction, and they
    are what the classifier learns from."""
    if not names:
        return
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        for name in names:
            if not name:
                continue
            if verdict is None:
                conn.execute("INSERT INTO fund_name_verdicts (name, verdict, margin, model, updated_at)"
                             " VALUES (?,NULL,NULL,NULL,?) ON CONFLICT (name) DO NOTHING", (name, now))
            else:
                conn.execute("INSERT INTO fund_name_verdicts (name, verdict, margin, model, updated_at)"
                             " VALUES (?,?,NULL,?,?) ON CONFLICT (name) DO UPDATE SET"
                             " verdict=excluded.verdict, model=excluded.model, updated_at=excluded.updated_at",
                             (name, verdict, model, now))


def fund_verdicts(names: list[str]) -> dict[str, str]:
    """{name: verdict} for the names that have one."""
    if not names:
        return {}
    out: dict[str, str] = {}
    with _connect() as conn:
        for chunk in (names[i:i + 400] for i in range(0, len(names), 400)):
            marks = ",".join("?" for _ in chunk)
            rows = conn.execute(f"SELECT name, verdict FROM fund_name_verdicts"
                                f" WHERE verdict IS NOT NULL AND name IN ({marks})", tuple(chunk)).fetchall()
            out.update({r["name"]: r["verdict"] for r in rows})
    return out


def pending_fund_names(limit: int = 32, grace_s: float = 0.0) -> list[str]:
    """Fund names waiting for a verdict, oldest first. With `grace_s`, a name
    whose own record has not been read yet is left alone until that long has
    passed — the vendor's description gets first refusal, and only then does
    the name decide (2026-09-20). A name already read is returned at once."""
    if grace_s <= 0:
        with _connect() as conn:
            rows = conn.execute("SELECT name FROM fund_name_verdicts WHERE verdict IS NULL"
                                " ORDER BY updated_at LIMIT ?", (int(limit),)).fetchall()
        return [r["name"] for r in rows]
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=grace_s)).isoformat()
    with _connect() as conn:
        rows = conn.execute("SELECT name FROM fund_name_verdicts WHERE verdict IS NULL"
                            " AND (model = 'description' OR updated_at < ?)"
                            " ORDER BY updated_at LIMIT ?", (cutoff, int(limit))).fetchall()
    return [r["name"] for r in rows]


def mark_fund_records_read(names: list[str]) -> None:
    """Note that a fund's own record was read and said neither thing, so the
    name classifier may take it without waiting out its grace."""
    if not names:
        return
    with _lock, _connect() as conn:
        for name in names:
            conn.execute("UPDATE fund_name_verdicts SET model='description'"
                         " WHERE name=? AND verdict IS NULL", (name,))


def fund_examples(verdict: str, limit: int = 200, model: str | None = None) -> list[tuple[str, str | None]]:
    """(name, vec) for the names settled as `verdict`, newest first. A name
    whose numbers were never kept — or were kept by a different model than
    `model`, whose numbers mean nothing here — comes back with None, and is
    read once."""
    with _connect() as conn:
        rows = conn.execute("SELECT name, vec, model FROM fund_name_verdicts WHERE verdict = ?"
                            " ORDER BY updated_at DESC LIMIT ?", (verdict, int(limit))).fetchall()
    return [(r["name"], r["vec"] if model is None or r["model"] == model else None) for r in rows]


def save_fund_vectors(model: str, rows: list[tuple[str, str]]) -> None:
    """(name, vec) for names already in the table — what makes a reference
    point arithmetic rather than a re-reading."""
    if not rows:
        return
    with _lock, _connect() as conn:
        for name, vec in rows:
            conn.execute("UPDATE fund_name_verdicts SET vec=?, model=? WHERE name=?", (vec, model, name))


def save_fund_verdicts(model: str, rows: list[tuple[str, str, float, str | None]]) -> None:
    """(name, verdict, margin, vec) from the classifier. The vector is kept
    with the verdict, so a name that later joins the known set costs nothing
    to include."""
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        for name, verdict, margin, vec in rows:
            conn.execute("INSERT INTO fund_name_verdicts (name, verdict, margin, model, vec, updated_at)"
                         " VALUES (?,?,?,?,?,?) ON CONFLICT (name) DO UPDATE SET verdict=excluded.verdict,"
                         " margin=excluded.margin, model=excluded.model, vec=excluded.vec,"
                         " updated_at=excluded.updated_at",
                         (name, verdict, float(margin), model, vec, now))


def save_news_vectors(model: str, rows: list[tuple[str, str, str]]) -> None:
    """(owner, article_id, vec) rows, replacing any earlier vector."""
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        for owner, aid, vec in rows:
            conn.execute("DELETE FROM news_vectors WHERE owner=? AND article_id=?", (owner, aid))
            conn.execute("INSERT INTO news_vectors (owner, article_id, model, vec, embedded_at) VALUES (?,?,?,?,?)",
                         (owner, aid, model, vec, now))


def news_vectors_since(owner: str, model: str, since_iso: str) -> list[dict]:
    """`owner`'s vectors from `model` embedded after `since_iso`, with each
    story's publication time — the search cache's increment."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT v.article_id, v.vec, v.embedded_at, a.published_at FROM news_vectors v"
            " JOIN news_articles a ON a.owner = v.owner AND a.article_id = v.article_id"
            " WHERE v.owner=? AND v.model=? AND v.embedded_at > ? ORDER BY v.embedded_at",
            (owner, model, since_iso)).fetchall()
    return [dict(r) for r in rows]


def articles_by_ids(owner: str, ids: list[str]) -> list[dict]:
    """`owner`'s stories by id, in recent_articles' shape, newest first."""
    if not ids:
        return []
    out: list[dict] = []
    with _connect() as conn:
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                "SELECT article_id, title, summary, source, url, published_at, tickers, image_url, author, body, feeds"
                f" FROM news_articles WHERE owner=? AND article_id IN ({marks})", [owner, *chunk]).fetchall()
            for r in rows:
                d = dict(r)
                d["tickers"] = sorted({str(t).upper() for t in json.loads(d.get("tickers") or "[]")})
                d["title"], d["summary"] = unescape(d.get("title") or ""), unescape(d.get("summary") or "")
                d["feeds"] = _feed_list(d.get("feeds"))
                out.append(d)
    out.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    return out


def purge_vendor_data(owner: str, seam: str, provider: str | None = None) -> dict[str, int]:
    """Delete what one reader's key for a vendor fetched, when that key is
    removed (2026-09-18). FMP, Massive (Polygon) and Finnhub require their
    data deleted when the customer's access ends; removing the key is the
    point AlphaDesk can see that happen. `provider` None means every vendor
    on the seam.

    News: a story only this feed delivered is deleted; one another of the
    reader's feeds also delivered keeps its row, without this feed's name.
    Market data: the forecast log and the dollar-volume pool are per vendor.
    """
    out = {"news": 0, "forecasts": 0, "dollar_pools": 0}
    with _lock, _connect() as conn:
        if seam == "news":
            rows = conn.execute("SELECT article_id, feeds FROM news_articles WHERE owner=?"
                                " AND feeds IS NOT NULL", (owner,)).fetchall()
            for r in rows:
                feeds = [f for f in (r["feeds"] or "").split(",") if f]
                if provider is not None and provider not in feeds:
                    continue
                keep = [f for f in feeds if provider is not None and f != provider]
                if keep:
                    conn.execute("UPDATE news_articles SET feeds=? WHERE owner=? AND article_id=?",
                                 (",".join(keep), owner, r["article_id"]))
                else:
                    conn.execute("DELETE FROM news_articles WHERE owner=? AND article_id=?",
                                 (owner, r["article_id"]))
                    out["news"] += 1
            conn.execute(_ORPHAN_VECTORS)
        elif seam == "prices":
            if provider is None:
                out["forecasts"] = conn.execute("DELETE FROM earnings_forecasts WHERE owner=?", (owner,)).rowcount or 0
                out["dollar_pools"] = conn.execute("DELETE FROM reader_dollar_pools WHERE owner=?", (owner,)).rowcount or 0
            else:
                out["forecasts"] = conn.execute("DELETE FROM earnings_forecasts WHERE owner=? AND vendor=?",
                                                (owner, provider)).rowcount or 0
                out["dollar_pools"] = conn.execute("DELETE FROM reader_dollar_pools WHERE owner=? AND vendor=?",
                                                   (owner, provider)).rowcount or 0
    return out


# Every table that holds one account's rows, keyed by `user_id` or, for the
# reader's vendor data, by `owner` (the reader's id). delete_account() empties
# each, children before the account row (the user_id tables reference users).
# A new per-account table MUST be added here, or deletion leaves it behind —
# tests/test_accounts.py checks the schema against this list.
_ACCOUNT_TABLES_BY_USER = ("user_sign_ins", "user_api_keys", "user_views", "user_baskets",
                           "user_boards", "agent_access_tokens", "oauth_codes", "oauth_grants",
                           "user_chart_state", "warm_paths")
_ACCOUNT_TABLES_BY_OWNER = ("news_articles", "news_vectors", "earnings_announcements", "release_habits",
                            "press_release_checks", "earnings_forecasts", "reader_dollar_pools")


def delete_account(user_id: str) -> dict[str, int] | None:
    """Delete an account and EVERYTHING it holds (2026-09-18): its keys,
    views, baskets, board, chart settings, sign-in records, agent tokens and
    connections, and the vendor data fetched for it. One transaction, so a
    failure leaves the account whole rather than half-deleted. None when no
    such account exists. The Privacy Policy promises this on request."""
    with _lock, _connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            return None
        out: dict[str, int] = {}
        for table in _ACCOUNT_TABLES_BY_OWNER:
            out[table] = conn.execute(f"DELETE FROM {table} WHERE owner=?", (user_id,)).rowcount or 0
        for table in _ACCOUNT_TABLES_BY_USER:
            out[table] = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,)).rowcount or 0
        out["users"] = conn.execute("DELETE FROM users WHERE user_id=?", (user_id,)).rowcount or 0
    return out
