/** Board layout strings: hidden panels recorded, new panels shown
 * (lib/layoutEntries.ts).
 *
 *     pnpm test
 */
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseLayout, resolveLayout, serializeLayout } from "../layoutEntries.ts"

const analysis = [
  { id: "chart" }, { id: "filings" }, { id: "performance" }, { id: "stats" }, { id: "history" }, { id: "news" },
]
const ids = (entries: { id: string }[]) => entries.map(e => e.id)

test("a layout saved before panels were added shows them next to the panel they follow", () => {
  const got = resolveLayout("chart,filings,news", analysis, true)
  assert.deepEqual(ids(got), ["chart", "filings", "performance", "stats", "history", "news"])
})

test("a reordered layout keeps its order and seats a new panel after its page predecessor", () => {
  const got = resolveLayout("news,chart:8,filings", analysis, true)
  assert.deepEqual(ids(got), ["news", "chart", "filings", "performance", "stats", "history"])
  assert.equal(got[1].span, 8)
})

test("a panel the reader hid stays hidden", () => {
  const got = resolveLayout("chart,filings,news,-stats,-history", analysis, true)
  assert.deepEqual(ids(got), ["chart", "filings", "performance", "news"])
})

test("a view does not gain new tiles, and opt-in tiles never join on their own", () => {
  assert.deepEqual(ids(resolveLayout("chart,news", analysis, false)), ["chart", "news"])
  const withOptIn = [...analysis, { id: "heatmap", optIn: true }]
  assert.ok(!ids(resolveLayout("chart", withOptIn, true)).includes("heatmap"))
})

test("no layout, or none of its panels here, is the default board", () => {
  assert.deepEqual(resolveLayout("", analysis, true), [])
  assert.deepEqual(resolveLayout("gone,-stats", analysis, true), [])
})

test("saving records every default panel not shown, and keeps hides for panels this page lacks", () => {
  const s = serializeLayout([{ id: "chart", span: 8 }, { id: "news", span: null }], analysis, true, new Set(["elsewhere", "stats"]))
  assert.equal(s, "chart:8,news,-filings,-performance,-stats,-history,-elsewhere")
  const back = parseLayout(s, analysis)
  assert.deepEqual(ids(back.visible), ["chart", "news"])
  assert.ok(back.hidden.has("elsewhere"))
  assert.equal(serializeLayout([{ id: "chart", span: null }], analysis, false), "chart")
})

test("a tile's place in its row round-trips, and left is not written", () => {
  const all = [{ id: "news" }, { id: "chart" }, { id: "tape" }]
  const raw = "news:6@c,chart:4@r,tape:8"
  const { visible } = parseLayout(raw, all)
  assert.deepEqual(visible, [
    { id: "news", span: 6, align: "center" },
    { id: "chart", span: 4, align: "right" },
    { id: "tape", span: 8 },
  ])
  assert.equal(serializeLayout(visible, all, false), raw)
  // A place on an auto-width tile is kept too; an unknown place is dropped.
  assert.deepEqual(parseLayout("news@c,chart@x", all).visible, [{ id: "news", span: null, align: "center" }, { id: "chart", span: null }])
})
