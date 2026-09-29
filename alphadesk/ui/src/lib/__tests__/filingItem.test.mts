import { strict as assert } from "node:assert"
import { test } from "node:test"
import { shortItem } from "../filingItem.ts"

test("a long SEC item name is cut at its first clause so the count survives", () => {
  // Real labels from EDGAR, seen in the live feed on 2026-09-29.
  assert.equal(
    shortItem("Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers: Compensatory Arrangements of Certain Officers"),
    "Departure of Directors or Certain Officers")
  assert.equal(
    shortItem("Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing"),
    "Notice of Delisting or Failure to Satisfy a…")
  // Short ones are left exactly as the SEC wrote them.
  assert.equal(shortItem("Results of Operations and Financial Condition"),
               "Results of Operations and Financial Condition")
  assert.equal(shortItem("Regulation FD Disclosure"), "Regulation FD Disclosure")
  assert.equal(shortItem("Other Events"), "Other Events")
})

test("a cut never lands mid-word and never leaves a trailing space", () => {
  const out = shortItem("Entry into a Material Definitive Agreement That Runs On Considerably Past The Limit")
  assert.ok(out.endsWith("…"))
  assert.ok(!out.includes(" …"))
  assert.ok(out.length <= 54)
})
