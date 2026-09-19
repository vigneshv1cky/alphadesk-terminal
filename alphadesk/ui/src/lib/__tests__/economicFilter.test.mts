import assert from "node:assert/strict"
import { test } from "node:test"
import { DEFAULT_FILTER, countryCounts, isDefault, parseFilter, passes } from "../economicFilter.ts"

const holiday = { impact: "none", country: "MV" }
const cpi = { impact: "high", country: "US" }
const pmi = { impact: "medium", country: "JP" }
const auction = { impact: "low", country: "KR" }

test("the default hides only no-impact entries, in every country", () => {
  assert.deepEqual([holiday, cpi, pmi, auction].map(r => passes(r, DEFAULT_FILTER)), [false, true, true, true])
  assert.equal(passes({ impact: null, country: "US" }, DEFAULT_FILTER), false)
})

test("an impact floor and a country set both apply", () => {
  assert.deepEqual([holiday, cpi, pmi, auction].map(r => passes(r, { impact: "medium", countries: [] })), [false, true, true, false])
  assert.deepEqual([holiday, cpi, pmi, auction].map(r => passes(r, { impact: "all", countries: ["US"] })), [false, true, false, false])
  assert.equal(passes(holiday, { impact: "all", countries: [] }), true)
})

test("countries are counted most releases first; stored filters are read defensively", () => {
  assert.deepEqual(countryCounts([cpi, { impact: "low", country: "us" }, pmi, { impact: "low", country: null }]),
    [{ code: "US", count: 2 }, { code: "JP", count: 1 }])
  assert.deepEqual(parseFilter('{"impact":"high","countries":["us",3]}'), { impact: "high", countries: ["US"] })
  assert.deepEqual(parseFilter("not json"), DEFAULT_FILTER)
  assert.equal(isDefault(parseFilter(null)), true)
})
