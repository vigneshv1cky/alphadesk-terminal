/** Scale math for the chart renderer.
 *
 * The renderer draws nothing that does not pass through these functions, so a
 * bug here is a chart that is subtly, confidently wrong — an axis off by a
 * pixel is invisible; a log scale that is not really logarithmic is not.
 *
 * Plain assertions over a runner because the frontend has no test harness and
 * one dependency for one file is a poor trade:
 *
 *     pnpm test
 *
 * Node strips the types itself, so this still costs no dependency. That is
 * also why the relative imports below carry an explicit `.ts`: type stripping
 * does no extension guessing, and without it Node cannot resolve them — which
 * is what left this file unrunnable, and therefore unrun, until now. The `@/`
 * aliases it pulls in transitively are type-only, so they erase before Node
 * ever has to resolve them.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { MIN_COLUMN_PX, columnBucket, columnHeight, paneExtent, sessionKind, sessionLayout, steadyColumnStats } from "../../components/chart/panes.ts"
import {
  indexToX, xToIndex, priceToY, yToPrice, niceStep, priceTicks,
  padRange, padRangeInset, zoomAt, visibleExtent, scaledRange,
  clampView,
} from "../chartScales.ts"

let pass = 0, fail = 0
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log(`  ✓ ${name}`) }
  else { fail++; console.log(`  ✗ ${name} ${extra}`) }
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps

const s = { from: 0, to: 100, width: 1000, height: 400, min: 100, max: 200 }

console.log("index <-> x")
ok("left edge maps to 0", near(indexToX(s, 0), 0))
ok("right edge maps to width", near(indexToX(s, 100), 1000))
ok("round trips", near(xToIndex(s, indexToX(s, 37.5)), 37.5))

console.log("price <-> y (inverted)")
ok("max sits at the top", near(priceToY(s, 200), 0))
ok("min sits at the bottom", near(priceToY(s, 100), 400))
ok("midpoint centres", near(priceToY(s, 150), 200))
ok("round trips", near(yToPrice(s, priceToY(s, 172.5)), 172.5))
ok("a flat series centres rather than pinning to an edge",
   near(priceToY({ ...s, min: 5, max: 5 }, 5), 200))

console.log("log scale")
const ls = { ...s, min: 10, max: 1000 }
ok("equal ratios take equal space",
   near(priceToY(ls, 100, true), 200, 1e-6),
   `got ${priceToY(ls, 100, true)}`)
ok("log round trips", near(yToPrice(ls, priceToY(ls, 250, true), true), 250, 1e-6))

console.log("ticks")
ok("nice steps snap to 1/2/2.5/5", niceStep(0.3) === 0.5 && niceStep(3) === 5 && niceStep(12) === 20,
   `${niceStep(0.3)} ${niceStep(3)} ${niceStep(12)}`)
const t = priceTicks(100, 200)
ok("ticks land inside the range", t.every(v => v >= 100 && v <= 200))
ok("ticks are evenly spaced", new Set(t.slice(1).map((v, i) => (v - t[i]).toFixed(6))).size === 1)
ok("an inverted range yields none", priceTicks(200, 100).length === 0)
ok("a degenerate range does not hang", priceTicks(5, 5).length === 0)

console.log("padding")
ok("pads both sides", (() => { const p = padRange(100, 200); return p.min < 100 && p.max > 200 })())
ok("a flat range still gets width", (() => { const p = padRange(50, 50); return p.max > p.min })())
ok("inset padding keeps the top of the series below the inset", (() => {
  const h = 400, inset = 92
  const p = padRangeInset(100, 200, inset, h)
  const topPx = (p.max - 200) / (p.max - p.min) * h
  return topPx >= inset - 1e-6 && p.min === padRange(100, 200).min
})())
ok("no inset is the plain padding", (() => {
  const a = padRangeInset(100, 200, 0, 400), b = padRange(100, 200)
  return a.min === b.min && a.max === b.max
})())

console.log("zoom")
const z = zoomAt(s, 50, 0.5, 100)
ok("zooming in narrows the span", (z.to - z.from) < 100)
ok("the anchored bar stays put",
   near(indexToX({ ...s, ...z }, 50), indexToX(s, 50), 0.5),
   `${indexToX({ ...s, ...z }, 50)} vs ${indexToX(s, 50)}`)
ok("cannot zoom past a floor", (() => {
  let v = { from: 0, to: 100 }
  for (let i = 0; i < 40; i++) v = zoomAt({ ...s, ...v }, 50, 0.5, 100)
  return (v.to - v.from) >= 5
})())

console.log("visible extent")
const bars = Array.from({ length: 50 }, (_, i) => ({ h: 100 + i, l: 90 + i }))
const e = visibleExtent(bars, 10, 20)
ok("tracks only what is on screen", e.min === 100 && e.max === 120, JSON.stringify(e))
ok("an empty series does not explode", (() => { const x = visibleExtent([], 0, 10); return Number.isFinite(x.min) })())

console.log("pane extents")
const hist = (vals) => ({ id: "x", height: 60, series: [{ kind: "histogram", color: "#000",
  points: vals.map((v, i) => ({ t: String(i), v })) }] })
const lineP = (vals) => ({ id: "x", height: 60, series: [{ kind: "line", color: "#000",
  points: vals.map((v, i) => ({ t: String(i), v })) }] })
const a = paneExtent(hist([100, 500, 900]))
ok("a positive histogram floors at exactly zero", a.min === 0, JSON.stringify(a))
ok("and still pads its top", a.max > 900)
const b = paneExtent(hist([-50, 20, 80]))
ok("a signed histogram (MACD) pads both ways", b.min < -50 && b.max > 80)
ok("a line pane pads both sides", (() => { const c = paneExtent(lineP([10, 20])); return c.min < 10 && c.max > 20 })())
ok("a fixed range (RSI 0-100) is untouched",
   (() => { const d = paneExtent({ id: "rsi", height: 60, range: { min: 0, max: 100 }, series: [] })
            return d.min === 0 && d.max === 100 })())

console.log(`\n${pass} passed, ${fail} failed`)
// The plain assertions above run as the file is evaluated; this is how they
// reach the runner. It used to be `process.exit`, which ended the process
// before node's own test blocks — every one below this line — had run at
// all (2026-09-16). They had also never been imported, so they would have
// thrown had they ever executed.
test("the scale assertions above all held", () => {
  assert.equal(fail, 0, `${fail} scale assertion(s) failed — see the log above`)
})


test("the view overscrolls a little past both ends, never more", () => {
  // 100 bars, a 40-bar window. Past the newest: 30% of the span.
  assert.deepEqual(clampView(80, 120, 100), { from: 72, to: 112 })
  // Past the oldest: a whole screenful, because that is the direction the
  // reader pulls into while the history loads behind them (2026-09-16). A
  // 40-bar window may therefore sit 40 bars clear of the first bar.
  assert.deepEqual(clampView(-30, 10, 100), { from: -30, to: 10 })
  assert.deepEqual(clampView(-60, -20, 100), { from: -40, to: 0 })
  // Inside the series, untouched.
  assert.deepEqual(clampView(10, 50, 100), { from: 10, to: 50 })
})

test("both ends keep room to push into", () => {
  // Neither end is locked: the reader can push the series a third of a
  // screen past the live edge and a whole screen past the oldest bar. The
  // void that a zoom-out used to leave beside the live price is fixed where
  // it was caused, in zoomAt, not by walling the edge off (2026-09-16).
  const wide = clampView(2_000, 5_000, 4_000)
  assert.equal(wide.to - 4_000, 900)                  // 30% of the span
  assert.equal(wide.to - wide.from, 3_000)            // the zoom level is untouched
  // The LEFT keeps its proportional room, because that is the direction the
  // reader pulls INTO: theirs lets you fling onto blank canvas and fills it
  // behind you, and a tight cap there turns one gesture into short tugs
  // against a wall (2026-09-16 recording).
  const back = clampView(-5_000, -2_000, 4_000)
  assert.equal(back.from, -3_000)                     // one screenful of blank
  assert.equal(back.to - back.from, 3_000)
  // A tight window keeps the proportional margin: 30% of 40 bars is 12.
  assert.deepEqual(clampView(80, 120, 100), { from: 72, to: 112 })
})

// Sessions: the four US equity sessions by ET minute of day.
ok("03:59 is overnight", sessionKind(3 * 60 + 59) === "night")
ok("04:00 is pre-market", sessionKind(4 * 60) === "pre")
ok("09:30 is regular", sessionKind(9 * 60 + 30) === "regular")
ok("16:00 is after-hours", sessionKind(16 * 60) === "after")
ok("20:00 is overnight", sessionKind(20 * 60) === "night")
ok("a run of overnight bars becomes one night band", (() => {
  // 21:00 ET on a September day is 01:00Z the next day.
  const bars = ["2026-09-09T01:00:00Z", "2026-09-09T01:01:00Z", "2026-09-09T13:30:00Z"].map(t => ({ t }))
  const l = sessionLayout(bars)
  return l.bands.length === 1 && l.bands[0].kind === "night" && l.bands[0].from === 0 && l.bands[0].to === 2
})())

ok("Saturday and Sunday are the weekend band, until Sunday's overnight session", (() => {
  // Sat 2026-09-19 12:00 ET = 16:00Z; Sun 19:59 ET = 23:59Z; Sun 20:00 ET = Mon 00:00Z; Mon 09:30 ET = 13:30Z.
  const bars = ["2026-09-19T16:00:00Z", "2026-09-20T23:59:00Z", "2026-09-21T00:00:00Z", "2026-09-21T13:30:00Z"].map(t => ({ t }))
  const l = sessionLayout(bars)
  return l.bands.length === 2 && l.bands[0].kind === "weekend" && l.bands[0].from === 0 && l.bands[0].to === 2
    && l.bands[1].kind === "night" && l.bands[1].from === 2 && l.bands[1].to === 3
})())

import { priceTicksLog } from "../chartScales.ts"
import { volumeColumns } from "../../components/chart/panes.ts"

ok("log ticks are 1-2-5 per decade", (() => {
  const t = priceTicksLog(10, 1000)
  return t.includes(10) && t.includes(20) && t.includes(50) && t.includes(100) && t.includes(500) && t.includes(1000)
})())
ok("log ticks thin to decades across a wide range", (() => {
  const t = priceTicksLog(1, 1e7)
  return t.length <= 12 && t.every(v => Math.abs(Math.log10(v) - Math.round(Math.log10(v))) < 1e-9)
})())
ok("a narrow log range falls back to the linear ladder", (() => {
  const t = priceTicksLog(100, 104)
  return t.length >= 3 && t[0] >= 100 && t[t.length - 1] <= 104
})())
ok("volume buckets hold still when the view moves one bar", (() => {
  const entries = Array.from({ length: 400 }, (_, i) => ({ i, v: 1 + (i % 7), up: i % 2 === 0 }))
  const a = volumeColumns(entries, { from: 0, to: 400, width: 200, height: 0, min: 0, max: 0 }, 200, 7)
  const b = volumeColumns(entries, { from: 1, to: 401, width: 200, height: 0, min: 0, max: 0 }, 200, 7)
  // Same buckets (same sums) — only their x moved by one bar's width.
  const sumsA = a.map(c => c.v).join(","), sumsB = b.map(c => c.v).join(",")
  return sumsA === sumsB && Math.abs((a[3].x - b[3].x) - 200 / 400) < 1e-6
})())


test("an empty screen past the oldest bar keeps the price scale steady", () => {
  const bars = [{ h: 11, l: 9 }, { h: 12, l: 10 }, { h: 13, l: 11 }]
  // Over the series: its own high and low.
  assert.deepEqual(visibleExtent(bars, 0, 2), { min: 9, max: 13 })
  // Pulled onto blank canvas before the first bar, waiting for a page: the
  // nearest bar holds the scale, rather than the axis collapsing to 0-1 and
  // throwing the price line off the pane.
  assert.deepEqual(visibleExtent(bars, -400, -50), { min: 9, max: 11 })
  // Past the live edge, the last bar does the same.
  assert.deepEqual(visibleExtent(bars, 50, 400), { min: 11, max: 13 })
  // No bars at all is still the neutral axis.
  assert.deepEqual(visibleExtent([], 0, 10), { min: 0, max: 1 })
})

test("a price scale set by hand stretches about its own middle", () => {
  // The gutter drag holds an absolute range, so panning through history
  // cannot move it (2026-09-16 recording).
  const r = { min: 100, max: 200 }
  assert.deepEqual(scaledRange(r, 1), r)
  assert.deepEqual(scaledRange(r, 2), { min: 125, max: 175 })       // closing in
  assert.deepEqual(scaledRange(r, 0.5), { min: 50, max: 250 })      // opening up
  // Opened far enough, a price scale may run below zero — theirs shows minus
  // twenty on a four-dollar stock, and the axis is the reader's to set.
  assert.ok(scaledRange({ min: 4, max: 6 }, 0.125).min < 0)
})

test("on a log axis it stretches about the log middle", () => {
  // The linear centre of 10 to 1,000 is 505, which sits near the top of a
  // log pane; stretching about it ran the series off the bottom.
  const { min, max } = scaledRange({ min: 10, max: 1_000 }, 2, true)
  assert.ok(Math.abs(min - 31.6227766) < 1e-6 && Math.abs(max - 316.227766) < 1e-4)
  // Nonsense in, the range back unchanged rather than an inverted axis.
  assert.deepEqual(scaledRange({ min: 5, max: 5 }, 2), { min: 5, max: 5 })
  assert.deepEqual(scaledRange({ min: 1, max: 2 }, 0), { min: 1, max: 2 })
})


test("zooming out over blank canvas holds the live edge, not the emptiness", () => {
  // 4,000 bars, a 1,000-bar window at the live edge with the usual 5% gap,
  // and the wheel turned three times with the cursor out in that gap. Held
  // on the cursor, the blank grew its SHARE of the screen every turn until
  // the last bar sat a third of the way in and stayed there — the void in
  // the recording of 2026-09-16. Anchored at the newest bar instead, the gap
  // stays the same slice of the view, which is the same number of pixels.
  let v = { from: 3_050, to: 4_050 }
  for (let i = 0; i < 3; i++) {
    const s = { ...v, width: 900, height: 0, min: 0, max: 0 }
    v = zoomAt(s, 4_040, 2, 4_000)                    // cursor past the last bar
    const span = v.to - v.from
    assert.ok(Math.abs((v.to - 4_000) / span - 0.05) < 0.001,
      `turn ${i + 1}: the gap is ${((v.to - 4_000) / span * 100).toFixed(1)}% of the view`)
  }
  assert.equal(v.to - v.from, 8_000)                  // and it did zoom out
})

test("inside the series the bar under the cursor still stays put", () => {
  const s = { from: 3_050, to: 4_050, width: 900, height: 0, min: 0, max: 0 }
  const held = zoomAt(s, 3_500, 2, 4_000)
  assert.ok(Math.abs((3_500 - held.from) / (held.to - held.from) - 0.45) < 0.01)
})

// ── a steady volume axis (2026-09-21) ──────────────────────────────────────
// A quantity's column height IS the reading, so the ceiling is measured over
// the whole series: panning must not make a quiet bar look busy once the busy
// ones leave the screen.

const vol = [
  { t: "a", v: 10 }, { t: "b", v: 20 }, { t: "c", v: 900 }, { t: "d", v: 30 },
]
const at = (t: string) => ["a", "b", "c", "d"].indexOf(t)

ok("one bar per column: the ceiling is the tallest bar anywhere",
  steadyColumnStats(vol, at, 1).max === 900)
ok("the ceiling does not move when only part of the series is on screen",
  steadyColumnStats(vol.slice(0, 2), at, 1).max !== steadyColumnStats(vol, at, 1).max)
ok("bucketed, the ceiling is the tallest SUM, not the tallest bar",
  steadyColumnStats(vol, at, 2).max === 930)     // c+d = 930 beats a+b = 30
ok("a bucket is anchored to the absolute bar index",
  steadyColumnStats(vol, at, 4).max === 960)     // one bucket holds all four
ok("the average is of the columns, at the drawn bucket width",
  steadyColumnStats(vol, at, 1).mean === 240)    // (10+20+900+30)/4
ok("a wider bucket has a taller average column",
  steadyColumnStats(vol, at, 2).mean === 480)    // (30 + 930)/2
ok("a session with no trades is left out of the average, not counted as zero",
  steadyColumnStats([...vol, { t: "e", v: 0 }], (t) => ["a","b","c","d","e"].indexOf(t), 1).mean === 240)

// A 40-bar view in an 800px plot has room for every bar; a 4,000-bar view
// does not, and its columns are summed.
const roomy = { from: 0, to: 40, width: 800, height: 100, min: 0, max: 1 }
const packed = { from: 0, to: 4000, width: 800, height: 100, min: 0, max: 1 }
ok("each bar draws its own column when there is room", columnBucket(40, roomy, 800, 7) === 1)
ok("a view too dense to draw one column a bar sums them", columnBucket(4000, packed, 800, 7) > 1)
ok("the bucket width follows the view's SPAN, so a pan does not change it",
  columnBucket(4000, packed, 800, 7) === columnBucket(3000, packed, 800, 7))

// A column is held up to a floor so a quiet session stays legible beside a
// busy one — but a TRUE ZERO draws nothing, or a session with no trades would
// show a row of bars.
ok("a tall column keeps its own height", columnHeight(500, 100, 20) === 80)
ok("a negative value is as tall as its distance from zero",
  columnHeight(-40, 100, 140) === 40)

// The floor is one pixel — the owner preferred true heights to a floor tall
// enough to misread — but a true zero still draws nothing.
ok("the floor is a single pixel", MIN_COLUMN_PX === 1)
ok("a column too short to see is held up to it", columnHeight(1, 100, 99.9) === 1)
ok("no trades draws no column at all", columnHeight(0, 100, 100) === 0)
