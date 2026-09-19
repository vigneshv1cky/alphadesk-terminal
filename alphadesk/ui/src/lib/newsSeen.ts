import { useSyncExternalStore } from "react"

/** New stories about the board's stocks (2026-09-15).
 *
 * "New" is relative to when this browser last had the News page open: a
 * per-viewer convenience, so it lives in this browser's storage and simply
 * starts over where storage is unavailable. The rail counts stories naming a
 * board chip published since then; the News page marks them while it is open
 * and moves the mark forward. Pure helpers are separate from the storage so
 * they are tested without a browser. */

export type Story = { article_id: string; published_at: string | null; tickers: string[] }

/** The stories naming any of `symbols`, and those of them published after
 * `since` (none are new before a first visit). */
export function boardStories(stories: Story[], symbols: string[], since: string | null): { onBoard: Set<string>; fresh: Set<string> } {
  const board = new Set(symbols.map(s => s.toUpperCase()))
  const onBoard = new Set<string>(), fresh = new Set<string>()
  const cut = since ? Date.parse(since) : NaN
  for (const s of stories) {
    if (!s.tickers.some(t => board.has(t.toUpperCase()))) continue
    onBoard.add(s.article_id)
    if (Number.isFinite(cut) && s.published_at && Date.parse(s.published_at) > cut) fresh.add(s.article_id)
  }
  return { onBoard, fresh }
}

const KEY = "alphadesk.news.seen"
const EVENT = "alphadesk-news-seen"

export function readSeen(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

/** Move the mark to `iso` (now by default) and tell every surface. */
export function markSeen(iso: string = new Date().toISOString()): void {
  try { localStorage.setItem(KEY, iso) } catch { /* private mode: nothing is remembered */ }
  window.dispatchEvent(new Event(EVENT))
}

function subscribe(fn: () => void) {
  window.addEventListener(EVENT, fn)
  window.addEventListener("storage", fn)
  return () => { window.removeEventListener(EVENT, fn); window.removeEventListener("storage", fn) }
}

export function useNewsSeen(): string | null {
  return useSyncExternalStore(subscribe, readSeen, () => null)
}
