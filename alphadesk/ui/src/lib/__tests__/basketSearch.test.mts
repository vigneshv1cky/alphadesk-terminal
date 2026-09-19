import assert from "node:assert/strict"
import test from "node:test"
import { searchBaskets } from "../basketSearch.ts"

const B = [
  { id: "freight", label: "Shipping & freight rates", why: "Container lines and parcel carriers", symbols: ["ZIM", "MATX", "FDX"] },
  { id: "autos", label: "EV credits & auto tariffs", why: "Carmakers on EV policy", symbols: ["TSLA", "F", "GM"] },
  { id: "miners", label: "Safe havens", why: "Gold, silver and the dollar", symbols: ["GLD", "NEM"] },
]
const ids = (q: string) => searchBaskets(B, q).map(b => b.id)

test("a word finds a basket by the start of a word in its name or description", () => {
  assert.deepEqual(ids("ship"), ["freight"])
  assert.deepEqual(ids("gold"), ["miners"])
  assert.deepEqual(ids("carri"), ["freight"])
})

test("a ticker finds every basket holding it, whole, not as a prefix", () => {
  assert.deepEqual(ids("zim"), ["freight"])
  assert.deepEqual(ids("F"), ["autos"])       // Ford, not FDX
})

test("every word must match, and an empty search keeps them all", () => {
  assert.deepEqual(ids("gold silver"), ["miners"])
  assert.deepEqual(ids("gold ship"), [])
  assert.deepEqual(ids("  "), ["freight", "autos", "miners"])
})
