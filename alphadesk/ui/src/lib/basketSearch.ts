import type { Theme } from "@/lib/api"

/** Which baskets a rail search keeps (2026-09-18). Every word typed must
 * begin a word of the basket's name or description, or be one of its
 * tickers exactly — so "ship" finds "Shipping & freight rates", "zim" finds
 * every basket holding ZIM, and "gold miners" needs both words. A ticker
 * matches whole, and a word of one or two characters is taken as a ticker
 * only: "F" is Ford, not every basket whose text has a word starting with f.
 * An empty search keeps every basket, in its own order. */
export function searchBaskets(baskets: readonly Theme[], query: string): Theme[] {
  const words = query.toLowerCase().split(/[^a-z0-9./^=-]+/).filter(Boolean)
  if (!words.length) return [...baskets]
  return baskets.filter(b => {
    const text = `${b.label} ${b.why ?? ""}`.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)
    const tickers = new Set(b.symbols.map(s => s.toLowerCase()))
    return words.every(w => tickers.has(w) || (w.length > 2 && text.some(t => t.startsWith(w))))
  })
}
