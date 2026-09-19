/** The Sectors page's figures moved by live prices (lib/sectorsLive.ts).
 *
 *     pnpm test
 */
import { test } from "node:test"
import assert from "node:assert/strict"
import { liveGroup, liveRow, rotation } from "../sectorsLive.ts"

const row = (symbol: string, price: number, bases: Record<string, number>) => ({
  symbol, price, change_pct: 0, w1: 1, m1: 1, m3: 1, ytd: 1, y1: 1, rel_m1: 0, rel_m3: 0, rotation: null, bases,
})

test("a live price moves every return from its own base", () => {
  const r = liveRow(row("XLE", 100, { d1: 100, w1: 110, m1: 80, m3: 50, ytd: 125, y1: 100 }), { price: 110, stale: false })
  assert.deepEqual([r.price, r.change_pct, r.w1, r.m1, r.m3, r.ytd, r.y1], [110, 10, 0, 37.5, 120, -12, 10])
})

test("a stale tick or a missing base keeps the server's figure", () => {
  const base = row("XLK", 100, { d1: 100 })
  assert.equal(liveRow(base, { price: 150, stale: true }), base)
  const r = liveRow(base, { price: 110, stale: false })
  assert.equal(r.change_pct, 10)
  assert.equal(r.m3, 1)                                           // no m3 base: unchanged
})

test("relative returns follow both live prices, and the standing with them", () => {
  const bench = row("SPY", 100, { m1: 100, m3: 100 })
  const xle = row("XLE", 100, { m1: 100, m3: 80 })
  const g = liveGroup([xle], bench, { SPY: { price: 102, stale: false }, XLE: { price: 101, stale: false } })
  assert.equal(g.bench.m1, 2)
  assert.deepEqual([g.rows[0].rel_m1, g.rows[0].rel_m3, g.rows[0].rotation], [-1, 24.25, "weakening"])
  assert.equal(rotation(null, 1), null)
})
