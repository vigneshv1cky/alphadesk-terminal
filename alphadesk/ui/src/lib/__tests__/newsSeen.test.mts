/** New stories about the board's stocks (lib/newsSeen.ts).
 *
 *     pnpm test
 */
import { test } from "node:test"
import assert from "node:assert/strict"
import { boardStories } from "../newsSeen.ts"

const s = (id: string, at: string, tickers: string[]) => ({ article_id: id, published_at: at, tickers })
const stories = [
  s("a", "2026-09-15T19:10:00Z", ["NVDA", "AMD"]),
  s("b", "2026-09-15T18:00:00Z", ["nvda"]),
  s("c", "2026-09-15T19:20:00Z", ["TSLA"]),
]

test("stories naming a board chip, and the ones since the last visit", () => {
  const got = boardStories(stories, ["NVDA", "XLE"], "2026-09-15T19:00:00Z")
  assert.deepEqual([...got.onBoard], ["a", "b"])
  assert.deepEqual([...got.fresh], ["a"])
})

test("before a first visit nothing is new, and an empty board matches nothing", () => {
  assert.equal(boardStories(stories, ["NVDA"], null).fresh.size, 0)
  assert.equal(boardStories(stories, [], "2026-09-15T00:00:00Z").onBoard.size, 0)
})
