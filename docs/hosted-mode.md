# Accounts, sign-in and keys

How the hosted service identifies readers, keeps their keys, and keeps each
reader's data separate. The history of how the design arrived here is at
the end of this page.

## Sign-in

- **Sign-in is compulsory by default.** An instance is gated unless
  `ALPHADESK_AUTH=off` is set deliberately (development: one local account,
  no sign-in). Only `/api` data routes are gated; the page shell and static
  files stay open, so a deep link can load the landing page.
- **One user, one login, no sign-up.** The only door is the email and
  password the operator sets in the settings: `ALPHADESK_LOGIN_EMAIL` with
  `ALPHADESK_LOGIN_PASSWORD_HASH` (make the hash with
  `python -m alphadesk.main hash-password`; `ALPHADESK_LOGIN_PASSWORD`, 12 or
  more characters, also works but is readable to anyone who can read the
  settings). At start the account is made — or, if that email already has an
  account, it is given the password and keeps its data. Any other account is
  refused, along with its sessions and agent tokens. With sign-in on and no
  login set the server will not start. Google, GitHub and Microsoft sign-in
  were removed on 2026-10-03.
- **The email address is the account key.** The identifier is an email, not a
  free-form username.
- **`ALPHADESK_BASE_URL` is required behind a proxy**: the app cannot infer
  HTTPS (agent connections depend on it).

  Passwords are hashed with scrypt (n=2^14, r=8, p=1, 32-byte salt),
  verified in constant time, at least 10 characters, and prompted, never
  passed as arguments. Five failures for one email lock sign-in for that
  account for 60 seconds, and a failure never distinguishes an unknown email
  from a wrong password.

## Sessions

- HMAC-SHA256-signed cookies (HttpOnly, SameSite; set
  `ALPHADESK_COOKIE_SECURE=1` behind HTTPS), 14-day lifetime. The signing
  secret comes from `ALPHADESK_SECRET`, or a generated file (mode 0600) in the
  data directory.
- Every cookie carries the account's **session version**, re-checked on each
  request (cached about 30 seconds). "Sign out everywhere" on the Account
  page, `user revoke`, and disabling or deleting an account all end live
  sessions within that window, not at the 14-day expiry.

## The key vault

- Every reader's vendor keys (market data, news, transcripts) are sealed
  with **AES-256-GCM** under `ALPHADESK_VAULT_KEY` (32 bytes, base64,
  required — never generated silently, because losing it makes every stored
  key unreadable). Each row is a whole config object encrypted under a fresh
  96-bit nonce and stored as `nonce || ciphertext || tag`, base64.
- Keys are entered on the Account page over HTTPS. The API returns only a
  four-character hint, never the key. A decrypted key exists in memory only
  while a provider is built, and never appears in an error, a log line or a
  response — with one deliberate exception: the reader's own **Export keys**
  download (2026-10-02), which hands the keys back as a plain-text file
  (2026-10-02; a passphrase sent to the route still seals it). It answers only to the reader's browser session (never an agent
  token or OAuth grant), requires a sign-in within the last ten minutes, is
  limited to five an hour, and is logged by count only.
- **The server holds no vendor keys of its own.** Market data accumulates:
  a reader may connect several vendors, and a per-reader router asks them in
  the catalogue's order for each panel. A panel none of them carries answers
  HTTP 428 with a prompt naming the vendors and plans that would.
- **Removing a key deletes what it fetched**, as FMP, Massive (Polygon) and
  Finnhub require when access ends.

## Keeping readers apart

- The signed-in reader rides a request-scoped context variable; every keyed
  surface resolves vendors and cache ownership from it. A background thread
  does not inherit it, deliberately, and work started for a reader carries
  that reader's identity across explicitly.
- News stories are stored **per reader** (the rows their own feeds fetched)
  and polled only for readers seen within `NEWS_USER_ACTIVE_HOURS` (48); a
  reader who stops visiting costs nothing and is released on the next cycle.
  Several feeds merge into one window per reader, never across readers.
- Every cache that holds vendor data is keyed by the reader (and, for movers,
  by the vendors they connected). The Treasury yield curve is the one shared
  entry; EDGAR data is public and shared.
- Alpaca allows one market-data connection per account, so each reader's
  live stream holds its own connection.

## Agent access

Readers connect their own agent to the read-only tools at
`/api/agent/tools/mcp`; every call runs as exactly that reader, rate-limited
to 120 requests a minute per credential. Two credentials exist:

- **Tokens** created on the Agent access page (beside Account) for Claude Code, Codex, Cursor and
  opencode: shown once, stored as SHA-256, at most 10 live, revoked at once.
- **OAuth 2.1** for connector apps that add a server by URL (Claude.ai,
  ChatGPT): registration, PKCE, refresh and revoke, with clients sealed and
  codes and tokens stored as hashes; a single-use 5-minute code, one-hour
  access tokens, 90-day rotating refresh tokens, and one live grant per
  registered app. The consent page is signed, same-site checked and
  unframeable.

The standalone agent server (`python -m alphadesk.main mcp`) has no reader
identity and is not gated: never expose its HTTP transport publicly.

## Owners and access

- `ALPHADESK_OWNER_EMAILS` names the owner accounts: they reach the Admin
  page (every account, last seen, sign-in methods; sign out everywhere,
  disable, delete), are never gated, and have their own panels kept warm
  (the server replays their recent read requests in the background while
  they are active).
- AlphaDesk is **free**. Every account records a trial, but the access gate
  (`ALPHADESK_BILLING_ENFORCE`) is off and no payment processor is
  configured, so no plan or subscription screen is shown.

## Retention and deletion

Vendor data is kept only as long as a feature reads it, pruned hourly
(stories 7 days, article text 72 hours, and so on — the full table is in
[data-sources.md](data-sources.md)). A reader can delete their own account
from the Account page, confirmed by typing its email; every row keyed to it
is removed in one transaction, and the test suite checks the list of
per-account tables against the schema. Owners cannot delete their own
account (it would lock the operator out).

## Storage

`ledger/db.py` routes the store to **Postgres** when `ALPHADESK_DATABASE_URL`
(or `DATABASE_URL`) is a `postgres://` string — production uses Cloud SQL,
whose unix socket rides a `?host=/cloudsql/…` parameter — and to SQLite in
the data directory otherwise. The SQL is written in the dialect both share;
the driver is `pg8000` (pure Python, BSD). On start the store drops tables
retired from the schema, deliberately.

## History

- **2026-09-01** — the sign-in gate, then single sign-on as the only door,
  and the Postgres storage option for Cloud Run.
- **2026-09-02** — the key vault and per-reader news.
- **2026-09-13** — every vendor key comes from the reader: the operator's
  display-data keys, shared news feed and default model key were removed,
  along with keyless unofficial sources.
- **2026-09-17** — the in-app agent and then the in-app model were removed;
  readers bring their own agent over the agent connection.
- **2026-09-18** — accounts and admin, free mode, vendor-data retention and
  account deletion.
- **2026-09-19** — search by meaning with a self-hosted embedding model, and
  owners' panels kept warm.
