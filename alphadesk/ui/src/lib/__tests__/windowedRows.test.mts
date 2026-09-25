import assert from "node:assert/strict"
import test from "node:test"
import { rowAt, runningOffsets, visibleRange } from "../windowedRows.ts"

// The news list measured on the owner's machine: rows average about 104px,
// the box that scrolls them is 778px, and the list runs to thousands.
const EST = 104
const BOX = 778
const even = (n: number) => new Array(n).fill(EST)

test("offsets are a running total, with one more entry than there are rows", () => {
  assert.deepEqual(runningOffsets([10, 20, 30]), [0, 10, 30, 60])
  assert.deepEqual(runningOffsets([]), [0])
})

test("a row is found by where it starts, not where it ends", () => {
  const o = runningOffsets([10, 20, 30]) // starts at 0, 10, 30
  assert.equal(rowAt(o, 0), 0)
  assert.equal(rowAt(o, 9), 0)
  assert.equal(rowAt(o, 10), 1)  // exactly on a boundary belongs to the row it opens
  assert.equal(rowAt(o, 29), 1)
  assert.equal(rowAt(o, 30), 2)
  assert.equal(rowAt(o, 99), 2)  // past the end stays on the last row
})

test("an empty list asks for nothing", () => {
  assert.deepEqual(visibleRange(runningOffsets([]), 0, BOX, 6, 0), { start: 0, end: 0 })
})

test("the window is a handful of rows however long the list is", () => {
  // THE WHOLE POINT: eight hundred stories and eight thousand must render
  // the same number of rows, or the freeze comes back at a bigger list.
  const small = visibleRange(runningOffsets(even(800)), 4000, BOX, 6, 800)
  const huge = visibleRange(runningOffsets(even(8000)), 4000, BOX, 6, 8000)
  assert.equal(small.end - small.start, huge.end - huge.start)
  assert.ok(huge.end - huge.start < 25, `rendered ${huge.end - huge.start} rows`)
})

test("the window covers the whole box, top and bottom edges included", () => {
  const o = runningOffsets(even(800))
  const { start, end } = visibleRange(o, 4000, BOX, 0, 800)
  assert.ok(o[start] <= 4000, "the first row must start at or above the viewport top")
  assert.ok(o[end] >= 4000 + BOX, "the last row must reach past the viewport bottom")
})

test("overscan widens the window without running off either end", () => {
  const o = runningOffsets(even(800))
  const top = visibleRange(o, 0, BOX, 6, 800)
  assert.equal(top.start, 0, "cannot overscan above the first row")
  const bottom = visibleRange(o, o[800] - BOX, BOX, 6, 800)
  assert.equal(bottom.end, 800, "cannot overscan past the last row")
})

test("rows of different heights are placed by their own height, not the estimate", () => {
  // A headline with a summary is taller than one without; if the offsets
  // used the estimate anyway, the list would drift further out of place the
  // further down it was scrolled.
  const heights = [200, 60, 200, 60, 200]
  const o = runningOffsets(heights)
  assert.deepEqual(o, [0, 200, 260, 460, 520, 720])
  assert.equal(rowAt(o, 259), 1)
  assert.equal(rowAt(o, 260), 2)
})

test("a viewport taller than the list asks for every row and no more", () => {
  const o = runningOffsets(even(3))
  assert.deepEqual(visibleRange(o, 0, 5000, 6, 3), { start: 0, end: 3 })
})
