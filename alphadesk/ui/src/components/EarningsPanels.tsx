import { useMemo, useState } from "react"
import type { MetricPeriod } from "@/lib/api"
import { QueryFailure } from "@/components/KeyPrompt"
import { fiscalYearEndMonth, periodLabel as fiscalPeriodLabel } from "@/lib/fiscal"
import { useEarningsInsights, useFundamentals, useQuote } from "@/lib/queries"
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
  // THOUSANDS WERE MISSING (2026-09-28, the reader, on Northann's chart).
  // The scale jumped from millions straight to two decimals, so 171,895 read
  // "171895.00" -- nine characters and a fraction in a 38px axis gutter, which
  // ran off the left of the viewBox and was clipped mid-number. It was also a
  // discontinuity in its own right: 999,999 printed in full while 1,000,000
  // printed as "1M".
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`
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
          {/* LEFT AXIS: MONEY, READ OFF THE SCALE ITSELF. These used to be
              maxVal and maxVal/2, which are only evenly spaced when the scale
              starts at zero — and it starts at minVal. Northann's loss is 16x
              its revenue (max 171,895 against min -2,833,275), so half of max
              sat 3.9px below max at 9.5px type and the two labels printed on
              top of each other. Taking the top, middle and bottom OF THE SCALE
              is spaced by construction, whatever the data does, and it is what
              the EPS panel below already did. */}
          {[maxVal, (maxVal + minVal) / 2, minVal].map((v, i) => (
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

/* ── Earnings per share — as FILED, no estimate line ────────────────────── */

const eps = (v: number | null) => (v == null ? "—" : v.toFixed(2))

/** DILUTED EPS THE COMPANY FILED, quarter by quarter (2026-09-28, the owner:
 * "removing all forecast or claims data from earnings tab and keeping only the
 * facts").
 *
 * This used to draw a hollow ring for the analyst estimate against a filled
 * dot for the actual, with a Beat/Missed verdict under it — three vendor
 * claims and a judgment built on them. The estimates were measured against a
 * licensed consensus and agreed on about half the rows. What replaced them is
 * the company's own diluted EPS out of SEC XBRL, which needs no key.
 *
 * THE COST IS COVERAGE, and it is real: XBRL is US-GAAP, so a foreign private
 * issuer filing under IFRS has none. Measured on thirteen companies that had
 * just reported, three were in that position. They get an empty panel that
 * says so, rather than a vendor's claim dressed as a filing.
 */
export function EpsPanel({ symbol }: { symbol: string }) {
  const { data, isPending } = useFundamentals(symbol, "quarterly")
  const { data: quote } = useQuote(symbol)
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)
  const [hover, setHover] = useState<number | null>(null)

  const points = useMemo(() => {
    const series = data?.series?.diluted_eps ?? []
    return series.slice(-8).map(p => ({
      t: p.t, v: p.v,
      label: fiscalPeriodLabel(p.t, "quarterly", fyEnd) ?? p.t.slice(5),
    }))
  }, [data, fyEnd])

  const body = () => {
    if (isPending) return <Empty>loading…</Empty>
    if (!points.length) {
      return <Empty>SEC EDGAR holds no filed earnings per share for {symbol}. That is usual for a
        foreign private issuer, which reports under IFRS and tags its filings differently.</Empty>
    }
    const vals = points.map(p => p.v)
    const hi = Math.max(...vals, 0)
    const lo = Math.min(...vals, 0)
    const span = hi - lo || 1
    const y = (v: number) => PLOT_B - ((v - lo) / span) * (PLOT_B - PLOT_T)
    const step = (PLOT_R + 32 - PLOT_L) / points.length
    const path = points.map((p, i) => `${i ? "L" : "M"}${PLOT_L + step * (i + 0.5)},${y(p.v)}`).join(" ")

    return (
      <div className="px-3 pb-2 pt-1">
        <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="block w-full" role="img"
             aria-label="Diluted earnings per share by quarter, as filed with the SEC">
          {[0.25, 0.5, 0.75].map(f => {
            const gy = PLOT_T + (PLOT_B - PLOT_T) * f
            return <line key={f} x1={PLOT_L} x2={PLOT_R + 32} y1={gy} y2={gy}
                         className="stroke-grid-line" strokeDasharray="3 3" strokeWidth="1" />
          })}
          {/* Read off the scale, so the labels are spaced whatever the data
              does — the fault that put two of them 3.9px apart next door. */}
          {[hi, (hi + lo) / 2, lo].map((v, i) => (
            <text key={i} x={PLOT_L - 6} y={y(v) + 3} textAnchor="end"
                  className="fill-n600" fontSize="9.5">{v.toFixed(2)}</text>
          ))}
          {/* The zero line is solid: profit and loss is the one division here
              that is a fact about the number rather than a reading of it. */}
          {lo < 0 && <line x1={PLOT_L} x2={PLOT_R + 32} y1={y(0)} y2={y(0)}
                           className="stroke-n400" strokeWidth="1" />}
          <path d={path} fill="none" className="stroke-foreground" strokeWidth="1.4" />
          {points.map((p, i) => {
            const cx = PLOT_L + step * (i + 0.5)
            const dim = hover != null && hover !== i
            return (
              <g key={p.t} opacity={dim ? 0.45 : 1}>
                <circle cx={cx} cy={y(p.v)} r="5.5" className={p.v >= 0 ? "fill-gain" : "fill-loss"} />
                <text x={cx} y={PLOT_B + 14} textAnchor="middle"
                      className={`fill-n600 ${hover === i ? "font-semibold" : ""}`}
                      fontSize="9.5">{p.label}</text>
              </g>
            )
          })}
          {points.map((p, i) => (
            <rect key={`h-${p.t}`} x={PLOT_L + step * i} y={PLOT_T} width={step} height={PLOT_B - PLOT_T + 16}
                  fill="transparent" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
          ))}
        </svg>
        {(() => {
          const at = hover ?? points.length - 1
          const p = points[at]
          // A year earlier is FOUR QUARTERS BACK in a filed series, which is
          // the only comparison here — and it is filed against filed, never
          // against anybody's expectation of it.
          const prior = at >= 4 ? points[at - 4] : null
          return (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption">
              <span className="font-semibold">{p.label}</span>
              <span className="num text-muted-foreground">quarter ended {p.t}</span>
              <span className="num">Diluted EPS <span className="font-semibold">{p.v.toFixed(2)}</span></span>
              {prior && (
                <span className="num text-muted-foreground">
                  a year earlier <span className="font-semibold">{prior.v.toFixed(2)}</span>
                </span>
              )}
            </div>
          )
        })()}
      </div>
    )
  }

  return (
    <Widget span={6} symbol={symbol} title="Earnings per share"
            subtitle="diluted, as filed with the SEC">
      {body()}
    </Widget>
  )
}

/* ── Earnings history — every quarter the company has filed ─────────────── */

/** THE FILED RECORD AS A TABLE. The estimate, actual and surprise columns are
 * gone with the vendor record behind them; surprise has no factual form at
 * all, because it is defined against an estimate. What is left is what the
 * company filed each quarter, and a year-over-year change computed from two
 * filed figures.
 *
 * It shares its request with the two charts above — one XBRL read serves all
 * three, because they take the same query key. */
export function EarningsHistoryPanel({ symbol, span = 6, scroll }: { symbol: string; span?: number; scroll?: number | string }) {
  const { data, isPending } = useFundamentals(symbol, "quarterly")
  const { data: quote } = useQuote(symbol)
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)

  const rows = useMemo(() => {
    const rev = data?.series?.revenue ?? []
    const net = data?.series?.net_income ?? []
    const eps = data?.series?.diluted_eps ?? []
    const at = (arr: { t: string; v: number }[], t: string) => arr.find(x => x.t === t)?.v ?? null
    const ends = [...new Set([...rev, ...net, ...eps].map(p => p.t))].sort().reverse().slice(0, 12)
    return ends.map(t => ({
      t,
      label: fiscalPeriodLabel(t, "quarterly", fyEnd) ?? t,
      revenue: at(rev, t), net: at(net, t), eps: at(eps, t),
    }))
  }, [data, fyEnd])

  return (
    <Widget span={span} symbol={symbol} title="Earnings history"
            subtitle="every quarter as filed with the SEC" scroll={scroll ?? 420}>
      {isPending ? <Empty>loading…</Empty>
        : rows.length === 0 ? (
          <Empty>SEC EDGAR holds no filed quarters for {symbol}. That is usual for a foreign
            private issuer, which reports under IFRS and tags its filings differently.</Empty>
        ) : (
        <Table>
          <THead>
            <TH className="w-[104px]" title="The fiscal quarter, by the period end the company filed">Quarter</TH>
            <TH align="right" className="w-[92px]" title="Revenue for the quarter, as filed">Revenue</TH>
            <TH align="right" className="w-[92px]" title="Net income for the quarter, as filed. Green above zero, red below — which is a fact about the figure, not a judgment on it">Net income</TH>
            <TH align="right" className="w-[80px]" title="Diluted earnings per share, as filed">Diluted EPS</TH>
            <TH align="right" title="Net margin: net income over revenue. Derived from two filed figures, and shown only where revenue is positive in the quarter">Net margin</TH>
          </THead>
          <tbody>
            {rows.map(r => {
              const margin = r.revenue && r.revenue > 0 && r.net != null ? (r.net / r.revenue) * 100 : null
              return (
                <tr key={r.t}>
                  <TD mono title={`Quarter ended ${r.t}`}>{r.label}</TD>
                  <TD align="right" mono>{compact(r.revenue)}</TD>
                  <TD align="right" mono className={r.net == null ? "" : r.net >= 0 ? "text-gain" : "text-loss"}>{compact(r.net)}</TD>
                  <TD align="right" mono className={r.eps == null ? "" : r.eps >= 0 ? "text-gain" : "text-loss"}>{eps(r.eps)}</TD>
                  <TD align="right" mono className="text-muted-foreground">{margin == null ? "—" : `${margin.toFixed(1)}%`}</TD>
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
