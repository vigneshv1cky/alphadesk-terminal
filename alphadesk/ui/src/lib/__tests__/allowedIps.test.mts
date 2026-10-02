import assert from "node:assert/strict"
import test from "node:test"
import { parseAllowedIps } from "../allowedIps.ts"

test("a comma or newline separated list becomes trimmed entries", () => {
  assert.deepEqual(parseAllowedIps("203.0.113.7, 198.51.100.0/24\n 2001:db8::1 "),
    ["203.0.113.7", "198.51.100.0/24", "2001:db8::1"])
  assert.deepEqual(parseAllowedIps("  "), [])
  assert.deepEqual(parseAllowedIps(""), [])
})

test("an entry that is not an address or range is named", () => {
  assert.throws(() => parseAllowedIps("203.0.113.7, banana"), /banana/)
  assert.throws(() => parseAllowedIps("300.1.1.1"), /300\.1\.1\.1/)
  assert.throws(() => parseAllowedIps("203.0.113.7/33"), /203\.0\.113\.7\/33/)
})

test("ranges are accepted for both address families", () => {
  assert.deepEqual(parseAllowedIps("10.0.0.0/8,2001:db8::/32"), ["10.0.0.0/8", "2001:db8::/32"])
})
