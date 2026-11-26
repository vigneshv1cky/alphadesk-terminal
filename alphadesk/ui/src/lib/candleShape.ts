/** The shape of a candle body, an OHLC tick and a volume column.
 *
 * Softened 2026-11-23 (the owner: "the bars in chart seem rigid too"). Every
 * shape is still a path SEGMENT appended to one of a handful of batched paths
 * — a rounded corner is an arc command inside the same string, never an
 * element per bar.
 *
 * VALUES STAY EXACT. A corner only takes the radius out of the CORNER: the
 * flat top edge stays on the open (or close) and the flat bottom edge on the
 * other, so a rounded body still starts and ends on its prices. The radius is
 * capped at half the body's height (both ends rounded) or its full height
 * (one end), so the arcs never meet in a way that pulls an edge inward, and
 * at half its width, so the sides stay straight.
 */

export interface CandleStyle {
  /** Body width as a share of the bar's slot; the rest is the gap. */
  width: number
  /** Corner radius as a share of the body width. */
  radius: number
  /** The largest corner, in pixels, whatever the width. */
  radiusCap: number
  /** Below this body width (px) a corner is not drawn: at a pixel or two it
   * would only blur the bar. */
  minRoundWidth: number
  /** Wick opacity against a full-strength body. */
  wickOpacity: number
  /** Body fill opacity. */
  bodyOpacity: number
  /** ZOOMED OUT: a body narrower than this (px) is drawn the narrow way. */
  narrowBelow?: number
  /** Narrow: body fill opacity (a packed wall of full-strength columns reads
   * as a hard block). */
  narrowBodyOpacity?: number
  /** Narrow: wick opacity, when the wick stays a 1px line. */
  narrowWickOpacity?: number
  /** Narrow: draw the high–low range as a soft column AT THE BODY'S WIDTH
   * behind the body, instead of a separate 1px wick — one softer column. */
  narrowMerge?: boolean
  /** Narrow, merged: the high–low column's opacity. */
  narrowShadowOpacity?: number
  /** Narrow: keep at least this much space (px) between neighbours. */
  narrowGap?: number
}

/** The corner a body of this size gets, in pixels. `ends` is how many ends
 * are rounded: 2 for a candle body, 1 for a column standing on a baseline. */
export function cornerRadius(st: CandleStyle, w: number, h: number, ends: 1 | 2 = 2): number {
  if (st.radius <= 0 || w < st.minRoundWidth) return 0
  const r = Math.min(w * st.radius, st.radiusCap, w / 2, ends === 2 ? h / 2 : h)
  return r < 0.25 ? 0 : r
}

const f = (n: number) => n.toFixed(1)

/** A rectangle as a path segment, its corners rounded by `r` at the chosen
 * end(s). `round` picks the ends: "both" for a candle body, "top" or
 * "bottom" for a column whose other end sits on the zero line. With r = 0 it
 * is exactly the plain rectangle the chart always drew. */
export function rectPath(x: number, y: number, w: number, h: number, r = 0,
                         round: "both" | "top" | "bottom" = "both"): string {
  if (r <= 0) return `M${f(x)},${f(y)}h${f(w)}v${f(h)}h${f(-w)}Z`
  const top = round !== "bottom", bot = round !== "top"
  const x1 = x + w, y1 = y + h
  let d = top
    ? `M${f(x)},${f(y + r)}A${f(r)},${f(r)} 0 0 1 ${f(x + r)},${f(y)}H${f(x1 - r)}A${f(r)},${f(r)} 0 0 1 ${f(x1)},${f(y + r)}`
    : `M${f(x)},${f(y)}H${f(x1)}`
  d += bot
    ? `V${f(y1 - r)}A${f(r)},${f(r)} 0 0 1 ${f(x1 - r)},${f(y1)}H${f(x + r)}A${f(r)},${f(r)} 0 0 1 ${f(x)},${f(y1 - r)}Z`
    : `V${f(y1)}H${f(x)}Z`
  return d
}

/** The style the chart drew until 2026-11-23: square, 70% of the slot. */
export const SQUARE: CandleStyle = {
  width: 0.7, radius: 0, radiusCap: 0, minRoundWidth: Infinity, wickOpacity: 1, bodyOpacity: 1,
}

/** THE CANDLES THE CHART DRAWS (2026-11-23, the owner's pick of the drafts
 * drawn on the real chart: "B + merged column").
 *
 * Normal zoom: bodies 62% of the slot (a little more air than the old 70%),
 * corners a quarter of the width capped at 3px, wicks at 70% so they sit
 * back from the body.
 *
 * Zoomed out, once a body is under 3px wide (one candle per pixel column,
 * lib/chartBuckets): the 1px wick is gone and the high-to-low range is drawn
 * as a 40% column AT THE BODY'S WIDTH behind a 90% body — one soft column
 * instead of a hard bar beside a hard line, which is what read as rigid.
 * High, low, open and close all stay exactly where they were.
 *
 * Drafts not taken: corners only (A); a softer body fill too (C); narrow
 * candles merely lighter; the merged column with a kept 0.6px gap (it only
 * differs below a 2.8px slot). */
export const CANDLES: CandleStyle = {
  width: 0.62, radius: 0.25, radiusCap: 3, minRoundWidth: 4, wickOpacity: 0.7, bodyOpacity: 1,
  narrowBelow: 3, narrowBodyOpacity: 0.9, narrowMerge: true, narrowShadowOpacity: 0.4,
}
