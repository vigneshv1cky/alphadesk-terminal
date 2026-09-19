import { useEffect, useState } from "react"
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

export function useLiveTrade(symbol: string): { tick: LiveTick | null; live: boolean } {
  const [tick, setTick] = useState<LiveTick | null>(null)
  const [live, setLive] = useState(false)
  // The header's global pause. Unwatching here is what closes the tab's
  // connection once the last surface lets go.
  const enabled = useLiveEnabled()

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
      onTrade: t => { if (t.symbol === sym) { received.at = Date.now(); setTick(t) } },
      onTradeLive: (s, l) => { if (s === sym) setLive(l) },
    })
    const clock = window.setInterval(() => {
      setTick(t => {
        if (!t || t.stale) return t
        const age = t.age_s + (Date.now() - received.at) / 1000
        return age > STALE_AFTER_S ? { ...t, age_s: age, stale: true } : t
      })
    }, 5000)
    return () => { window.clearInterval(clock); unwatch() }
  }, [symbol, enabled])

  return { tick, live }
}
