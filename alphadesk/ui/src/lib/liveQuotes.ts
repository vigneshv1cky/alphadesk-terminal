import { useEffect, useState } from "react"
import { useLiveEnabled } from "@/lib/liveState"
import { watch, type PriceTick } from "@/lib/liveStream"

/** Live prices for a LIST of equities — a panel's rows — on the tab's one
 * live connection (lib/liveStream, 2026-09-15; it was a connection per
 * panel).
 *
 * The movers panels poll every minute or two, so in session they flashed once
 * a poll — technically live, and nothing like the ticker beside them. The
 * server pushes each row's price when it moves, at most every few seconds per
 * row, because a flash fired more often reads as a permanent tint.
 *
 * WHAT TO EXPECT on a free key, which streams IEX, a few percent of
 * consolidated volume: busy rows flash often, quiet ones rarely, some never —
 * and a row that does not flash means this feed saw no print, not that the
 * stock did not trade.
 */
export type QuoteTick = PriceTick

/** How many rows one panel keeps live. Order is the caller's, so the top of
 * the panel is what stays live; the rest keep their polled price. */
export const STREAM_QUOTES_MAX = 40

export function useLiveQuotes(symbols: string[]): Record<string, QuoteTick> {
  // Sorted, so the same rows in a different order are the same watch.
  const key = [...symbols.slice(0, STREAM_QUOTES_MAX)].map(s => s.toUpperCase()).sort().join(",")
  const [ticks, setTicks] = useState<Record<string, QuoteTick>>({})
  const enabled = useLiveEnabled()
  useEffect(() => {
    setTicks({})
    if (!key || !enabled) return
    const mine = new Set(key.split(","))
    return watch({
      quotes: [...mine],
      onQuotes: moved => {
        const hit = moved.filter(t => mine.has(t.symbol))
        if (!hit.length) return
        // Replaced, not mutated — the panel compares identity to re-render.
        setTicks(prev => {
          const next = { ...prev }
          for (const t of hit) next[t.symbol] = t
          return next
        })
      },
    })
  }, [key, enabled])
  return ticks
}
