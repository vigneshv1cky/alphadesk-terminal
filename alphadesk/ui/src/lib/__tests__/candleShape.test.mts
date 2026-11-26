import assert from "node:assert/strict"
import test from "node:test"
import { CANDLES, SQUARE, cornerRadius, rectPath } from "../candleShape.ts"

const st = CANDLES

/** Every y a path's commands land on, from its absolute coordinates. */
function ys(d: string): number[] {
  const out: number[] = []
  for (const m of d.matchAll(/([MLHVA])([^MLHVAZ]*)/g)) {
    const n = m[2].trim().split(/[ ,]+/).filter(Boolean).map(Number)
    if (m[1] === "M" || m[1] === "L") out.push(n[1])
    else if (m[1] === "V") out.push(n[0])
    else if (m[1] === "A") out.push(n[6])
  }
  return out
}

test("square style draws the plain rectangle the chart always drew", () => {
  assert.equal(rectPath(10, 20, 8, 30, cornerRadius(SQUARE, 8, 30)), "M10.0,20.0h8.0v30.0h-8.0Z")
})

test("a rounded body still starts and ends on its prices", () => {
  const r = cornerRadius(st, 10, 30)
  assert.ok(r > 0)
  const got = ys(rectPath(10, 20, 10, 30, r))
  assert.equal(Math.min(...got), 20)
  assert.equal(Math.max(...got), 50)
})

test("no corner on a bar a few pixels wide", () => {
  assert.equal(cornerRadius(st, 3, 40), 0)
  assert.equal(cornerRadius(st, 1, 40), 0)
})

test("a short body never rounds past half its height", () => {
  const r = cornerRadius(st, 20, 2)
  assert.ok(r <= 1)
  const got = ys(rectPath(0, 100, 20, 2, r))
  assert.equal(Math.min(...got), 100)
  assert.equal(Math.max(...got), 102)
})

test("a column rounds only the end away from the zero line", () => {
  const r = cornerRadius(st, 10, 40, 1)
  const top = rectPath(0, 10, 10, 40, r, "top")
  assert.match(top, /^M0\.0,1\d\.\dA/)          // starts on an arc at the top
  assert.match(top, /V50\.0H0\.0Z$/)            // square foot on the baseline
  const bottom = rectPath(0, 10, 10, 40, r, "bottom")
  assert.match(bottom, /^M0\.0,10\.0H10\.0/)     // square top on the baseline
})

test("the radius is capped in pixels on a wide body", () => {
  assert.equal(cornerRadius(st, 200, 200), st.radiusCap)
})
