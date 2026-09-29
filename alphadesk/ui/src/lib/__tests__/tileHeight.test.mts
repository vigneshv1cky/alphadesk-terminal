import test from "node:test"
import assert from "node:assert/strict"
import {
  bandFor, tilePx, stepFor, DEFAULT_STEP, TILE_PX, TILE_STEPS,
} from "../tileHeight.ts"

test("a phone is a kind of screen, not a short one", () => {
  // Width decides it first, whatever the length — a tall phone is still a
  // phone, and a long one must not be handed desktop heights.
  assert.equal(bandFor(375, 812), "phone")
  assert.equal(bandFor(375, 1400), "phone")
  assert.equal(bandFor(639, 900), "phone")
  assert.equal(bandFor(640, 900), "standard")
})

test("among desktops the window's own height picks the row", () => {
  assert.equal(bandFor(1440, 700), "short")
  assert.equal(bandFor(1440, 800), "short")
  assert.equal(bandFor(1440, 801), "standard")
  assert.equal(bandFor(1440, 900), "standard")
  assert.equal(bandFor(1440, 1100), "standard")
  assert.equal(bandFor(1440, 1101), "tall")
  assert.equal(bandFor(2560, 1300), "tall")
})

test("a short WIDE window gets short heights, not tall ones", () => {
  // The thing being chosen is a height, so a wide window that is not tall
  // must not be treated as a big screen.
  assert.equal(bandFor(2560, 720), "short")
  assert.ok(tilePx(3, 2560, 720) < tilePx(3, 2560, 1300))
})

test("every size fits on the screen it is meant for", () => {
  // The point of banding: Large must never be taller than the window it was
  // chosen for, or a tile cannot be read without scrolling past its own foot.
  const cases: [number, number][] = [[375, 812], [1440, 800], [1440, 900], [2560, 1300]]
  for (const [w, h] of cases) {
    for (const s of TILE_STEPS) assert.ok(tilePx(s, w, h) < h, `step ${s} at ${w}x${h}`)
  }
})

test("the sizes are ordered, and every band is complete", () => {
  for (const band of Object.keys(TILE_PX) as (keyof typeof TILE_PX)[]) {
    const row = TILE_PX[band]
    assert.ok(row[1] < row[2] && row[2] < row[3], `${band} is not ascending`)
    for (const s of TILE_STEPS) assert.equal(typeof row[s], "number")
  }
})

test("a bigger band is never smaller at the same step", () => {
  for (const s of TILE_STEPS) {
    assert.ok(TILE_PX.short[s] <= TILE_PX.standard[s])
    assert.ok(TILE_PX.standard[s] <= TILE_PX.tall[s])
  }
})

test("a layout that names no step gets the default, not nothing", () => {
  // With Fit gone every tile must have a size; a board saved before this
  // change names none, and must still render something sensible.
  assert.equal(stepFor(null), DEFAULT_STEP)
  assert.equal(stepFor(undefined), DEFAULT_STEP)
  assert.equal(stepFor(0), DEFAULT_STEP)
})

test("a step a build does not know falls back rather than being clamped", () => {
  // A link from a deployment with more steps than this one: the tile's own
  // default is a better answer than the nearest step we happen to have.
  assert.equal(stepFor(4), DEFAULT_STEP)
  assert.equal(stepFor(-1), DEFAULT_STEP)
})

test("a panel's floor lifts a saved step but never lowers one", () => {
  // The chart refuses to be drawn small; it must not also refuse to be large.
  assert.equal(stepFor(1, 2), 2)
  assert.equal(stepFor(3, 2), 3)
  assert.equal(stepFor(2, 2), 2)
  assert.equal(stepFor(null, 3), 3)
})
