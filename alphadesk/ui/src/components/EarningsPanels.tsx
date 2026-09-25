import { useMemo, useState } from "react"
import type { MetricPeriod } from "@/lib/api"
import { QueryFailure } from "@/components/KeyPrompt"
import { fiscalYearEndMonth, lastQuarters, periodLabel as fiscalPeriodLabel, reportedQuarterLabel } from "@/lib/fiscal"
import {
  useEarningsContext, useEarningsHistory, useEarningsInsights, useFundamentals, useQuote,
} from "@/lib/queries"
import { Empty, Table, TD, TH, THead, TR, Widget, btnCls } from "@/components/terminal"

/** The three company-scoped panels under the earnings calendar.
 *
 * Everything drawn here is a code-fetched fact except the insights table,
 * which is analyst consensus — the one forecast the terminal shows, labelled
 * as consensus and never as the company's own numbers.
 *
 * Quantities are not directions: the revenue and earnings bars run on the
 * neutral ramp with only the latest revenue bar in accent — they must not be
 * green. Green and red appear once, on the EPS dots, where beat/miss really
 * is a direction against the estimate.
 */

const compact = (n: number | null | undefined): string => {
  if (n == null) return "—"
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(0)}M`
  return n.toFixed(2)
}

function PeriodToggle({ value, onChange }: {
  value: MetricPeriod
  onChange: (p: MetricPeriod) => void
}) {
  return (
    // A gap, not fused borders: since the soft-radius pass every button has
    // rounded corners, and two pills sharing an edge read as one broken one.
    <span className="inline-flex gap-1">
      {(["annual", "quarterly"] as const).map(p => (
        <button
          key={p}
          onClick={() => onChange(p)}
          aria-pressed={value === p}
          className={btnCls({ active: value === p })}
        >
          {p === "annual" ? "Annual" : "Quarterly"}
        </button>
      ))}
    </span>
  )
}

/* ── Revenue vs. earnings — grouped bars + a margin line on its own axis ── */

const VB_W = 560
const VB_H = 176
const PLOT_L = 44
const PLOT_R = 516
const PLOT_T = 14
const PLOT_B = 150

export function RevenueEarningsPanel({ symbol }: { symbol: string }) {
  const [period, setPeriod] = useState<MetricPeriod>("quarterly")
  const { data, isPending } = useFundamentals(symbol, period)
  const { data: quote } = useQuote(symbol)
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)
  // The bar under the cursor; the readout below the chart follows it and
  // rests on the latest bar otherwise (theirs reads out on hover, 2026-09-12).
  const [hover, setHover] = useState<number | null>(null)

  const groups = useMemo(() => {
    const rev = data?.series?.revenue ?? []
    const net = data?.series?.net_income ?? []
    const take = period === "quarterly" ? 8 : 6
    return rev.slice(-take).map(r => {
      const ni = net.find(n => n.t === r.t)
      return {
        t: r.t,
        rev: r.v,
        net: ni?.v ?? null,
        margin: ni != null && r.v ? (ni.v / r.v) * 100 : null,
      }
    })
  }, [data, period])

  const body = () => {
    if (isPending) return <Empty>loading…</Empty>
    if (!groups.length) return <Empty>no reported financials for {symbol}</Empty>

    const maxVal = Math.max(...groups.flatMap(g => [g.rev, g.net ?? 0]), 1)
    const minVal = Math.min(...groups.map(g => g.net ?? 0), 0)
    const span = maxVal - minVal || 1
    const y = (v: number) => PLOT_B - ((v - minVal) / span) * (PLOT_B - PLOT_T)
    const margins = groups.map(g => g.margin).filter((m): m is number => m != null)
    const mLo = Math.min(...margins, 0)
    const mHi = Math.max(...margins, 1)
    const my = (v: number) => PLOT_B - ((v - mLo) / (mHi - mLo || 1)) * (PLOT_B - PLOT_T)
    const step = (PLOT_R - PLOT_L) / groups.length
    const barW = Math.min(18, step * 0.28)

    return (
      <div className="px-3 pb-2 pt-1">
        <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="block w-full" role="img"
             aria-label={`Revenue and earnings by ${period === "annual" ? "year" : "quarter"}, with profit margin`}>
          {/* gridlines: dashed, the zero line solid */}
          {[0.25, 0.5, 0.75].map(f => {
            const gy = PLOT_T + (PLOT_B - PLOT_T) * f
            return <line key={f} x1={PLOT_L} x2={PLOT_R} y1={gy} y2={gy}
                         className="stroke-grid-line" strokeDasharray="3 3" strokeWidth="1" />
          })}
          <line x1={PLOT_L} x2={PLOT_R} y1={y(0)} y2={y(0)} className="stroke-n400" strokeWidth="1" />
          {/* left axis: money */}
          {[maxVal, maxVal / 2].map((v, i) => (
            <text key={i} x={PLOT_L - 6} y={y(v) + 3} textAnchor="end"
                  className="fill-n600" fontSize="9.5">{compact(v)}</text>
          ))}
          {/* right axis: margin % */}
          {margins.length > 0 && [mHi, (mHi + mLo) / 2].map((v, i) => (
            <text key={i} x={PLOT_R + 6} y={my(v) + 3} textAnchor="start"
                  className="fill-n600" fontSize="9.5">{v.toFixed(0)}%</text>
          ))}
          {/* grouped bars: revenue on the neutral base step, earnings a step
              lighter, the LATEST revenue bar in accent — a quantity, not a
              direction, so never green */}
          {groups.map((g, i) => {
            const cx = PLOT_L + step * (i + 0.5)
            const latest = i === groups.length - 1
            const dim = hover != null && hover !== i
            return (
              <g key={g.t} opacity={dim ? 0.45 : 1}>
                <rect x={cx - barW - 1} width={barW} y={y(Math.max(g.rev, 0))}
                      height={Math.abs(y(g.rev) - y(0))}
                      className={latest ? "fill-accent" : "fill-n500"} />
                {g.net != null && (
                  <rect x={cx + 1} width={barW} y={y(Math.max(g.net, 0))}
                        height={Math.abs(y(g.net) - y(0))} className="fill-n300" />
                )}
                <text x={cx} y={PLOT_B + 14} textAnchor="middle"
                      className={`fill-n600 ${hover === i ? "font-semibold" : ""}`} fontSize="9.5">{fiscalPeriodLabel(g.t, period, fyEnd)}</text>
              </g>
            )
          })}
          {/* the hover targets: one column per period, over everything */}
          {groups.map((g, i) => (
            <rect key={`h-${g.t}`} x={PLOT_L + step * i} y={PLOT_T} width={step} height={PLOT_B - PLOT_T + 16}
                  fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          ))}
          {/* the margin line, ink — nothing else on screen is coloured */}
          {margins.length > 1 && (
            <polyline
              points={groups
                .map((g, i) => (g.margin == null ? null : `${PLOT_L + step * (i + 0.5)},${my(g.margin)}`))
                .filter(Boolean)
                .join(" ")}
              fill="none" className="stroke-foreground" strokeWidth="1.5" />
          )}
        </svg>
        {/* the readout: the hovered period, else the latest — its label,
            its end date, and the three figures the bars only suggest */}
        {(() => {
          const g = groups[hover ?? groups.length - 1]
          return (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption">
              <span className="font-semibold">{fiscalPeriodLabel(g.t, period, fyEnd)}</span>
              <span className="num text-muted-foreground">{period === "annual" ? "year" : "quarter"} ended {g.t.slice(0, 10)}</span>
              <span className="num">Revenue <span className="font-semibold">{compact(g.rev)}</span></span>
              <span className="num">Net income <span className="font-semibold">{g.net == null ? "—" : compact(g.net)}</span></span>
              <span className="num">Margin <span className="font-semibold">{g.margin == null ? "—" : `${g.margin.toFixed(1)}%`}</span></span>
            </div>
          )
        })()}
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-label font-medium uppercase tracking-caps text-muted-foreground">
          <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="h-[9px] w-[9px] bg-n500" /> Revenue</span>
          <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="h-[9px] w-[9px] bg-n300" /> Net income</span>
          <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="h-[2px] w-[14px] bg-foreground" /> Margin</span>
        </div>
      </div>
    )
  }

  return (
    <Widget span={6} symbol={symbol} title="Revenue vs. earnings"
            actions={<PeriodToggle value={period} onChange={setPeriod} />}
           >
      {body()}
    </Widget>
  )
}

/* ── Earnings per share — hollow ring estimate, filled dot actual ───────── */

export function EpsPanel({ symbol }: { symbol: string }) {
  const { data, isPending } = useEarningsContext(symbol)
  const { data: quote } = useQuote(symbol)
  // The next report's date comes from the earnings record's upcoming row;
  // the quote's own earnings stamp lags and names the LAST report for weeks.
  const { data: history } = useEarningsHistory(symbol)
  const nextDate = history?.reports?.find(r => r.upcoming)?.date ?? quote?.earnings_date ?? null
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)
  const [hover, setHover] = useState<number | null>(null)

  const points = useMemo(() => {
    // The last four reported quarters, oldest first: the chart reads left to
    // right into the present. Each point is labelled for the fiscal quarter
    // it covers when the fiscal year end is known, else by its report date.
    const hist = lastQuarters(data?.report_history ?? [])
    const out = hist.map(h => ({
      ...h, upcoming: false as boolean,
      // A row dated by its quarter end is labelled by that period; a row
      // dated by its report day, by the quarter that closed before it.
      label: (h.period_end ? fiscalPeriodLabel(h.period_end, "quarterly", fyEnd) : reportedQuarterLabel(h.date, fyEnd)) ?? h.date.slice(5),
    }))
    if (data?.next_q_eps_estimate != null) {
      const next = nextDate
      out.push({
        date: next ?? "next", label: (next && reportedQuarterLabel(next, fyEnd)) ?? "Next",
        eps_estimate: data.next_q_eps_estimate, eps_actual: null,
        surprise_pct: null, upcoming: true,
      })
    }
    return out
  }, [data, fyEnd, nextDate])

  const body = () => {
    if (isPending) return <Empty>loading…</Empty>
    if (!points.length) return <Empty>no reported quarters for {symbol}</Empty>

    const vals = points.flatMap(p => [p.eps_estimate, p.eps_actual]).filter((v): v is number => v != null)
    const lo = Math.min(...vals, 0)
    const hi = Math.max(...vals)
    const span = hi - lo || 1
    const y = (v: number) => PLOT_B - ((v - lo) / span) * (PLOT_B - PLOT_T)
    const step = (PLOT_R + 32 - PLOT_L) / points.length

    return (
      <div className="px-3 pb-2 pt-1">
        <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="block w-full" role="img"
             aria-label="EPS estimate against actual, by quarter">
          {[0.25, 0.5, 0.75].map(f => {
            const gy = PLOT_T + (PLOT_B - PLOT_T) * f
            return <line key={f} x1={PLOT_L} x2={PLOT_R + 32} y1={gy} y2={gy}
                         className="stroke-grid-line" strokeDasharray="3 3" strokeWidth="1" />
          })}
          {[hi, (hi + lo) / 2, lo].map((v, i) => (
            <text key={i} x={PLOT_L - 6} y={y(v) + 3} textAnchor="end"
                  className="fill-n600" fontSize="9.5">{v.toFixed(2)}</text>
          ))}
          {points.map((p, i) => {
            const cx = PLOT_L + step * (i + 0.5)
            const beat = p.eps_actual != null && p.eps_estimate != null && p.eps_actual >= p.eps_estimate
            const dim = hover != null && hover !== i
            return (
              <g key={p.date} opacity={dim ? 0.45 : 1}>
                {p.eps_estimate != null && (
                  <circle cx={cx} cy={y(p.eps_estimate)} r="6.5" fill="none"
                          className="stroke-n500" strokeWidth="1.6" />
                )}
                {p.eps_actual != null && (
                  <circle cx={cx} cy={y(p.eps_actual)} r="6.5"
                          className={beat ? "fill-gain" : "fill-loss"} />
                )}
                <text x={cx} y={PLOT_B + 14} textAnchor="middle"
                      className={`fill-n600 ${hover === i ? "font-semibold" : ""}`}
                      fontSize="9.5">{p.label}</text>
              </g>
            )
          })}
          {points.map((p, i) => (
            <rect key={`h-${p.date}`} x={PLOT_L + step * i} y={PLOT_T} width={step} height={PLOT_B - PLOT_T + 16}
                  fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          ))}
        </svg>
        {(() => {
          const p = points[hover ?? points.length - 1]
          const diff = p.eps_actual != null && p.eps_estimate != null ? p.eps_actual - p.eps_estimate : null
          const verdict = diff == null ? null : Math.abs(diff) < 0.005 ? "Met" : diff > 0 ? `Beat by $${diff.toFixed(2)}` : `Missed by $${Math.abs(diff).toFixed(2)}`
          return (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption">
              <span className="font-semibold">{p.label}</span>
              <span className="num text-muted-foreground">{p.upcoming ? (p.date !== "next" ? `reports ${p.date}` : "next report") : `reported ${p.date}`}</span>
              <span className="num">Estimate <span className="font-semibold">{p.eps_estimate == null ? "—" : p.eps_estimate.toFixed(2)}</span></span>
              {!p.upcoming && <span className="num">Actual <span className="font-semibold">{p.eps_actual == null ? "—" : p.eps_actual.toFixed(2)}</span></span>}
              {verdict && (
                <span className={`num font-semibold ${diff! > 0.005 ? "text-gain" : diff! < -0.005 ? "text-loss" : "text-muted-foreground"}`}>
                  {verdict}{p.surprise_pct != null ? ` (${p.surprise_pct > 0 ? "+" : ""}${p.surprise_pct.toFixed(1)}%)` : ""}
                </span>
              )}
            </div>
          )
        })()}
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-label font-medium uppercase tracking-caps text-muted-foreground">
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <span className="h-[10px] w-[10px] rounded-full border-[1.6px] border-n500" /> Estimate
          </span>
          <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="h-[10px] w-[10px] rounded-full bg-gain" /> Beat</span>
          <span className="flex items-center gap-1.5 whitespace-nowrap"><span className="h-[10px] w-[10px] rounded-full bg-loss" /> Miss</span>
          {data?.beat_streak && <span className="whitespace-nowrap">{data.beat_streak}</span>}
          {nextDate && (
            <span className="ml-auto whitespace-nowrap normal-case tracking-normal">Next report {nextDate}</span>
          )}
        </div>
      </div>
    )
  }

  return (
    <Widget span={6} symbol={symbol} title="Earnings per share"
            subtitle="estimate vs actual, last four quarters">
      {body()}
    </Widget>
  )
}

/* ── Earnings history — every report on record ──────────────────────────── */

const eps = (v: number | null) => (v == null ? "—" : v.toFixed(2))

/** The full record as a table: the next scheduled report on top with its
 * consensus estimates, then every reported quarter — estimate, actual,
 * surprise, and the quarter's revenue joined from the income statement.
 * Past revenue estimates are on no free source, so that column is filled
 * for the upcoming row only and reads "—" elsewhere, never a guess. */
export function EarningsHistoryPanel({ symbol, span = 6, scroll }: { symbol: string; span?: number; scroll?: number | string }) {
  const { data, isPending, isError, error } = useEarningsHistory(symbol)
  const { data: quote } = useQuote(symbol)
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)
  const rows = data?.reports ?? []
  return (
    <Widget span={span} symbol={symbol} title="Earnings history"
            subtitle="estimate, actual, surprise · revenue as filed" scroll={scroll ?? 420}
           >
      {isPending ? <Empty>loading…</Empty>
        : isError ? <QueryFailure error={error}>the report record is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no reports on record for {symbol}</Empty> : (
        <Table>
          <THead>
            <TH className="w-[128px]" title="The report day, or the fiscal quarter when the vendor dates reports by the quarter they cover. NEXT marks the scheduled report">Date</TH>
            <TH align="right" className="w-[64px]" title="Earnings per share as reported: green at or above the estimate, red below it">EPS</TH>
            <TH align="right" className="w-[72px]" title="The analyst consensus for earnings per share before the report">EPS est.</TH>
            <TH align="right" className="w-[76px]" title="How far reported earnings per share came in above or below the estimate, in percent">Surprise</TH>
            <TH align="right" title="The quarter's revenue as filed with the SEC">Revenue</TH>
            <TH align="right" title="The analyst consensus for revenue. Only the upcoming report carries one; past revenue estimates are on no source here">Revenue est.</TH>
          </THead>
          <tbody>
            {rows.map(r => {
              const beat = r.eps_actual != null && r.eps_estimate != null
                ? (r.eps_actual >= r.eps_estimate ? "text-gain" : "text-loss") : ""
              return (
                <tr key={r.date} title={r.upcoming ? "Scheduled — estimates are the analyst consensus" : undefined}>
                  <TD mono title={r.date_kind === "period_end" ? "This vendor dates reports by the quarter they cover; the report day itself is not on its record" : undefined}>
                    {r.date_kind === "period_end" && r.period_end
                      ? <span className="text-muted-foreground">{fiscalPeriodLabel(r.period_end, "quarterly", fyEnd)}</span>
                      : r.date}
                    {r.upcoming && <span className="ml-1.5 text-label font-medium uppercase tracking-caps text-accent-700">next</span>}
                  </TD>
                  <TD align="right" mono className={beat}>{eps(r.eps_actual)}</TD>
                  <TD align="right" mono className="text-muted-foreground">{eps(r.eps_estimate)}</TD>
                  <TD align="right" mono className={beat}>
                    {r.surprise_pct == null ? "—" : `${r.surprise_pct > 0 ? "+" : ""}${r.surprise_pct.toFixed(2)}%`}
                  </TD>
                  <TD align="right" mono className={beat}>{compact(r.revenue)}</TD>
                  <TD align="right" mono className="text-muted-foreground">{compact(r.revenue_estimate)}</TD>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}

/* ── Earnings insights — the consensus grid ─────────────────────────────── */

export function EarningsInsightsPanel({ symbol, span = 12 }: { symbol: string; span?: number }) {
  const { data, isPending, isError, error } = useEarningsInsights(symbol)
  const periods = data?.periods ?? []
  return (
    <Widget span={span} symbol={symbol} title="Earnings insights"
            subtitle="analyst consensus — a forecast, not the company's numbers"
           >
      {isPending ? (
        <Empty>loading…</Empty>
      ) : isError ? (
        <QueryFailure error={error}>the consensus is unavailable right now</QueryFailure>
      ) : !periods.length ? (
        <Empty>no analyst coverage upstream for {symbol}</Empty>
      ) : (
        // Eight columns cannot share a phone: below its natural width the
        // grid scrolls sideways inside the tile instead of overlapping.
        <div className="overflow-x-auto">
        <div className="min-w-[700px]">
        <Table>
          <THead>
            <TH className="w-[18%]" title="The fiscal period being forecast">Period</TH>
            <TH align="right" title="How many analysts' forecasts make up the consensus">Analysts</TH>
            <TH align="right" title="The average forecast for earnings per share">EPS avg</TH>
            <TH align="right" title="The lowest forecast for earnings per share">EPS low</TH>
            <TH align="right" title="The highest forecast for earnings per share">EPS high</TH>
            <TH align="right" title="The average revenue forecast">Rev avg</TH>
            <TH align="right" title="The lowest revenue forecast">Rev low</TH>
            <TH align="right" title="The highest revenue forecast">Rev high</TH>
          </THead>
          <tbody>
            {periods.map(p => (
              <TR key={p.period}>
                <TD className="font-semibold">{p.label}</TD>
                <TD align="right" mono>{p.eps?.analysts ?? p.revenue?.analysts ?? "—"}</TD>
                <TD align="right" mono className="font-semibold">
                  {p.eps?.avg != null ? p.eps.avg.toFixed(2) : "—"}
                </TD>
                <TD align="right" mono>{p.eps?.low != null ? p.eps.low.toFixed(2) : "—"}</TD>
                <TD align="right" mono>{p.eps?.high != null ? p.eps.high.toFixed(2) : "—"}</TD>
                <TD align="right" mono className="font-semibold">{compact(p.revenue?.avg)}</TD>
                <TD align="right" mono>{compact(p.revenue?.low)}</TD>
                <TD align="right" mono>{compact(p.revenue?.high)}</TD>
              </TR>
            ))}
          </tbody>
        </Table>
        </div>
        </div>
      )}
    </Widget>
  )
}
