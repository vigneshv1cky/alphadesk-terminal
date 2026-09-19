import type { ChartBar } from "@/lib/api"

/** Overlay indicator math, computed in the browser from the bars already on
 * screen.
 *
 * Client-side on purpose. RSI and MACD are computed on the server because the
 * server also decides whether the feed is dense enough to trust them — that
 * gate is a product rule, not a display detail. A moving average carries no
 * such claim: it is a restatement of the closes you can already see, so
 * computing it here costs one pass over an array the page is holding anyway
 * and adds no round trip when you toggle it.
 *
 * Every function returns an array the same length as its input, with `null`
 * wherever the window has not filled yet, so a caller can zip it against the
 * bars by index without tracking an offset.
 */

export type Point = { t: string; v: number }

function zip(bars: ChartBar[], values: (number | null)[]): Point[] {
  const out: Point[] = []
  for (let i = 0; i < bars.length; i++) {
    const v = values[i]
    if (v != null && Number.isFinite(v)) out.push({ t: bars[i].t, v })
  }
  return out
}

export function sma(bars: ChartBar[], period: number): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  let sum = 0
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c
    if (i >= period) sum -= bars[i - period].c
    if (i >= period - 1) out[i] = sum / period
  }
  return zip(bars, out)
}

export function ema(bars: ChartBar[], period: number): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  const k = 2 / (period + 1)
  let prev: number | null = null
  for (let i = 0; i < bars.length; i++) {
    // Seeded with a simple average of the first `period` closes rather than
    // the first close alone — seeding on one print lets a single outlier bias
    // the whole series, and on a sparse feed that first print is exactly the
    // one most likely to be unrepresentative.
    if (i === period - 1) {
      let s = 0
      for (let j = 0; j < period; j++) s += bars[j].c
      prev = s / period
      out[i] = prev
    } else if (prev != null) {
      prev = bars[i].c * k + prev * (1 - k)
      out[i] = prev
    }
  }
  return zip(bars, out)
}

/** Bollinger bands — the middle SMA plus/minus `mult` standard deviations.
 * Population deviation over the window, which is what the standard defines. */
export function bollinger(bars: ChartBar[], period = 20, mult = 2): {
  upper: Point[]; middle: Point[]; lower: Point[]
} {
  const up: (number | null)[] = new Array(bars.length).fill(null)
  const mid: (number | null)[] = new Array(bars.length).fill(null)
  const low: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += bars[j].c
    const mean = sum / period
    let variance = 0
    for (let j = i - period + 1; j <= i; j++) variance += (bars[j].c - mean) ** 2
    const sd = Math.sqrt(variance / period)
    mid[i] = mean
    up[i] = mean + mult * sd
    low[i] = mean - mult * sd
  }
  return { upper: zip(bars, up), middle: zip(bars, mid), lower: zip(bars, low) }
}

/** Volume-weighted average price, reset at each session boundary.
 *
 * The reset matters: VWAP is a session statistic, and carrying it across an
 * overnight gap produces a line that means nothing on either day. Bars carry
 * an ISO timestamp, so the date part is the session key.
 */
export function vwap(bars: ChartBar[]): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  let day = ""
  let pv = 0
  let vol = 0
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]
    const d = b.t.slice(0, 10)
    if (d !== day) { day = d; pv = 0; vol = 0 }
    const typical = (b.h + b.l + b.c) / 3
    const v = b.v ?? 0
    pv += typical * v
    vol += v
    out[i] = vol > 0 ? pv / vol : null
  }
  return zip(bars, out)
}

/** Weighted moving average — linearly weighted, heaviest on the newest close.
 * Between an SMA and an EMA in how fast it turns. */
export function wma(bars: ChartBar[], period: number): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  const denom = (period * (period + 1)) / 2
  for (let i = period - 1; i < bars.length; i++) {
    let acc = 0
    for (let k = 0; k < period; k++) acc += bars[i - period + 1 + k].c * (k + 1)
    out[i] = acc / denom
  }
  return zip(bars, out)
}

/** Take a Point series back to a bar-shaped array so an EMA can be run over
 * it. DEMA and TEMA are EMAs of EMAs, and this is the join between them. */
function asBars(bars: ChartBar[], pts: Point[]): ChartBar[] {
  const by = new Map(pts.map(p => [p.t, p.v]))
  return bars.filter(b => by.has(b.t)).map(b => ({ ...b, c: by.get(b.t)! }))
}

/** Double EMA: 2·EMA − EMA(EMA). Cuts the lag an EMA carries. */
export function dema(bars: ChartBar[], period: number): Point[] {
  const e1 = ema(bars, period)
  const e2 = ema(asBars(bars, e1), period)
  const by1 = new Map(e1.map(p => [p.t, p.v]))
  return e2.map(p => ({ t: p.t, v: 2 * (by1.get(p.t) ?? p.v) - p.v }))
}

/** Triple EMA: 3·EMA − 3·EMA² + EMA³. Less lag again, more noise with it. */
export function tema(bars: ChartBar[], period: number): Point[] {
  const e1 = ema(bars, period)
  const e2 = ema(asBars(bars, e1), period)
  const e3 = ema(asBars(bars, e2), period)
  const by1 = new Map(e1.map(p => [p.t, p.v]))
  const by2 = new Map(e2.map(p => [p.t, p.v]))
  return e3.map(p => ({
    t: p.t,
    v: 3 * (by1.get(p.t) ?? p.v) - 3 * (by2.get(p.t) ?? p.v) + p.v,
  }))
}

/** True range: the greater of today's spread and the two gaps to yesterday's
 * close. The input to ATR, Keltner's width and ADX alike. */
function trueRange(bars: ChartBar[]): number[] {
  return bars.map((b, i) =>
    i === 0 ? b.h - b.l
      : Math.max(b.h - b.l, Math.abs(b.h - bars[i - 1].c), Math.abs(b.l - bars[i - 1].c)))
}

/** Wilder's smoothing: the running average he defined for ATR, ADX and RSI —
 * a 1/period EMA seeded on a simple mean. Distinct from `ema`, whose 2/(n+1)
 * factor makes it turn roughly twice as fast, so the two are NOT
 * interchangeable even though both are "smoothed averages". */
function rma(values: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let prev: number | null = null
  let seed = 0, seen = 0
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v == null || !Number.isFinite(v)) continue
    if (prev == null) {
      seed += v
      if (++seen === period) { prev = seed / period; out[i] = prev }
    } else {
      prev = (prev * (period - 1) + v) / period
      out[i] = prev
    }
  }
  return out
}

/** Keltner's width. A SIMPLE mean of true range, not Wilder's — kept as it
 * was so the existing channel does not silently move; the ATR pane below uses
 * Wilder's, which is what "ATR" means when it is the thing being read. */
function atr(bars: ChartBar[], period: number): (number | null)[] {
  const tr = trueRange(bars)
  const out: (number | null)[] = new Array(bars.length).fill(null)
  let sum = 0
  for (let i = 0; i < bars.length; i++) {
    sum += tr[i]
    if (i >= period) sum -= tr[i - period]
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}

/** Keltner channels — an EMA centre with ATR-scaled rails. Unlike Bollinger,
 * the width tracks true range rather than closing deviation, so a gap widens
 * it where Bollinger would shrug. */
export function keltner(bars: ChartBar[], period = 20, mult = 2): {
  upper: Point[]; middle: Point[]; lower: Point[]
} {
  const mid = ema(bars, period)
  const a = atr(bars, period)
  const byIndex = new Map(bars.map((b, i) => [b.t, i]))
  const up: Point[] = [], low: Point[] = []
  for (const p of mid) {
    const i = byIndex.get(p.t)!
    const width = a[i]
    if (width == null) continue
    up.push({ t: p.t, v: p.v + mult * width })
    low.push({ t: p.t, v: p.v - mult * width })
  }
  return { upper: up, middle: mid, lower: low }
}

/** Donchian price channel — the highest high and lowest low of the window. */
export function priceChannel(bars: ChartBar[], period = 20): {
  upper: Point[]; lower: Point[]
} {
  const up: (number | null)[] = new Array(bars.length).fill(null)
  const low: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period - 1; i < bars.length; i++) {
    let hi = -Infinity, lo = Infinity
    for (let j = i - period + 1; j <= i; j++) {
      hi = Math.max(hi, bars[j].h)
      lo = Math.min(lo, bars[j].l)
    }
    up[i] = hi; low[i] = lo
  }
  return { upper: zip(bars, up), lower: zip(bars, low) }
}

/** Price envelopes — an SMA shifted by a fixed percentage either way. */
export function envelopes(bars: ChartBar[], period = 20, pct = 2.5): {
  upper: Point[]; middle: Point[]; lower: Point[]
} {
  const mid = sma(bars, period)
  const k = pct / 100
  return {
    middle: mid,
    upper: mid.map(p => ({ t: p.t, v: p.v * (1 + k) })),
    lower: mid.map(p => ({ t: p.t, v: p.v * (1 - k) })),
  }
}

/* ── Oscillators ─────────────────────────────────────────────────────────────
 *
 * These draw in their OWN pane rather than over price, because none of them is
 * in price units — %R runs -100..0, OBV is a share count, ATR is a spread.
 *
 * All computed here from the bars already on screen, like the overlays above.
 * RSI and MACD stay server-side because the server is also what measures
 * whether the feed can support them; these inherit that same verdict rather
 * than making their own (see CHART_MIN_COVERAGE) — an oscillator on a sparse
 * feed is precisely the chart that looks right and is not.
 */

/** Highest high and lowest low over the window ending at `i`. */
function extremes(bars: ChartBar[], i: number, period: number): { hi: number; lo: number } {
  let hi = -Infinity, lo = Infinity
  for (let j = i - period + 1; j <= i; j++) {
    if (bars[j].h > hi) hi = bars[j].h
    if (bars[j].l < lo) lo = bars[j].l
  }
  return { hi, lo }
}

const typicalPrice = (b: ChartBar) => (b.h + b.l + b.c) / 3

/** Stochastic oscillator. %K is where the close sits inside the window's
 * range; %D is its 3-period average. A window with no range at all is 50 —
 * dead centre — rather than a divide by zero. */
export function stochastic(bars: ChartBar[], kPeriod = 14, dPeriod = 3): { k: Point[]; d: Point[] } {
  const kRaw: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = kPeriod - 1; i < bars.length; i++) {
    const { hi, lo } = extremes(bars, i, kPeriod)
    kRaw[i] = hi === lo ? 50 : ((bars[i].c - lo) / (hi - lo)) * 100
  }
  const dRaw: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = kPeriod + dPeriod - 2; i < bars.length; i++) {
    let sum = 0
    for (let j = i - dPeriod + 1; j <= i; j++) sum += kRaw[j] ?? 0
    dRaw[i] = sum / dPeriod
  }
  return { k: zip(bars, kRaw), d: zip(bars, dRaw) }
}

/** Williams %R — the stochastic measured from the top of the range, so it runs
 * -100 (at the low) to 0 (at the high). */
export function williamsR(bars: ChartBar[], period = 14): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period - 1; i < bars.length; i++) {
    const { hi, lo } = extremes(bars, i, period)
    out[i] = hi === lo ? -50 : ((hi - bars[i].c) / (hi - lo)) * -100
  }
  return zip(bars, out)
}

/** Commodity Channel Index. The 0.015 is Lambert's constant, chosen so most
 * readings land inside ±100; it is not a unit conversion. */
export function cci(bars: ChartBar[], period = 20): Point[] {
  const tp = bars.map(typicalPrice)
  const out: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += tp[j]
    const mean = sum / period
    let dev = 0
    for (let j = i - period + 1; j <= i; j++) dev += Math.abs(tp[j] - mean)
    const md = dev / period
    out[i] = md === 0 ? 0 : (tp[i] - mean) / (0.015 * md)
  }
  return zip(bars, out)
}

/** Rate of change, as a percentage of the close `period` bars back. */
export function roc(bars: ChartBar[], period = 12): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period; i < bars.length; i++) {
    const base = bars[i - period].c
    out[i] = base === 0 ? null : ((bars[i].c - base) / base) * 100
  }
  return zip(bars, out)
}

/** Money Flow Index — RSI weighted by volume, so it needs volume to mean
 * anything. A window with no turnover at all yields nothing rather than the
 * 100 the formula would otherwise report from an empty denominator. */
export function mfi(bars: ChartBar[], period = 14): Point[] {
  const tp = bars.map(typicalPrice)
  const out: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = period; i < bars.length; i++) {
    let pos = 0, neg = 0
    for (let j = i - period + 1; j <= i; j++) {
      const flow = tp[j] * (bars[j].v ?? 0)
      if (tp[j] > tp[j - 1]) pos += flow
      else if (tp[j] < tp[j - 1]) neg += flow
    }
    if (pos + neg === 0) continue
    out[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg)
  }
  return zip(bars, out)
}

/** Average true range, Wilder's smoothing. In price units, so its pane scale
 * is the symbol's own — not comparable across symbols. */
export function atrSeries(bars: ChartBar[], period = 14): Point[] {
  return zip(bars, rma(trueRange(bars), period))
}

/** On-balance volume: a running total that adds the day's volume on an up
 * close and subtracts it on a down one. The LEVEL is arbitrary — only its
 * direction, and whether it agrees with price, carries information. */
export function obv(bars: ChartBar[]): Point[] {
  const out: (number | null)[] = new Array(bars.length).fill(null)
  let acc = 0
  for (let i = 0; i < bars.length; i++) {
    const v = bars[i].v ?? 0
    if (i > 0) {
      if (bars[i].c > bars[i - 1].c) acc += v
      else if (bars[i].c < bars[i - 1].c) acc -= v
    }
    out[i] = acc
  }
  return zip(bars, out)
}

/** ADX with its two directional lines. ADX measures trend STRENGTH only — it
 * says nothing about direction, which is what +DI/-DI are drawn alongside it
 * for. Conventionally read as trending above 25. */
export function adx(bars: ChartBar[], period = 14): { adx: Point[]; plusDI: Point[]; minusDI: Point[] } {
  const n = bars.length
  const plusDM: number[] = new Array(n).fill(0)
  const minusDM: number[] = new Array(n).fill(0)
  for (let i = 1; i < n; i++) {
    const up = bars[i].h - bars[i - 1].h
    const down = bars[i - 1].l - bars[i].l
    // Only the LARGER of the two moves counts, and only if it is outward.
    plusDM[i] = up > down && up > 0 ? up : 0
    minusDM[i] = down > up && down > 0 ? down : 0
  }
  const trS = rma(trueRange(bars), period)
  const pS = rma(plusDM, period)
  const mS = rma(minusDM, period)
  const pdi: (number | null)[] = new Array(n).fill(null)
  const mdi: (number | null)[] = new Array(n).fill(null)
  const dx: (number | null)[] = new Array(n).fill(null)
  for (let i = 0; i < n; i++) {
    const t = trS[i], p = pS[i], m = mS[i]
    if (t == null || p == null || m == null || t === 0) continue
    const P = (100 * p) / t, M = (100 * m) / t
    pdi[i] = P
    mdi[i] = M
    dx[i] = P + M === 0 ? 0 : (100 * Math.abs(P - M)) / (P + M)
  }
  return { adx: zip(bars, rma(dx, period)), plusDI: zip(bars, pdi), minusDI: zip(bars, mdi) }
}

/** The indicators that get their own pane under price. RSI and MACD come from
 * the server; the rest are computed above. */
export type PaneId = "rsi" | "macd" | "stoch" | "williams" | "cci" | "roc" | "mfi" | "atr" | "obv" | "adx"

/** `minBars` is the indicator's own WARM-UP: how many bars it needs before it
 * produces anything worth drawing. Per indicator on purpose. A single global
 * threshold has to be set to the hungriest one — MACD's 26+9 — and then hides
 * RSI-9 from a 24-bar month that supports it fine, which is what made a switch
 * to the 1M range silently drop every pane the reader had chosen. */
export const PANE_INDICATORS: { id: PaneId; label: string; group: string; minBars: number }[] = [
  { id: "rsi",      label: "Relative Strength Index (9)",    group: "Momentum",   minBars: 9 },
  { id: "stoch",    label: "Stochastic Oscillator (14, 3)",  group: "Momentum",   minBars: 17 },
  { id: "williams", label: "Williams %R (14)",               group: "Momentum",   minBars: 14 },
  { id: "cci",      label: "Commodity Channel Index (20)",   group: "Momentum",   minBars: 20 },
  { id: "roc",      label: "Rate of Change (12)",            group: "Momentum",   minBars: 13 },
  { id: "macd",     label: "MACD (12, 26, 9)",               group: "Trend",      minBars: 35 },
  // Wilder smooths twice, so ADX needs about two periods before it settles.
  { id: "adx",      label: "Average Directional Index (14)", group: "Trend",      minBars: 28 },
  { id: "atr",      label: "Average True Range (14)",        group: "Volatility", minBars: 14 },
  { id: "mfi",      label: "Money Flow Index (14)",          group: "Volume",     minBars: 15 },
  { id: "obv",      label: "On-Balance Volume",              group: "Volume",     minBars: 2 },
]

export type OverlayId =
  | "sma20" | "sma50" | "ema20" | "ema50" | "wma20" | "dema20" | "tema20"
  | "bb" | "keltner" | "channel" | "envelopes" | "vwap"

/** Grouped the way theirs groups them, so the menu can be scanned by kind
 * rather than read end to end. */
export const OVERLAYS: { id: OverlayId; label: string; color: string; group: string }[] = [
  { id: "sma20",     label: "Simple Moving Average (20)",            color: "var(--n800)", group: "Moving averages" },
  { id: "sma50",     label: "Simple Moving Average (50)",            color: "var(--n600)", group: "Moving averages" },
  { id: "ema20",     label: "Exponential Moving Average (20)",       color: "var(--accent-700)", group: "Moving averages" },
  { id: "ema50",     label: "Exponential Moving Average (50)",       color: "var(--accent-600)", group: "Moving averages" },
  { id: "wma20",     label: "Weighted Moving Average (20)",          color: "var(--n500)", group: "Moving averages" },
  { id: "dema20",    label: "Double Exponential Moving Average (20)", color: "var(--n400)", group: "Moving averages" },
  { id: "tema20",    label: "Triple Exponential Moving Average (20)", color: "var(--n300)", group: "Moving averages" },
  { id: "bb",        label: "Bollinger Bands (20, 2)",               color: "var(--n600)", group: "Bands & channels" },
  { id: "keltner",   label: "Keltner Channels (20, 2)",              color: "var(--n500)", group: "Bands & channels" },
  { id: "channel",   label: "Price Channel (20)",                    color: "var(--n400)", group: "Bands & channels" },
  { id: "envelopes", label: "Price Envelopes (20, 2.5%)",            color: "var(--n600)", group: "Bands & channels" },
  { id: "vwap",      label: "VWAP",                                  color: "var(--accent)", group: "Volume" },
]


/** RSI, Wilder's — average gain over average loss, both by his smoothing,
 * which is what every charting package means by the name. */
export function rsi(bars: ChartBar[], period = 14): Point[] {
  const gains: (number | null)[] = [null]
  const losses: (number | null)[] = [null]
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i].c - bars[i - 1].c
    gains.push(Math.max(0, d))
    losses.push(Math.max(0, -d))
  }
  const ag = rma(gains, period)
  const al = rma(losses, period)
  const out: (number | null)[] = new Array(bars.length).fill(null)
  for (let i = 0; i < bars.length; i++) {
    const g = ag[i], l = al[i]
    if (g == null || l == null) continue
    out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l)
  }
  return zip(bars, out)
}

/** An EMA over an index-aligned series that may start with nulls — the
 * signal line of MACD is an EMA of a line that itself has a warm-up. */
function emaOver(values: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  const k = 2 / (period + 1)
  let prev: number | null = null
  let seed = 0, seen = 0
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v == null || !Number.isFinite(v)) continue
    if (prev == null) {
      seed += v
      if (++seen === period) { prev = seed / period; out[i] = prev }
    } else {
      prev = v * k + prev * (1 - k)
      out[i] = prev
    }
  }
  return out
}

/** MACD: fast EMA minus slow EMA, its signal EMA, and the difference. */
export function macd(bars: ChartBar[], fast = 12, slow = 26, signal = 9): {
  macd: Point[]; signal: Point[]; hist: Point[]
} {
  const closes = bars.map(b => b.c)
  const f = emaOver(closes, fast)
  const sl = emaOver(closes, slow)
  const line: (number | null)[] = closes.map((_, i) =>
    f[i] != null && sl[i] != null ? (f[i] as number) - (sl[i] as number) : null)
  const sig = emaOver(line, signal)
  const hist: (number | null)[] = line.map((v, i) =>
    v != null && sig[i] != null ? v - (sig[i] as number) : null)
  return { macd: zip(bars, line), signal: zip(bars, sig), hist: zip(bars, hist) }
}

// ── The catalogue (2026-09-05) ─────────────────────────────────────────────
//
// An indicator on a chart is an INSTANCE of a type with its own parameters,
// colour and weight — two SMAs of different lengths are two instances, and
// each has a settings dialog. The catalogue below is the types; `Indicator`
// is the instance the prefs persist. `OVERLAYS` and `PANE_INDICATORS` above
// survive only to migrate prefs written before this.

export type IndicatorType =
  | "sma" | "ema" | "wma" | "dema" | "tema" | "bb" | "keltner" | "channel" | "envelopes" | "vwap"
  | "rsi" | "macd" | "stoch" | "williams" | "cci" | "roc" | "mfi" | "atr" | "obv" | "adx"

export type ParamDef = {
  key: string; label: string; min: number; max: number; step?: number; def: number
  /** Left out of the legend name — RSI's band levels are settings, not part
   * of what the reading is called. */
  legend?: false
}
export type IndicatorDef = {
  type: IndicatorType
  label: string
  /** The legend's short name — "SMA", "MACD". */
  short: string
  group: string
  place: "overlay" | "pane"
  params: ParamDef[]
  color: string
  /** Warm-up in bars, from the params: how many the indicator needs before
   * it produces anything worth drawing. Per indicator, so a shorter range
   * drops only what genuinely cannot be computed. */
  warmup: (p: Record<string, number>) => number
  /** Declares a fixed scale (RSI's 0–100). Bounded panes get a taller box. */
  bounded?: boolean
}

const len = (def: number, max = 500): ParamDef => ({ key: "length", label: "Length", min: 1, max, def })

export const INDICATORS: IndicatorDef[] = [
  { type: "sma", label: "Simple Moving Average", short: "SMA", group: "Moving averages", place: "overlay",
    params: [len(20)], color: "var(--n800)", warmup: p => p.length },
  { type: "ema", label: "Exponential Moving Average", short: "EMA", group: "Moving averages", place: "overlay",
    params: [len(20)], color: "var(--accent-700)", warmup: p => p.length },
  { type: "wma", label: "Weighted Moving Average", short: "WMA", group: "Moving averages", place: "overlay",
    params: [len(20)], color: "var(--n500)", warmup: p => p.length },
  { type: "dema", label: "Double Exponential Moving Average", short: "DEMA", group: "Moving averages", place: "overlay",
    params: [len(20)], color: "var(--n400)", warmup: p => p.length * 2 },
  { type: "tema", label: "Triple Exponential Moving Average", short: "TEMA", group: "Moving averages", place: "overlay",
    params: [len(20)], color: "var(--n300)", warmup: p => p.length * 3 },
  { type: "bb", label: "Bollinger Bands", short: "BB", group: "Bands & channels", place: "overlay",
    params: [len(20), { key: "mult", label: "StdDev", min: 0.1, max: 10, step: 0.1, def: 2 }],
    color: "var(--n600)", warmup: p => p.length },
  { type: "keltner", label: "Keltner Channels", short: "KC", group: "Bands & channels", place: "overlay",
    params: [len(20), { key: "mult", label: "Multiplier", min: 0.1, max: 10, step: 0.1, def: 2 }],
    color: "var(--n500)", warmup: p => p.length },
  { type: "channel", label: "Price Channel", short: "PC", group: "Bands & channels", place: "overlay",
    params: [len(20)], color: "var(--n400)", warmup: p => p.length },
  { type: "envelopes", label: "Price Envelopes", short: "ENV", group: "Bands & channels", place: "overlay",
    params: [len(20), { key: "pct", label: "Percent", min: 0.1, max: 50, step: 0.1, def: 2.5 }],
    color: "var(--n600)", warmup: p => p.length },
  { type: "vwap", label: "VWAP", short: "VWAP", group: "Volume", place: "overlay",
    params: [], color: "var(--accent)", warmup: () => 1 },

  { type: "rsi", label: "Relative Strength Index", short: "RSI", group: "Momentum", place: "pane", bounded: true,
    params: [len(9), { key: "oversold", label: "Oversold", min: 1, max: 49, def: 30, legend: false },
             { key: "overbought", label: "Overbought", min: 51, max: 99, def: 70, legend: false }],
    color: "var(--foreground)", warmup: p => p.length + 1 },
  { type: "stoch", label: "Stochastic Oscillator", short: "Stoch", group: "Momentum", place: "pane", bounded: true,
    params: [{ key: "k", label: "%K length", min: 1, max: 200, def: 14 }, { key: "d", label: "%D smoothing", min: 1, max: 50, def: 3 }],
    color: "var(--foreground)", warmup: p => p.k + p.d },
  { type: "williams", label: "Williams %R", short: "%R", group: "Momentum", place: "pane", bounded: true,
    params: [len(14)], color: "var(--foreground)", warmup: p => p.length },
  { type: "cci", label: "Commodity Channel Index", short: "CCI", group: "Momentum", place: "pane",
    params: [len(20)], color: "var(--foreground)", warmup: p => p.length },
  { type: "roc", label: "Rate of Change", short: "ROC", group: "Momentum", place: "pane",
    params: [len(12)], color: "var(--foreground)", warmup: p => p.length + 1 },
  { type: "macd", label: "MACD", short: "MACD", group: "Trend", place: "pane",
    params: [{ key: "fast", label: "Fast length", min: 1, max: 200, def: 12 },
             { key: "slow", label: "Slow length", min: 2, max: 400, def: 26 },
             { key: "signal", label: "Signal smoothing", min: 1, max: 100, def: 9 }],
    color: "var(--foreground)", warmup: p => p.slow + p.signal },
  // Wilder smooths twice, so ADX needs about two periods before it settles.
  { type: "adx", label: "Average Directional Index", short: "ADX", group: "Trend", place: "pane", bounded: true,
    params: [len(14)], color: "var(--n500)", warmup: p => p.length * 2 },
  { type: "atr", label: "Average True Range", short: "ATR", group: "Volatility", place: "pane",
    params: [len(14)], color: "var(--foreground)", warmup: p => p.length },
  { type: "mfi", label: "Money Flow Index", short: "MFI", group: "Volume", place: "pane", bounded: true,
    params: [len(14)], color: "var(--foreground)", warmup: p => p.length + 1 },
  { type: "obv", label: "On-Balance Volume", short: "OBV", group: "Volume", place: "pane",
    params: [], color: "var(--n500)", warmup: () => 2 },
]

export type Indicator = {
  id: string
  type: IndicatorType
  params: Record<string, number>
  color?: string
  width?: number
  hidden?: boolean
}

export const indicatorDef = (type: IndicatorType) => INDICATORS.find(d => d.type === type)!

let seq = 0
/** Snap a parameter onto its step — whole numbers for a length, the
 * declared step otherwise — inside its bounds. A fractional length (20.5)
 * indexed a bar that did not exist and unmounted the whole board. */
export function quantizeParam(d: ParamDef, v: number): number {
  const step = d.step ?? 1
  const snapped = Math.round(v / step) * step
  return Math.min(d.max, Math.max(d.min, Number(snapped.toFixed(6))))
}

/** Every param on its step and in bounds, and the relations between them
 * kept (MACD's fast below its slow). What the computations read. */
export function cleanParams(def: IndicatorDef, params: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const d of def.params) {
    const v = params[d.key]
    out[d.key] = typeof v === "number" && Number.isFinite(v) ? quantizeParam(d, v) : d.def
  }
  if ("fast" in out && "slow" in out && out.fast >= out.slow) {
    const f = def.params.find(d => d.key === "fast"), s = def.params.find(d => d.key === "slow")
    if (f && s) { out.fast = f.def; out.slow = s.def }
  }
  return out
}

export function newIndicator(type: IndicatorType, params: Record<string, number> = {}, color?: string): Indicator {
  const def = indicatorDef(type)
  const p: Record<string, number> = {}
  for (const d of def.params) p[d.key] = params[d.key] ?? d.def
  const ind: Indicator = { id: `${type}-${Date.now().toString(36)}${(seq++).toString(36)}`, type, params: p }
  if (color) ind.color = color
  return ind
}

/** "SMA 20", "BB 20 2", "MACD 12 26 9" — the name the legend shows. */
export function indicatorLabel(ind: Indicator): string {
  const def = indicatorDef(ind.type)
  const vals = def.params.filter(d => d.legend !== false).map(d => ind.params[d.key] ?? d.def)
  return [def.short, ...vals].join(" ")
}

/** What a legacy pref id meant, so a chart set up before instances keeps
 * its indicators rather than losing them to a schema change. */
export const LEGACY: Record<string, { type: IndicatorType; params?: Record<string, number>; color?: string }> = {
  sma20: { type: "sma", params: { length: 20 }, color: "var(--n800)" },
  sma50: { type: "sma", params: { length: 50 }, color: "var(--n600)" },
  ema20: { type: "ema", params: { length: 20 }, color: "var(--accent-700)" },
  ema50: { type: "ema", params: { length: 50 }, color: "var(--accent-600)" },
  wma20: { type: "wma" }, dema20: { type: "dema" }, tema20: { type: "tema" },
  bb: { type: "bb" }, keltner: { type: "keltner" }, channel: { type: "channel" },
  envelopes: { type: "envelopes" }, vwap: { type: "vwap" },
  rsi: { type: "rsi" }, macd: { type: "macd" }, stoch: { type: "stoch" }, williams: { type: "williams" },
  cci: { type: "cci" }, roc: { type: "roc" }, mfi: { type: "mfi" }, atr: { type: "atr" },
  obv: { type: "obv" }, adx: { type: "adx" },
}

export type OverlaySeries = { id: string; color: string; points: Point[]; width?: number }

/** Turn the overlay instances into series the renderer can draw.
 *
 * The band indicators expand to several lines, so this returns a flat list
 * tagged with the instance id rather than one entry per instance — the
 * renderer should not have to know which indicators happen to be multi-line,
 * and the legend can still find its own lines. */
export function buildOverlays(bars: ChartBar[], inds: Indicator[]): OverlaySeries[] {
  const out: OverlaySeries[] = []
  inds = inds.map(i => ({ ...i, params: cleanParams(indicatorDef(i.type), i.params) }))
  const fade = (c: string, a: number) => {
    // Token references cannot be faded arithmetically; opacity via a
    // colour-mix keeps the theme's colour and drops its weight.
    if (!c.startsWith("#")) return `color-mix(in srgb, ${c} ${Math.round(a * 100)}%, transparent)`
    const n = c.replace("#", "")
    const v = parseInt(n.length === 3 ? n.split("").map(ch => ch + ch).join("") : n, 16)
    return `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${a})`
  }
  for (const ind of inds) {
    const def = indicatorDef(ind.type)
    if (def.place !== "overlay" || ind.hidden) continue
    const c = ind.color ?? def.color
    const w = ind.width ?? 1
    const p = ind.params
    const one = (points: Point[]) => out.push({ id: ind.id, color: c, points, width: w })
    const band = (upper: Point[], middle: Point[] | null, lower: Point[]) => {
      out.push({ id: ind.id, color: fade(c, 0.75), points: upper, width: w })
      if (middle) out.push({ id: ind.id, color: fade(c, 0.45), points: middle, width: w })
      out.push({ id: ind.id, color: fade(c, 0.75), points: lower, width: w })
    }
    switch (ind.type) {
      case "sma": one(sma(bars, p.length)); break
      case "ema": one(ema(bars, p.length)); break
      case "wma": one(wma(bars, p.length)); break
      case "dema": one(dema(bars, p.length)); break
      case "tema": one(tema(bars, p.length)); break
      case "vwap": one(vwap(bars)); break
      case "bb": { const b = bollinger(bars, p.length, p.mult); band(b.upper, b.middle, b.lower); break }
      case "keltner": { const k = keltner(bars, p.length, p.mult); band(k.upper, k.middle, k.lower); break }
      case "envelopes": { const e = envelopes(bars, p.length, p.pct); band(e.upper, e.middle, e.lower); break }
      case "channel": { const ch = priceChannel(bars, p.length); band(ch.upper, null, ch.lower); break }
    }
  }
  return out
}
