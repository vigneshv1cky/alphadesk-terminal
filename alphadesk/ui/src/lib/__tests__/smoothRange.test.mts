import assert from "node:assert/strict"
import test from "node:test"
import { easeRange } from "../smoothRange.ts"

test("each step moves both ends part of the way and never past the target", () => {
  let cur = { min: 100, max: 120 }
  const target = { min: 90, max: 140 }
  let last = Math.abs(cur.max - target.max)
  for (let i = 0; i < 6; i++) {
    cur = easeRange(cur, target, 0.32)
    const gap = Math.abs(cur.max - target.max)
    assert.ok(gap < last || gap === 0, "closer each step")
    assert.ok(cur.max <= target.max && cur.min >= target.min, "never overshoots")
    last = gap
  }
})

test("it lands exactly on the target within a few dozen frames", () => {
  let cur = { min: 0, max: 10 }
  const target = { min: 50, max: 500 }
  let frames = 0
  while (cur !== target && frames < 200) { cur = easeRange(cur, target, 0.32); frames++ }
  assert.equal(cur, target)
  assert.ok(frames < 40, `took ${frames} frames`)
})

test("a target already reached is returned as it is, and bad numbers snap", () => {
  const t = { min: 1, max: 2 }
  assert.equal(easeRange({ min: 1.00001, max: 2.00001 }, t, 0.32), t)
  assert.equal(easeRange({ min: NaN, max: 2 }, t, 0.32), t)
  assert.equal(easeRange({ min: 1, max: 2 }, { min: -Infinity, max: 3 }, 0.32).max, 3)
})
