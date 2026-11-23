import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { Empty } from "@/components/terminal"
import { QueryFailure } from "@/components/KeyPrompt"
import { ChartCanvas } from "@/components/chart/ChartCanvas"
import { etDateKey, on } from "@/lib/api"
import { rangeReaching } from "@/lib/periodChart"
import { useChartTheme } from "@/lib/theme"
import { cn } from "@/lib/utils"

/** ONE ROW'S PRICE OVER THE PERIOD THE LIST MEASURED (2026-11-23, the
 * owner: "show a chart in period movers").
 *
 * The SAME ROUTE AS EVERY CHART TILE — /api/chart at a daily range, so the
 * vendor, interval and history floor are the chart tiles' own — cut to the
 * period's two sessions: the start close is the first bar and the end close
 * (or the latest bar, while the period ends now) is the last.
 *
 * DRAWN ON THE PERCENT SCALE FROM THE START CLOSE, so the axis reads the
 * change directly and the last point is the change measured. A rule at 0%
 * and a mark at each end make the two closes the list used visible. The
 * chart's daily bars come from the chart vendor while the list's two closes
 * come from the whole-market day; both are split-adjusted, but a dividend
 * adjustment can separate them slightly, so the readout gives the chart's
 * own two figures and says so when they differ from the list's change. */

const HEIGHT = 300

export function PeriodChart({ symbol, from, to, live, listChange, label }: {
  symbol: string
  /** The session whose close the change runs from. */
  from: string
  /** The session it runs to; ignored while `live`. */
  to: string
  live: boolean
  /** The list's own change for the row, to compare with the chart's. */
  listChange: number | null
  /** The row's name, for the heading. */
  label?: string | null
}) {
  const theme = useChartTheme()
  const range = rangeReaching(from)
  const q = useQuery({
    queryKey: ["period-chart", symbol, range],
    queryFn: ({ signal }) => on(signal).chartRange(symbol, range, "1d"),
    staleTime: 5 * 60_000,
    refetchInterval: live ? 120_000 : false,
  })
  const bars = useMemo(() => (q.data?.bars ?? []).filter(b => {
    const day = etDateKey(b.t)
    return day >= from && (live || day <= to)
  }), [q.data, from, to, live])
  const first = bars[0], last = bars[bars.length - 1]
  const startsLate = !!first && etDateKey(first.t) !== from
  const change = first && last ? (last.c / first.c - 1) * 100 : null
  const drift = change != null && listChange != null && Math.abs(change - listChange) > 0.5
  const overlays = useMemo(() => {
    if (!first || !last || bars.length < 2) return []
    const lo = Math.min(...bars.map(b => b.l)), hi = Math.max(...bars.map(b => b.h))
    const mark = theme.text
    return [
      // 0%: the start close, across the period.
      { color: mark, width: 1, points: [{ t: first.t, v: first.c }, { t: last.t, v: first.c }] },
      // The two sessions the change is measured between.
      { color: mark, width: 1, points: [{ t: first.t, v: lo }, { t: first.t, v: hi }] },
      { color: mark, width: 1, points: [{ t: last.t, v: lo }, { t: last.t, v: hi }] },
    ]
  }, [bars, first, last, theme.text])

  const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
  return (
    <div className="border-b border-row-rule">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 pb-1 pt-2">
        <span className="text-body font-semibold">{symbol}</span>
        {label && <span className="truncate text-caption text-muted-foreground">{label}</span>}
        {first && last && change != null && (
          <span className="tnum text-caption text-muted-foreground">
            {etDateKey(first.t)} close {first.c.toFixed(2)} → {live ? "latest" : `${etDateKey(last.t)} close`} {last.c.toFixed(2)}
            {" · "}
            <span className={cn("font-semibold", change >= 0 ? "text-gain" : "text-loss")}>{pct(change)}</span>
          </span>
        )}
      </div>
      <div style={{ height: HEIGHT }}>
        {q.isPending ? <Empty>loading</Empty>
          : q.isError ? <QueryFailure error={q.error}>the chart is unavailable right now</QueryFailure>
          : bars.length < 2 ? <Empty>no daily bars for {symbol} over this period</Empty>
          : (
            <ChartCanvas
              bars={bars}
              kind="line"
              scale="percent"
              percentBase={{ price: first.c, index: 0 }}
              height={HEIGHT}
              overlays={overlays}
              seriesId={`period:${symbol}:${from}:${live ? "now" : to}`}
              interval="1d"
              priceLine={false}
              live={false}
              focusFrom={0}
              {...theme}
            />
          )}
      </div>
      {(startsLate || drift) && (
        <p className="px-3 pb-2 text-caption text-muted-foreground">
          {startsLate && `The chart's daily bars begin at ${etDateKey(first!.t)}, after the period's start. `}
          {drift && `The list measured ${pct(listChange!)} from the whole market's closes; the chart's own daily bars read ${pct(change!)}.`}
        </p>
      )}
    </div>
  )
}
