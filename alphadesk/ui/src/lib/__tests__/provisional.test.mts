import assert from "node:assert/strict"
import { test } from "node:test"
import { foldLiveTrade, provisionalPoints, provisionalSlots, tradeIsPastLastBar } from "../provisional.ts"

const LAST = "2026-09-14T14:39:00+00:00"          // the last consolidated 1-minute bar

test("server closes after the last bar are kept one per minute; the trade replaces its minute", () => {
  const pts = provisionalPoints(LAST, [
    { t: "2026-09-14T14:39:00+00:00", c: 1 },       // the bar itself: not provisional
    { t: "2026-09-14T14:40:00+00:00", c: 240 },
    { t: "2026-09-14T14:42:00+00:00", c: 242 },
  ], { price: 243.5, at: "2026-09-14T14:42:31.5Z" }, "1m")
  assert.deepEqual(pts.map(p => p.c), [240, 243.5])
  assert.deepEqual(provisionalSlots(LAST, pts, "1m").map(p => p.k), [1, 3])
})

test("a trade in a new minute adds a point; nothing without a fixed interval", () => {
  const pts = provisionalPoints(LAST, [], { price: 250, at: "2026-09-14T14:54:02Z" }, "1m")
  assert.deepEqual(provisionalSlots(LAST, pts, "1m"), [{ k: 15, c: 250 }])
  assert.deepEqual(provisionalPoints(LAST, [{ t: "2026-09-14T14:45:00Z", c: 1 }], null, "1d"), [])
})

test("only a trade past the last bar's own period leaves the bar alone", () => {
  assert.equal(tradeIsPastLastBar(LAST, "2026-09-14T14:39:40Z", "1m"), false)
  assert.equal(tradeIsPastLastBar(LAST, "2026-09-14T14:40:00Z", "1m"), true)
  assert.equal(tradeIsPastLastBar(LAST, "2026-09-14T14:54:00Z", "5m"), true)
})

const MIN = "2026-09-15T14:25:00+00:00"
const bar = (h: number, l: number, c: number) => ({ t: MIN, o: c, h, l, c, v: 1 })

test("a live trade moves the last bar's close, and its high and low accumulate", () => {
  let got = foldLiveTrade([bar(212.5, 212.2, 212.4)], "NVDA:1D:1m", { price: 212.9, at: "2026-09-15T14:25:20Z" }, null)
  assert.deepEqual([got.bars[0].h, got.bars[0].l, got.bars[0].c], [212.9, 212.2, 212.9])
  got = foldLiveTrade([bar(212.5, 212.2, 212.4)], "NVDA:1D:1m", { price: 212.6, at: "2026-09-15T14:25:40Z" }, got.forming)
  assert.deepEqual([got.bars[0].h, got.bars[0].c], [212.9, 212.6])    // the 212.9 wick stays
})

test("switching stocks in the same minute does not carry the old stock's high and low", () => {
  const nvda = foldLiveTrade([bar(212.8, 212.5, 212.6)], "NVDA:1D:1m", { price: 212.7, at: "2026-09-15T14:25:10Z" }, null)
  const veea = foldLiveTrade([bar(6.33, 6.25, 6.3)], "VEEA:1D:1m", { price: 6.28, at: "2026-09-15T14:25:30Z" }, nvda.forming)
  assert.deepEqual([veea.bars[0].h, veea.bars[0].l, veea.bars[0].c], [6.33, 6.25, 6.28])
})

test("a trade from before the last bar, or past a delayed series' bar, leaves the bars alone", () => {
  const bars = [bar(10, 9, 9.5)]
  assert.equal(foldLiveTrade(bars, "X", { price: 50, at: "2026-09-15T14:24:59Z" }, null).bars, bars)
  assert.equal(foldLiveTrade(bars, "X", { price: 50, at: "2026-09-15T14:41:00Z" }, null, true).bars, bars)
})
