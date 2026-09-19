import { useMemo, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { api, type Quote } from "@/lib/api"
import { keys, useQuotes, useThemes } from "@/lib/queries"
import { BasketDialog } from "@/components/BasketDialog"
import { Empty, Flash, Widget, btnCls } from "@/components/terminal"
import { compact, HEAT, HEAT_FILL, HEAT_NONE, Treemap, heatHasData, type Heat } from "@/components/Treemap"
import { MarketChart } from "@/widgets/chart"
import { SymbolNews } from "@/components/SymbolNews"

/** One curated basket: its members, and whichever member you are looking at.
 *
 * The Themes rail was here once and was deleted, because the links carried a
 * ?q= nothing read — buttons that looked like filters and filtered nothing.
 * The note left behind said to rebuild it on top of a real surface rather than
 * before one. This is that surface: every row is a live quote, and the chart
 * and news below are scoped to the row you pick.
 *
 * The whole basket is priced in ONE request. Each row fetching its own looked
 * fine and was not: nine concurrent per-symbol calls land on nine threadpool
 * workers, the upstream throttled, and two or three came back 404 at random —
 * so those rows rendered as dashes, which reads as "no price exists" rather
 * than "we asked too fast". /api/quotes walks the list server-side and fills
 * the same per-symbol cache on the way, so opening one of these names on
 * Analysis afterwards is already answered.
 */
const money = (n: number | null | undefined, d = 2) =>
  n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })

function Row({ symbol, data, loading, active, onPick }: {
  symbol: string
  data: Quote | null | undefined
  loading: boolean
  active: boolean
  onPick: () => void
}) {
  const isPending = loading
  const chg = data?.change_pct ?? null
  const up = (chg ?? 0) >= 0
  return (
    <tr
      onClick={onPick}
      className={`row-rule cursor-pointer ${active ? "bg-muted" : "hover:bg-muted/50"}`}
    >
      <td className="px-3 py-1.5">
        <span className="num font-semibold">{symbol}</span>
      </td>
      <td className="max-w-[220px] truncate px-3 py-1.5 text-muted-foreground">
        {isPending ? "…" : data?.name ?? ""}
      </td>
      <td className="tnum px-3 py-1.5 text-right">
        <Flash value={data?.price}>{money(data?.price)}</Flash>
      </td>
      <td className={`tnum px-3 py-1.5 text-right ${
        chg == null ? "text-muted-foreground" : up ? "text-gain" : "text-loss"}`}>
        {chg == null ? "—" : `${up ? "+" : ""}${chg.toFixed(2)}%`}
      </td>
      <td className="tnum px-3 py-1.5 text-right text-muted-foreground">{compact(data?.volume)}</td>
      <td className="tnum px-3 py-1.5 text-right text-muted-foreground">{money(data?.week52_low)}</td>
      <td className="tnum px-3 py-1.5 text-right text-muted-foreground">{money(data?.week52_high)}</td>
      <td className="tnum px-3 py-1.5 text-right">{compact(data?.market_cap)}</td>
    </tr>
  )
}

export default function ThemePage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const { data, isPending } = useThemes()
  const [metric, setMetric] = useState<Heat>("move")
  // The reader's own basket can be edited or deleted (2026-09-18); deleting
  // asks once more in place, since it cannot be undone.
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()

  const theme = useMemo(
    () => (data?.themes ?? []).find(t => t.id === id) ?? null,
    [data, id],
  )
  const symbols = useMemo(() => theme?.symbols ?? [], [theme])
  const quotes = useQuotes(symbols)
  const priced = quotes.data?.quotes
  // The map's own basket, with the one measure on screen filled in.
  const heat = useQuotes(symbols, HEAT_FILL[metric])
  const heatPriced = heat.data?.quotes as Record<string, unknown> | undefined
  const picked = params.get("symbol")?.toUpperCase() || symbols[0] || ""
  const pick = (sym: string) => {
    const next = new URLSearchParams(params)
    next.set("symbol", sym)
    setParams(next, { replace: true })
  }

  if (isPending) return <div className="collage"><Widget span={12} title="Theme"><Empty>loading…</Empty></Widget></div>
  if (!theme) {
    return (
      <div className="collage">
        <Widget span={12} title="Theme">
          <Empty>no theme called “{id}” — check THEMES in the server config</Empty>
        </Widget>
      </div>
    )
  }

  return (
    <div className="collage">
      {editing && <BasketDialog basket={theme} onClose={() => setEditing(false)} />}
      <Widget
        span={12}
        title={theme.label}
        subtitle={`${theme.mine ? "your basket · " : ""}${symbols.length} names · pick a row to scope the chart`}
        actions={theme.mine ? (confirming ? (
          <>
            <span className="text-caption text-muted-foreground">Delete this basket?</span>
            <button type="button" className={btnCls({ variant: "danger" })}
                    onClick={async () => {
                      await api.deleteBasket(theme.id)
                      await qc.invalidateQueries({ queryKey: keys.themes })
                      navigate("/")
                    }}>Delete</button>
            <button type="button" className={btnCls()} onClick={() => setConfirming(false)}>Keep</button>
          </>
        ) : (
          <>
            <button type="button" className={btnCls()} onClick={() => setEditing(true)}>Edit</button>
            <button type="button" className={btnCls({ variant: "danger" })} onClick={() => setConfirming(true)}>Delete</button>
          </>
        )) : undefined}
        scroll={320}
        bodyClassName="overflow-x-auto"
      >
        {/* What moves the basket, whole, above its members (2026-09-18, the
            owner's call): in the subtitle it was cut to "Miners, bitcoin-
            treasury companies a…" beside the title. */}
        {theme.why && (
          <p className="border-b border-row-rule px-3 py-2.5 text-body leading-[1.45] text-muted-foreground">{theme.why}</p>
        )}
        <table className="w-full border-collapse text-body">
          <thead>
            <tr className="text-label font-medium uppercase tracking-caps text-muted-foreground">
              <th className="px-3 py-2.5 text-left font-medium" data-tip="The ticker. Click a row to scope the chart and news to it" aria-description="The ticker. Click a row to scope the chart and news to it">Symbol</th>
              <th className="px-3 py-2.5 text-left font-medium" data-tip="The company or fund name" aria-description="The company or fund name">Name</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="The latest price" aria-description="The latest price">Price</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="Change since the previous session's close" aria-description="Change since the previous session's close">Chg %</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="Shares traded today" aria-description="Shares traded today">Volume</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="The lowest price over the past 52 weeks" aria-description="The lowest price over the past 52 weeks">52w Low</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="The highest price over the past 52 weeks" aria-description="The highest price over the past 52 weeks">52w High</th>
              <th className="px-3 py-2.5 text-right font-medium" data-tip="Market capitalisation: the share price times the shares outstanding" aria-description="Market capitalisation: the share price times the shares outstanding">Mkt Cap</th>
            </tr>
          </thead>
          <tbody>
            {symbols.map(s => (
              <Row key={s} symbol={s} data={priced?.[s]} loading={quotes.isPending}
                   active={s === picked} onPick={() => pick(s)} />
            ))}
          </tbody>
        </table>
      </Widget>

      {picked && <MarketChart symbol={picked} span={8} />}
      {picked && <SymbolNews symbol={picked} span={4} scroll={420} />}
      <Widget
        span={12}
        title="Heatmap"
        subtitle={metric === "move" ? "sized by how far each moved today · colored by which way"
          : `sized by ${HEAT.find(h => h.id === metric)!.label.toLowerCase()} · colored by today's move`}
        toolbar={
          <>
            {HEAT.map(h => (
              <button
                key={h.id}
                onClick={() => setMetric(h.id)}
                aria-pressed={h.id === metric}
                className={btnCls({ variant: "ghost", active: h.id === metric })}
              >
                {h.label}
              </button>
            ))}
          </>
        }
      >
        <div className="p-2">
          {heat.data && !heatHasData(symbols, heatPriced, metric) && (
            <p className="px-1 pb-2 text-caption text-muted-foreground">{HEAT_NONE[metric]}</p>
          )}
          <Treemap symbols={symbols} priced={heat.data?.quotes} metric={metric}
                   picked={picked} onPick={pick} />
        </div>
      </Widget>

      <div className="col-span-12 px-1 text-caption text-muted-foreground">
        <Link to={`/analysis?symbol=${encodeURIComponent(picked)}`} className="hover:underline">
          Open {picked} in Analysis →
        </Link>
      </div>
    </div>
  )
}
