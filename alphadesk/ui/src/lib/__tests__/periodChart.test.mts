import assert from "node:assert/strict"
import test from "node:test"
import { rangeReaching } from "../periodChart.ts"

const today = new Date("2026-11-23T15:00:00Z")

test("the shortest daily range that reaches the start", () => {
  assert.equal(rangeReaching("2026-11-02", today), "1M")
  assert.equal(rangeReaching("2026-10-02", today), "3M")
  assert.equal(rangeReaching("2026-06-01", today), "6M")
  assert.equal(rangeReaching("2025-12-31", today), "1Y")
  assert.equal(rangeReaching("2025-11-20", today), "1Y")      // a 1Y period's start is just past a year
  assert.equal(rangeReaching("2025-10-01", today), "5Y")
  assert.equal(rangeReaching("2021-12-01", today), "5Y")
})
