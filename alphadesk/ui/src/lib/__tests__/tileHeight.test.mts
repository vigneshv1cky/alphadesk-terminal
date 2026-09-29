import test from "node:test"
import assert from "node:assert/strict"
import {
  bandFor, tilePx, stepFor, DEFAULT_STEP, TILE_PX, TILE_STEPS,
  BAND_MIN_HEIGHT, SHORT_MAX_HEIGHT, STANDARD_MAX_HEIGHT, STEP_LABEL, type ScreenBand,
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

test("every size fits the shortest window its own band is designed for", () => {
  // The rule that caps Extra large. A band covers a RANGE of windows and only
  // its TOP edge is a boundary in the code, so the bottom edge is a judgement
  // written down in BAND_MIN_HEIGHT — and a size that does not fit it cannot
  // be read without scrolling past the tile's own foot. Asserted at the floor,
  // never at a comfortable size in the middle, because the middle always
  // passes.
  for (const band of Object.keys(TILE_PX) as ScreenBand[]) {
    for (const s of TILE_STEPS) {
      assert.ok(TILE_PX[band][s] < BAND_MIN_HEIGHT[band],
        `${band} step ${s} is ${TILE_PX[band][s]}px, past its ${BAND_MIN_HEIGHT[band]}px floor`)
    }
  }
})

test("a band's floor really is below the band, so the floor is not wishful", () => {
  // A floor set above the band it describes would make the test above pass
  // while telling the reader nothing. The standard band starts at one past
  // the short band's ceiling, and the tall band at one past standard's.
  assert.equal(BAND_MIN_HEIGHT.standard, SHORT_MAX_HEIGHT + 1)
  assert.equal(BAND_MIN_HEIGHT.tall, STANDARD_MAX_HEIGHT + 1)
  assert.ok(BAND_MIN_HEIGHT.short < SHORT_MAX_HEIGHT)
  assert.ok(BAND_MIN_HEIGHT.phone < BAND_MIN_HEIGHT.short)
})

test("real windows get sizes that fit them", () => {
  const cases: [number, number][] = [
    [375, 667], [375, 812], [1440, 700], [1440, 800],
    [1440, 900], [1440, 1100], [2560, 1300],
  ]
  for (const [w, h] of cases) {
    for (const s of TILE_STEPS) assert.ok(tilePx(s, w, h) < h, `step ${s} at ${w}x${h}`)
  }
})

test("the sizes are ordered, and every band is complete", () => {
  for (const band of Object.keys(TILE_PX) as (keyof typeof TILE_PX)[]) {
    const row = TILE_PX[band]
    for (let i = 1; i < TILE_STEPS.length; i++) {
      assert.ok(row[TILE_STEPS[i]] > row[TILE_STEPS[i - 1]],
        `${band} is not ascending at step ${TILE_STEPS[i]}`)
    }
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
})

test("extra small is step ZERO, and zero is a choice rather than an absence", () => {
  // The whole reason XS is 0: the ids stay in ascending size order, so every
  // ordering comparison still works on the number, and a layout already saved
  // keeps its meaning instead of being redrawn one size smaller. The cost is
  // that a step can be falsy, which is why nothing may test it for truthiness.
  assert.equal(stepFor(0), 0)
  assert.notEqual(stepFor(0), DEFAULT_STEP)
  for (const band of Object.keys(TILE_PX) as ScreenBand[]) {
    assert.ok(TILE_PX[band][0] < TILE_PX[band][1], `${band} XS is not below S`)
  }
})

test("the ids never move, or every board already saved changes size", () => {
  // A stored `~2` means Medium and must go on meaning Medium. Pinned as a
  // number, deliberately: this is the one thing about the ladder that cannot
  // be changed without a migration there is no version marker to write.
  assert.equal(STEP_LABEL[1], "S")
  assert.equal(STEP_LABEL[2], "M")
  assert.equal(STEP_LABEL[3], "L")
  assert.equal(STEP_LABEL[0], "XS")
  assert.equal(STEP_LABEL[4], "XL")
  assert.equal(DEFAULT_STEP, 2)
})

test("a step a build does not know falls back rather than being clamped", () => {
  // A link from a deployment with more steps than this one: the tile's own
  // default is a better answer than the nearest step we happen to have.
  assert.equal(stepFor(5), DEFAULT_STEP)
  assert.equal(stepFor(-1), DEFAULT_STEP)
})

test("extra large is a real step, above large", () => {
  assert.equal(stepFor(4), 4)
  for (const band of ["phone", "short", "standard", "tall"] as const) {
    assert.ok(TILE_PX[band][4] > TILE_PX[band][3], `${band} XL is not above L`)
  }
})

test("a panel's floor lifts a saved step but never lowers one", () => {
  // The chart refuses to be drawn small; it must not also refuse to be large.
  assert.equal(stepFor(1, 2), 2)
  assert.equal(stepFor(3, 2), 3)
  assert.equal(stepFor(2, 2), 2)
  assert.equal(stepFor(null, 3), 3)
})
