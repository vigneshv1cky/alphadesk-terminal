import assert from "node:assert/strict"
import test from "node:test"
import { bucketBars } from "../chartBuckets.ts"

const bar = (o: number, h: number, l: number, c: number) => ({ o, h, l, c })

test("bars that fit are returned one each", () => {
  const bars = [bar(1, 2, 0.5, 1.5), bar(1.5, 3, 1, 2), bar(2, 2.5, 1.8, 2.2)]
  const got = bucketBars(bars, 0, 2, 100)
  assert.equal(got.length, 3)
  assert.deepEqual(got.map(b => b.i), [0, 1, 2])
  assert.deepEqual(got.map(b => b.n), [1, 1, 1])
})

test("a crowd of bars becomes about one candle per column", () => {
  const bars = Array.from({ length: 48000 }, (_, i) => bar(i, i + 2, i - 2, i + 1))
  const got = bucketBars(bars, 0, 47999, 400)
  assert.ok(got.length <= 400 && got.length >= 300, `got ${got.length}`)
  assert.equal(got.reduce((n, b) => n + b.n, 0), 48000)          // every bar is in exactly one candle
})

test("a folded candle keeps the first open, the last close, the highest high and the lowest low", () => {
  const bars = [bar(10, 12, 9, 11), bar(11, 20, 10, 12), bar(12, 13, 2, 3), bar(3, 5, 1, 4)]
  const got = bucketBars(bars, 0, 3, 1)
  assert.equal(got.length, 1)
  assert.deepEqual({ o: got[0].o, h: got[0].h, l: got[0].l, c: got[0].c, n: got[0].n }, { o: 10, h: 20, l: 1, c: 4, n: 4 })
  assert.equal(got[0].i, 1.5)
})

test("a window inside a longer list is bucketed on its own bars only", () => {
  const bars = Array.from({ length: 1000 }, (_, i) => bar(i, i + 1, i - 1, i))
  const got = bucketBars(bars, 100, 299, 50)
  assert.equal(got.reduce((n, b) => n + b.n, 0), 200)
  assert.ok(got[0].i >= 100 && got[got.length - 1].i <= 299)
})

test("an empty or inverted window is nothing", () => {
  assert.deepEqual(bucketBars([bar(1, 1, 1, 1)], 3, 2, 10), [])
})
