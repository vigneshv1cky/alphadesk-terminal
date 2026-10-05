import assert from "node:assert/strict"
import test from "node:test"
import { releaseLongMinutePins } from "../pinReset.ts"

test("minute and second pins on long ranges are released; short ranges and hours keep theirs", () => {
  const got = releaseLongMinutePins(
    { "1D": "1m", "5D": "1m", "1M": "1m", "3M": "5m", "6M": "30s", "1Y": "1h", "5Y": "1d" }, false)
  assert.deepEqual(got, { "1D": "1m", "5D": "1m", "1Y": "1h", "5Y": "1d" })
})

test("a record already reset is left exactly as it is, so a minute bar chosen on purpose stays", () => {
  const mine = { "1M": "1m" }
  assert.equal(releaseLongMinutePins(mine, true), mine)
})

test("applying it twice changes nothing more", () => {
  const once = releaseLongMinutePins({ "3M": "1m", "1D": "1m" }, false)
  assert.deepEqual(releaseLongMinutePins(once, false), once)
  assert.deepEqual(once, { "1D": "1m" })
})

test("an empty record stays empty", () => {
  assert.deepEqual(releaseLongMinutePins({}, false), {})
})
