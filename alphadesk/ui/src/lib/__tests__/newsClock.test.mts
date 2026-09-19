import assert from "node:assert/strict"
import test from "node:test"
import { etDay, newsTime } from "../newsClock.ts"

// 2026-09-17 19:47 New York = 23:47 UTC.
const NOW = new Date("2026-09-17T23:47:00Z")

test("a story from today is a bare time, as it was before", () => {
  assert.equal(newsTime("2026-09-17T21:13:05Z", NOW), "5:13 PM ET")
})

test("yesterday is named rather than dated", () => {
  assert.equal(newsTime("2026-09-16T18:30:00Z", NOW), "Yesterday 2:30 PM ET")
})

test("older stories in the window carry the day", () => {
  assert.equal(newsTime("2026-09-11T13:05:00Z", NOW), "Sep 11 · 9:05 AM ET")
})

test("another year carries the year too", () => {
  assert.equal(newsTime("2025-12-31T18:00:00Z", NOW), "Dec 31, 2025 · 1:00 PM ET")
})

test("the day is New York's, not the reader's or UTC's", () => {
  // 00:30 UTC on the 18th is still the evening of the 17th in New York, so
  // this is TODAY's news to a reader watching the US market.
  assert.equal(newsTime("2026-09-18T00:30:00Z", NOW), "8:30 PM ET")
  assert.equal(etDay(new Date("2026-09-18T00:30:00Z")), "2026-09-17")
})

test("nothing renders for a missing or unparseable stamp", () => {
  assert.equal(newsTime(null, NOW), "")
  assert.equal(newsTime("", NOW), "")
  assert.equal(newsTime("not a date", NOW), "")
})
