import assert from "node:assert/strict"
import test from "node:test"
import { downloadName, passphraseProblem } from "../keyExport.ts"

test("a passphrase under twelve characters is turned back before anything is sent", () => {
  assert.match(passphraseProblem("short", "short") ?? "", /at least 12/)
  assert.match(passphraseProblem("", "") ?? "", /at least 12/)
})

test("the two entries must match, so a typo cannot seal the keys under a passphrase nobody typed", () => {
  assert.match(passphraseProblem("correct horse battery", "correct horse batter") ?? "", /do not match/)
})

test("a long enough, matching passphrase has no problem", () => {
  assert.equal(passphraseProblem("correct horse battery", "correct horse battery"), null)
})

test("the length is counted in characters, not bytes", () => {
  // twelve one-character symbols that each take several bytes
  assert.equal(passphraseProblem("🔑".repeat(12), "🔑".repeat(12)), null)
})

test("the saved file is named by the server's header, with a safe fallback", () => {
  assert.equal(downloadName('attachment; filename="alphadesk-keys-20261002.json"'), "alphadesk-keys-20261002.json")
  assert.equal(downloadName(null), "alphadesk-keys.json")
  assert.equal(downloadName("attachment"), "alphadesk-keys.json")
})

test("a filename from the header cannot carry a path", () => {
  assert.equal(downloadName('attachment; filename="../../etc/passwd"'), "alphadesk-keys.json")
})
