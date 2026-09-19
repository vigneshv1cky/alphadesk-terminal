import assert from "node:assert/strict"
import test from "node:test"
import { defaultDay } from "../earningsDefaultDay.ts"

const week = [
  { date: "2026-09-14", count: 32 }, { date: "2026-09-15", count: 17 }, { date: "2026-09-16", count: 13 },
  { date: "2026-09-17", count: 18 }, { date: "2026-09-18", count: 13 },
]
const at = (today: string, days = week, stepped = false) => defaultDay(days, "2026-09-14", "2026-09-18", today, stepped)

test("a weekday opens on itself", () => {
  assert.deepEqual(at("2026-09-16"), { day: "2026-09-16", stepBack: false })
})

test("a weekend opens on the Friday", () => {
  assert.deepEqual(at("2026-09-19"), { day: "2026-09-18", stepBack: false })
  assert.deepEqual(at("2026-09-20"), { day: "2026-09-18", stepBack: false })
})

test("a holiday opens on the last day before it that had reports", () => {
  const thanksgiving = week.map(d => (d.date === "2026-09-17" ? { ...d, count: 0 } : d))
  assert.deepEqual(at("2026-09-17", thanksgiving), { day: "2026-09-16", stepBack: false })
})

test("a Monday holiday steps back a week, and that week opens on its last reporting day", () => {
  const labourDay = week.map(d => (d.date === "2026-09-14" ? { ...d, count: 0 } : d))
  assert.deepEqual(at("2026-09-14", labourDay), { day: null, stepBack: true })
  // After the step the loaded week is the one before: its Friday.
  const prev = [{ date: "2026-09-07", count: 5 }, { date: "2026-09-11", count: 9 }]
  assert.deepEqual(defaultDay(prev, "2026-09-07", "2026-09-11", "2026-09-14", true), { day: "2026-09-11", stepBack: false })
})

test("a week the reader moved to opens whole", () => {
  assert.deepEqual(defaultDay(week, "2026-09-21", "2026-09-25", "2026-09-16", false), { day: null, stepBack: false })
})
