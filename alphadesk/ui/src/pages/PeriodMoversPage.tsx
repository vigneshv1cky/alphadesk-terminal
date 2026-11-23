import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Empty, Widget, btnCls, fieldCls } from "@/components/terminal"
import { QueryFailure } from "@/components/KeyPrompt"
import { Menu } from "@/components/ChartToolbar"
import { isNeedsKey, on, type MoverCategory, type MoverPeriod } from "@/lib/api"
import { useKeptState } from "@/lib/keptState"
import { cn } from "@/lib/utils"
import { FloorsPopover, MoversTable, SOURCE_LABELS, TabStrip, readFloors, writeFloors, type Floors } from "@/widgets/market"

/** GAINERS AND LOSERS OVER ANY PERIOD (2026-11-23, the owner: "I need a
 * section that find stocks that performed too well or too bad, in a certain
 * period"; picked over a z-score list, a versus-peers list and more buttons
 * on the Markets tile).
 *
 * ONE POINT-TO-POINT CHANGE: the price at the end against the close at the
 * start, both split-adjusted as of now and read fresh from the whole market
 * (ingest/movers.period_movers). Nothing is scored or ranked beyond the
 * measured change itself — the order IS the number on each row.
 *
 * A custom start on a weekend or holiday measures from the session before
 * it, and the subtitle names the two sessions actually used, so the reader
 * never has to guess which close the change runs from. Stocks and ETFs only:
 * no other category has a whole-market day to measure against. */

const PRESETS: { id: Exclude<MoverPeriod, "1D">; label: string; tip: string }[] = [
  { id: "1W", label: "1W", tip: "Against the close 5 sessions earlier" },
  { id: "1M", label: "1M", tip: "Against the close 21 sessions earlier" },
  { id: "3M", label: "3M", tip: "Against the close 63 sessions earlier" },
  { id: "6M", label: "6M", tip: "Against the close 126 sessions earlier" },
  { id: "YTD", label: "YTD", tip: "Against the last close of the year before" },
  { id: "1Y", label: "1Y", tip: "Against the close 252 sessions earlier" },
  { id: "CUSTOM", label: "Dates", tip: "From a start date of your choosing, to an end date or now" },
]

const CATEGORIES: { id: MoverCategory; label: string }[] = [
  { id: "stocks", label: "Stocks" },
  { id: "etfs", label: "ETFs" },
]

const TOP = 50
const FLOORS_TILE = "period-page"

/** YYYY-MM-DD in New York, which is the calendar sessions are named in. */
function nyDay(offsetYears = 0): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() + offsetYears)
  return d.toLocaleDateString("en-CA", { timeZone: "America/New_York" })
}

export default function PeriodMoversPage() {
  const [category, setCategory] = useKeptState<MoverCategory>("alphadesk.period.category", "stocks")
  const [period, setPeriod] = useKeptState<Exclude<MoverPeriod, "1D">>("alphadesk.period.period", "1M")
  const [from, setFrom] = useKeptState<string>("alphadesk.period.from", "")
  const [to, setTo] = useKeptState<string>("alphadesk.period.to", "")
  const [tab, setTab] = useState<"gainers" | "losers">("gainers")
  const [floors, setFloorsState] = useState<Floors | null>(() => readFloors(FLOORS_TILE, category))
  const pickCategory = (c: MoverCategory) => { setCategory(c); setFloorsState(readFloors(FLOORS_TILE, c)) }
  const setFloors = (f: Floors | null) => { setFloorsState(f); writeFloors(FLOORS_TILE, category, f) }

  const today = nyDay()
  const earliest = nyDay(-5)
  const custom = period === "CUSTOM"
  // A custom period is asked for only once its start is a whole date; the end
  // is optional and means "now" when empty.
  const ready = !custom || /^\d{4}-\d{2}-\d{2}$/.test(from)
  const q = useQuery({
    queryKey: ["period-movers", category, period, custom ? from : "", custom ? to : "",
               floors?.min_price ?? "d", floors?.min_turnover ?? "d", floors?.min_liquidity ?? 0, floors?.min_volatility ?? 0],
    queryFn: ({ signal }) => on(signal).categoryMovers(category, TOP, floors, null, period,
                                                      custom ? { from, to: to || null } : null),
    enabled: ready,
    staleTime: 60_000,
    // A period ending in the session still trading is rebuilt on the server
    // every two minutes; one ending in a finished session is settled.
    refetchInterval: query => (query.state.data?.live ? 120_000 : false),
    refetchIntervalInBackground: true,
  })
  const d = q.data
  const rows = useMemo(() => d?.tabs?.find(t => t.id === tab)?.rows ?? [], [d, tab])

  const subtitle = !ready ? "pick a start date"
    : q.isPending ? "loading"
    : q.isError ? (isNeedsKey(q.error) ? "needs a data key" : "unavailable right now")
    : d?.unavailable ? (d.note ?? "unavailable right now")
    : d?.period_from
      ? `${d.period_from} close to ${d.live ? "now" : `${d.period_to} close`}${
          d.sessions ? ` · ${d.sessions} sessions` : ""} · split-adjusted${
          d.source ? ` · ${SOURCE_LABELS[d.source] ?? d.source}` : ""}`
      : "unavailable right now"
  const changeTip = d?.period_from
    ? `Change from the ${d.period_from} close to ${d.live ? "the latest price" : `the ${d.period_to} close`}, both adjusted for splits`
    : undefined
  const statsTip = d && !d.live ? " — ending now, not at the end of the period" : ""

  return (
    <>
      <div className="px-4 pt-2">
        <h1 className="mb-2 text-emph font-extrabold tracking-tight">Period movers</h1>
      </div>
      <div className="collage !pt-0">
        <Widget
          span={12}
          title="Gainers and losers over a period"
          subtitle={subtitle}
          actions={d && !d.unavailable ? (
            <Menu label="Filter" align="right" chevron={false} active={!!floors}
                  title={d.note ? `Floors and method: ${d.note}` : "Set a price, turnover, liquidity or volatility floor"}>
              {close => (
                <FloorsPopover floors={{ min_price: d.floors.min_price, min_turnover: d.floors.min_turnover,
                                         min_liquidity: d.floors.min_liquidity, min_volatility: d.floors.min_volatility }}
                               defaults={{ min_price: d.floors.default_min_price, min_turnover: d.floors.default_min_turnover,
                                           min_liquidity: 0, min_volatility: 0 }}
                               onApply={setFloors} onClose={close} />
              )}
            </Menu>
          ) : undefined}
          // Wraps rather than scrolling sideways: the date fields open the
          // browser's own calendar, which a scrolling row would clip (#77).
          toolbarWraps
          toolbar={
            <div className="flex w-full flex-wrap items-center gap-2">
              <TabStrip tabs={CATEGORIES} value={category} onChange={pickCategory} />
              <div className="flex flex-wrap items-center gap-0.5" role="group" aria-label="Period">
                {PRESETS.map(p => (
                  <button key={p.id} type="button" onClick={() => setPeriod(p.id)} title={p.tip}
                          aria-pressed={period === p.id}
                          className={btnCls({ variant: "ghost", size: "lg", active: period === p.id }, "min-w-[40px]")}>
                    {p.label}
                  </button>
                ))}
              </div>
              {custom && (
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-1.5 text-caption text-muted-foreground">
                    From
                    <input type="date" value={from} min={earliest} max={to || today}
                           onChange={e => setFrom(e.target.value)} aria-label="Start date"
                           className={cn(fieldCls, "h-[28px] w-[140px] text-caption")} />
                  </label>
                  <label className="flex items-center gap-1.5 text-caption text-muted-foreground"
                         title="Leave empty to measure to the latest price">
                    To
                    <input type="date" value={to} min={from || earliest} max={today}
                           onChange={e => setTo(e.target.value)} aria-label="End date"
                           className={cn(fieldCls, "h-[28px] w-[140px] text-caption")} />
                  </label>
                  {to && (
                    <button type="button" onClick={() => setTo("")} className={btnCls({ variant: "ghost" })}
                            title="Measure to the latest price instead">
                      To now
                    </button>
                  )}
                </div>
              )}
              <div className="ml-auto">
                <TabStrip tabs={[{ id: "gainers", label: "Gainers" }, { id: "losers", label: "Losers" }] as const}
                          value={tab} onChange={setTab} />
              </div>
            </div>
          }
        >
          {!ready ? <Empty>Pick a start date. A weekend or holiday measures from the session before it.</Empty>
            : q.isPending ? <Empty>loading</Empty>
            : q.isError ? <QueryFailure error={q.error}>the period list is unavailable right now</QueryFailure>
            : d?.unavailable ? <Empty>{d.note ?? "unavailable right now"}</Empty>
            : <MoversTable rows={rows} changeHead={d?.change_label ?? "Change"} changeTip={changeTip}
                           nameHead={category === "stocks" ? "Company" : "Name"}
                           volTip={`Annualised volatility of daily returns over the last twenty sessions${statsTip}`}
                           liqTip={`Average dollar volume a day over the last twenty sessions${statsTip}`}
                           empty={tab === "gainers" ? "nothing is up over this period" : "nothing is down over this period"} />}
          {d?.note && !d.unavailable && (
            <p className="px-3 py-2 text-caption text-muted-foreground">{d.note}</p>
          )}
        </Widget>
      </div>
    </>
  )
}
