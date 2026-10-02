#!/usr/bin/env python3
"""Pull every daily bar for one symbol from AlphaDesk's data API.

An example, standard library only: it walks /api/v1/bars/{symbol} back from
today until the start of the reader's vendor's history, waits when it is told
to slow down, and saves the bars as JSON lines, oldest first.

    ALPHADESK_URL=https://your-alphadesk.example.com \\
    ALPHADESK_TOKEN=adk_... \\
    python pull_daily_bars.py AAPL aapl-daily.jsonl

The token comes from the Account page (Agent access). It is read from the
environment, never from an argument, so it does not land in shell history.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def get(url: str, token: str) -> dict:
    """One answer, waiting when the server says to (429 rate limit, 503 vendor
    busy) and giving up after a few tries instead of looping forever."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for _ in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:
                return json.load(reply)
        except urllib.error.HTTPError as err:
            if err.code in (429, 503):
                wait = int(err.headers.get("Retry-After") or 5) + 1
                print(f"{err.code}: waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise SystemExit(f"{err.code}: {err.read().decode(errors='replace')[:300]}")
    raise SystemExit("gave up: still being asked to slow down")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    symbol, path = sys.argv[1], sys.argv[2]
    base = os.environ["ALPHADESK_URL"].rstrip("/")
    token = os.environ["ALPHADESK_TOKEN"]

    bars: dict[str, dict] = {}                 # keyed by time: a page that overlaps adds nothing twice
    before = None
    while True:
        query = {"interval": "1d", "range": "MAX"}
        if before:
            query["before"] = before
        page = get(f"{base}/api/v1/bars/{urllib.parse.quote(symbol)}?{urllib.parse.urlencode(query)}", token)
        if not page["bars"]:                   # the start of the history: the walk is over
            print(page.get("note") or "reached the start of the history", file=sys.stderr)
            break
        for bar in page["bars"]:
            bars[bar["t"]] = bar
        if page["next_before"] == before:      # no progress: never loop on one page
            break
        before = page["next_before"]
        print(f"{len(bars)} bars so far, back to {before}", file=sys.stderr)

    with open(path, "w") as out:
        for t in sorted(bars):
            out.write(json.dumps(bars[t]) + "\n")
    print(f"saved {len(bars)} bars to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
