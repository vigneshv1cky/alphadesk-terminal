import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { api, type Quote } from "@/lib/api"
import { useQuotes } from "@/lib/queries"
import { normalize } from "@/lib/symbols"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { Empty, Flash, Widget } from "@/components/terminal"
import { ComposedBoard } from "@/components/ComposedBoard"
import { MarketChart } from "@/widgets/chart"
import { SymbolNews } from "@/components/SymbolNews"
import { ComparisonPanel } from "@/components/ComparisonPanel"
import { ComparisonMetricsPanel, PricePerformancePanel, RelativePerformancePanel } from "@/components/Compare"

/** The symbols you are following.
 *
 * NOT HOLDINGS, and this is the one page where that distinction is the whole
 * design. AlphaDesk books nothing and owns nothing, so there is no cost basis
 * to show and no P&L to compute. Their portfolio view has both because it sits
 * on an account; ours cannot, and inventing them would be the one kind of
 * number this terminal must never produce. What it can honestly say is what
 * these names are doing right now — so the columns match their table exactly
 * up to the point where position data would start, and then stop.
 *
 * THE COMPARISON PANELS LIVE HERE TOO (2026-09-16, the owner's call): the
 * Compare tab was the same board chips read side by side, and a second tab
 * for that was a place to go rather than a thing to see. Its four panels —
 * relative performance, the returns table, the metric grid with peers, and
 * the cards — now sit under this table, on the same lineup.
 *
 * THE LIST IS THE BOARD (2026-09-16, the owner's call). It used to be a
 * second saved list with its own add box, which meant two gestures for one
 * idea — and the strip is the gesture the whole app teaches: it scopes
 * every page, and every table here adds a symbol to it. So this page is
 * the board priced, symbols arrive from the strip's search, and a row's ×
 * takes one off the board.
 *
 * Priced in ONE request. Each row fetching its own quote is the pattern that
 * made the theme pages throttle and return 404s for a third of their rows at
 * random.
 */
const money = (n: number | null | undefined, d = 2) =>
  n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
const compact = (n: number | null | undefined): string => {
  if (n == null) return "—"
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

function Row({ symbol, data, loading, active, onPick, onRemove }: {
  symbol: string
  data: Quote | null | undefined
  loading: boolean
  active: boolean
  onPick: () => void
  onRemove: () => void
}) {
  const chg = data?.change_pct ?? null
  const up = (chg ?? 0) >= 0
  return (
    <tr
      onClick={onPick}
      aria-selected={active}
      className={`row-rule cursor-pointer ${active ? "bg-muted" : "hover:bg-muted/50"}`}
    >
      <td className="px-3 py-1.5 text-body"><span className="num font-semibold">{symbol}</span></td>
      <td className="max-w-[220px] truncate px-3 py-1.5 text-body text-muted-foreground">
        {loading ? "…" : data?.name ?? ""}
      </td>
      <td className="tnum px-3 py-1.5 text-right text-body">
        <Flash value={data?.price}>{money(data?.price)}</Flash>
      </td>
      <td className={`tnum px-3 py-1.5 text-right text-body ${
        chg == null ? "text-muted-foreground" : up ? "text-gain" : "text-loss"}`}>
        {chg == null ? "—" : `${up ? "+" : ""}${chg.toFixed(2)}%`}
      </td>
      <td className="tnum px-3 py-1.5 text-right text-body text-muted-foreground">
        {compact(data?.volume)}
      </td>
      <td className="tnum px-3 py-1.5 text-right text-body text-muted-foreground">
        {data?.week52_low == null || data?.week52_high == null
          ? "—" : `${money(data.week52_low)} – ${money(data.week52_high)}`}
      </td>
      <td className="tnum px-3 py-1.5 text-right text-body">{compact(data?.market_cap)}</td>
      <td className="px-3 py-1.5 text-right">
        <button
          type="button"
          // Stops the click reaching the row, or removing a symbol would also
          // select it on the way out.
          onClick={e => { e.stopPropagation(); onRemove() }}
          aria-label={`Take ${symbol} off the board`}
          className="px-1 text-emph leading-none text-muted-foreground hover:text-loss"
        >
          ×
        </button>
      </td>
    </tr>
  )
}

const TH = "sticky top-0 z-10 border-b border-row-rule bg-panel px-3 py-2 font-medium"

export default function PortfolioPage() {
  const { symbols, ordered, remove } = useBoardSymbols()
  const [params, setParams] = useSearchParams()
  // The comparison lineup is the strip itself, active first — the same one
  // the Compare tab used. Peers of the active chip are fetched on request
  // and never join the board.
  const lineup = ordered.length ? ordered : symbols
  const active = lineup[0] ?? ""
  const [showPeers, setShowPeers] = useState(false)
  const peers = useQuery({
    queryKey: ["peers", active],
    queryFn: () => api.peers(active),
    enabled: !!active,
    staleTime: 24 * 60 * 60_000,
  })

  // This page shows the 52-week range and market cap, which the quote
  // vendor may not carry; the server fills them from the reader's own bars
  // and the vendor that lists caps in bulk (2026-09-16).
  const quotes = useQuotes(symbols, "range,cap")
  const priced = quotes.data?.quotes
  const picked = normalize(params.get("symbol") || "") || symbols[0] || ""
  const pick = (sym: string) => {
    const next = new URLSearchParams(params)
    next.set("symbol", sym)
    setParams(next, { replace: true })
  }

  const watchlistPanel = (
      <Widget
        span={12}
        title="My Portfolio"
        subtitle={`${symbols.length} on the board · no positions, no cost basis`}
        scroll={340}
        bodyClassName="overflow-x-auto"
      >
        {symbols.length === 0 ? (
          <Empty>nothing on the board yet — add a symbol on the strip above</Empty>
        ) : (
          <table className="w-full min-w-[760px] border-separate border-spacing-0">
            <thead>
              <tr className="text-label font-medium uppercase tracking-caps text-muted-foreground">
                <th className={`${TH} text-left`} data-tip="A symbol on the board. Click a row to scope the chart and news below to it" aria-description="A symbol on the board. Click a row to scope the chart and news below to it">Symbol</th>
                <th className={`${TH} text-left`} data-tip="The company or fund name" aria-description="The company or fund name">Name</th>
                <th className={`${TH} text-right`} data-tip="The latest price" aria-description="The latest price">Price</th>
                <th className={`${TH} text-right`} data-tip="Change since the previous session's close" aria-description="Change since the previous session's close">Chg %</th>
                <th className={`${TH} text-right`} data-tip="Shares traded today" aria-description="Shares traded today">Volume</th>
                <th className={`${TH} text-right`} data-tip="The lowest and highest prices over the past 52 weeks" aria-description="The lowest and highest prices over the past 52 weeks">52w Range</th>
                <th className={`${TH} text-right`} data-tip="Market capitalisation: the share price times the shares outstanding" aria-description="Market capitalisation: the share price times the shares outstanding">Mkt Cap</th>
                <th className={TH} />
              </tr>
            </thead>
            <tbody>
              {symbols.map(s => (
                <Row
                  key={s}
                  symbol={s}
                  data={priced?.[s]}
                  loading={quotes.isPending}
                  active={s === picked}
                  onPick={() => pick(s)}
                  onRemove={() => remove(s)}
                />
              ))}
            </tbody>
          </table>
        )}
      </Widget>
  )

  const needPick = (label: string, span: number) => (
    <Widget span={span} title={label} expandable={false}>
      <div className="px-3 py-4 text-left text-body text-muted-foreground">
        Pick a symbol in the table to scope this panel.
      </div>
    </Widget>
  )

  return (
    <ComposedBoard
      page="portfolio"
      panels={[
        { id: "watchlist", label: "My Portfolio", node: watchlistPanel },
        { id: "chart", label: "Chart",
          node: picked ? <MarketChart symbol={picked} span={8} /> : needPick("Chart", 8) },
        // The NUMBERS before the picture (2026-09-16, the owner's own board).
        // Price performance is a table of returns over the trailing periods,
        // read at a glance; the rebased lines are the same story drawn, and
        // they take a moment to read. The table earns the place directly
        // under the chart.
        { id: "performance", label: "Price performance", node: <PricePerformancePanel symbols={lineup} quoteFill="range,cap" /> },
        { id: "relative", label: "Relative performance", node: <RelativePerformancePanel symbols={lineup} /> },
        { id: "metrics", label: "Comparison analysis",
          node: <ComparisonMetricsPanel symbols={lineup} active={active} peers={peers.data}
                                        showPeers={showPeers} onTogglePeers={() => setShowPeers(v => !v)} /> },
        { id: "cards", label: "Side by side", node: <ComparisonPanel symbols={lineup} title="Side by side" /> },
        // Last on the board, and paging further back on request: the
        // company's headlines are a read at the end of the page, not the
        // first thing between the table and the comparisons (2026-09-16).
        { id: "news", label: "Symbol news",
          node: picked ? <SymbolNews symbol={picked} span={12} scroll={420} /> : needPick("Symbol News", 12) },
      ]}
    />
  )
}
