import assert from "node:assert/strict"
import { test } from "node:test"
import { moneyIn, moneyOut } from "../floors.ts"

test("a floor reads into the input as K, M or B", () => {
  assert.equal(moneyIn(1_000_000), "1M")
  assert.equal(moneyIn(2_500_000_000), "2.5B")
  assert.equal(moneyIn(250_000), "250K")
  assert.equal(moneyIn(5), "5")
  assert.equal(moneyIn(0), "0")
})

test("the input reads back as a number, K, M and B accepted in any case", () => {
  assert.equal(moneyOut("1M"), 1_000_000)
  assert.equal(moneyOut("1.5m"), 1_500_000)
  assert.equal(moneyOut("250k"), 250_000)
  assert.equal(moneyOut("2B"), 2_000_000_000)
  assert.equal(moneyOut("$2,000"), 2000)
  assert.equal(moneyOut(" 5 "), 5)
  assert.equal(moneyOut(".5"), 0.5)
})

test("anything else is not a floor", () => {
  assert.equal(moneyOut(""), null)
  assert.equal(moneyOut("abc"), null)
  assert.equal(moneyOut("1x"), null)
  assert.equal(moneyOut("-5"), null)
  assert.equal(moneyOut("1.2.3"), null)
})

test("round trip", () => {
  for (const v of [1000, 250_000, 1_000_000, 1_500_000, 2_500_000_000]) assert.equal(moneyOut(moneyIn(v)), v)
})
