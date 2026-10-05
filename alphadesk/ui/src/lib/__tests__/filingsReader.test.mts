import assert from "node:assert/strict"
import test from "node:test"
import { describeFiling, dayLabel, filingKey, groupByDay, moveSelection, otherTickers, timeLabel } from "../filingsReader.ts"

test("a filing with declared items shows them as the registrant worded them", () => {
  const d = describeFiling({ form: "8-K", items: [{ number: "5.02", label: "Departure of Directors" }, { number: "9.01", label: "Financial Statements and Exhibits" }] })
  assert.equal(d.declared, true)
  assert.deepEqual(d.lines, [{ n: "5.02", label: "Departure of Directors" }, { n: "9.01", label: "Financial Statements and Exhibits" }])
})

test("a filing with no items shows what the form is, and says it is not a declared event", () => {
  assert.deepEqual(describeFiling({ form: "SCHEDULE 13G/A", items: [] }), { declared: false, lines: [{ n: "", label: "Passive stake report, amended" }] })
  assert.equal(describeFiling({ form: "SC TO-I/A" }).lines[0].label, "Issuer tender offer, amended")
  assert.equal(describeFiling({ form: "SCHEDULE 13D" }).lines[0].label, "Active stake report (a holder of 5% or more)")
  assert.equal(describeFiling({ form: "S-1" }).lines[0].label, "S-1")                       // an unknown form is shown as it is, never guessed
})

test("a filing's key is its accession, else something that stays the same between polls", () => {
  assert.equal(filingKey({ accession: "0001-26-1", form: "8-K", cik: "1", filed_at: "t" }), "0001-26-1")
  assert.equal(filingKey({ accession: null, form: "8-K", cik: "123", filed_at: "2026-10-05T10:00:00-04:00" }), "8-K|123|2026-10-05T10:00:00-04:00")
})

test("times and days are on the New York clock, whatever the reader's", () => {
  assert.equal(timeLabel("2026-10-05T10:55:07-04:00"), "10:55 AM")
  assert.equal(timeLabel("2026-10-05T14:55:07Z"), "10:55 AM")
  assert.equal(timeLabel("nonsense"), "—")
  const now = new Date("2026-10-05T16:00:00Z")                                              // noon in New York
  assert.equal(dayLabel("2026-10-05T10:55:07-04:00", now), "Today")
  assert.equal(dayLabel("2026-10-04T23:30:00-04:00", now), "Yesterday")
  assert.equal(dayLabel("2026-10-02T17:36:02-04:00", now), "Fri, Oct 2")
  assert.equal(dayLabel("2026-10-06T00:30:00Z", new Date("2026-10-06T03:00:00Z")), "Today")       // both are the evening of the 5th in New York
  assert.equal(dayLabel("2026-10-06T00:30:00Z", new Date("2026-10-06T16:00:00Z")), "Yesterday")   // 8:30 PM on the 5th, seen at noon on the 6th
})

test("rows are grouped into runs of the same day, in the order given", () => {
  const now = new Date("2026-10-05T16:00:00Z")
  const rows = [{ filed_at: "2026-10-05T11:00:00-04:00" }, { filed_at: "2026-10-05T09:00:00-04:00" }, { filed_at: "2026-10-02T17:00:00-04:00" }]
  const g = groupByDay(rows, now)
  assert.deepEqual(g.map(x => [x.label, x.rows.length]), [["Today", 2], ["Fri, Oct 2", 1]])
  assert.deepEqual(groupByDay([], now), [])
})

test("keyboard moves stay inside the list and recover from no selection", () => {
  assert.equal(moveSelection(5, 0, -1), 0)
  assert.equal(moveSelection(5, 4, 1), 4)
  assert.equal(moveSelection(5, 2, 1), 3)
  assert.equal(moveSelection(5, -1, 1), 1)
  assert.equal(moveSelection(0, 0, 1), -1)
})

test("a company's other tickers are listed without the first", () => {
  assert.deepEqual(otherTickers(["CHSCL", "CHSCM", "CHSCN"]), ["CHSCM", "CHSCN"])
  assert.deepEqual(otherTickers(["KR"]), [])
  assert.deepEqual(otherTickers(undefined), [])
})
