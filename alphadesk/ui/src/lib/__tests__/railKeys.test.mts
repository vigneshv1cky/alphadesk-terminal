import assert from "node:assert/strict"
import test from "node:test"
import { opensOnSpace, railStep } from "../railKeys.ts"

test("the arrows step one stop and wrap at both ends", () => {
  assert.equal(railStep("ArrowDown", 0, 5), 1)
  assert.equal(railStep("ArrowDown", 4, 5), 0)
  assert.equal(railStep("ArrowUp", 3, 5), 2)
  assert.equal(railStep("ArrowUp", 0, 5), 4)
})

test("Home and End go to the first and last stop", () => {
  assert.equal(railStep("Home", 3, 5), 0)
  assert.equal(railStep("End", 1, 5), 4)
})

test("focus on none of the stops enters from the matching end", () => {
  assert.equal(railStep("ArrowDown", -1, 5), 0)
  assert.equal(railStep("ArrowUp", -1, 5), 4)
})

test("any other key, or an empty rail, moves nothing", () => {
  assert.equal(railStep("Tab", 2, 5), -1)
  assert.equal(railStep("ArrowLeft", 2, 5), -1)
  assert.equal(railStep("Enter", 2, 5), -1)
  assert.equal(railStep("ArrowDown", -1, 0), -1)
  assert.equal(railStep("End", -1, 0), -1)
})

test("a single stop stays put", () => {
  assert.equal(railStep("ArrowDown", 0, 1), 0)
  assert.equal(railStep("ArrowUp", 0, 1), 0)
})

test("Space opens a link row and leaves buttons to the browser", () => {
  assert.equal(opensOnSpace(" ", "A"), true)
  assert.equal(opensOnSpace(" ", "BUTTON"), false)
  assert.equal(opensOnSpace("Enter", "A"), false)
})
