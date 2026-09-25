import { useMemo, useState } from "react"
import { api, type NewsArticle } from "@/lib/api"

/** Reading further back than the live window, on request (2026-09-16).
 *
 * Every news surface shows the same window — the reader's recent stories —
 * and every one of them ran out at its bottom edge. This pages the reader's
 * own stored history behind whichever list is on screen, and the surfaces
 * share it so they cannot drift apart in behaviour.
 *
 * A FILTERED list (one company's headlines) is the awkward case: the pages
 * come back from the whole window, so a hundred older stories may hold none
 * about this symbol. A press therefore reads up to PAGES_PER_PRESS pages
 * and stops at the first that yields a match — bounded, so a quiet company
 * cannot walk the whole archive on one click, and cheap for a busy one. An
 * unfiltered list stops after the first page, which always counts.
 */

const PAGES_PER_PRESS = 3
// THE PAGE IS THE SERVER'S CAP, NOT A FIFTH OF IT (2026-09-25, #74, the
// reader watching the count climb: "I see that its increasing as i reload,
// why cant i have it all at once").
//
// The window is filled by paging backwards until the oldest story held is
// older than the lookback, and at a hundred a page that is about
// THIRTY-SIX round trips to cover a busy 72 hours — each one paying the
// reader's own distance to the server, ~110-250ms, whatever it carries.
// The number on screen climbs the whole time.
//
// MEASURED on one page: 100 stories is 15KB gzipped in 16ms, 500 is 76KB in
// 31ms. Five times the rows for 1.9 times the server time, because the
// round trip dominates and the rows are cheap. So ask for what the route
// will actually give — `api_news` caps a page at 500 — and the same window
// arrives in about eight trips instead of thirty-six.
//
// The LIVE query is untouched at 300: that one is refetched every sixty
// seconds by every open tab, and it is the payload that note about
// "several megabytes on a 60-second poll" is about. These pages are read
// once.
const PAGE = 500

export type OlderState = "idle" | "loading" | "end" | "error"

export function useOlderNews(window_: NewsArticle[], matches?: (a: NewsArticle) => boolean, symbol?: string) {
  const [older, setOlder] = useState<NewsArticle[]>([])
  const [state, setState] = useState<OlderState>("idle")

  /** The window and everything paged in, newest first, each story once. */
  const all = useMemo(() => {
    const seen = new Set<string>()
    return [...window_, ...older].filter(a => !seen.has(a.article_id) && seen.add(a.article_id))
  }, [window_, older])

  const shown = useMemo(() => (matches ? all.filter(matches) : all), [all, matches])

  const loadMore = async () => {
    if (state === "loading") return
    setState("loading")
    let before = all.length ? all[all.length - 1].published_at : null
    try {
      // With a symbol the server pages that symbol's own stories, so one
      // page is always enough; otherwise a filtered panel may need a few
      // pages of everything before one names it.
      for (let page = 0; page < (matches && !symbol ? PAGES_PER_PRESS : 1); page++) {
        if (!before) break
        const got = await api.newsPage({ before, limit: PAGE, symbol })
        if (!got.articles.length) { setState("end"); return }
        setOlder(o => [...o, ...got.articles])
        before = got.articles[got.articles.length - 1].published_at
        if (!matches || got.articles.some(matches)) break
      }
      setState("idle")
    } catch {
      setState("error")
    }
  }

  /** Back to the live window: the paged-in stories are dropped, so the
   * panel returns to the height it had before the reader went digging. */
  const reset = () => { setOlder([]); setState("idle") }

  return { shown, older, state, loadMore, reset }
}
