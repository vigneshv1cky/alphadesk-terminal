import { useCallback, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { NewsReader } from "@/components/NewsReader"
import { OlderNews } from "@/components/OlderNews"
import type { NewsArticle } from "@/lib/api"
import { useSymbolNews } from "@/lib/queries"
import { useOlderNews } from "@/lib/olderNews"
import { Empty, Widget } from "@/components/terminal"
import { newsTime } from "@/lib/newsClock"

/** Headlines for ONE company over the whole news window (three days), asked
 * of the server per symbol (2026-09-18). It used to filter the shared
 * reading list, which holds only the newest 500 stories across every feed —
 * a few hours — so a quiet name showed three stories of its window.
 *
 * Reading happens IN the panel: a click swaps the list for the reader and
 * the back row swaps it back — no navigation, the page stays put. If the
 * symbol is not in the window there is nothing to show, and it says which
 * symbol it found nothing for rather than rendering an empty box.
 *
 * Older stories load on request, through the shared pager (lib/olderNews).
 */
export function SymbolNews({ symbol, span = 4, scroll = 300, framed = true }: {
  symbol: string
  span?: number
  scroll?: number | string
  /** False inside a panel that already has its own heading (the chart's
   * side panel): the stories alone, without a card and a second title. */
  framed?: boolean
}) {
  const { data, isPending, isError, error } = useSymbolNews(symbol)
  // A coin's stories are chosen by the server — all crypto and what moves
  // it, not the coin's own tag (2026-09-19) — so none is filtered out here.
  const coin = /-(USD|USDT|USDC|BTC)$/.test(symbol)
  const matches = useCallback((a: NewsArticle) => coin || a.tickers.includes(symbol), [symbol, coin])
  const { shown: headlines, older, state, loadMore, reset } = useOlderNews(data?.articles ?? [], matches, symbol)
  const [openId, setOpenId] = useState<string | null>(null)
  const open = headlines.find(h => h.article_id === openId) ?? null

  const More = (
    <OlderNews state={state} onLoad={() => void loadMore()} onReset={reset} loaded={older.length}
               subject={coin ? "crypto stories" : "stories about this company"} />
  )

  const body = (
    <>
      {open ? (
        <NewsReader article={open} onBack={() => setOpenId(null)} />
      ) : isPending ? (
        <Empty>loading…</Empty>
      ) : isError ? (
        <QueryFailure error={error}>the news window is unavailable right now</QueryFailure>
      ) : !headlines.length ? (
        <div>
          <Empty>{coin ? "no crypto headlines in the current window" : `no headlines for ${symbol} in the current window`}</Empty>
          {More}
        </div>
      ) : (
        <div>
          {headlines.map(h => (
            <button
              key={h.article_id}
              type="button"
              onClick={() => setOpenId(h.article_id)}
              className="row-rule block w-full rounded-none px-3 py-3 text-left hover:bg-foreground/5"
            >
              {/* Same row anatomy as the market tape (widgets/builtin), so
                  the two news surfaces read as one product. */}
              <span className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
                <span className="text-accent-700">{h.source}</span>
                {h.why && <span className="text-muted-foreground">{h.why}</span>}
                {h.published_at && (
                  <span className="normal-case tracking-normal text-muted-foreground">
                    {newsTime(h.published_at)}
                  </span>
                )}
              </span>
              <span className="block text-body font-semibold leading-[1.3]">{h.title}</span>
            </button>
          ))}
          {More}
        </div>
      )}
    </>
  )
  if (!framed) return <div className="min-w-0">{body}</div>
  return (
    <Widget
      span={span}
      symbol={symbol}
      title="News"
      subtitle={headlines.length ? `${headlines.length} in the window${coin ? " · all crypto and what moves it" : ""}` : undefined}
      scroll={scroll}
    >
      {body}
    </Widget>
  )
}
