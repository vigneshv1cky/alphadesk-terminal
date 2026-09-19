import assert from "node:assert/strict"
import { test } from "node:test"
import { fiscalQuarter, fiscalYearEndMonth, lastQuarters, periodLabel, reportedQuarterLabel } from "../fiscal.ts"

test("the fiscal year end month reads from the last fiscal year end", () => {
  assert.equal(fiscalYearEndMonth("2025-09-27"), 9)     // Apple
  assert.equal(fiscalYearEndMonth("2026-01-31"), 1)     // GameStop
  assert.equal(fiscalYearEndMonth(null), null)
  assert.equal(fiscalYearEndMonth("garbage"), null)
})

test("quarters are named as the company names them", () => {
  assert.deepEqual(fiscalQuarter("2026-06-27", 9), { q: 3, fy: 2026 })    // Apple's June quarter is Q3 FY26
  assert.deepEqual(fiscalQuarter("2026-09-26", 9), { q: 4, fy: 2026 })
  assert.deepEqual(fiscalQuarter("2025-12-27", 9), { q: 1, fy: 2026 })    // December closes Apple's Q1 of the NEXT fiscal year
  assert.deepEqual(fiscalQuarter("2026-08-01", 1), { q: 2, fy: 2027 })    // GameStop's July quarter, ended 1 August: Q2 FY27
  assert.deepEqual(fiscalQuarter("2026-07-26", 1), { q: 2, fy: 2027 })    // NVIDIA's July quarter: Q2 FY27
  assert.deepEqual(fiscalQuarter("2026-06-30", 12), { q: 2, fy: 2026 })   // a calendar-year company
  assert.equal(fiscalQuarter("2026-06-30", null), null)
})

test("labels fall back to the calendar when the fiscal year end is unknown", () => {
  assert.equal(periodLabel("2026-06-27", "quarterly", 9), "Q3 FY26")
  assert.equal(periodLabel("2025-09-27", "annual", 9), "FY25")
  assert.equal(periodLabel("2026-06-30", "quarterly", null), "Q2 '26")
  assert.equal(periodLabel("2026-06-30", "annual", null), "2026")
})

test("a report is labelled for the quarter it covers", () => {
  assert.equal(reportedQuarterLabel("2026-07-30", 9), "Q3 FY26")    // Apple reported its June quarter on 30 July
  assert.equal(reportedQuarterLabel("2026-10-29", 9), "Q4 FY26")    // the next report covers the September quarter
  assert.equal(reportedQuarterLabel("2026-09-09", 1), "Q2 FY27")    // GameStop's early-September report
  assert.equal(reportedQuarterLabel("2026-07-30", null), null)
})

test("the EPS chart keeps the last four quarters, oldest first, whatever order they arrive in", () => {
  const q = (date: string) => ({ date })
  // FMP's whole record, oldest first — NVIDIA's reaches back to 1999.
  const whole = ["1999-05-18", "2025-11-19", "2026-02-25", "2026-05-27", "2026-08-26"].map(q)
  assert.deepEqual(lastQuarters(whole).map(r => r.date), ["2025-11-19", "2026-02-25", "2026-05-27", "2026-08-26"])
  // Newest first gives the same four in the same order.
  assert.deepEqual(lastQuarters([...whole].reverse()).map(r => r.date), ["2025-11-19", "2026-02-25", "2026-05-27", "2026-08-26"])
  // Fewer than four: all of them.
  assert.deepEqual(lastQuarters([q("2026-08-26"), q("2026-05-27")]).map(r => r.date), ["2026-05-27", "2026-08-26"])
})
