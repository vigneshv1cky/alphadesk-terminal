/** The PROVISIONAL line (2026-09-13): what a delayed chart draws past its
 * last consolidated bar.
 *
 * A free Alpaca key's consolidated bars end fifteen minutes ago. The minutes
 * since then are known only from one exchange (IEX): its prints are real,
 * but at a few percent of the volume. So they are never bars — no candle, no
 * volume, no indicator reads them — just closes, drawn as a dashed line the
 * real bars overwrite as they arrive. A live trade extends that line; it does
 * not rewrite the fifteen-minute-old bar, which is what it did before.
 *
 * Pure: the chart engine and the canvas call these, and the tests pin them.
 */
import { intervalSeconds } from "./chartTime.ts"

export type ProvisionalPoint = { t: string; c: number }

/** Server points plus the live trade, one point per interval bucket after
 * the last bar; the trade replaces the close of the bucket it falls in.
 * Empty when the interval has no fixed length or nothing follows the bar. */
export function provisionalPoints(
  lastT: string | undefined, points: ProvisionalPoint[] | undefined,
  tick: { price: number; at: string } | null, interval: string | undefined,
): ProvisionalPoint[] {
  const secs = interval ? intervalSeconds(interval) : null
  const last = lastT ? Date.parse(lastT) : NaN
  if (!secs || !Number.isFinite(last)) return []
  const span = secs * 1000
  const byBucket = new Map<number, ProvisionalPoint>()
  const add = (at: number, p: ProvisionalPoint) => {
    if (!Number.isFinite(at) || at < last + span) return
    const bucket = last + Math.floor((at - last) / span) * span
    byBucket.set(bucket, { t: new Date(bucket).toISOString(), c: p.c })
  }
  for (const p of points ?? []) add(Date.parse(p.t), p)
  if (tick) add(Date.parse(tick.at.replace(" ", "T")), { t: tick.at, c: tick.price })
  return [...byBucket.entries()].sort((a, b) => a[0] - b[0]).map(([, p]) => p)
}

/** Each point's slot count after the last bar — 1 is the bar right after it —
 * so the canvas spaces the line by time on its index axis. */
export function provisionalSlots(
  lastT: string | undefined, points: ProvisionalPoint[], interval: string | undefined,
): { k: number; c: number }[] {
  const secs = interval ? intervalSeconds(interval) : null
  const last = lastT ? Date.parse(lastT) : NaN
  if (!secs || !Number.isFinite(last)) return []
  return points
    .map(p => ({ k: Math.round((Date.parse(p.t) - last) / (secs * 1000)), c: p.c }))
    .filter(p => p.k >= 1)
}

/** Whether a live trade belongs past the last bar of a delayed series —
 * then it goes on the provisional line, not into the bar. */
export function tradeIsPastLastBar(lastT: string, at: string, interval: string | undefined): boolean {
  const secs = interval ? intervalSeconds(interval) : null
  const t = Date.parse(at.replace(" ", "T"))
  if (!secs || !Number.isFinite(t)) return false
  return t >= Date.parse(lastT) + secs * 1000
}

/** The bar still forming, as live trades have moved it. */
export type FormingBar = { series: string; t: string; h: number; l: number }

type TickBar = { t: string; h: number; l: number; c: number }

/** The series with the live trade folded into its last bar: the close is
 * the trade, and the high and low ACCUMULATE across trades (a wick that
 * printed 105 stays at 105 after the price comes back to 100) until the
 * poll delivers a new last bar.
 *
 * The accumulated extremes belong to ONE series, so they are keyed by it
 * and by the bar's time. Keyed by the time alone, switching stocks inside
 * the same minute carried the previous stock's high and low into the new
 * one's last bar (2026-09-15): NVDA's 212 on a $6 stock drew one enormous
 * wick, and the axis stretched to fit it pressed the real prices into a
 * flat line, until the next minute's bar replaced it.
 *
 * Returns the bars (the same array when the trade changes nothing) and
 * the forming record to keep. `tradeIsLate` is for a delayed series, whose
 * newer trades go on the provisional line instead. */
export function foldLiveTrade<B extends TickBar>(
  bars: B[], series: string, tick: { price: number; at: string } | null,
  forming: FormingBar | null, tradeIsLate = false,
): { bars: B[]; forming: FormingBar | null } {
  if (!bars.length || !tick) return { bars, forming }
  const last = bars[bars.length - 1]
  const at = Date.parse(tick.at.replace(" ", "T"))
  // A trade stamped before the last bar began belongs to an earlier bar.
  if ((Number.isFinite(at) && at < Date.parse(last.t)) || tradeIsLate) return { bars, forming }
  const f = forming && forming.series === series && forming.t === last.t
    ? { ...forming }
    : { series, t: last.t, h: last.h, l: last.l }
  f.h = Math.max(f.h, last.h, tick.price)
  f.l = Math.min(f.l, last.l, tick.price)
  if (tick.price === last.c && f.h === last.h && f.l === last.l) return { bars, forming: f }
  return { bars: [...bars.slice(0, -1), { ...last, c: tick.price, h: f.h, l: f.l }], forming: f }
}
