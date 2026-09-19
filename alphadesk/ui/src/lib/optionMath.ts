/** One option position's numbers at expiry (2026-09-14): break-even, the
 * best and worst outcome, the chance it finishes in profit and the move the
 * market prices by expiry — what the contract panel shows beside the chain.
 *
 * Figures are per CONTRACT (100 shares). The chance of profit is the
 * lognormal probability under the contract's own implied volatility with a
 * zero rate and no dividend: a reading of what the option's price implies,
 * not a forecast. Pure, so it is tested without a page. */

export type OptionType = "call" | "put"
export type Direction = "long" | "short"

export const MULTIPLIER = 100

/** Standard normal CDF (Abramowitz–Stegun 7.1.26, |error| < 1.5e-7). */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2)
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(x * x) / 2)
  return x >= 0 ? (1 + y) / 2 : (1 - y) / 2
}

/** Years from now to 16:00 New York on the expiry date, at least one hour. */
export function yearsToExpiry(expiry: string, now: Date = new Date()): number {
  // 16:00 New York is 20:00 UTC in daylight time, 21:00 in standard time;
  // the hour does not matter at the scale this is read.
  const close = new Date(`${expiry}T20:00:00Z`).getTime()
  return Math.max(close - now.getTime(), 3_600_000) / (365 * 24 * 3_600_000)
}

export interface Position {
  type: OptionType
  direction: Direction
  strike: number
  /** Price paid (long) or received (short) per share. */
  premium: number
}

export function breakEven(p: Position): number {
  return p.type === "call" ? p.strike + p.premium : p.strike - p.premium
}

/** Profit or loss per contract at expiry with the underlying at `price`. */
export function payoffAt(p: Position, price: number): number {
  const intrinsic = p.type === "call" ? Math.max(price - p.strike, 0) : Math.max(p.strike - price, 0)
  const long = (intrinsic - p.premium) * MULTIPLIER
  return p.direction === "long" ? long : -long
}

/** Best and worst outcome per contract; null is unlimited. */
export function extremes(p: Position): { maxGain: number | null; maxLoss: number | null } {
  const paid = p.premium * MULTIPLIER
  if (p.type === "call") {
    return p.direction === "long" ? { maxGain: null, maxLoss: paid } : { maxGain: paid, maxLoss: null }
  }
  const floor = Math.max(p.strike - p.premium, 0) * MULTIPLIER    // the underlying cannot go below zero
  return p.direction === "long" ? { maxGain: floor, maxLoss: paid } : { maxGain: paid, maxLoss: floor }
}

/** The probability the position finishes above break-even (long call, short
 * put) or below it (long put, short call), from implied volatility `iv`
 * (a fraction, 0.32 for 32%). Null without an IV. */
export function profitChance(p: Position, spot: number, iv: number | null, years: number): number | null {
  if (!iv || iv <= 0 || spot <= 0) return null
  const be = breakEven(p)
  if (be <= 0) return p.type === "put" ? (p.direction === "long" ? 0 : 1) : null
  const sd = iv * Math.sqrt(years)
  const above = normCdf((Math.log(spot / be) - (sd * sd) / 2) / sd)   // P(S_T > break-even)
  const longWins = p.type === "call" ? above : 1 - above
  return p.direction === "long" ? longWins : 1 - longWins
}

/** One standard deviation of the underlying by expiry, in price. */
export function expectedMove(spot: number, iv: number | null, years: number): number | null {
  return iv && iv > 0 ? spot * iv * Math.sqrt(years) : null
}

/** Points to draw the payoff: `n` prices across spot ± `width` (a fraction). */
export function payoffCurve(p: Position, spot: number, width: number, n = 81): { price: number; pnl: number }[] {
  const lo = Math.max(spot * (1 - width), 0)
  const hi = spot * (1 + width)
  const pts = []
  for (let i = 0; i < n; i++) {
    const price = lo + ((hi - lo) * i) / (n - 1)
    pts.push({ price, pnl: payoffAt(p, price) })
  }
  // The kink at the strike, exactly, so the drawn line bends where it should.
  if (p.strike > lo && p.strike < hi) pts.push({ price: p.strike, pnl: payoffAt(p, p.strike) })
  return pts.sort((a, b) => a.price - b.price)
}

/** Days to expiry as the strip shows it: 0 on the day. */
export function daysToExpiry(expiry: string, today: string): number {
  return Math.round((new Date(`${expiry}T12:00:00Z`).getTime() - new Date(`${today}T12:00:00Z`).getTime()) / 86_400_000)
}
