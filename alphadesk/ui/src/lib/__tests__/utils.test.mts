import assert from "node:assert/strict"
import test from "node:test"
import { cn } from "../utils.ts"

test("a later class replaces an earlier one that sets the same property", () => {
  // The two cases that needed workarounds on 2026-09-18.
  assert.equal(cn("h-[30px] px-2", "h-[44px]"), "px-2 h-[44px]")
  assert.equal(cn("hover:text-foreground", "hover:text-loss"), "hover:text-loss")
  assert.equal(cn("w-full", "w-24"), "w-24")
})

test("our theme's colour names are read as colours, not as font sizes", () => {
  // A size and a colour on the same element must BOTH survive.
  assert.equal(cn("text-[12px] text-muted-foreground"), "text-[12px] text-muted-foreground")
  assert.equal(cn("text-[13px]", "text-accent-700"), "text-[13px] text-accent-700")
  // Two colours: the later wins.
  assert.equal(cn("text-muted-foreground", "text-foreground"), "text-foreground")
  assert.equal(cn("bg-panel", "bg-surface"), "bg-surface")
})

test("the type roles are read as sizes, so a colour beside one survives", () => {
  assert.equal(cn("text-caption text-muted-foreground"), "text-caption text-muted-foreground")
  assert.equal(cn("text-label", "text-accent"), "text-label text-accent")
  // Two sizes: the later wins, whether a role or an arbitrary value.
  assert.equal(cn("text-body", "text-caption"), "text-caption")
  assert.equal(cn("text-[12px]", "text-emph"), "text-emph")
  assert.equal(cn("tracking-caps uppercase", "tracking-ticker"), "uppercase tracking-ticker")
})

test("a border's width and its colour are different properties", () => {
  assert.equal(cn("border border-border", "border-accent"), "border border-accent")
  assert.equal(cn("border-b-2 border-border"), "border-b-2 border-border")
})

test("classes it does not recognise are kept, never dropped", () => {
  // The app's own utilities and container queries.
  assert.equal(cn("row-rule num", "@container"), "row-rule num @container")
  assert.equal(cn("@[520px]:truncate text-[11px]"), "@[520px]:truncate text-[11px]")
  assert.equal(cn("[&_td]:h-[44px] w-full"), "[&_td]:h-[44px] w-full")
})

test("falsy fragments are dropped as before", () => {
  assert.equal(cn("a", false, null, undefined, 0, "", "b"), "a b")
})
