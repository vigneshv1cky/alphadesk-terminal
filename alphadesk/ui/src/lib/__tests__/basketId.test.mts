import assert from "node:assert/strict"
import test from "node:test"
import { newBasketId } from "../basketId.ts"

test("a basket id is my- plus the name as a slug and a short tail", () => {
  assert.equal(newBasketId("Shipping & Freight!", () => 0), "my-shipping-freight-0000")
  assert.match(newBasketId("Shipping"), /^my-shipping-[a-z0-9]{4}$/)
})

test("a name with nothing to slug still makes a valid id", () => {
  assert.match(newBasketId("★★★"), /^my-[a-z0-9]{4}$/)
})

test("the id always fits the server's pattern", () => {
  const id = newBasketId("a".repeat(80))
  assert.match(id, /^my-[a-z0-9-]{2,40}$/)
})
