import type { ChartBar } from "@/lib/api"
// Relative with an explicit extension, not the usual `@/` alias: this is a
// VALUE import now, and `pnpm test` runs these files through bare Node, which
// knows nothing about Vite's alias. The type-only import this replaced was
// erased before Node ever tried to resolve it, so the alias cost nothing then
// and breaks the scale-math test now.
import {
  adx, atrSeries, cci, indicatorDef, indicatorLabel, macd, mfi, obv, roc, rsi, stochastic, williamsR,
  type Indicator, type Point, cleanParams } from "../../lib/indicators.ts"
import { indexToX, type Scale } from "../../lib/chartScales.ts"

/** Pane definitions for the renderer.
 *
 * A pane is a horizontal band under the price with its OWN y scale. That
 * independence is the whole point: volume is in millions of shares, RSI is
 * bounded 0–100, and revenue is in billions. Sharing one axis would flatten
 * every one of them except the largest into the floor.
 *
 * They share the x scale, because they are all describing the same bars — a
 * pane that scrolled independently of the price above it would be lying about
 * which bar a value belongs to.
 */

export type PaneSeries =
  | {
      kind: "histogram"; points: Point[]; color: string; downColor?: string; signs?: boolean
      /** Four shades rather than two: a column that is SHRINKING toward zero
       * draws lighter than one growing away from it, which is how a MACD
       * histogram says "the divergence is fading" before it crosses. */
      shade?: boolean
      /** Sum into wider columns when the bars get denser than the pixels.
       * Opt-in because it is only meaningful for a QUANTITY: summing a bucket
       * of volume is still volume, whereas summing a bucket of MACD histogram
       * values is not any reading at all. */
      aggregate?: boolean
    }
  | { kind: "line"; points: Point[]; color: string; width?: number }
  | { kind: "area"; points: Point[]; color: string }

export type Pane = {
  id: string
  height: number
  series: PaneSeries[]
  /** Fixed scale, for a bounded indicator like RSI. Omitted means fit to data. */
  range?: { min: number; max: number }
  /** Horizontal reference lines — RSI's 30/70, MACD's zero. */
  levels?: number[]
  /** Drawn top-left inside the pane, so a stack of them stays legible. */
  label?: string
  /** A tinted band between two levels — RSI's 30–70 — so the neutral zone
   * reads as a zone rather than as two unrelated dashed lines. */
  band?: { from: number; to: number; color: string }
  /** How to format this pane's axis. Volume and revenue want compact
   * notation; an oscillator wants plain numbers. */
  compact?: boolean
  /** Measure the axis over the WHOLE series rather than the bars on screen
   * (2026-09-21, the owner: volume "changes perception that volume was high
   * or low when it wasn't"). For a QUANTITY the height of a column is the
   * reading, so a scale that re-fits as you pan makes a quiet bar look busy
   * the moment the busy ones scroll off. An oscillator is the opposite case
   * — see paneExtent — so this is opt-in, and volume is the one that takes
   * it. */
  steady?: boolean
}

const fmtCompact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })

export function paneAxisLabel(v: number, compact?: boolean): string {
  if (compact) return fmtCompact.format(v)
  return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)
}

/** The volume band. Coloured by each bar's own direction, because volume alone
 * says nothing about which way the move went. */
export function volumePane(bars: ChartBar[], height: number, gain: string, loss: string): Pane | null {
  if (!bars.some(b => b.v)) return null
  return {
    id: "volume",
    height,
    compact: true,
    // One scale for the whole series: a column's height IS the reading.
    steady: true,
    series: [{
      kind: "histogram",
      points: bars.map(b => ({ t: b.t, v: b.v ?? 0 })),
      color: gain,
      downColor: loss,
      // Direction comes from the bar, not the value's sign.
      signs: false,
      // A session of minute bars is thousands of one-pixel columns — a solid
      // block rather than a histogram. Summed buckets are still volume.
      aggregate: true,
    }],
  }
}

/** THE FLOOR A COLUMN IS DRAWN TO, in pixels (2026-09-21, the owner: "keep a
 * minimum height for bars, so even low ones are visible"). With the volume
 * band measured over the whole series, one busy session leaves a quiet one
 * sub-pixel — present in the data and invisible on the screen, which is the
 * same fault as the scale that moved, in the other direction.
 *
 * A column is held up to this, and a TRUE ZERO is drawn at nothing at all.
 * That distinction is the whole reason this is not simply a minimum: the
 * floor is there so "small" is legible, and zero must stay distinguishable
 * from small rather than being rounded up into it. The previous code held
 * every column to 1px INCLUDING the zeroes, which drew a row of bars along
 * a session with no trades.
 */
export const MIN_COLUMN_PX = 2

/** A column's drawn height: its true height, or the floor when that would be
 * invisible, or nothing at all when the value is zero. Pure. */
export function columnHeight(value: number, zeroY: number, y: number): number {
  if (!value) return 0
  return Math.max(MIN_COLUMN_PX, Math.abs(zeroY - y))
}

/** The min/max a pane's own axis should span.
 *
 * `visible` limits it to the bars on screen, which is what the price pane has
 * always done and what these did not. Scaling a pane to the WHOLE series meant
 * one spike anywhere in it set the scale forever: on a 5-session NVDA window
 * a single -1.35 MACD print against a typical +-0.1 left the middle 90% of
 * every series inside a quarter of the pane, and zooming into a calm stretch
 * did not recover the detail, because the outlier was still counted while
 * being nowhere on screen. Omitted, the whole series is measured, which is
 * still right for a caller that draws all of it.
 */
export function paneExtent(
  pane: Pane, visible?: (t: string) => boolean,
): { min: number; max: number } {
  if (pane.range) return pane.range
  let min = Infinity, max = -Infinity
  for (const s of pane.series) {
    for (const p of s.points) {
      if (visible && !visible(p.t)) continue
      if (p.v < min) min = p.v
      if (p.v > max) max = p.v
    }
  }
  if (!Number.isFinite(min)) return { min: 0, max: 1 }
  // A histogram reads from zero — starting its axis at the smallest bar makes
  // every bar look the same height.
  const histogram = pane.series.some(s => s.kind === "histogram")
  if (histogram) {
    min = Math.min(0, min)
    max = Math.max(0, max)
  }
  if (min === max) return { min: min - 1, max: max + 1 }
  const pad = (max - min) * 0.08
  // Pad away from zero only. Padding a histogram's floor below zero puts a
  // negative tick on an axis that cannot go negative — a volume pane reading
  // "-123M" is simply wrong, and it was.
  return {
    min: histogram && min === 0 ? 0 : min - pad,
    max: histogram && max === 0 ? 0 : max + pad,
  }
}

/** The pane an indicator INSTANCE draws — its params, its colour, its
 * conventional reference lines.
 *
 * One builder rather than ten exports: every one of these is the same shape
 * — a series or two, a scale, and the conventional levels — and the
 * differences between them are data, not control flow the caller should have
 * to know. Returns null when the series is too short to draw, which the
 * caller filters out; a pane with one point in it is a horizontal line that
 * means nothing.
 *
 * Bounded oscillators declare a FIXED range: fitted to its own data, an RSI
 * sitting quietly at 45 all session would be drawn touching both edges of
 * the pane and read as violent. */
export function indicatorPane(
  ind: Indicator,
  bars: ChartBar[],
  height: number,
  theme: { gain: string; loss: string; text: string },
): Pane | null {
  const def = indicatorDef(ind.type)
  const p = cleanParams(def, ind.params)
  const color = ind.color ?? def.color
  const w = ind.width ?? 1.5
  const base = { id: ind.id, height, label: indicatorLabel(ind) }
  const enough = (pts: Point[]) => pts.length >= 2
  const line = (points: Point[], c = color, width = w): PaneSeries => ({ kind: "line", points, color: c, width })

  switch (ind.type) {
    case "rsi": {
      const pts = rsi(bars, p.length)
      if (!enough(pts)) return null
      // The RSI-based moving average theirs draws with it: a 14-bar SMA of
      // the reading, which is what a crossover on the oscillator is judged
      // against.
      const ma: Point[] = []
      const win: number[] = []
      let sum = 0
      for (const pt of pts) {
        win.push(pt.v); sum += pt.v
        if (win.length > 14) sum -= win.shift()!
        if (win.length === 14) ma.push({ t: pt.t, v: sum / 14 })
      }
      return {
        ...base, range: { min: 0, max: 100 },
        levels: [p.oversold, 50, p.overbought],
        band: { from: p.oversold, to: p.overbought, color },
        series: [line(pts), line(ma, "var(--warn)", 1)],
      }
    }
    case "macd": {
      const m = macd(bars, p.fast, p.slow, p.signal)
      if (!enough(m.hist)) return null
      return {
        ...base, levels: [0],
        series: [
          // signs:true — here the VALUE's sign is the direction, unlike
          // volume; shade — a fading column draws lighter than a growing one.
          { kind: "histogram", points: m.hist, color: theme.gain, downColor: theme.loss, signs: true, shade: true },
          line(m.macd), line(m.signal, theme.text),
        ],
      }
    }
    case "stoch": {
      const { k, d } = stochastic(bars, p.k, p.d)
      if (!enough(k)) return null
      return {
        ...base, range: { min: 0, max: 100 }, levels: [20, 50, 80],
        series: [line(k), line(d, "var(--n500)")],
      }
    }
    case "williams": {
      const pts = williamsR(bars, p.length)
      if (!enough(pts)) return null
      return { ...base, range: { min: -100, max: 0 }, levels: [-80, -50, -20], series: [line(pts)] }
    }
    case "cci": {
      const pts = cci(bars, p.length)
      if (!enough(pts)) return null
      // Unbounded in principle, so fitted — but the ±100 rails still drawn,
      // because they are what the reading is conventionally judged against.
      return { ...base, levels: [-100, 0, 100], series: [line(pts)] }
    }
    case "roc": {
      const pts = roc(bars, p.length)
      if (!enough(pts)) return null
      return { ...base, levels: [0], series: [line(pts)] }
    }
    case "mfi": {
      const pts = mfi(bars, p.length)
      if (!enough(pts)) return null       // no volume on this feed → no pane
      return { ...base, range: { min: 0, max: 100 }, levels: [20, 50, 80], series: [line(pts)] }
    }
    case "atr": {
      const pts = atrSeries(bars, p.length)
      if (!enough(pts)) return null
      // Price units, so it gets the plain axis rather than compact notation.
      return { ...base, series: [line(pts)] }
    }
    case "obv": {
      const pts = obv(bars)
      if (!enough(pts)) return null
      // Share counts run to the millions, and the LEVEL carries no meaning —
      // only the slope — so compact notation loses nothing worth keeping.
      return { ...base, compact: true, levels: [0], series: [{ kind: "area", points: pts, color }] }
    }
    case "adx": {
      const { adx: a, plusDI, minusDI } = adx(bars, p.length)
      if (!enough(a)) return null
      // 25 is the conventional trending/not line. ADX alone says nothing about
      // WHICH way, which is why both directional lines are drawn with it.
      return {
        ...base, range: { min: 0, max: 100 }, levels: [25],
        series: [line(plusDI, theme.gain, 1), line(minusDI, theme.loss, 1), line(a)],
      }
    }
    default:
      return null
  }
}

/** Group a histogram's bars into columns wide enough to read.
 *
 * At intraday density there are several bars per pixel, and drawing one 1px
 * column each produces a solid block that reads as a filled area rather than a
 * histogram — which is the single biggest reason our volume band did not look
 * like theirs. Below the threshold nothing is grouped and the bars sit on their
 * own index, exactly as before.
 *
 * A column's direction is where the MAJORITY of its volume came from, not its
 * first or last bar — one big print should not colour a quiet hour.
 *
 * Module scope, not a closure inside the component: it feeds a useMemo, and a
 * function rebuilt every render either has to be left out of the deps (a lie)
 * or put in (defeating the memo).
 */
/** How many bars share one drawn column: 1 when each gets its own, otherwise
 * the bucket width. Anchored to the view's SPAN, so it changes with the zoom
 * and not with a pan — which is what lets a steady axis be measured over the
 * whole series with the same buckets the visible ones are drawn with. Pure. */
export function columnBucket(count: number, s: Scale, plotW: number, minPx: number): number {
  if (plotW / Math.max(1, count) >= minPx) return 1
  return Math.max(1, Math.ceil((s.to - s.from) / Math.max(1, Math.floor(plotW / minPx))))
}

/** The tallest column the whole series would draw at this bucket width — the
 * ceiling a `steady` histogram keeps while the view moves. Pure. */
export function steadyColumnMax(points: Point[], indexOf: (t: string) => number | undefined, per: number): number {
  if (per <= 1) return points.reduce((m, p) => Math.max(m, p.v), 0)
  const sums = new Map<number, number>()
  for (const p of points) {
    const i = indexOf(p.t)
    if (i == null) continue
    const k = Math.floor(i / per)
    sums.set(k, (sums.get(k) ?? 0) + p.v)
  }
  let max = 0
  for (const v of sums.values()) if (v > max) max = v
  return max
}

export function volumeColumns(
entries: { i: number; v: number; up: boolean }[],
s: Scale, plotW: number, minPx: number,
): { x: number; w: number; v: number; up: boolean }[] {
if (!entries.length) return []
const natural = plotW / entries.length
if (natural >= minPx) {
  return entries.map(e => ({
    x: indexToX(s, e.i + 0.5), w: Math.max(1, natural * 0.7), v: e.v, up: e.up,
  }))
}
// Buckets are anchored to the ABSOLUTE bar index (bucket k holds bars
// k*per … k*per+per-1), not to whichever bar happens to be first on
// screen: anchored to the view, every column changed membership, height
// and colour each time the view moved by one bar, and the histogram
// shimmered under a pan. The bucket size follows the view's span, so it
// only changes when the zoom does.
const per = columnBucket(entries.length, s, plotW, minPx)
const buckets = new Map<number, { sum: number; upVol: number }>()
for (const e of entries) {
  const k = Math.floor(e.i / per)
  const b = buckets.get(k) ?? { sum: 0, upVol: 0 }
  b.sum += e.v
  if (e.up) b.upVol += e.v
  buckets.set(k, b)
}
const out: { x: number; w: number; v: number; up: boolean }[] = []
for (const [k, b] of [...buckets.entries()].sort((a, c) => a[0] - c[0])) {
  const x0 = indexToX(s, k * per), x1 = indexToX(s, (k + 1) * per)
  out.push({ x: (x0 + x1) / 2, w: Math.max(1, (x1 - x0) * 0.72), v: b.sum, up: b.upVol * 2 >= b.sum })
}
return out
}

/** Which trading session each bar belongs to, and where the days break.
 *
 * An intraday chart spanning several days is drawn as one continuous line,
 * because the x scale is bar INDEX — so the overnight gap between a 16:00
 * close and the next 09:30 open occupies exactly one bar's width, the same as
 * a single minute. Nothing on the canvas says a night passed there. Marking
 * the breaks is what lets a reader tell a gap-down from a move.
 *
 * Sessions are classified in EASTERN time via Intl, not by a fixed UTC offset:
 * the market keeps its own clock, and a hardcoded -5 would mislabel every bar
 * for the eight months of the year the US is on daylight time.
 *
 * Extended hours are shaded where present, each session in its own tint
 * the way theirs does it — pre-market amber, after-hours blue, the
 * overnight session violet, the regular session on the plain ground.
 * Saturday and Sunday in New York are their own teal band (2026-09-19, the
 * owner's request): only coins trade then, and a weekend drawn as three
 * sessions' tints read as two ordinary days. Sunday from 20:00 stays the
 * overnight session, which opens the stock week then. On the IEX feed that is rare —
 * measured on a 5-session NVDA window, 1,559 regular bars against 8 pre-market
 * and no after-hours at all — so this will usually draw nothing. That is the
 * honest outcome: a band appears when the feed actually printed outside the
 * session, rather than being implied whenever the clock says it could have.
 */
export type SessionKind = "night" | "pre" | "regular" | "after" | "weekend"

export type SessionLayout = {
  /** Runs of consecutive bars in one session kind, as [start, end] indices. */
  bands: { kind: SessionKind; from: number; to: number }[]
  /** Bar indices where the ET calendar date changes — a new trading day. */
  dividers: number[]
}

/** The US equity day in ET, theirs' four sessions: overnight 20:00–04:00,
 * pre-market 04:00–09:30, regular 09:30–16:00, after-hours 16:00–20:00. */
const NIGHT_END_MIN = 4 * 60
const OPEN_MIN = 9 * 60 + 30
const CLOSE_MIN = 16 * 60
const NIGHT_START_MIN = 20 * 60

export function sessionKind(minuteOfDay: number): SessionKind {
  if (minuteOfDay < NIGHT_END_MIN || minuteOfDay >= NIGHT_START_MIN) return "night"
  if (minuteOfDay < OPEN_MIN) return "pre"
  return minuteOfDay < CLOSE_MIN ? "regular" : "after"
}

/** The session of a New York weekday ("Sat", "Sun", …) and minute of day. */
export function sessionOn(weekday: string, minuteOfDay: number): SessionKind {
  if (weekday === "Sat" || (weekday === "Sun" && minuteOfDay < NIGHT_START_MIN)) return "weekend"
  return sessionKind(minuteOfDay)
}

export function sessionLayout(bars: { t: string }[]): SessionLayout {
  const bands: SessionLayout["bands"] = []
  const dividers: number[] = []
  if (!bars.length) return { bands, dividers }

  // One formatter, reused. Constructing one per bar is what makes date
  // handling show up in a profile at a few thousand bars.
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour12: false, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", weekday: "short",
  })

  let day = ""
  let runKind: SessionKind | null = null
  let runFrom = 0

  for (let i = 0; i < bars.length; i++) {
    const p = fmt.formatToParts(new Date(bars[i].t))
    const get = (t: string) => p.find(x => x.type === t)?.value ?? "0"
    const d = `${get("year")}-${get("month")}-${get("day")}`
    // Intl renders midnight as hour 24 under hour12:false; normalise it, or
    // the first bar of a day classifies as after-hours.
    const minute = (Number(get("hour")) % 24) * 60 + Number(get("minute"))
    const kind = sessionOn(get("weekday"), minute)

    if (d !== day) {
      if (day) dividers.push(i)
      day = d
    }
    if (kind !== runKind) {
      if (runKind && runKind !== "regular") bands.push({ kind: runKind, from: runFrom, to: i })
      runKind = kind
      runFrom = i
    }
  }
  if (runKind && runKind !== "regular") bands.push({ kind: runKind, from: runFrom, to: bars.length })
  return { bands, dividers }
}
