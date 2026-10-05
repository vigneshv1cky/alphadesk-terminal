import assert from "node:assert/strict"
import test from "node:test"
import { percentBase } from "../percentBase.ts"

const bars = [100, 110, 90, 120].map(c => ({ c }))

test("on a whole bar the base is that bar's close, as before", () => {
  assert.equal(percentBase(bars, 0), 100)
  assert.equal(percentBase(bars, 1), 110)
  assert.equal(percentBase(bars, 2), 90)
})

test("between two bars it blends their closes, so it moves smoothly with the view", () => {
  assert.equal(percentBase(bars, 0.5), 105)
  assert.equal(percentBase(bars, 1.25), 110 + (90 - 110) * 0.25)
  let last = percentBase(bars, 0)!
  for (const f of [0.1, 0.3, 0.6, 0.9, 1.0]) {                       // between bar 0 and bar 1: never jumps back
    const v = percentBase(bars, f)!
    assert.ok(v >= last, `${v} at ${f}`)
    last = v
  }
})

test("a view that starts before the data or past its end is clamped, and an empty series has no base", () => {
  assert.equal(percentBase(bars, -5), 100)
  assert.equal(percentBase(bars, 3), 120)
  assert.equal(percentBase(bars, 40), 120)
  assert.equal(percentBase([], 2), undefined)
  assert.equal(percentBase([{ c: 0 }], 0), undefined)
})
