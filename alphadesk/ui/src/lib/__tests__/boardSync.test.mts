import { strict as assert } from "node:assert"
import { test } from "node:test"
import { whichWins } from "../boardSync.ts"

const EARLY = "2026-09-20T10:00:00.000Z"
const LATE = "2026-09-21T10:00:00.000Z"

test("the later arrangement wins", () => {
  assert.equal(whichWins({ tiles: "a", at: EARLY }, { tiles: "b", at: LATE }), "adopt")
  assert.equal(whichWins({ tiles: "a", at: LATE }, { tiles: "b", at: EARLY }), "push")
})

test("two devices that agree do nothing", () => {
  assert.equal(whichWins({ tiles: "a", at: EARLY }, { tiles: "a", at: LATE }), "keep")
})

test("a board the account has never seen is pushed up, not lost", () => {
  assert.equal(whichWins({ tiles: "a", at: EARLY }, null), "push")
  assert.equal(whichWins({ tiles: "a", at: null }, { tiles: "", at: LATE }), "push")
})

test("a browser with nothing takes the account's", () => {
  assert.equal(whichWins({ tiles: "", at: null }, { tiles: "b", at: EARLY }), "adopt")
})

test("a browser with nothing and an account with nothing stays put", () => {
  assert.equal(whichWins({ tiles: "", at: null }, null), "keep")
})

test("an undated local copy loses — it predates the feature", () => {
  // The fault this fixes: without this line, a browser that had ever been
  // used kept its own board forever and the two devices never converged.
  assert.equal(whichWins({ tiles: "a", at: null }, { tiles: "b", at: EARLY }), "adopt")
})

test("an undated ACCOUNT row loses to a dated local one", () => {
  assert.equal(whichWins({ tiles: "a", at: LATE }, { tiles: "b", at: null }), "push")
})

test("the same instant is not a change — this browser keeps and re-pushes", () => {
  assert.equal(whichWins({ tiles: "a", at: LATE }, { tiles: "b", at: LATE }), "push")
})

// Which chip is SELECTED is part of the board, not decoration. Picking a
// different one changes nothing about the list, so a comparison that reads
// only the list says "no change" and the focus never follows to the other
// device (2026-09-21).
test("the same symbols with a different one selected is a change", () => {
  assert.equal(whichWins({ tiles: "NVDA,VEEE|NVDA", at: EARLY },
                         { tiles: "NVDA,VEEE|VEEE", at: LATE }), "adopt")
})

test("the same symbols and the same selection is not a change", () => {
  assert.equal(whichWins({ tiles: "NVDA,VEEE|VEEE", at: EARLY },
                         { tiles: "NVDA,VEEE|VEEE", at: LATE }), "keep")
})

test("a selection made later wins over a list changed earlier", () => {
  assert.equal(whichWins({ tiles: "NVDA,VEEE|VEEE", at: LATE },
                         { tiles: "NVDA,VEEE,CVX|NVDA", at: EARLY }), "push")
})
