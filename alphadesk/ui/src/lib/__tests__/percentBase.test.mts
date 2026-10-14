import assert from "node:assert/strict"
import test from "node:test"
import { previousSessionLastIndex } from "../percentBase.ts"

test("the zero bar is the previous session's last regular bar, not the first bar loaded", () => {
  const bars = [
    { t: "2026-10-12T00:00:00Z" },   // Sunday 8:00pm New York, overnight: not a session
    { t: "2026-10-12T14:00:00Z" },   // Monday 10:00
    { t: "2026-10-12T19:45:00Z" },   // Monday 15:45, Monday's last regular bar
    { t: "2026-10-12T21:00:00Z" },   // Monday 17:00, after hours
    { t: "2026-10-13T13:30:00Z" },   // Tuesday 09:30
    { t: "2026-10-13T19:45:00Z" },   // Tuesday 15:45
    { t: "2026-10-14T14:15:00Z" },   // Wednesday 10:15, today
  ]
  assert.equal(previousSessionLastIndex(bars), 5)          // Tuesday 15:45
})

test("one session or none: no previous session to measure from", () => {
  assert.equal(previousSessionLastIndex([{ t: "2026-10-14T14:15:00Z" }]), -1)
  assert.equal(previousSessionLastIndex([{ t: "2026-10-12T00:00:00Z" }]), -1)
  assert.equal(previousSessionLastIndex([]), -1)
})
