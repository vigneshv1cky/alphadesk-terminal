import type { ChartBar } from "@/lib/api"

/** The ways a price series can be drawn (2026-09-05).
 *
 * Eleven of theirs. Every one of these is a different PICTURE of the same
 * bars — the data underneath does not change, the indicators read the real
 * closes, and the price tag still says the real last price. Heikin Ashi is
 * the one that redraws the bars themselves, and it is a smoothing for the
 * eye: the readout under the cursor keeps reporting the real bar, because a
 * Heikin Ashi "close" is an average, not a price anything traded at.
 *
 * Not here: Renko, Kagi, line break, point & figure. Those are not drawings
 * of time-indexed bars at all — they build their own bricks from price
 * movement and throw the clock away, which means their own x axis, their
 * own projection and their own drawing anchors. A separate block.
 */
export type SeriesKind =
  | "candles" | "hollow" | "heikin" | "bars"
  | "line" | "step" | "area" | "baseline" | "hlc" | "highlow" | "columns"

export const SERIES_KINDS: { id: SeriesKind; label: string; glyph: string }[] = [
  { id: "candles",  label: "Candles",        glyph: "╇" },
  { id: "hollow",   label: "Hollow candles", glyph: "═" },
  { id: "heikin",   label: "Heikin Ashi",    glyph: "⬡" },
  { id: "bars",     label: "Bars",           glyph: "╀" },
  { id: "line",     label: "Line",           glyph: "↗" },
  { id: "step",     label: "Step line",      glyph: "┐" },
  { id: "area",     label: "Area",           glyph: "◢" },
  { id: "baseline", label: "Baseline",       glyph: "≡" },
  { id: "hlc",      label: "HLC area",       glyph: "░" },
  { id: "highlow",  label: "High-low",       glyph: "↕" },
  { id: "columns",  label: "Columns",        glyph: "▂" },
]

/** Heikin Ashi bars: each open is the midpoint of the previous HA bar, each
 * close the mean of the real O/H/L/C, and the high and low reach to whichever
 * of the real high/low and the HA open/close is further. The first bar seeds
 * from itself. Volume and time carry through untouched. */
export function heikinAshi(bars: ChartBar[]): ChartBar[] {
  const out: ChartBar[] = []
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]
    const c = (b.o + b.h + b.l + b.c) / 4
    const prev = out[i - 1]
    const o = prev ? (prev.o + prev.c) / 2 : (b.o + b.c) / 2
    out.push({ ...b, o, c, h: Math.max(b.h, o, c), l: Math.min(b.l, o, c) })
  }
  return out
}
