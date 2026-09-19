/** The tab's one live connection: its URL and the age of remembered ticks
 * (lib/liveStream.ts).
 *
 *     pnpm test
 */
import { test } from "node:test"
import assert from "node:assert/strict"
import { aged, liveUrl } from "../liveStream.ts"

test("every surface's symbols ride one URL, unioned and sorted", () => {
  const url = liveUrl([
    { trades: ["nvda"], quotes: ["TSLA", "AAPL"] },
    { quotes: ["AAPL", "NVDA"] },
    { crypto: ["BTC-USD"] },
  ])
  assert.equal(url, "/api/stream?trades=NVDA&quotes=AAPL%2CNVDA%2CTSLA&crypto=BTC-USD")
  // The same set mounted in another order is the same connection.
  assert.equal(liveUrl([{ crypto: ["BTC-USD"] }, { quotes: ["NVDA", "TSLA", "AAPL"] }, { trades: ["NVDA"] }]), url)
})

test("nothing watched is no connection", () => {
  assert.equal(liveUrl([]), null)
  assert.equal(liveUrl([{ quotes: [] }]), null)
})

test("a remembered tick is handed on as old as it really is", () => {
  const kept = { tick: { symbol: "NVDA", price: 212, at: "t", age_s: 2, stale: false }, received: 1_000 }
  assert.deepEqual(aged(kept, 11_000), { ...kept.tick, age_s: 12, stale: false })
  assert.equal(aged(kept, 40_000).stale, true)
})

test("a surface watching news adds it to the one URL", () => {
  assert.equal(liveUrl([{ news: true }]), "/api/stream?news=1")
  assert.equal(liveUrl([{ quotes: ["NVDA"] }, { news: true }]), "/api/stream?quotes=NVDA&news=1")
  assert.equal(liveUrl([{ news: false }]), null)
})
