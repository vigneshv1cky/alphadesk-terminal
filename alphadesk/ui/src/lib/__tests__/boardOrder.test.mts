import { strict as assert } from "node:assert"
import { test } from "node:test"
import { byRecency } from "../boardOrder.ts"

test("the symbol looked at most recently comes first", () => {
  assert.deepEqual(byRecency(["NVDA", "TSLA", "SPCX"], ["SPCX", "NVDA"]), ["SPCX", "NVDA", "TSLA"])
})

test("a symbol this browser has never opened keeps the link's own order", () => {
  // A shared board: only COIN has ever been scoped to here.
  assert.deepEqual(byRecency(["AAPL", "MSFT", "COIN"], ["COIN"]), ["COIN", "AAPL", "MSFT"])
  assert.deepEqual(byRecency(["AAPL", "MSFT"], []), ["AAPL", "MSFT"])
})

test("recency for symbols no longer on the board is ignored", () => {
  assert.deepEqual(byRecency(["TSLA"], ["GONE", "TSLA"]), ["TSLA"])
})

test("the board's own membership decides, not the recency list", () => {
  assert.deepEqual(byRecency([], ["NVDA"]), [])
})
