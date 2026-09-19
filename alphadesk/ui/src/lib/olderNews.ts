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
const PAGE = 100

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
