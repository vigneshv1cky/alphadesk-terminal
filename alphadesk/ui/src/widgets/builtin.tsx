import { useCallback, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { HeadlineTickers } from "@/components/HeadlineTickers"
import { NewsReader } from "@/components/NewsReader"
import { OlderNews } from "@/components/OlderNews"
import type { NewsArticle } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { useNews, useSymbolNews } from "@/lib/queries"
import { useOlderNews } from "@/lib/olderNews"
import { Btn, Empty, Widget } from "@/components/terminal"
import { registerWidget } from "@/widgets/registry"
import { TILE_BODY_HEIGHT } from "@/widgets/tile"
import { newsTime } from "@/lib/newsClock"

/** The tiles AlphaDesk ships with.
 *
 * Each is an ordinary component that fetches its own data and registers
 * itself at import time. A plugin adds a tile the same way; re-registering a
 * built-in id replaces it. Ordering leaves gaps so third-party tiles can slot
 * between these without renumbering.
 */

export function NewsTape({ span = 12 }: {
  /** The markets board runs this full width; the news view runs it at 4 as the
   * secondary column beside the window, the way their news view puts a
   * headline list beside the main list. */
  span?: number
}) {
  const news = useNews()
  // The board's marked chip scopes this tile like every other (feedback,
  // 2026-09-02): with a symbol active, only stories naming it — the whole
  // window stays one click away on the toggle.
  const { active } = useBoardSymbols()
  const [showAll, setShowAll] = useState(false)
  const scoped = !!active && !showAll
  // One row per ARTICLE — /api/news dedupes server-side, so a story naming
  // six tickers is one row with six chips, not six rows.
  //
  // Older stories page in on request through the shared pager, the same one
  // the symbol panel and the news view use (2026-09-16). The 60-row cap is
  // what the tile shows unasked; each press of Load older raises it by what
  // it read, and Show less returns the tile to the live window.
  //
  // Scoped, the tile reads the symbol's OWN window from the server
  // (2026-09-18): the shared list is the newest 500 stories of every feed,
  // a few hours, and filtering it showed XLK one headline of its six.
  const matches = useCallback((h: NewsArticle) => h.tickers.includes(active), [active])
  const symbolNews = useSymbolNews(scoped ? active : "")
  const base = scoped ? (symbolNews.data?.articles ?? []) : (news.data?.articles ?? [])
  const { shown, older, state, loadMore, reset } = useOlderNews(base, scoped ? matches : undefined, scoped ? active : undefined)
  const headlines = shown.slice(0, 60 + older.length)
  // Reading happens IN the tile: a click swaps the list for the reader, and
  // the back row swaps it back. No navigation — the board stays where it is.
  const [openId, setOpenId] = useState<string | null>(null)
  const open = headlines.find(h => h.article_id === openId) ?? null
  return (
  <Widget
    span={span}
    title={scoped ? `${active} News` : "Market News"}
    subtitle={`${headlines.length} headlines, newest first`}
    scroll={TILE_BODY_HEIGHT}
    actions={active ? (
      <>
        <Btn active={scoped} onClick={() => setShowAll(false)}>{active}</Btn>
        <Btn active={!scoped} onClick={() => setShowAll(true)}>All</Btn>
      </>
    ) : undefined}
  >
    {open ? (
      <NewsReader article={open} onBack={() => setOpenId(null)} />
    ) : news.isError ? (
      <QueryFailure error={news.error}>the news window is unavailable right now</QueryFailure>
    ) : !news.data || (scoped && !symbolNews.data) ? (
      <Empty>loading…</Empty>
    ) : headlines.length === 0 ? (
      <div>
        <Empty>{scoped ? `no ${active} news in the window` : "no news in the window"}</Empty>
        <OlderNews state={state} onLoad={() => void loadMore()} onReset={reset} loaded={older.length}
                   subject={scoped ? "stories about this company" : "stories"} />
      </div>
    ) : (
      <ul>
        {/* The source/age line runs in the DEEP accent step, not the accent
            itself: accent-to-ground is tuned to 3:1, which is chrome-grade,
            and a body-size label needs the 700 step to clear the floor. */}
        {headlines.map(h => (
          <li key={h.article_id} className="row-rule hover:bg-foreground/5">
            <button type="button" onClick={() => setOpenId(h.article_id)} className="block w-full px-3 py-3 text-left">
              <span className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
                <HeadlineTickers symbols={h.tickers} />
                <span className="text-accent-700">{h.source}</span>
                {h.published_at && (
                  <span className="normal-case tracking-normal text-muted-foreground">
                    {newsTime(h.published_at)}
                  </span>
                )}
              </span>
              <span className="block text-body font-semibold leading-[1.3]">{h.title}</span>
            </button>
          </li>
        ))}
        <li>
          <OlderNews state={state} onLoad={() => void loadMore()} onReset={reset} loaded={older.length}
                     subject={scoped ? "stories about this company" : "stories"} />
        </li>
      </ul>
    )}
  </Widget>
  )
}

// Their Markets board is six panels: chart, equity overview, three movers and
// market news. The status strip, the window list and reporting-soon are not
// among them, and both of the latter now own a whole view (/news, /earnings),
// so they were duplicates that made the board ragged for no new information.
// Deleted rather than left unregistered — an unused component is a component
// nobody maintains. Git has them if a deployment wants the tiles back.
registerWidget({ id: "news-tape", label: "Market news", order: 30, component: NewsTape })
