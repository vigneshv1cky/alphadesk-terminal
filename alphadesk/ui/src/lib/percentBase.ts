/** The zero point of the percent scale, blended between bars (2026-10-05, the
 * owner: the chart shakes a lot).
 *
 * Percent mode rebases to the first bar on screen, so every pan or zoom step that
 * moved that bar by one switched the base to a different close, and the whole
 * line and its axis jumped by the difference (about a day's move, on a daily
 * chart). The base is now the close at the exact left edge of the view: the
 * closes of the two bars around it, weighted by how far the edge is between
 * them, so it moves smoothly while the view moves. Pure. */
export function percentBase(closes: { c: number }[], from: number): number | undefined {
  if (!closes.length) return undefined
  const f = Math.max(0, from)
  const i = Math.min(closes.length - 1, Math.floor(f))
  const a = closes[i]?.c
  if (!a) return undefined
  const b = closes[Math.min(closes.length - 1, i + 1)]?.c
  if (!b || i >= closes.length - 1) return a
  const w = f - Math.floor(f)
  return a + (b - a) * w
}
