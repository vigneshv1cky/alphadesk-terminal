import assert from "node:assert/strict"
import test from "node:test"
import { compactVolume, measureLines, spanWords, tickSize } from "../measure.ts"

// The measurement in their recording: TNON from 6.87 down to 5.56 across 51
// bars and a day and a half, on 1.39M shares.
const THEIRS = { from: 6.87, to: 5.56, bars: 51, seconds: 91_800, volume: 1_390_000 }

test("the label says money, per cent and ticks, then bars and clock, then volume", () => {
  assert.deepEqual(measureLines(THEIRS), [
    "−1.31 (−19.07%) −131",
    "51 bars, 1d 1h 30m",
    "Vol 1.39M",
  ])
})

test("a rise reads as a rise", () => {
  const [first] = measureLines({ ...THEIRS, from: 5.56, to: 6.87 })
  assert.equal(first, "+1.31 (+23.56%) +131")
})

test("the money follows the instrument's tick, not the size of the move", () => {
  // A 75-cent move on a five-dollar stock is −0.75, not −0.7490 (2026-09-16).
  const [first] = measureLines({ from: 5.43, to: 4.681, bars: 214, seconds: 19_260, volume: 869_000 })
  assert.equal(first, "−0.75 (−13.79%) −75")
})

test("a sub-dollar name counts in hundredths of a cent, as it quotes", () => {
  assert.equal(tickSize(6.87), 0.01)
  assert.equal(tickSize(0.42), 0.0001)
  const [first] = measureLines({ from: 0.4200, to: 0.4350, bars: 3, seconds: 180, volume: 0 })
  assert.equal(first, "+0.0150 (+3.57%) +150")
})

test("the clock takes the two largest units that are not zero", () => {
  assert.equal(spanWords(91_800), "1d 1h 30m")
  assert.equal(spanWords(5_400), "1h 30m")
  assert.equal(spanWords(2_700), "45m")
  assert.equal(spanWords(45), "45s")
  assert.equal(spanWords(86_400), "1d")
  assert.equal(spanWords(-5_400), "1h 30m")           // either direction
})

test("volume is short enough to sit in a label", () => {
  assert.equal(compactVolume(1_390_000), "1.39M")
  assert.equal(compactVolume(930_400), "930K")
  assert.equal(compactVolume(12_300), "12.3K")
  assert.equal(compactVolume(12_340_000_000), "12.34B")
  assert.equal(compactVolume(0), "0")
})

test("unknown volume drops the line rather than claiming nothing traded", () => {
  const lines = measureLines({ ...THEIRS, volume: null })
  assert.equal(lines.length, 2)
  assert.equal(lines[1], "51 bars, 1d 1h 30m")
})

test("one bar is a bar, and an anchor off the series drops the count", () => {
  assert.equal(measureLines({ ...THEIRS, bars: 1 })[1], "1 bar, 1d 1h 30m")
  assert.equal(measureLines({ ...THEIRS, bars: null })[1], "1d 1h 30m")
})
