import { useEffect, useState } from "react"
import { useLiveEnabled } from "@/lib/liveState"
import { watch } from "@/lib/liveStream"

/** Live crypto prices for the coins a surface shows, on the tab's one live
 * connection (lib/liveStream).
 *
 * The stream owns nothing but the price; the polled list owns the rows, the
 * order and the 24-hour base — the same split the chart uses, where the
 * polled series owns the bars and a tick only moves the live edge.
 *
 * It watches exactly the coins given (2026-09-15). It watched a fixed list
 * of 28 kept from the old ticker tape, so a coin outside it (USDT, USDC, a
 * coin climbing into Gainers) sat still between polls, and every movers tile
 * subscribed those 28 whatever its category.
 */
export type CryptoTick = { symbol: string; price: number; at: string; stale: boolean }

/** What one stream may carry — the server's LIVE_COINS_MAX. */
const MAX_COINS = 40

export function useCryptoTicks(symbols: string[]): Record<string, CryptoTick> {
  // Sorted, so the same coins in another order are the same watch.
  const key = [...new Set(symbols.map(s => s.toUpperCase()))].slice(0, MAX_COINS).sort().join(",")
  const [ticks, setTicks] = useState<Record<string, CryptoTick>>({})
  const enabled = useLiveEnabled()
  useEffect(() => {
    setTicks({})
    if (!key || !enabled) return
    const mine = new Set(key.split(","))
    return watch({
      crypto: [...mine],
      onCrypto: moved => {
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
