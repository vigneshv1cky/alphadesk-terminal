import assert from "node:assert/strict"
import { test } from "node:test"
import { ago, etClock, etDayClock, inBackfillWindow, nextDay, reportedLabel, sessionLabel, timely, whenLabel } from "../earningsClock.ts"

// Instants are written in UTC; New York is UTC-4 in September (EDT).
const FRI = "2026-09-11"

test("a same-day sighting from 06:00 ET stands as the clock; the 01:47 sweep does not", () => {
  assert.equal(timely("2026-09-11T10:59:00Z", FRI), true)      // 6:59 AM ET
  assert.equal(timely("2026-09-11T09:59:00Z", FRI), false)     // 5:59 AM ET, before the loop
  assert.equal(timely("2026-09-12T05:47:00Z", FRI), false)     // Sat 1:47 AM ET, the sweep
  assert.equal(timely("2026-09-11T10:59:00Z", "2026-09-04"), false)   // last week's row stamped today
})

test("the backfill window is the report day or the next morning before noon ET", () => {
  assert.equal(inBackfillWindow("2026-09-12T05:47:00Z", FRI), true)    // Sat 1:47 AM
  assert.equal(inBackfillWindow("2026-09-12T15:59:00Z", FRI), true)    // Sat 11:59 AM
  assert.equal(inBackfillWindow("2026-09-12T16:00:00Z", FRI), false)   // Sat noon: too late
  assert.equal(inBackfillWindow("2026-09-14T13:00:00Z", FRI), false)   // Monday
  assert.equal(inBackfillWindow("garbage", FRI), false)
  assert.equal(nextDay("2026-09-30"), "2026-10-01")
})

test("clocks read in New York", () => {
  assert.equal(etClock("2026-09-11T10:59:00Z", FRI), "6:59 AM")
  assert.equal(etClock("2026-09-12T05:47:00Z", FRI, true), "Sep 12 1:47 AM")   // dated when off the day
  assert.equal(etClock("2026-09-11T20:31:00Z", FRI, true), "4:31 PM")           // on the day, no date
  assert.equal(etDayClock("2026-09-12T05:47:00Z"), "Sat 1:47 AM")
  assert.equal(etClock("garbage", FRI), "")
})

test("the When cell: out with EDGAR's clock, a same-day sighting, a weekend sighting, a plain Out", () => {
  const base = { report_date: FRI, session: "BMO", confirmed: true }
  assert.equal(whenLabel({ ...base, eps_actual: 1.05, released_at: "2026-09-11T10:59:00Z" }, "2026-09-13"), "Out 6:59 AM")
  assert.equal(whenLabel({ ...base, eps_actual: 1.05, actual_at: "2026-09-11T11:20:00Z" }, "2026-09-13"), "Out 7:20 AM")
  assert.equal(whenLabel({ ...base, eps_actual: 1.05, actual_at: "2026-09-12T05:47:00Z" }, "2026-09-13"), "Seen Sat 1:47 AM")
  assert.equal(whenLabel({ ...base, eps_actual: 1.05, actual_at: "2026-09-14T13:00:00Z" }, "2026-09-15"), "Out pre-mkt")
  assert.equal(whenLabel({ ...base, session: "DAY", eps_actual: 1.05, actual_at: "2026-09-14T13:00:00Z" }, "2026-09-15"), "Out")
  // EDGAR's acceptance wins over a sighting when both exist
  assert.equal(whenLabel({ ...base, eps_actual: 1.05, released_at: "2026-09-11T20:31:00Z", actual_at: "2026-09-12T05:47:00Z" }, "2026-09-13"), "Out 4:31 PM")
})

test("a release without a clock of its own reads Out with the vendor's session, never a filing time", () => {
  // Optical Cable: released Wednesday before the open, 8-K filed Friday 4:15 PM
  assert.equal(whenLabel({ report_date: "2026-09-09", session: "BMO", confirmed: true, released_on: "2026-09-09", eps_actual: 0.21 }, "2026-09-14"), "Out pre-mkt")
  assert.equal(whenLabel({ report_date: FRI, session: "AMC", confirmed: true, released_on: FRI }, "2026-09-13"), "Out after")
  assert.equal(whenLabel({ report_date: FRI, session: null, confirmed: true, released_on: FRI }, "2026-09-13"), "Out")
})

test("the When cell: a passed day reads Pending or Not seen, never TBA", () => {
  assert.equal(whenLabel({ report_date: FRI, session: "AMC", confirmed: true }, "2026-09-13"), "Pending")
  assert.equal(whenLabel({ report_date: FRI, session: null, confirmed: false }, "2026-09-13"), "Not seen")
})

test("the When cell ahead of the day: the named session, or TBA for a projection", () => {
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "BMO", confirmed: true }, "2026-09-13"), "Pre-mkt")
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "AMC", confirmed: true }, "2026-09-13"), "After")
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "DAY", confirmed: true }, "2026-09-13"), "Day")
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "AMC", confirmed: false }, "2026-09-13"), "TBA")
  assert.equal(whenLabel({ report_date: "2026-09-13", session: "AMC", confirmed: false }, "2026-09-13"), "TBA")   // today is not past
})

test("an unconfirmed upcoming report shows the company's usual session with an asterisk", () => {
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "DAY", confirmed: false, session_predicted: "AMC" }, "2026-09-14"), "After*")
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "DAY", confirmed: false, session_predicted: "BMO" }, "2026-09-14"), "Pre-mkt*")
  // a vendor's confirmed session wins over the habit
  assert.equal(whenLabel({ report_date: "2026-09-17", session: "BMO", confirmed: true, session_predicted: "AMC" }, "2026-09-14"), "Pre-mkt")
  // a passed day is Pending / Not seen, never a prediction
  assert.equal(whenLabel({ report_date: "2026-09-11", session: "DAY", confirmed: false, session_predicted: "AMC" }, "2026-09-14"), "Not seen")
})

test("session words and ages", () => {
  assert.equal(sessionLabel({ session: "BMO", confirmed: true, eps_actual: null }), "Before the open")
  assert.equal(sessionLabel({ session: "AMC", confirmed: false, eps_actual: 1.0 }), "After the close")
  assert.equal(sessionLabel({ session: "DAY", confirmed: false, eps_actual: null }), "Time to be announced")
  const now = Date.parse("2026-09-13T12:00:00Z")
  assert.equal(ago("2026-09-13T11:58:30Z", now), "2 min ago")
  assert.equal(ago("2026-09-13T09:00:00Z", now), "3 h ago")
  assert.equal(ago("2026-09-10T12:00:00Z", now), "3 d ago")
  assert.equal(ago("2026-09-13T13:00:00Z", now), "")   // the future is not an age
})

// ── The results feed's clock (2026-09-28) ─────────────────────────────────
// The reader, looking at the live tab: "OUT is not needed right?" — on a feed
// where every row has reported it is on every line and says nothing.
test("reportedLabel drops Out and shows the clock alone", () => {
  assert.equal(reportedLabel({
    report_date: "2026-09-22", session: "BMO",
    released_at: "2026-09-22T06:55:14-04:00", released_on: "2026-09-22",
  }), etClock("2026-09-22T06:55:14-04:00", "2026-09-22"))
})

test("a filing that landed days later shows no time and borrows none", () => {
  // 25 of a fortnight's 169 rows were filed one to six days after the release
  // they report. The company's own words date the DAY; nothing dates the hour,
  // and the news feed could time 1 of 17 of them. This used to print the
  // FILING day — one to six days after the release, beside a row already
  // dated correctly — which reads as the public moment and is not.
  assert.equal(reportedLabel({
    report_date: "2026-09-22", session: null,
    released_on: "2026-09-22", filed_on: "2026-09-25",
  }), "day only")
})

test("no clock and no later filing falls back to the session", () => {
  assert.equal(reportedLabel({ report_date: "2026-09-22", session: "AMC", released_on: "2026-09-22" }), "after")
  assert.equal(reportedLabel({ report_date: "2026-09-22", session: "BMO", released_on: "2026-09-22" }), "pre-mkt")
  assert.equal(reportedLabel({ report_date: "2026-09-22", session: null, released_on: "2026-09-22" }), "day only")
})
