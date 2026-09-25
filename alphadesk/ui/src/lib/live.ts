import { useEffect, useRef, useState } from "react"
import { useLiveEnabled } from "@/lib/liveState"

/** The live trade feed for one symbol, on the tab's one live connection
 * (lib/liveStream, 2026-09-15 — it was a connection per symbol).
 *
 * The stream is an OVERLAY on the polled series, never a replacement for it.
 * REST still owns the bars — their structure, their history, the coverage
 * verdict — and a tick only ever moves the live edge between polls. That split
 * matters because on a free key the feed is IEX: it prints a fraction of
 * consolidated volume, so a symbol can be genuinely quiet here for minutes
 * while trading perfectly well elsewhere. Anything shown from a tick has to be
 * able to say how old it is; `stale` marks when the server last heard one.
 */
import { STALE_AFTER_S, watch, type TradeTick } from "@/lib/liveStream"

export type LiveTick = TradeTick

/** How often a trade may move React state, at most.
 *
 * A BUSY SYMBOL PRINTS FASTER THAN A CHART CAN BE READ (2026-09-25, #76).
 * Every trade set state here, and the chart re-renders on that state — bars,
 * scales, indicator geometry, axis ticks, candle paths, for every print.
 * MEASURED on /chart with one tile during the session: 2.4-3.5 MB of
 * allocation a SECOND, taking a tab from 46MB to 680MB in five minutes,
 * while /calendars — same app, no chart — allocated nothing at all.
 *
 * MEASURED at three settings on NVDA during the session, which prints about
 * four times a second: no coalescing and 250ms both allocate 2.5 MB/s (250ms
 * is a no-op at that print rate), 500ms allocates 0.98, and 1000ms is flat.
 * Each render costs roughly 600KB. 500ms is the trade taken: twice a second
 * is past what anyone reads off a chart, and 13 distinct prices still showed
 * in a 30-second window.
 *
 * IT IS CHURN, NOT A LEAK — the collector reclaims it, observed dropping
 * 186MB to 42MB mid-measurement. What this buys is a BOUND: the render rate
 * no longer follows the print rate, so a symbol printing fifty times a
 * second costs the same as one printing twice.
 *
 * The NEWEST tick always wins, so nothing is lost but renders nobody saw.
 * Leading edge: the first print after a quiet moment shows at once, and only
 * a burst is coalesced. */
const TICK_MS = 500

export function useLiveTrade(symbol: string): { tick: LiveTick | null; live: boolean } {
  const [tick, setTick] = useState<LiveTick | null>(null)
  const [live, setLive] = useState(false)
  // The header's global pause. Unwatching here is what closes the tab's
  // connection once the last surface lets go.
  const enabled = useLiveEnabled()
  // The newest tick not yet shown, and the timer that will show it.
  const pending = useRef<LiveTick | null>(null)
  const flush = useRef<number | null>(null)
  const lastFlush = useRef(0)

  useEffect(() => {
    setTick(null)
    setLive(false)
    const sym = symbol.toUpperCase()
    if (!sym || !enabled) return
    // The server stamps `stale` when it EMITS, and it emits only on a new
    // trade — so the last frame's flag never changed here however old it
    // got, and a quiet IEX symbol kept rewriting the last bar with a print
    // from an hour ago. The age is carried forward on a clock.
    const received = { at: Date.now() }
    const unwatch = watch({
      trades: [sym],
      onTrade: t => {
        if (t.symbol !== sym) return
        received.at = Date.now()
        // Coalesced, newest wins. The age clock below still reads
        // `received.at`, which every print updates, so a stream that is
        // busy is never mistaken for a stale one.
        pending.current = t
        const since = Date.now() - lastFlush.current
        if (since >= TICK_MS) {
          lastFlush.current = Date.now()
          pending.current = null
          setTick(t)
        } else if (flush.current == null) {
          flush.current = window.setTimeout(() => {
            flush.current = null
            lastFlush.current = Date.now()
            const next = pending.current
            pending.current = null
            if (next) setTick(next)
          }, TICK_MS - since)
        }
      },
      onTradeLive: (s, l) => { if (s === sym) setLive(l) },
    })
    const clock = window.setInterval(() => {
      setTick(t => {
        if (!t || t.stale) return t
        const age = t.age_s + (Date.now() - received.at) / 1000
        return age > STALE_AFTER_S ? { ...t, age_s: age, stale: true } : t
      })
    }, 5000)
    return () => {
      window.clearInterval(clock)
      if (flush.current != null) { window.clearTimeout(flush.current); flush.current = null }
      pending.current = null
      unwatch()
    }
  }, [symbol, enabled])

  return { tick, live }
}
