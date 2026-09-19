/** What the measure tool says (2026-09-16).
 *
 * Ours printed one line — the change, the percentage, a bar count and a
 * rounded duration — where theirs prints the three things a trader actually
 * reads off a measurement: how far price moved in money, per cent AND ticks;
 * how long that took in bars and in clock time; and how much traded while it
 * happened. The owner asked for theirs, so these are its rules, written out
 * and testable rather than inline in the renderer.
 */

/** The smallest increment the instrument moves in. US equities quote in
 * cents above a dollar and in hundredths of a cent below it (the sub-dollar
 * rule), which is what makes "−131 ticks" meaningful on a $6 stock. */
export function tickSize(price: number): number {
  return Math.abs(price) >= 1 ? 0.01 : 0.0001
}

/** A duration as they write it: the two largest units that are not zero,
 * "1d 4h", "1h 30m", "45m". Seconds only ever stand alone, for a measurement
 * inside one bar. */
export function spanWords(seconds: number): string {
  const s = Math.max(0, Math.round(Math.abs(seconds)))
  if (s < 60) return `${s}s`
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const parts = d ? [`${d}d`, h ? `${h}h` : "", m ? `${m}m` : ""]
    : h ? [`${h}h`, m ? `${m}m` : ""]
    : [`${m}m`]
  return parts.filter(Boolean).join(" ")
}

/** Traded volume, short enough for a label: 1.45M, 930K, 12.3B. */
export function compactVolume(v: number): string {
  const n = Math.abs(v)
  if (!Number.isFinite(n) || n <= 0) return "0"
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}K`
  return String(Math.round(n))
}

export interface Measurement {
  /** Price at the first anchor, and at the second. */
  from: number
  to: number
  /** Bars between the anchors, when both landed on one. */
  bars: number | null
  /** Clock time between them. */
  seconds: number
  /** Volume traded across them, when the bars are in hand. */
  volume: number | null
}

/** The three lines of the label, in their order. The first carries money,
 * per cent and ticks; the second the bars and the clock; the third the
 * volume, and it is dropped when no volume is known rather than printed as
 * a zero that would read as "nothing traded". */
export function measureLines(m: Measurement): string[] {
  const delta = m.to - m.from
  const sign = delta >= 0 ? "+" : "−"
  const abs = Math.abs(delta)
  const pct = m.from === 0 ? 0 : (abs / Math.abs(m.from)) * 100
  // Decimals follow the INSTRUMENT, not the size of the move: a dollar
  // stock quotes in cents, so a 75-cent move is −0.75, never −0.7490.
  const tick = tickSize(m.from)
  const money = abs.toFixed(tick >= 0.01 ? 2 : 4)
  const ticks = Math.round(abs / tick)
  const first = `${sign}${money} (${sign}${pct.toFixed(2)}%) ${sign}${ticks}`
  const bars = m.bars == null ? "" : `${m.bars} ${m.bars === 1 ? "bar" : "bars"}, `
  const second = `${bars}${spanWords(m.seconds)}`
  return m.volume == null ? [first, second] : [first, second, `Vol ${compactVolume(m.volume)}`]
}
