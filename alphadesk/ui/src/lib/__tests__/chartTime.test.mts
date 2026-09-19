import assert from "node:assert/strict"
import { test } from "node:test"
import { barCloseCountdown, countdownLabel, validTimeZone } from "../chartTime.ts"

test("intraday countdown runs from the bar start to its close", () => {
  const start = Date.parse("2026-09-04T15:59:00-04:00")
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "1m", start + 15_000), 45)
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "5m", start + 15_000), 285)
  // Over: the bar has closed, nothing to count.
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "1m", start + 61_000), null)
  // Before the bar started — a clock skew — is not a countdown either.
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "1m", start - 1_000), null)
})

test("a daily bar closes sixteen hours after its exchange midnight", () => {
  const start = Date.parse("2026-09-04T00:00:00-04:00")
  assert.equal(barCloseCountdown("2026-09-04T00:00:00-04:00", "1d", start + 15 * 3_600_000), 3_600)
  assert.equal(barCloseCountdown("2026-09-04T00:00:00-04:00", "1wk", start), null)
  assert.equal(barCloseCountdown("garbage", "1m", start), null)
})

test("countdown labels", () => {
  assert.equal(countdownLabel(45), "00:45")
  assert.equal(countdownLabel(285), "04:45")
  assert.equal(countdownLabel(3_600), "1:00:00")
})

test("time zones are validated by the runtime", () => {
  assert.equal(validTimeZone("Asia/Tokyo"), true)
  assert.equal(validTimeZone("Mars/Olympus"), false)
  assert.equal(validTimeZone(""), false)
  assert.equal(validTimeZone(42), false)
})

test("the countdown parses any interval id", () => {
  const start = Date.parse("2026-09-04T15:59:00-04:00")
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "10s", start + 3_000), 7)
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "3m", start + 60_000), 120)
  assert.equal(barCloseCountdown("2026-09-04T15:59:00-04:00", "2h", start + 3_600_000), 3_600)
})

import { timeAxisTicks, timeParts } from "../chartTime.ts"

const minutes = (startIso: string, n: number, stepMin = 1) => {
  const t0 = Date.parse(startIso)
  return Array.from({ length: n }, (_, i) => new Date(t0 + i * stepMin * 60_000).toISOString())
}

test("minute bars label the hours, and the day number at a day change", () => {
  // 09:30 ET to 16:00 ET, then the next morning 09:30 — an overnight gap
  // that is one bar wide.
  const day1 = minutes("2026-09-08T13:30:00Z", 391)
  const day2 = minutes("2026-09-09T13:30:00Z", 391)
  const parts = timeParts([...day1, ...day2], "America/New_York")
  const ticks = timeAxisTicks(parts, 0, parts.length - 1, 12, 2026)
  const labels = ticks.map(t => t.label)
  assert.ok(labels.includes("10:00") && labels.includes("12:00"), labels.join(","))
  const day = ticks.find(t => t.label === "9")
  assert.ok(day && day.major && day.i === 391, JSON.stringify(ticks))
  assert.ok(ticks.length <= 12)
  assert.ok(!labels.some(l => l.startsWith("Sep")))
})

test("daily bars label days inside a month and the month at its start", () => {
  const t0 = Date.parse("2026-08-03T00:00:00-04:00")
  const times = Array.from({ length: 60 }, (_, i) => new Date(t0 + i * 86_400_000).toISOString())
  const parts = timeParts(times, "America/New_York")
  const ticks = timeAxisTicks(parts, 0, 59, 10, 2026)
  assert.ok(ticks.some(t => t.label === "Sep" && t.major), JSON.stringify(ticks))
  assert.ok(ticks.some(t => /^\d+$/.test(t.label)), "day numbers")
  assert.ok(ticks.length <= 10)
})

test("a window in another year names the year on the month", () => {
  const t0 = Date.parse("2024-02-20T00:00:00-05:00")
  const times = Array.from({ length: 30 }, (_, i) => new Date(t0 + i * 86_400_000).toISOString())
  const ticks = timeAxisTicks(timeParts(times, "America/New_York"), 0, 29, 8, 2026)
  assert.ok(ticks.some(t => t.label === "Mar 2024"), JSON.stringify(ticks))
})

test("years alone when even the months will not fit", () => {
  const t0 = Date.parse("2016-01-01T00:00:00-05:00")
  const times = Array.from({ length: 10 * 52 }, (_, i) => new Date(t0 + i * 7 * 86_400_000).toISOString())
  const parts = timeParts(times, "America/New_York")
  const ticks = timeAxisTicks(parts, 0, parts.length - 1, 6, 2026)
  assert.ok(ticks.length > 0 && ticks.every(t => /^\d{4}$/.test(t.label)), JSON.stringify(ticks))
  assert.ok(ticks.length <= 6)
})

import { focusIndex, thinTicks } from "../chartTime.ts"

test("a sparse series labels the boundary, not the bar's own minute", () => {
  // Prints at 11:58, 12:06, 12:33, 13:02 ET: the bar past noon is 12:06.
  const times = ["15:58", "16:06", "16:33", "17:02"].map(t => `2026-09-09T${t}:00Z`)
  const ticks = timeAxisTicks(timeParts(times, "America/New_York"), 0, 3, 3, 2026)
  assert.ok(ticks.some(t => t.label === "12:00"), JSON.stringify(ticks))
  assert.ok(!ticks.some(t => t.label === "12:06"))
})

test("ticks closer than the gap keep the coarser level", () => {
  const out = thinTicks([
    { x: 10, level: 1 }, { x: 20, level: 2 }, { x: 30, level: 1 }, { x: 100, level: 1 },
  ], 48)
  assert.deepEqual(out.map(t => t.x), [20, 100])
})

test("1D focuses on the last session's day, the buffer before it is history", () => {
  const day1 = minutes("2026-09-09T13:30:00Z", 391)
  const day2 = minutes("2026-09-10T13:30:00Z", 200)
  assert.equal(focusIndex([...day1, ...day2], "1D"), 391)
  assert.equal(focusIndex([...day1, ...day2], "5D"), 0)
})

test("a day of a few overnight prints does not count as the session", () => {
  const day1 = minutes("2026-09-09T13:30:00Z", 391)
  const night = minutes("2026-09-11T01:00:00Z", 5)   // 21:00 ET on the 10th
  assert.equal(focusIndex([...day1, ...night], "1D"), 0)
})

test("calendar ranges count back from the last bar; All opens on everything", () => {
  const t0 = Date.parse("2026-01-05T00:00:00-05:00")
  const times = Array.from({ length: 250 }, (_, i) => new Date(t0 + i * 86_400_000).toISOString())
  const i1m = focusIndex(times, "1M")
  assert.ok(i1m > 200 && i1m < 230, String(i1m))
  assert.equal(focusIndex(times, "MAX"), 0)
  assert.equal(focusIndex(times, "YTD"), 0)   // all of it is this year
})
