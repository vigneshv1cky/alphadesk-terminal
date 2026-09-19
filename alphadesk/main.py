"""AlphaDesk entrypoint.

  python -m alphadesk.main dashboard      # the terminal (API + SPA)
  python -m alphadesk.main mcp            # expose the same data to agents
  python -m alphadesk.main backfill --hours 168
  python -m alphadesk.main earnings       # refresh the calendar, show it

AlphaDesk is a CONSUMPTION terminal: it fetches, reads and presents market
information. It does not trade, hold positions, or score decisions — the
execution and measurement layers (entry booking, tiered exits, forward
grading vs SPY, backtests) were removed on 2026-08-18. Recover them from git
if that direction ever returns.
"""

import argparse
import asyncio
import time
import logging
import sys


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _web_server():
    import os

    import uvicorn

    from alphadesk.app.dashboard import app as dashboard_app

    return uvicorn.Server(uvicorn.Config(
        dashboard_app,
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),  # VM sets 0.0.0.0
        port=int(os.environ.get("DASHBOARD_PORT", "8000")),
        log_level="warning",
        # Graceful shutdown must have a DEADLINE here. The default waits for
        # every in-flight request to finish — and this app's SSE endpoints
        # are deliberately infinite requests, so one open browser tab made
        # every stop wait forever and every deploy eat systemd's 90-second
        # SIGKILL timeout. Five seconds drains anything real; the streams are
        # then cancelled, which their clients already treat as a reconnect.
        timeout_graceful_shutdown=5,
    ))


async def _serve() -> None:
    """The keyless EDGAR release loop, the per-user news loop, the daily
    earnings forecast capture, and the web server. Every market figure a
    panel shows is fetched on the request path from the signed-in user's own
    vendors; the forecast capture is the one keyed call made without a
    request, once a day per active reader, stored as theirs."""

    async def _edgar_releases_loop():
        """Results releases from SEC EDGAR, keyless public data (2026-09-13).
        Every fifteen minutes from 06:00 ET to midnight on a weekday, the
        day's 8-Ks with Item 2.02 are stamped with EDGAR's acceptance
        instant; before noon the previous weekday is checked again (an
        after-close release accepted the next morning). A week is
        backfilled once at start. Each user's calendar joins this table to
        the reports their own vendors list. No vendor key is used here — a
        loop has no user, so it may only read public government data."""
        from alphadesk.config import now_et
        from alphadesk.ingest import edgar_releases
        from alphadesk.ingest.earnings import previous_weekday
        loop = asyncio.get_running_loop()
        log = logging.getLogger("alphadesk.edgar_releases")
        try:
            await loop.run_in_executor(None, lambda: edgar_releases.backfill(7))
        except Exception as exc:
            log.error("EDGAR release backfill error: %s", exc)
        while True:
            now = now_et()
            if now.weekday() < 5 and now.hour >= 6:
                today = now.date().isoformat()
                try:
                    await loop.run_in_executor(None, lambda: edgar_releases.refresh_day(today))
                    if now.hour < 12:
                        await loop.run_in_executor(None, lambda: edgar_releases.refresh_day(previous_weekday(today)))
                except Exception as exc:
                    log.error("EDGAR release refresh error: %s", exc)
            from alphadesk.app import scheduler
            scheduler.beat()
            await asyncio.sleep(15 * 60)

    async def _news_loop():
        """Background news ingest for each active user with their own news
        key: poll their feeds since their last cycle (first run:
        NEWS_LOOKBACK_HOURS) and persist the articles as theirs.

        No model runs here or anywhere else in the app (2026-09-17):
        /api/screener is a plain database read."""
        from datetime import timedelta

        from alphadesk.config import (NEWS_LOOKBACK_HOURS, NEWS_REFRESH_MINUTES,
                                      NEWS_USER_ACTIVE_HOURS, now_et)
        from alphadesk.ingest import news
        from alphadesk.ledger import store
        loop = asyncio.get_running_loop()
        log = logging.getLogger("alphadesk.news")
        # Per-reader poll cursors, in memory: a reader ABSENT from this dict
        # (fresh key, or a return after the process restarted) backfills from
        # the full lookback window on their first cycle — that is the
        # "window backfills on arrival" behavior, and it costs little because
        # enrichment_cache already holds most of what the backfill re-fetches.
        user_last: dict[str, object] = {}
        # Vendor data past its use is deleted hourly (store.prune_vendor_data,
        # 2026-09-18): only a database write, no vendor call. The first cycle
        # prunes at once: the monotonic clock counts from the machine's boot,
        # so starting this at 0 skipped the first hour on a fresh container.
        last_prune = float("-inf")
        while True:
            if time.monotonic() - last_prune >= 3600:
                last_prune = time.monotonic()
                try:
                    pruned = await loop.run_in_executor(None, store.prune_vendor_data)
                    if any(pruned.values()):
                        log.info("pruned vendor data: %s", {k: v for k, v in pruned.items() if v})
                except Exception as exc:
                    log.warning("vendor-data prune failed: %s", exc)
            # Every ACTIVE user with their own news key — each on their own
            # key, each failure their own (poll_user logs and returns 0).
            # There is no server feed (2026-09-13).
            try:
                active = await loop.run_in_executor(
                    None, store.news_poll_users, NEWS_USER_ACTIVE_HOURS)
                # The real-time leg: each active reader's own Benzinga socket
                # is held open here, with no browser tab (2026-09-17). Held
                # only while a tab subscribed, a reader away from the terminal
                # saw a story no sooner than the next cycle below; over the
                # socket it lands in seconds. Idempotent — this revives a
                # dropped connection and releases readers gone inactive.
                try:
                    from alphadesk.ingest import stream as streams
                    held, gone = await loop.run_in_executor(None, streams.hold_news_for, active)
                    if gone:
                        log.info("news stream: holding %d reader(s), released %d", held, gone)
                except Exception as exc:
                    log.warning("news stream holds: %s", exc)
                for uid in active:
                    u_since = user_last.get(uid) or (now_et() - timedelta(hours=NEWS_LOOKBACK_HOURS))
                    user_last[uid] = now_et()
                    un = await loop.run_in_executor(None, news.poll_user, uid, u_since)
                    if un:
                        log.info("Ingested %d articles for reader %s", un, uid[:8])
                for gone in set(user_last) - set(active):
                    user_last.pop(gone, None)   # inactive readers restart from lookback on return
            except Exception as exc:
                log.error("per-user news cycle error: %s", exc)
            from alphadesk.app import scheduler
            scheduler.beat()
            await asyncio.sleep(NEWS_REFRESH_MINUTES * 60)

    async def _forecast_loop():
        """The earnings forecast log's daily capture (2026-09-14): from
        FORECAST_CAPTURE_HOUR_ET, once a day, each reader seen within
        FORECAST_USER_ACTIVE_HOURS who has a calendar vendor gets their
        vendors' upcoming reports recorded — under their identity, on their
        keys, stored as theirs. A reader whose calendar was already captured
        today (by opening it) is skipped, so a restart never doubles a day."""
        from alphadesk.config import FORECAST_CAPTURE_HOUR_ET, FORECAST_USER_ACTIVE_HOURS, now_et
        from alphadesk.ingest import earnings_calendar
        from alphadesk.ledger import store
        loop = asyncio.get_running_loop()
        log = logging.getLogger("alphadesk.forecasts")
        done: dict[str, str] = {}
        while True:
            now = now_et()
            today = now.date().isoformat()
            if now.hour >= FORECAST_CAPTURE_HOUR_ET:
                try:
                    users = await loop.run_in_executor(None, store.forecast_capture_users, FORECAST_USER_ACTIVE_HOURS)
                    for uid in users:
                        if done.get(uid) == today:
                            continue
                        days = await loop.run_in_executor(None, store.forecast_capture_days, uid)
                        if any(today in d for d in days.values()):
                            done[uid] = today
                            continue
                        try:
                            counts = await loop.run_in_executor(None, earnings_calendar.capture_daily, uid)
                            if counts:
                                log.info("earnings forecasts for reader %s: %s", uid[:8], counts)
                        except Exception as exc:
                            log.warning("earnings forecasts failed for reader %s: %s", uid[:8], exc)
                        done[uid] = today
                except Exception as exc:
                    log.error("earnings forecast cycle error: %s", exc)
            from alphadesk.app import scheduler
            scheduler.beat()
            await asyncio.sleep(30 * 60)

    # The web server is the FOREGROUND task and the ingest loops are
    # background tasks — not one gather over all three. Uvicorn installs the
    # SIGINT/SIGTERM handlers and its serve() returns once it has drained;
    # gathered alongside two deliberately infinite loops, that return was
    # simply absorbed: the process stayed up until systemd's stop timeout
    # SIGKILLed it, ~90 seconds of downtime on every single deploy.
    # Search by meaning: the model loads and stored stories are embedded on a
    # background thread; search is words-only until it is ready.
    from alphadesk import semantic
    semantic.start_worker()
    # An owner's panels, replayed in the background so they open warm
    # (alphadesk/prewarm.py) — first pass right after start-up.
    from alphadesk import prewarm
    prewarm.start()
    ingest_tasks = [asyncio.create_task(_edgar_releases_loop()),
                    asyncio.create_task(_news_loop()),
                    asyncio.create_task(_forecast_loop())]
    try:
        await _web_server().serve()
    finally:
        # HARD DEADLINE on shutdown, including interpreter teardown itself.
        # Cancelling a task does not kill the executor THREAD running its
        # blocking call, and the runtime's cleanup joins those threads before
        # exiting — a mid-flight enrichment call (LLM timeout: 60s) kept the
        # "stopped" process alive for another minute, measured on the VM. The
        # timer is a daemon thread: a clean exit ignores it; a wedged
        # teardown gets cut short with the same effect systemd's SIGKILL
        # had, minus the 90-second wait. Everything the process manages is
        # already closed by the cleanup below before the timer can fire.
        import os
        import threading
        failsafe = threading.Timer(15.0, lambda: os._exit(0))
        failsafe.daemon = True
        failsafe.start()
        for t in ingest_tasks:
            t.cancel()
        await asyncio.gather(*ingest_tasks, return_exceptions=True)
        # Close the equity websocket properly: the account's single
        # connection slot is released by a real close frame, where an
        # OS-dropped socket leaves the next process fighting a ghost for it.
        from alphadesk.ingest import stream as market_streams
        await asyncio.get_running_loop().run_in_executor(None, market_streams.shutdown_all)


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="alphadesk")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dashboard", help="run the terminal")
    p_back = sub.add_parser("backfill")
    p_back.add_argument("--hours", type=float, default=72)
    sub.add_parser("earnings", help="stamp today's EDGAR results releases and list the last three days")
    p_acc = sub.add_parser("calendar-accuracy", help="score the local account's calendar vendors against EDGAR release days")
    p_acc.add_argument("--days", type=int, default=30)
    p_mcp = sub.add_parser("mcp", help="serve the terminal's data to agents over MCP")
    p_mcp.add_argument("--http", action="store_true",
                       help="streamable HTTP instead of stdio")
    # `user …` manages hosted-mode accounts and parses its own argv — an
    # allowlist edited at the terminal, which is the whole phase-1 policy.
    if len(sys.argv) > 1 and sys.argv[1] == "user":
        from alphadesk.app.auth import make_user_cli
        make_user_cli()
        sys.exit(0)
    p_keys = sub.add_parser("keys", help="development: seal vendor keys from the environment into the local account")
    p_keys.add_argument("action", choices=["import-env"])
    args = parser.parse_args()

    if args.cmd == "dashboard":
        import os
        log = logging.getLogger("alphadesk")
        log.info("Terminal on http://%s:%s",
                 os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
                 os.environ.get("DASHBOARD_PORT", "8000"))
        asyncio.run(_serve())
    elif args.cmd == "backfill":
        from alphadesk.ingest import edgar_releases
        from alphadesk.ledger import store
        store.init()
        n = edgar_releases.backfill(days=max(1, int(args.hours / 24) or 7))
        print(f"EDGAR results releases stamped: {n}")
    elif args.cmd == "mcp":
        # stdio is the transport most clients use, and it carries the protocol
        # on stdout — so logging must NOT go there or it corrupts the stream.
        if not args.http:
            logging.getLogger().handlers.clear()
            logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
        from alphadesk.mcp_server import serve
        serve(http=args.http)
        return
    elif args.cmd == "keys":
        # DEVELOPMENT ONLY. The server never reads a vendor key from its
        # environment at request time (2026-09-13); this copies the ones a
        # developer keeps in .env into the open instance's local account,
        # sealed in the vault, so the local board runs on keys exactly the
        # way a signed-in user's does.
        import os
        from alphadesk.ledger import store, vault
        store.init()
        uid = store.ensure_local_user()
        pairs = {"alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), "polygon": ("POLYGON_API_KEY", None),
                 "finnhub": ("FINNHUB_API_KEY", None), "alphavantage": ("ALPHAVANTAGE_API_KEY", None),
                 "fmp": ("FMP_API_KEY", None), "coingecko": ("COINGECKO_API_KEY", None)}
        done = []
        for vendor, (k_env, s_env) in pairs.items():
            key = (os.environ.get(k_env) or "").strip()
            if not key:
                continue
            secret = (os.environ.get(s_env) or "").strip() if s_env else ""
            store.set_user_key(uid, "prices", vendor, vault.encrypt({"api_key": key, "api_secret": secret}), key[-4:])
            done.append(vendor)
        # Finnhub is sealed for market data only: its general news feed carries
        # almost no tickers, so as a news key it delivered nothing (0 of 100
        # stories tagged, 2026-09-13). A reader can still connect it by hand.
        news = {"polygon": ("POLYGON_API_KEY", None), "alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
                "fmp": ("FMP_API_KEY", None)}
        for vendor, (k_env, s_env) in news.items():
            key = (os.environ.get(k_env) or "").strip()
            if key:
                secret = (os.environ.get(s_env) or "").strip() if s_env else ""
                store.set_user_key(uid, "news", vendor, vault.encrypt({"api_key": key, "api_secret": secret}), key[-4:])
                done.append(f"news:{vendor}")
        print(f"sealed into the local account: {', '.join(done) or 'nothing (no vendor keys in the environment)'}")
    elif args.cmd == "calendar-accuracy":
        from alphadesk.ingest import calendar_accuracy
        from alphadesk.ledger import store
        store.init()
        rep = calendar_accuracy.report(store.ensure_local_user(), args.days)
        print(f"releases {rep['start']}..{rep['end']} with a same-day clock: {rep['releases']}"
              f" · captures since {rep['captures_since'] or 'never'}")
        if not rep["vendors"]:
            print("no captures yet — open the earnings calendar; each day it is built is recorded")
        for vendor, by_h in sorted(rep["vendors"].items()):
            for h, m in by_h.items():
                if not m["counted"]:
                    print(f"  {vendor:9} {h}d ahead: no capture that early yet")
                    continue
                n = m["counted"]
                print(f"  {vendor:9} {h}d ahead: {n} releases · listed {m['listed']} · date exact {m['date_exact']}"
                      f" ({100 * m['date_exact'] // n}%) · within a day {m['date_within_1']}"
                      f" · session named {m['session_named']}, right {m['session_right']}")
    elif args.cmd == "earnings":
        from datetime import date, timedelta
        from alphadesk.ingest import edgar_releases
        from alphadesk.ledger import store
        store.init()
        today = date.today()
        print(f"stamped today: {edgar_releases.refresh_day(today.isoformat())}")
        rows = store.releases_between((today - timedelta(days=3)).isoformat(), today.isoformat())
        print(f"\n=== results 8-Ks on EDGAR, last 3 days ({len(rows)}) ===")
        for r in rows[-40:]:
            print(f"  {r['file_date']}  {(r['accepted_at'] or '')[11:16]:5}  {r['symbol']:6}  {r['company'] or ''}")
    sys.exit(0)


if __name__ == "__main__":
    main()
