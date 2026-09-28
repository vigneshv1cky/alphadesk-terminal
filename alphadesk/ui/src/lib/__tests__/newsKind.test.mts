import { strict as assert } from "node:assert"
import { test } from "node:test"
import { isWireRelease } from "../newsKind.ts"

test("a wire host is the company's own word, a reporter's article is not", () => {
  assert.equal(isWireRelease({ url: "https://www.globenewswire.com/x", source: "globenewswire.com" }), true)
  assert.equal(isWireRelease({ url: "https://www.businesswire.com/y", source: "businesswire.com" }), true)
  assert.equal(isWireRelease({ url: "https://ir.example.com/a", source: "prnewswire.com" }), true)
  // A reporter writing ABOUT a company is not the company speaking.
  assert.equal(isWireRelease({ url: "https://www.benzinga.com/news/x", source: "benzinga" }), false)
  assert.equal(isWireRelease({ url: "https://www.reuters.com/x", source: "reuters.com" }), false)
  // A lookalike host must not pass.
  assert.equal(isWireRelease({ url: "https://notglobenewswire.com/x", source: "" }), false)
  assert.equal(isWireRelease({ url: "", source: "" }), false)
})
