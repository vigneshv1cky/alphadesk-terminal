"""Try the agent tools the way an agent would, and print what each one returns.

It signs in with an access token read from ~/.alphadesk-agent-token (so the
token never goes on a command line or into a chat): make a token on the Agent
access page and save it in that file. It only reads; nothing here changes your
data or places an order, though each call leaves its usual row in the call log.

Run:   python scripts/agent_probe.py [SYMBOL]          (default NVDA)
Aim it at another server with ALPHADESK_PROBE_URL, for example
       ALPHADESK_PROBE_URL=https://your-server.example python scripts/agent_probe.py GRML
The address must be one the server answers to (ALPHADESK_BASE_URL or
ALPHADESK_ALLOWED_HOSTS). The default is a server on this machine.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("ALPHADESK_PROBE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/agent/tools/mcp"
TOKEN_FILE = Path.home() / ".alphadesk-agent-token"


async def call(session, name, **args):
    res = await session.call_tool(name, args)
    text = "".join(getattr(c, "text", "") for c in res.content)
    try:
        return json.loads(text), res.isError
    except ValueError:
        return text, res.isError


async def main(sym: str):
    try:
        token = TOKEN_FILE.read_text().strip()
    except OSError:
        sys.exit(f"{TOKEN_FILE} does not exist. Make a token on the Agent access page and save it there "
                 "(the token is one word starting adk_).")
    if not token.startswith(("adk_", "ado_")) or " " in token:
        sys.exit(f"{TOKEN_FILE} does not hold an access token (it should be one word starting adk_). "
                 "Make a token on the Agent access page, copy it, then run:  pbpaste > ~/.alphadesk-agent-token")
    async with streamablehttp_client(URL, headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("tools:", len(tools), "| what_moved present:", "what_moved" in tools)

            prof, err = await call(s, "company_profile", symbol=sym)
            print("\n== company_profile", "ERROR" if err else "")
            if isinstance(prof, dict):
                print("name:", prof.get("name"), "| shares_outstanding:", prof.get("shares_outstanding"))
            else:
                print(str(prof)[:300])

            wm, err = await call(s, "what_moved", symbol=sym, days=90, min_move_pct=15)
            print("\n== what_moved", "ERROR" if err else "")
            if isinstance(wm, dict) and not err:
                print("vendor:", wm.get("price_vendor"), "| sessions:", wm.get("sessions"),
                      "| big days:", len(wm["big_move_days"]), "| with nothing attached:", wm["big_moves_with_nothing_attached"])
                for d in wm["big_move_days"]:
                    print(f"  {d['date']} {d['change_pct']:+.1f}%  stories={len(d['stories'])} filings={len(d['filings'])}"
                          + ("  [nothing attached]" if d["nothing_attached"] else ""))
                    for st in d["stories"][:2]:
                        print("      -", (st.get("title") or "")[:90], f"[{st.get('kind')}, {st.get('named_tickers')} tickers]")
                for f in wm["filing_reactions"][:6]:
                    print(f"  filing {f['form']} {f['filed']} -> {f['reaction_session']} {f['change_pct']:+.1f}%")
                print("notes:", wm.get("notes"))
                filed = [f for d in wm["big_move_days"] for f in d["filings"] if f["readable"]]
            else:
                print(str(wm)[:400])
                filed = []

            fl, err = await call(s, "list_filings", symbol=sym)
            if isinstance(fl, list):
                six = next((f for f in fl if f["form"] == "6-K"), None)
                holder = next((f for f in fl if f["form"].startswith("SCHEDULE 13")), None)
                print("\n== list_filings:", len(fl), "rows | has SCHEDULE 13 rows:", bool(holder))
                if six:
                    ft, err = await call(s, "filing_text", accession=six["accession"])
                    txt = ft.get("text", "") if isinstance(ft, dict) else ""
                    print("   newest 6-K", six["accession"], "| pages:", ft.get("pages") if isinstance(ft, dict) else ft,
                          "| includes a press-release exhibit:", "[EXHIBIT" in txt)
            ms, err = await call(s, "move_state", symbols=[sym])
            print("\n== move_state", "ERROR " + str(ms)[:300] if err else "")
            if isinstance(ms, dict) and not err:
                st = (ms.get("symbols") or {}).get(sym)
                if st:
                    print("   session", st.get("session"), "| reliable:", st.get("reliable"), "| change:", st.get("change_pct"),
                          "| given back from high %:", st.get("given_back_from_high_pct"), "| last 60m:", st.get("last_60min_change_pct"))
                    print("   direction:", st.get("direction"), "| volume:", st.get("volume"))
                else:
                    print("   failed:", ms.get("failed"))

            pi, err = await call(s, "priced_in", symbol=sym)
            print("\n== priced_in", "ERROR " + str(pi)[:300] if err else "")
            if isinstance(pi, dict) and not err:
                print("   past reports read:", len(pi.get("past_reports") or []), "| typical report move %:", pi.get("typical_report_move_pct"),
                      "| next report:", pi.get("next_report"), "| targets:", pi.get("analyst_targets"))
                print("   notes:", pi.get("notes"))

            cd, err = await call(s, "candidates", limit=8)
            print("\n== candidates", "ERROR " + str(cd)[:300] if err else "")
            if isinstance(cd, dict) and not err:
                print("   for session(s):", cd.get("sessions"), "| filings since:", cd.get("filings_since"), "| count:", cd.get("count"), "| unavailable:", cd.get("unavailable"))
                for c in cd.get("candidates", [])[:8]:
                    print(f"   {c['symbol']:6} weight={c['evidence_weight']} board={c['on_board']} moved={c['already_moved_pct']}  " +
                          "; ".join(e["detail"] for e in c["evidence"])[:90])

            mc, err = await call(s, "movers_in_context", direction="gainers", top=5)
            print("\n== movers_in_context", "ERROR " + str(mc)[:300] if err else "")
            if isinstance(mc, dict) and not err:
                print("   data_freshness:", mc.get("data_freshness"))
                print("   session:", mc.get("session"), "| rows:", mc.get("count"), "| unavailable:", mc.get("unavailable"))
                for r in mc.get("rows", [])[:5]:
                    print(f"   {r['symbol']:6} {r['change_pct']:+6.1f}%  own stories={r['news']['own']} lists={r['news']['named_in_lists']}  flags={r['flags']}")

            ns, err = await call(s, "news_scan", hours=18, limit=8)
            print("\n== news_scan", "ERROR " + str(ns)[:300] if err else "")
            if isinstance(ns, dict) and not err:
                print("   stories read:", ns.get("stories_read"), "| names:", ns.get("names"), "| unavailable:", ns.get("unavailable"))
                for r in ns.get("rows", [])[:8]:
                    print(f"   {r['symbol']:6} stories={r['stories']} kinds={r['by_kind']} day={r.get('day_change_pct')}  " +
                          (r['newest'][0]['title'] or '')[:60])

            ef, err = await call(s, "entry_facts", symbol=sym, risk_dollars=100, stop_pct=5)
            print("\n== entry_facts", "ERROR " + str(ef)[:300] if err else "")
            if isinstance(ef, dict) and not err:
                print("   data_freshness:", ef.get("data_freshness"))
                print("   broker:", ef.get("broker"), "| quote:", ef.get("quote"))
                print("   liquidity:", ef.get("liquidity"))
                print("   risks:", ef.get("risks"), "| sizing:", ef.get("sizing"), "| unavailable:", ef.get("unavailable"))

            ra, err = await call(s, "related_assets", symbol=sym)
            print("\n== related_assets", "ERROR " + str(ra)[:300] if err else "")
            if isinstance(ra, dict) and not err:
                ow = ra.get("from_own_words") or {}
                print("   read:", ow.get("read"))
                for c in ow.get("crypto", [])[:5]:
                    print(f"   crypto {c['asset']:6} x{c['mentions']} priceable={c['priceable']} ({c['price_symbol']}) :: {c['snippet'][:90]}")
                print("   companies:", [(c['ticker'], c['mentions']) for c in ow.get("companies", [])[:6]])
                print("   vendor peers:", (ra.get("vendor_peers") or {}).get("peers"), "| funds:", len((ra.get("funds") or {}).get("funds", [])),
                      "| unavailable:", ra.get("unavailable"))


asyncio.run(main((sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()))
