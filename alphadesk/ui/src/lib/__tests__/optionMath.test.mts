/** One option position's numbers at expiry (lib/optionMath.ts).
 *
 *     pnpm test
 */
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  breakEven, daysToExpiry, expectedMove, extremes, normCdf, payoffAt, payoffCurve, profitChance, yearsToExpiry,
} from "../optionMath.ts"

const near = (a: number | null, b: number, eps = 1e-3) => {
  assert.ok(a != null && Math.abs(a - b) < eps, `${a} ≈ ${b}`)
}

test("the normal CDF is right at the landmarks", () => {
  near(normCdf(0), 0.5, 1e-6)
  near(normCdf(1), 0.841345, 1e-5)
  near(normCdf(-1.96), 0.024998, 1e-5)
})

test("break-even and payoff per contract, long and short", () => {
  const call = { type: "call" as const, direction: "long" as const, strike: 210, premium: 2.65 }
  assert.equal(breakEven(call), 212.65)
  near(payoffAt(call, 220), 735)          // (10 − 2.65) × 100
  near(payoffAt(call, 200), -265)
  near(payoffAt({ ...call, direction: "short" }, 200), 265)
  const put = { type: "put" as const, direction: "long" as const, strike: 205, premium: 1.27 }
  assert.equal(breakEven(put), 203.73)
  near(payoffAt(put, 195), 873)
})

test("max gain and loss: a long call is unlimited up, a short put can lose down to zero", () => {
  assert.deepEqual(extremes({ type: "call", direction: "long", strike: 210, premium: 2 }), { maxGain: null, maxLoss: 200 })
  assert.deepEqual(extremes({ type: "call", direction: "short", strike: 210, premium: 2 }), { maxGain: 200, maxLoss: null })
  assert.deepEqual(extremes({ type: "put", direction: "long", strike: 205, premium: 1 }), { maxGain: 20400, maxLoss: 100 })
  assert.deepEqual(extremes({ type: "put", direction: "short", strike: 205, premium: 1 }), { maxGain: 100, maxLoss: 20400 })
})

test("profit chance falls as break-even moves away, and long plus short is one", () => {
  const years = 4 / 365
  const atm = profitChance({ type: "call", direction: "long", strike: 212.5, premium: 2.65 }, 212.04, 0.32, years)!
  const otm = profitChance({ type: "call", direction: "long", strike: 225, premium: 0.2 }, 212.04, 0.32, years)!
  assert.ok(atm > otm && atm < 0.5 && otm > 0)
  const short = profitChance({ type: "call", direction: "short", strike: 212.5, premium: 2.65 }, 212.04, 0.32, years)!
  near(atm + short, 1, 1e-9)
  assert.equal(profitChance({ type: "call", direction: "long", strike: 212.5, premium: 2.65 }, 212.04, null, years), null)
})

test("expected move is spot × IV × √years, and time to expiry never reaches zero", () => {
  near(expectedMove(200, 0.4, 0.25), 40, 1e-9)
  assert.ok(yearsToExpiry("2026-09-14", new Date("2026-09-15T00:00:00Z")) > 0)
  assert.equal(daysToExpiry("2026-09-18", "2026-09-14"), 4)
  assert.equal(daysToExpiry("2026-09-14", "2026-09-14"), 0)
})

test("the payoff curve includes the strike exactly and stays in price order", () => {
  const pts = payoffCurve({ type: "call", direction: "long", strike: 210, premium: 2 }, 212, 0.2, 11)
  assert.ok(pts.some(p => p.price === 210))
  assert.ok(pts.every((p, i) => i === 0 || p.price >= pts[i - 1].price))
})
