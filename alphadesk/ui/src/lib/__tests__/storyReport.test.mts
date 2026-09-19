import assert from "node:assert/strict"
import test from "node:test"
import { reportBehindStory, reportedLine } from "../storyReport.ts"

// ZTO Express: the quarter was announced on 18 August and Benzinga published
// the transcript on 16 September, with only its own date on the story.
const ZTO = [
  { report_date: "2026-05-19", eps_actual: 0.43 },
  { report_date: "2026-08-18", eps_actual: 0.56 },
  { report_date: "2026-11-18", eps_actual: null },   // still to come
]

test("the report behind a story is the last one made before it was published", () => {
  const r = reportBehindStory(ZTO, "2026-09-16T13:50:00Z")
  assert.equal(r?.report_date, "2026-08-18")
})

test("a report still to come is never the one behind a story", () => {
  assert.equal(reportBehindStory(ZTO, "2026-12-01T00:00:00Z")?.report_date, "2026-08-18")
  assert.equal(reportBehindStory([{ report_date: "2026-11-18", eps_actual: null }], "2026-12-01T00:00:00Z"), null)
})

test("a company that had not reported yet gets no line", () => {
  assert.equal(reportBehindStory(ZTO, "2026-01-05T00:00:00Z"), null)
  assert.equal(reportBehindStory(undefined, "2026-09-16T00:00:00Z"), null)
})

test("the line says how far back the report was", () => {
  assert.equal(reportedLine("2026-08-18", "2026-09-16T13:50:00Z"), "Reported Aug 18, 2026 — 4 weeks before this story")
  assert.equal(reportedLine("2026-09-09", "2026-09-16T13:50:00Z"), "Reported Sep 9, 2026 — 7 days before this story")
  assert.equal(reportedLine("2026-03-31", "2026-09-16T13:50:00Z"), "Reported Mar 31, 2026 — 6 months before this story")
})

test("a story that followed its report within a couple of days just names the day", () => {
  assert.equal(reportedLine("2026-09-15", "2026-09-16T13:50:00Z"), "Reported Sep 15, 2026")
  assert.equal(reportedLine("2026-09-16", "2026-09-16T13:50:00Z"), "Reported Sep 16, 2026")
})

test("a date that is not a date draws nothing", () => {
  assert.equal(reportedLine("not-a-date", "2026-09-16T13:50:00Z"), null)
})
