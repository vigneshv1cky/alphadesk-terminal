import { useLayoutEffect, useMemo, useRef, useState } from "react"
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

/** A DOLLAR SIGN ONLY WHERE THE COMPANY FILED DOLLARS (2026-09-29). TSMC
 * reports NT$2.89 trillion and Novo Nordisk DKK 309 billion; a "$" over either
 * misstates it by an order of magnitude. Non-USD figures carry no symbol and
 * the column heading names the currency once. */
const compact = (n: number | null | undefined, currency = "USD"): string => {
  if (n == null) return "—"
  // THE SIGN GOES OUTSIDE THE SYMBOL. Prefixing "$" to a number that already
  // carries its own minus prints "$-4M" for a loss (2026-09-29, caught on
  // Graphjet's history the moment the symbol was added).
  const c = currency === "USD" ? "$" : ""
  const a = Math.abs(n)
  const g = n < 0 ? "-" : ""
  if (a >= 1e12) return `${g}${c}${(a / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${g}${c}${(a / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${g}${c}${(a / 1e6).toFixed(0)}M`
  // THOUSANDS WERE MISSING (2026-09-28, the reader, on Northann's chart).
  // The scale jumped from millions straight to two decimals, so 171,895 read
  // "171895.00" -- nine characters and a fraction in a 38px axis gutter, which
  // ran off the left of the viewBox and was clipped mid-number. It was also a
  // discontinuity in its own right: 999,999 printed in full while 1,000,000
  // printed as "1M".
  if (a >= 1e3) return `${g}${c}${(a / 1e3).toFixed(1)}K`
  return `${g}${c}${a.toFixed(2)}`
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
const PLOT_L = 44
const PLOT_R = 516
const PLOT_T = 14
/** The band under the plot that the period labels sit in. */
const LABEL_BAND = 26
/** The drawing when nothing has been measured yet — the fixed box these
 * charts used to have, so the first paint is a chart rather than a sliver. */
const VB_H_SEED = 176

/** A PLOT AS TALL AS THE TILE IT IS IN (2026-09-29, the owner: "there is some
 * waste space, use the space properly").
 *
 * These charts drew into a fixed 560x176 box at full width, so their height
 * followed their WIDTH and nothing else: in an 803px-wide tile the drawing was
 * about 252px and the tile body is 476, leaving a third of the panel empty.
 * It went unnoticed while tiles were content-sized, because the tile simply
 * hugged the drawing — this is the cost of fixed tile heights arriving, and
 * the honest answer is for the drawing to use what it is given.
 *
 * The viewBox keeps its WIDTH of 560 and takes its height from the container's
 * aspect, so one unit is the same number of pixels in both directions: the
 * plot grows and NOTHING IS DISTORTED — labels and line weights stay exactly
 * the size they were, because the scale is set by the width, which has not
 * changed. Stretching the old box with `preserveAspectRatio: none` would have
 * filled the same space and squashed every glyph.
 *
 * It cannot loop the way the chart tile's measurement used to: the tile's
 * height is a constant now (lib/tileHeight), so the box this reads is settled
 * before it is read and nothing the SVG draws can change it. */
function usePlotBox() {
  const [vbH, setVbH] = useState(VB_H_SEED)
  const node = useRef<HTMLDivElement | null>(null)
  const obs = useRef<ResizeObserver | null>(null)
  // A CALLBACK REF, NOT A PLAIN ONE WITH AN EMPTY EFFECT. The plot only
  // renders once the figures arrive, so on the first layout there is no
  // element to observe — an effect that runs once would find null, return,
  // and never run again, leaving the drawing at its seed height for good.
  // That is exactly what happened: the box filled the tile and the viewBox
  // stayed 560x176, so the drawing was letterboxed inside it. A callback ref
  // fires when the node appears, however late that is.
  const ref = (el: HTMLDivElement | null) => {
    if (node.current === el) return
    obs.current?.disconnect()
    node.current = el
    if (!el) { obs.current = null; return }
    const measure = () => {
      const { width, height } = el.getBoundingClientRect()
      if (width < 1 || height < 1) return
      // A floor, so a panel squeezed into a very short tile still draws a
      // readable plot rather than collapsing to its labels.
      const next = Math.max(120, Math.round((VB_W * height) / width))
      setVbH(prev => (Math.abs(prev - next) < 2 ? prev : next))
    }
    measure()
    obs.current = new ResizeObserver(measure)
    obs.current.observe(el)
  }
  useLayoutEffect(() => () => obs.current?.disconnect(), [])
  return { ref, vbH, plotB: vbH - LABEL_BAND }
}

export function RevenueEarningsPanel({ symbol }: { symbol: string }) {
  const { ref: plotRef, vbH, plotB: PLOT_B } = usePlotBox()
  const [period, setPeriod] = useState<MetricPeriod>("quarterly")
  const { data, isPending } = useFundamentals(symbol, period)
  // The axis and the readout are money, so they follow the filer's own
  // currency — TSMC's bars are trillions of NT$, not of dollars.
  const cur = data?.currency || "USD"
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
      // THE PLOT TAKES THE ROOM, THE READOUT TAKES WHAT IT NEEDS: a column,
      // with the drawing as the one part that grows. Before this the whole
      // panel sat at the top of the tile and the rest was air.
      <div className="flex h-full flex-col px-3 pb-2 pt-1">
        <div ref={plotRef} className="min-h-0 flex-1">
        <svg viewBox={`0 0 ${VB_W} ${vbH}`} className="block h-full w-full" role="img"
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
                  className="fill-n600" fontSize="9.5">{compact(v, cur)}</text>
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
        </div>
        {/* the readout: the hovered period, else the latest — its label,
            its end date, and the three figures the bars only suggest */}
        {(() => {
          const g = groups[hover ?? groups.length - 1]
          return (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption">
              <span className="font-semibold">{fiscalPeriodLabel(g.t, period, fyEnd)}</span>
              <span className="num text-muted-foreground">{period === "annual" ? "year" : "quarter"} ended {g.t.slice(0, 10)}</span>
              <span className="num">Revenue <span className="font-semibold">{compact(g.rev, cur)}</span></span>
              <span className="num">Net income <span className="font-semibold">{g.net == null ? "—" : compact(g.net, cur)}</span></span>
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
  const { ref: plotRef, vbH, plotB: PLOT_B } = usePlotBox()
  const { data, isPending } = useFundamentals(symbol, "quarterly")
  const { data: quote } = useQuote(symbol)
  const fyEnd = fiscalYearEndMonth(quote?.fiscal_year_end)
  const [hover, setHover] = useState<number | null>(null)

  // THE SERIES MAY BE ANNUAL. A foreign private issuer files a 20-F and no
  // quarters, so the endpoint answers with its yearly series — and labelling
  // those "Q4 FY21" would call a full year its fourth quarter. The payload
  // says which grain it gave; the labels follow it.
  const grain: MetricPeriod = data?.period === "annual" ? "annual"
    : data?.period === "half" ? "half" : "quarterly"
  // Earnings per SHARE are per share of the reporting currency: Novo Nordisk's
  // are kroner a share. The subtitle names it rather than leaving a bare
  // number to be read as dollars.
  const epsCur = data?.currency || "USD"
  const points = useMemo(() => {
    const series = data?.series?.diluted_eps ?? []
    return series.slice(-8).map(p => ({
      t: p.t, v: p.v,
      label: fiscalPeriodLabel(p.t, grain, fyEnd) ?? p.t.slice(0, 4),
    }))
  }, [data, fyEnd, grain])

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
      <div className="flex h-full flex-col px-3 pb-2 pt-1">
        <div ref={plotRef} className="min-h-0 flex-1">
        <svg viewBox={`0 0 ${VB_W} ${vbH}`} className="block h-full w-full" role="img"
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
        </div>
        {(() => {
          const at = hover ?? points.length - 1
          const p = points[at]
          // A year earlier is FOUR QUARTERS BACK in a filed series, which is
          // the only comparison here — and it is filed against filed, never
          // against anybody's expectation of it.
          const back = grain === "annual" ? 1 : 4
          const prior = at >= back ? points[at - back] : null
          return (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption">
              <span className="font-semibold">{p.label}</span>
              <span className="num text-muted-foreground">{grain === "annual" ? "year" : grain === "half" ? "half-year" : "quarter"} ended {p.t}</span>
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
            subtitle={`diluted${grain === "annual" ? ", by year" : grain === "half" ? ", by half-year" : ""}, as filed with the SEC${
              epsCur === "USD" ? "" : ` · ${epsCur}`}`}>
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
  // An annual filer's rows are YEARS. Calling the column "Quarter" over them
  // would misstate every period in the table.
  const grain: MetricPeriod = data?.period === "annual" ? "annual"
    : data?.period === "half" ? "half" : "quarterly"
  const cur = data?.currency || "USD"
  const money = (v: number | null) => compact(v, cur)
  const unit = cur === "USD" ? "" : ` (${cur})`

  // A COLUMN THE COMPANY NEVER REPORTS IS DROPPED, NOT DASHED (2026-09-29,
  // the reader: "why grml revenue is blank here"). Greenland Mines is an
  // exploration-stage miner and tags no revenue concept at all — the only
  // revenue-shaped thing in its whole filing is a tax liability. So the dash
  // was TRUE, and it read exactly like "we could not find it", which is the
  // one thing it did not mean.
  // This is the convention the movers tables already set: currencies and
  // yields drop the Liquidity column rather than render it empty, because an
  // empty column reads as missing data. A dropped column is stated below the
  // table so its absence is a fact rather than an oversight.
  const has = (k: string) => ((data?.series?.[k] ?? []).length > 0)
  const showRevenue = has("revenue")
  const showNet = has("net_income")
  const showEps = has("diluted_eps")
  const absent = [!showRevenue && "revenue", !showNet && "net income",
                  !showEps && "earnings per share"].filter(Boolean) as string[]

  const rows = useMemo(() => {
    const rev = data?.series?.revenue ?? []
    const net = data?.series?.net_income ?? []
    const eps = data?.series?.diluted_eps ?? []
    const at = (arr: { t: string; v: number }[], t: string) => arr.find(x => x.t === t)?.v ?? null
    const ends = [...new Set([...rev, ...net, ...eps].map(p => p.t))].sort().reverse().slice(0, 12)
    return ends.map(t => ({
      t,
      label: fiscalPeriodLabel(t, grain, fyEnd) ?? t,
      revenue: at(rev, t), net: at(net, t), eps: at(eps, t),
    }))
  }, [data, fyEnd, grain])

  return (
    <Widget span={span} symbol={symbol} title="Earnings history"
            subtitle={`every ${grain === "annual" ? "year" : grain === "half" ? "half-year" : "quarter"} as filed with the SEC`} scroll={scroll ?? 420}>
      {isPending ? <Empty>loading…</Empty>
        : rows.length === 0 ? (
          <Empty>SEC EDGAR holds no filed periods for {symbol}. That is usual for a foreign
            private issuer, which reports under IFRS and tags its filings differently.</Empty>
        ) : (
        <Table>
          <THead>
            <TH className="w-[104px]" title="The fiscal period, by the period end the company filed">{grain === "annual" ? "Year" : grain === "half" ? "Half-year" : "Quarter"}</TH>
            {showRevenue && <TH align="right" className="w-[92px]" title="Revenue for the period, as filed">Revenue{unit}</TH>}
            {showNet && <TH align="right" className="w-[92px]" title="Net income for the period, as filed. Green above zero, red below — which is a fact about the figure, not a judgment on it">Net income{unit}</TH>}
            {showEps && <TH align="right" className="w-[80px]" title="Diluted earnings per share, as filed">Diluted EPS</TH>}
            {showRevenue && showNet && <TH align="right" title="Net margin: net income over revenue. DERIVED from two filed figures, not a figure the company filed, and shown only where revenue is positive in the period">Net margin</TH>}
          </THead>
          <tbody>
            {rows.map(r => {
              const margin = r.revenue && r.revenue > 0 && r.net != null ? (r.net / r.revenue) * 100 : null
              return (
                <tr key={r.t}>
                  <TD mono title={`${grain === "annual" ? "Year" : grain === "half" ? "Half-year" : "Quarter"} ended ${r.t}`}>{r.label}</TD>
                  {showRevenue && <TD align="right" mono>{money(r.revenue)}</TD>}
                  {showNet && <TD align="right" mono className={r.net == null ? "" : r.net >= 0 ? "text-gain" : "text-loss"}>{money(r.net)}</TD>}
                  {showEps && <TD align="right" mono className={r.eps == null ? "" : r.eps >= 0 ? "text-gain" : "text-loss"}>{eps(r.eps)}</TD>}
                  {showRevenue && showNet && <TD align="right" mono className="text-muted-foreground">{margin == null ? "—" : `${margin.toFixed(1)}%`}</TD>}
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
      {/* THE ABSENCE IS STATED, or a dropped column is indistinguishable from
          one nobody thought to add. An exploration-stage miner reporting no
          revenue is a fact about the company, and this is where it is said. */}
      {!isPending && rows.length > 0 && absent.length > 0 && (
        <p className="px-3 py-2 text-caption text-muted-foreground">
          {symbol} files no {absent.join(", ").replace(/, ([^,]*)$/, " or $1")} with
          the SEC, so {absent.length === 1 ? "that column is" : "those columns are"} not
          shown. Pre-revenue and exploration-stage companies commonly report none.
        </p>
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
