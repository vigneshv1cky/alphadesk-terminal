/** Scale and tick math for the chart renderer.
 *
 * Pure functions over plain numbers — no DOM, no React. Everything the
 * renderer does visually rests on these four operations (time↔x, price↔y), so
 * they are kept separate to be reasoned about and tested directly rather than
 * inferred from pixels on a screen.
 *
 * The viewport is expressed in BAR INDICES rather than timestamps. Market data
 * is not evenly spaced in time — nights, weekends and holidays are gaps — and
 * a time-linear axis renders those as dead space, which is why no trading
 * chart uses one. Index-linear means every bar gets equal width and the gaps
 * close, which is what a reader expects.
 */

export type Scale = {
  /** Index of the leftmost visible bar; fractional while panning. */
  from: number
  /** Index just past the rightmost visible bar. */
  to: number
  /** Plot area, excluding axes. */
  width: number
  height: number
  min: number
  max: number
}

/** Bar index -> x pixel. Fractional indices are valid mid-pan. */
export function indexToX(s: Scale, i: number): number {
  const span = s.to - s.from
  if (span <= 0) return 0
  return ((i - s.from) / span) * s.width
}

/** x pixel -> bar index. */
export function xToIndex(s: Scale, x: number): number {
  const span = s.to - s.from
  return s.from + (x / s.width) * span
}

/** Price -> y pixel. Inverted, because SVG's y grows downward and price does
 * not. Log mode compresses the axis so equal RATIOS occupy equal space. */
export function priceToY(s: Scale, price: number, log = false): number {
  if (log) {
    const lo = Math.log(Math.max(s.min, 1e-9))
    const hi = Math.log(Math.max(s.max, 1e-9))
    const p = Math.log(Math.max(price, 1e-9))
    return hi === lo ? s.height / 2 : s.height - ((p - lo) / (hi - lo)) * s.height
  }
  const range = s.max - s.min
  // A flat series has no range to scale against; centring beats dividing by
  // zero and beats pinning it to an edge, which would read as a collapse.
  if (range <= 0) return s.height / 2
  return s.height - ((price - s.min) / range) * s.height
}

/** y pixel -> price. */
export function yToPrice(s: Scale, y: number, log = false): number {
  if (log) {
    const lo = Math.log(Math.max(s.min, 1e-9))
    const hi = Math.log(Math.max(s.max, 1e-9))
    return Math.exp(hi - (y / s.height) * (hi - lo))
  }
  const range = s.max - s.min
  return s.max - (y / s.height) * range
}

/** "Nice" numbers for axis ticks — 1, 2, 2.5, 5 and their powers of ten.
 *
 * Ticks land on values a reader recognises. A naive range/8 produces labels
 * like 217.3847, which is precise and useless. */
export function niceStep(rough: number): number {
  if (rough <= 0 || !Number.isFinite(rough)) return 1
  const mag = 10 ** Math.floor(Math.log10(rough))
  const norm = rough / mag
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10
  return step * mag
}

/** Price-axis tick values across the visible range. */
export function priceTicks(min: number, max: number, target = 7): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return []
  const step = niceStep((max - min) / target)
  const first = Math.ceil(min / step) * step
  const out: number[] = []
  // Guard the loop: a pathological step could otherwise run away.
  for (let v = first, n = 0; v <= max && n < 200; v += step, n++) {
    out.push(Number(v.toFixed(10)))
  }
  return out
}

/** Ticks for the LOG scale: 1, 2 and 5 in every decade, thinned to whole
 * decades (then every k-th decade) when the range spans too many. Linear
 * spacing on a log axis put nine labels in the top decade and one in the
 * bottom; this is what a log chart is read against. Falls back to the
 * linear ladder when the range cannot be logged or is too narrow to reach
 * three log ticks. */
export function priceTicksLog(min: number, max: number, target = 7): number[] {
  if (!(min > 0) || !(max > min) || !Number.isFinite(max)) return priceTicks(min, max, target)
  const d0 = Math.floor(Math.log10(min)), d1 = Math.ceil(Math.log10(max))
  const within = (v: number) => v >= min && v <= max
  let out: number[] = []
  for (let d = d0; d <= d1; d++) for (const m of [1, 2, 5]) {
    const v = m * 10 ** d
    if (within(v)) out.push(Number(v.toPrecision(12)))
  }
  if (out.length > target * 1.6) {
    out = out.filter(v => Math.abs(Math.log10(v) - Math.round(Math.log10(v))) < 1e-9)
    const k = Math.ceil(out.length / target)
    if (k > 1) out = out.filter((_, i) => i % k === 0)
  }
  return out.length >= 3 ? out : priceTicks(min, max, target)
}

/** How many decimals a price axis needs, from the size of its step.
 * An index at 7,600 wants none; a sub-dollar ticker wants four. */
export function priceDecimals(step: number): number {
  if (step >= 100) return 0
  if (step >= 1) return 2
  if (step >= 0.01) return 2
  return Math.min(6, Math.max(2, Math.ceil(-Math.log10(step)) + 1))
}

/** Pad a min/max so the series never touches the pane edges. */
export function padRange(min: number, max: number, frac = 0.08): { min: number; max: number } {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 }
  if (max === min) {
    const bump = Math.abs(max) * 0.01 || 1
    return { min: min - bump, max: max + bump }
  }
  const pad = (max - min) * frac
  return { min: min - pad, max: max + pad }
}

/** Pad a min/max with room RESERVED at the top, in pixels — the legend's
 * height. The bottom keeps the usual fraction; the top takes whichever is
 * larger, the fraction or what covers the inset once the range is mapped
 * onto `heightPx`. With p the bottom fraction and q the top, the top pad
 * lands at q / (1 + p + q) of the height, so covering `insetPx` needs
 * q = insetPx (1 + p) / (heightPx - insetPx). */
export function padRangeInset(min: number, max: number, insetPx: number, heightPx: number, frac = 0.08): { min: number; max: number } {
  const flat = padRange(min, max, frac)
  if (!(insetPx > 0) || !(heightPx - insetPx > 20) || max === min || !Number.isFinite(min) || !Number.isFinite(max)) return flat
  const q = Math.max(frac, insetPx * (1 + frac) / (heightPx - insetPx))
  return { min: flat.min, max: max + (max - min) * q }
}

/** Keep a view window within reach of the series.
 *
 * Empty space is allowed at both ends, and not the same amount: a sliver past
 * the live edge, a whole screen past the oldest bar, which is the direction a
 * reader pulls into while the history loads behind them. Panning and zooming
 * share this one rule so they cannot disagree about where the edge of the
 * world is; an unclamped pan strands the reader on blank canvas with no way
 * back except changing the range, so the room is bounded at both ends.
 */
export function clampView(from: number, to: number, total: number): { from: number; to: number } {
  const span = to - from
  let f = from, t = to
  // A little overscroll at EITHER end: past the newest bar, room to read
  // the live edge against; past the oldest, room to read the first bars
  // against instead of having them glued to the plot's left edge. The
  // left used to pin at the first bar (2026-09-10: "remove that rule") —
  // it made a pan-back stop dead and cut the first time label in half.
  //
  // THE TWO ENDS ARE NOT THE SAME (2026-09-16, from three recordings).
  //
  // RIGHT: room to push into, not a locked edge. A flat 30% of the span
  // left a permanent void beside the live price after a zoom-out, and the
  // first fix — a hard cap of 120 bars — went too far the other way: zoomed
  // out, the chart would barely move to the right at all. The void was
  // never the allowance's fault but the ZOOM's, which anchored on a cursor
  // sitting in blank canvas and pushed the series away from the axis; that
  // is fixed in zoomAt, and the allowance can stay generous here.
  //
  // LEFT: room to pull INTO. Theirs lets a reader fling left until the
  // series is off the screen entirely and fills the blank behind them as
  // the history arrives, which is the motion the owner asked for; a tight
  // cap turns one gesture into short tugs against a wall. One screenful is
  // the allowance — enough for that fling, bounded so a pan can always
  // bring the bars back.
  const right = span * 0.3
  const left = span
  if (t > total + right) { t = total + right; f = t - span }
  if (f < -left) { f = -left; t = f + span }
  return { from: f, to: t }
}

/** The gap a chart OPENS with, as a share of the visible span: the live edge
 * reads against a little canvas instead of being pressed onto the price
 * axis, which is how every terminal draws it. Proportional, so it looks the
 * same at every zoom. */
export const RIGHT_GAP = 0.05

/** Zoom about a fixed bar index, so the bar under the cursor stays put — the
 * behaviour every charting tool has, and its absence is immediately obvious. */
export function zoomAt(s: Scale, anchorIndex: number, factor: number, total: number): { from: number; to: number } {
  const span = s.to - s.from
  const next = Math.max(5, Math.min(total * 3, span * factor))
  // THE ANCHOR IS A BAR, NOT A PIXEL (2026-09-16). Zooming out with the
  // cursor over the blank canvas past the live edge held THAT emptiness
  // still and pushed the series away from the axis, a little further on
  // every turn of the wheel, until the last bar sat a third of the way in
  // and stayed there. An anchor beyond the newest bar is pulled back to it,
  // so the live edge is what stays put — which is also what the eye expects
  // when it is the thing being looked at.
  const anchor = Math.min(anchorIndex, total)
  const ratio = span === 0 ? 0.5 : (anchor - s.from) / span
  const from = anchor - ratio * next
  return clampView(from, from + next, total)
}

/** The min/max of whatever is actually on screen, so the y axis tracks the
 * visible window rather than the whole history. */
export function visibleExtent(
  bars: { h: number; l: number }[], from: number, to: number,
): { min: number; max: number } {
  const lo = Math.max(0, Math.floor(from))
  const hi = Math.min(bars.length - 1, Math.ceil(to))
  let min = Infinity
  let max = -Infinity
  for (let i = lo; i <= hi; i++) {
    const b = bars[i]
    if (!b) continue
    if (b.l < min) min = b.l
    if (b.h > max) max = b.h
  }
  if (Number.isFinite(min)) return { min, max }
  // NOTHING ON SCREEN (2026-09-16): the reader has pulled onto blank canvas
  // past the oldest bar, waiting for the history to arrive. A 0-to-1 axis
  // there would redraw the price scale in single digits and throw the price
  // line off the pane for the moment it takes. The nearest bars keep the
  // scale steady until the page lands.
  const edge = from < 0 ? bars[0] : bars[bars.length - 1]
  return edge ? { min: edge.l, max: edge.h } : { min: 0, max: 1 }
}

/** A price range stretched or compressed about its own middle.
 *
 * What the price gutter's drag produces. Held in the axis' own units rather
 * than as a factor over whatever the visible bars fit to, so a scale the
 * reader set by hand survives panning through the history — theirs behaves
 * this way and it is what makes one price level readable across a long
 * stretch (2026-09-16).
 *
 * On a log axis the middle is the LOG middle: the linear centre of 10 to
 * 1,000 is 505, which sits near the top of a log pane, so stretching about
 * it runs the series off the bottom and compressing produces a negative
 * floor. A factor above 1 opens the scale up; below 1 closes it in.
 */
export function scaledRange(range: { min: number; max: number }, factor: number, log = false): { min: number; max: number } {
  const { min, max } = range
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min || !(factor > 0)) return range
  if (log && min > 0) {
    const lo = Math.log(min), hi = Math.log(max)
    const c = (lo + hi) / 2, h = (hi - lo) / 2 / factor
    return { min: Math.exp(c - h), max: Math.exp(c + h) }
  }
  const centre = (min + max) / 2
  const half = (max - min) / 2 / factor
  return { min: centre - half, max: centre + half }
}
