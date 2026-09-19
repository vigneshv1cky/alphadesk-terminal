import assert from "node:assert/strict"
import test from "node:test"
import { readKept } from "../keptState.ts"

test("a kept value comes back on the same day", () => {
  assert.equal(readKept(JSON.stringify({ day: "2026-09-18", value: "2026-09-18" }), "2026-09-18", null), "2026-09-18")
  assert.equal(readKept(JSON.stringify({ day: "2026-09-18", value: null }), "2026-09-18", "x"), null)
})

test("a value from another day, or none, or garbage, gives the fallback", () => {
  assert.equal(readKept(JSON.stringify({ day: "2026-09-17", value: "2026-09-17" }), "2026-09-18", null), null)
  assert.equal(readKept(null, "2026-09-18", "fallback"), "fallback")
  assert.equal(readKept("{not json", "2026-09-18", "fallback"), "fallback")
})
