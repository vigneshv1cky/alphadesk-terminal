/** Fewer shapes for a crowded chart (2026-10-05, the owner: the chart jitters and
 * is hard to focus on).
 *
 * A minute-bar chart over a month is 20,000 to 48,000 bars in a plot a few hundred
 * pixels wide: a hundred bars to a pixel, each one a string in the drawing path,
 * every one rebuilt on every zoom step, pan and tick. Past a pixel, a candle is
 * not visible on its own anyway, so a run of bars is drawn as ONE candle: the
 * first open, the last close, the highest high and the lowest low. At that zoom
 * it looks the same, and the work follows the plot's width, not the bar count.
 */

export interface Bucketed {
  /** Index of the bucket's middle, in the units of the bar list (may be .5). */
  i: number
  o: number
  h: number
  l: number
  c: number
  /** Bars folded into this one. */
  n: number
}

/** Bars `lo` to `hi` (inclusive) of `bars`, folded so that no more than about
 * `columns` candles come back. Returns the bars unchanged, one each, while they
 * fit with room to spare. Pure. */
export function bucketBars(
  bars: { o: number; h: number; l: number; c: number }[],
  lo: number,
  hi: number,
  columns: number,
): Bucketed[] {
  const count = hi - lo + 1
  if (count <= 0) return []
  const cols = Math.max(1, Math.floor(columns))
  const per = count > cols * 1.5 ? Math.ceil(count / cols) : 1
  const out: Bucketed[] = []
  for (let start = lo; start <= hi; start += per) {
    const end = Math.min(hi, start + per - 1)
    const first = bars[start]
    if (!first) continue
    let h = first.h, l = first.l, c = first.c, n = 1
    for (let k = start + 1; k <= end; k++) {
      const b = bars[k]
      if (!b) continue
      if (b.h > h) h = b.h
      if (b.l < l) l = b.l
      c = b.c
      n++
    }
    out.push({ i: (start + end) / 2, o: first.o, h, l, c, n })
  }
  return out
}
