import React, { useEffect, useMemo, useRef, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { useQueries, useQuery } from "@tanstack/react-query"
import { on, type ChartBar, type ChartRange, type CompareRow, type Peers, type Quote } from "@/lib/api"
import { keys, useQuotes } from "@/lib/queries"
import { compact } from "@/components/Treemap"
import { Empty, fieldCls, Table, TD, TH, THead, Widget, btnCls } from "@/components/terminal"

/** The board's chips against each other — theirs' "Comparison Analysis"
 * board, on our feeds (2026-09-12).
 *
 *   Relative performance — every chip's daily closes rebased to zero at the
 *   start of a range, one line each, so the question "which one ran" is
 *   read off the right edge.
 *   Price performance — the returns table: today, one week, one month,
 *   three months, year to date, one year, all from the same daily series
 *   and the live quote.
 *   Comparison — valuation and quality side by side: multiples, beta,
 *   yield, targets, the revenue trend and the beat record.
 *
 * Nothing is ranked. Rows keep the strip's order, active first. */

const dash = "—"
const COLORS = ["var(--accent-700)", "var(--info)", "var(--warn)", "var(--n500)", "var(--gain)", "var(--loss)"]
const RANGES: ChartRange[] = ["1M", "3M", "6M", "YTD", "1Y", "5Y"]

const pct = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? dash : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`
const tone = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "text-muted-foreground" : v > 0 ? "text-gain" : v < 0 ? "text-loss" : ""

/** Daily series for every chip, one query each, sharing the chart's own
 * cache keys so a Markets tile and this page never fetch the same thing
 * twice. */
function useDailySeries(symbols: string[], range: ChartRange) {
  return useQueries({
    queries: symbols.map(sym => ({
      queryKey: keys.chart(sym, range, "1d"),
      queryFn: ({ signal }) => on(signal).chartRange(sym, range, "1d"),
      enabled: !!sym,
      staleTime: 300_000,
    })),
  })
}

type Series = { symbol: string; bars: ChartBar[] }

/** Closes keyed by calendar day, so two symbols align on dates rather than
 * on array positions (a coin trades every day; a stock does not). */
function byDay(bars: ChartBar[]): Map<string, number> {
  const m = new Map<string, number>()
  for (const b of bars) m.set(b.t.slice(0, 10), b.c)
  return m
}

/** Where the x axis gets a tick: month starts, with the year at a year
 * change; on a one-month range, each Monday with its date. */
function timeTicks(days: string[], range: ChartRange): { i: number; label: string }[] {
  const out: { i: number; label: string }[] = []
  const monthly = range !== "1M"
  let prev = ""
  for (let i = 0; i < days.length; i++) {
    const d = days[i]
    if (monthly) {
      const ym = d.slice(0, 7)
      if (ym === prev) continue
      const first = prev === ""
      prev = ym
      if (first) continue
      const dt = new Date(`${d}T12:00:00Z`)
      const yearly = range === "5Y"
      if (yearly && dt.getUTCMonth() % 3 !== 0) continue
      const label = dt.getUTCMonth() === 0 || (yearly && out.length === 0)
        ? String(dt.getUTCFullYear())
        : dt.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })
      out.push({ i, label })
    } else {
      const dt = new Date(`${d}T12:00:00Z`)
      if (dt.getUTCDay() !== 1) continue
      out.push({ i, label: dt.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) })
    }
  }
  return out
}

export function RelativePerformancePanel({ symbols, span = 12, title = "Relative performance", toolbar }: {
  symbols: string[]; span?: number
  /** The Sectors page names its own and adds a picker of the lines drawn. */
  title?: string
  toolbar?: React.ReactNode
}) {
  const [range, setRange] = useState<ChartRange>("1Y")
  const results = useDailySeries(symbols, range)
  const series: Series[] = symbols.map((s, i) => ({ symbol: s, bars: results[i]?.data?.bars ?? [] }))
  const loading = results.some(r => r.isPending)
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(1000)
  const [hover, setHover] = useState<number | null>(null)
  // The SVG is drawn at the panel's real pixel width, so the text is never
  // stretched the way a scaled viewBox would stretch it.
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(Math.max(320, Math.round(el.clientWidth))))
    ro.observe(el)
    setWidth(Math.max(320, Math.round(el.clientWidth)))
    return () => ro.disconnect()
  }, [])

  // Rebase each line to 0% at the first day EVERY symbol has, so a line
  // that lists later does not start at zero on a different date.
  const drawn = useMemo(() => {
    const maps = series.map(s => byDay(s.bars))
    const days = [...new Set(series.flatMap(s => s.bars.map(b => b.t.slice(0, 10))))].sort()
    const common = days.filter(d => maps.every(m => m.has(d)))
    if (common.length < 2) return null
    const start = common[0]
    const lines = series.map((s, i) => {
      const base = maps[i].get(start)!
      const pts = common.map(d => (maps[i].get(d)! / base - 1) * 100)
      return { symbol: s.symbol, color: COLORS[i % COLORS.length], pts, last: pts[pts.length - 1] }
    })
    const all = lines.flatMap(l => l.pts)
    return { days: common, lines, min: Math.min(0, ...all), max: Math.max(0, ...all) }
  }, [series.map(s => s.bars).join()])   // eslint-disable-line react-hooks/exhaustive-deps

  const W = width, H = 320, PAD = { l: 10, r: 64, t: 12, b: 28 }
  const n = drawn?.days.length ?? 0
  const x = (i: number) => PAD.l + (i / Math.max(1, n - 1)) * (W - PAD.l - PAD.r)
  const y = (v: number) => drawn
    ? PAD.t + (1 - (v - drawn.min) / Math.max(1e-9, drawn.max - drawn.min)) * (H - PAD.t - PAD.b)
    : 0
  const yTicks = drawn ? niceTicks(drawn.min, drawn.max, 6) : []
  const xTicks = drawn ? timeTicks(drawn.days, range) : []
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!drawn) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left
    const i = Math.round(((px - PAD.l) / Math.max(1, W - PAD.l - PAD.r)) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const at = hover ?? (n ? n - 1 : 0)

  return (
    <Widget span={span} title={title} subtitle={`rebased to 0% at the start of the range · daily closes`}
            toolbar={toolbar}
            actions={
              <div className="flex items-center gap-0.5">
                {RANGES.map(r => (
                  <button key={r} type="button" onClick={() => setRange(r)}
                          className={btnCls({ variant: "ghost", active: r === range }, "num px-1.5")}>
                    {r}
                  </button>
                ))}
              </div>
            }>
      <div ref={box} className="px-2 pb-1 pt-2">
      {symbols.length < 2 ? <Empty>Add more chips to the board to compare {symbols[0] ?? "the active symbol"} against them.</Empty>
        : loading && !drawn ? <Empty>loading…</Empty>
        : !drawn ? <Empty>no overlapping history for these symbols on this range</Empty> : (
        <>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block max-w-full" aria-label="Relative performance"
               onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
            {/* y axis: gridlines and the percent at each, the zero line firmer */}
            {yTicks.map(t => (
              <g key={t}>
                <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={t === 0 ? 1.2 : 0.6} strokeDasharray={t === 0 ? undefined : "3 4"} />
                <text x={W - PAD.r + 8} y={y(t) + 4} fontSize="11" fill="var(--muted-foreground)" className="num">{pct(t, Math.abs(t) < 10 && t !== Math.round(t) ? 1 : 0)}</text>
              </g>
            ))}
            {/* x axis: a tick at each month (each Monday on 1M), the year where it turns */}
            <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke="var(--border)" strokeWidth={1} />
            {xTicks.map(t => (
              <g key={t.i}>
                <line x1={x(t.i)} x2={x(t.i)} y1={H - PAD.b} y2={H - PAD.b + 4} stroke="var(--border)" />
                <text x={x(t.i)} y={H - PAD.b + 16} fontSize="11" fill="var(--muted-foreground)" textAnchor="middle" className="num">{t.label}</text>
              </g>
            ))}
            {drawn.lines.map(l => (
              <path key={l.symbol} fill="none" stroke={l.color} strokeWidth={1.6}
                    d={l.pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
            ))}
            {/* the crosshair: the day under the cursor and each line's value there */}
            {hover != null && (
              <g>
                <line x1={x(at)} x2={x(at)} y1={PAD.t} y2={H - PAD.b} stroke="var(--muted-foreground)" strokeWidth={0.8} strokeDasharray="2 3" />
                {drawn.lines.map(l => <circle key={l.symbol} cx={x(at)} cy={y(l.pts[at])} r={3} fill={l.color} />)}
                <rect x={Math.min(W - PAD.r - 76, Math.max(PAD.l, x(at) - 38))} y={H - PAD.b + 5} width={76} height={16} rx={2} fill="var(--panel)" stroke="var(--border)" />
                <text x={Math.min(W - PAD.r - 38, Math.max(PAD.l + 38, x(at)))} y={H - PAD.b + 16.5} fontSize="11" fill="var(--foreground)" textAnchor="middle" className="num">{drawn.days[at]}</text>
              </g>
            )}
          </svg>
          <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 pt-1 text-caption">
            <span className="num text-muted-foreground">{hover != null ? drawn.days[at] : `${drawn.days[0]} → ${drawn.days[n - 1]}`}</span>
            {drawn.lines.map(l => (
              <span key={l.symbol} className="inline-flex items-center gap-1.5">
                <span className="inline-block h-[3px] w-[14px] rounded" style={{ background: l.color }} />
                <span className="font-semibold">{l.symbol}</span>
                <span className={`num ${tone(l.pts[at])}`}>{pct(l.pts[at])}</span>
              </span>
            ))}
          </div>
        </>
      )}
      </div>
    </Widget>
  )
}

function niceTicks(min: number, max: number, n: number): number[] {
  if (!(max > min)) return [0]
  const raw = (max - min) / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000)
  return out
}

/** The close on or before a day that is `daysBack` calendar days ago. */
function closeBefore(map: Map<string, number>, days: string[], daysBack: number): number | null {
  if (!days.length) return null
  const last = new Date(`${days[days.length - 1]}T12:00:00Z`)
  const target = new Date(last); target.setUTCDate(target.getUTCDate() - daysBack)
  const key = target.toISOString().slice(0, 10)
  for (let i = days.length - 1; i >= 0; i--) if (days[i] <= key) return map.get(days[i]) ?? null
  return null
}

function ytdBase(map: Map<string, number>, days: string[]): number | null {
  if (!days.length) return null
  const year = days[days.length - 1].slice(0, 4)
  const prior = days.filter(d => d < `${year}-01-01`)
  if (prior.length) return map.get(prior[prior.length - 1]) ?? null
  const first = days.find(d => d >= `${year}-01-01`)
  return first ? map.get(first) ?? null : null
}

export function PricePerformancePanel({ symbols, span = 12, minSymbols = 2, quoteFill }: {
  symbols: string[]; span?: number
  /** Compare needs two to compare; the Analysis page shows one stock's own returns. */
  minSymbols?: number
  /** The quote fill the page's own table already asks for. Passing the same
   * one makes this panel read that request instead of issuing a second one
   * for the same basket — the Portfolio page fetched it twice (2026-09-16). */
  quoteFill?: string
}) {
  const results = useDailySeries(symbols, "1Y")
  const { data: quotes } = useQuotes(symbols, quoteFill)
  const qmap = quotes?.quotes ?? {}
  const rows = symbols.map((sym, i) => {
    const bars = results[i]?.data?.bars ?? []
    const map = byDay(bars)
    const days = [...map.keys()].sort()
    const last = days.length ? map.get(days[days.length - 1])! : null
    const ret = (base: number | null) => (last != null && base != null && base !== 0 ? (last / base - 1) * 100 : null)
    const q: Quote | null = qmap[sym] ?? null
    return {
      symbol: sym, last: q?.price ?? last,
      d1: q?.change_pct ?? null,
      w1: ret(closeBefore(map, days, 7)), m1: ret(closeBefore(map, days, 30)), m3: ret(closeBefore(map, days, 91)),
      ytd: ret(ytdBase(map, days)), y1: ret(days.length ? map.get(days[0])! : null),
      // The quote's 52-week range when the vendor sends one; otherwise the
      // high and low of the year of daily bars this panel already holds
      // (Alpaca's quote carries none, which left the column blank).
      hi52: q?.week52_high ?? (bars.length ? Math.max(...bars.map(b => b.h ?? b.c)) : null),
      lo52: q?.week52_low ?? (bars.length ? Math.min(...bars.map(b => b.l ?? b.c)) : null),
    }
  })
  return (
    <Widget span={span} title="Price performance" subtitle="returns over the trailing periods · the live quote for today">
      {symbols.length < minSymbols ? <Empty>Add more chips to the board to compare.</Empty> : (
        <div className="overflow-x-auto"><div className="min-w-[640px]">
        <Table>
          <THead>
            <TH title="A symbol on the board">Symbol</TH>
            <TH align="right" title="The live quote's price, or the latest daily close when no quote answers">Last</TH>
            <TH align="right" title="Change since the previous session's close, from the live quote">1D</TH>
            <TH align="right" title="Return from the last close at least a week before the latest close">1W</TH>
            <TH align="right" title="Return from the last close at least 30 days before the latest close">1M</TH>
            <TH align="right" title="Return from the last close at least 91 days before the latest close">3M</TH>
            <TH align="right" title="Return since the last close of the previous year">YTD</TH>
            <TH align="right" title="Return from the first close in the past year of daily bars">1Y</TH>
            <TH align="right" title="Where the last price sits between the 52-week low and high">52w pos.</TH>
          </THead>
          <tbody>
            {rows.map(r => {
              const pos = r.last != null && r.hi52 != null && r.lo52 != null && r.hi52 > r.lo52
                ? ((r.last - r.lo52) / (r.hi52 - r.lo52)) * 100 : null
              return (
                <tr key={r.symbol}>
                  <TD className="font-semibold">{r.symbol}</TD>
                  <TD align="right" mono>{r.last == null ? dash : r.last.toFixed(2)}</TD>
                  {[r.d1, r.w1, r.m1, r.m3, r.ytd, r.y1].map((v, i) => (
                    <TD key={i} align="right" mono className={tone(v)}>{pct(v)}</TD>
                  ))}
                  <TD align="right" mono className="text-muted-foreground">{pos == null ? dash : `${pos.toFixed(0)}%`}</TD>
                </tr>
              )
            })}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}

/** The metric groups theirs offers from a dropdown, on the fields the
 * company record carries. `fmt` names the drawing: a plain ratio, a
 * fraction shown as a percent, a dollar amount, a count. */
type Fmt = "ratio" | "pct" | "pctraw" | "money" | "count"
type Col = { key: keyof CompareRow; label: string; title?: string; fmt: Fmt; d?: number }
const GROUPS: { id: string; label: string; cols: Col[] }[] = [
  { id: "valuation", label: "Valuation multiples", cols: [
    { key: "pe", label: "P/E", title: "Price to earnings: the share price over earnings per share for the last twelve months", fmt: "ratio" },
    { key: "forward_pe", label: "Fwd P/E", title: "Forward price to earnings: the share price over the analyst consensus for earnings per share ahead", fmt: "ratio" },
    { key: "peg", label: "PEG", title: "The P/E ratio divided by the expected annual earnings growth rate, in percent", fmt: "ratio", d: 2 },
    { key: "ps", label: "P/S", title: "Price to sales: market capitalisation over revenue for the last twelve months", fmt: "ratio" },
    { key: "pb", label: "P/B", title: "Price to book: the share price over book value (assets minus liabilities) per share", fmt: "ratio" },
    { key: "ev_sales", label: "EV/S", title: "Enterprise value (market capitalisation plus debt minus cash) over revenue", fmt: "ratio" },
    { key: "ev_ebitda", label: "EV/EBITDA", title: "Enterprise value (market capitalisation plus debt minus cash) over EBITDA, earnings before interest, taxes, depreciation and amortisation", fmt: "ratio" },
    { key: "dividend_yield", label: "Div. yield", title: "Dividends paid over the last twelve months as a percent of the share price", fmt: "pctraw", d: 2 },
  ] },
  { id: "profitability", label: "Profitability", cols: [
    { key: "gross_margin", label: "Gross", title: "Gross margin: revenue minus the cost of goods sold, as a share of revenue", fmt: "pct" },
    { key: "operating_margin", label: "Operating", title: "Operating margin: operating income as a share of revenue", fmt: "pct" },
    { key: "ebitda_margin", label: "EBITDA", title: "EBITDA margin: earnings before interest, taxes, depreciation and amortisation, as a share of revenue", fmt: "pct" },
    { key: "net_margin", label: "Net", title: "Net margin: net income as a share of revenue", fmt: "pct" },
    { key: "roe", label: "ROE", title: "Return on equity: net income over shareholders' equity", fmt: "pct" },
    { key: "roa", label: "ROA", title: "Return on assets: net income over total assets", fmt: "pct" },
    { key: "payout_ratio", label: "Payout", title: "Payout ratio: the share of earnings paid out as dividends", fmt: "pct" },
  ] },
  { id: "growth", label: "Growth", cols: [
    { key: "revenue_growth", label: "Revenue", title: "Revenue growth, latest quarter year on year", fmt: "pct" },
    { key: "earnings_growth", label: "Earnings", title: "Earnings growth, year on year", fmt: "pct" },
    { key: "earnings_q_growth", label: "Earnings QoQ", title: "Earnings growth, latest quarter", fmt: "pct" },
    { key: "revenue", label: "Revenue TTM", title: "Trailing twelve-month revenue", fmt: "money" },
    { key: "ebitda", label: "EBITDA", title: "Trailing twelve-month EBITDA", fmt: "money" },
    { key: "eps", label: "EPS", title: "Earnings per share over the last twelve months", fmt: "ratio", d: 2 },
    { key: "forward_eps", label: "Fwd EPS", title: "Consensus EPS, next twelve months", fmt: "ratio", d: 2 },
  ] },
  { id: "balance", label: "Balance sheet", cols: [
    { key: "current_ratio", label: "Current", title: "Current ratio: current assets over current liabilities. Below 1, short-term debts exceed short-term assets", fmt: "ratio", d: 2 },
    { key: "quick_ratio", label: "Quick", title: "Quick ratio: cash, marketable securities and receivables over current liabilities, leaving out inventory", fmt: "ratio", d: 2 },
    { key: "debt_to_equity", label: "Debt/equity", title: "Total debt over equity, percent", fmt: "ratio" },
    { key: "total_cash", label: "Cash", title: "Cash and short-term investments on the latest balance sheet", fmt: "money" },
    { key: "total_debt", label: "Debt", title: "Total debt on the latest balance sheet", fmt: "money" },
    { key: "operating_cash_flow", label: "Op. cash flow", title: "Cash generated by the business's operations, trailing", fmt: "money" },
    { key: "free_cash_flow", label: "Free cash flow", title: "Operating cash flow minus capital expenditure, trailing", fmt: "money" },
  ] },
  { id: "trading", label: "Trading", cols: [
    { key: "beta", label: "Beta", title: "How much the stock has moved with the market: 1 moves with it, above 1 swings more, below 1 less", fmt: "ratio", d: 2 },
    { key: "short_pct_float", label: "Short % float", title: "Shares short as a share of the float", fmt: "pct" },
    { key: "short_ratio", label: "Days to cover", title: "Shares short over average daily volume", fmt: "ratio" },
    { key: "avg_volume", label: "Avg volume", title: "Average shares traded a day", fmt: "count" },
    { key: "employees", label: "Employees", title: "Full-time employees, as the company reports", fmt: "count" },
  ] },
]

function cell(v: number | string | null | undefined, c: Col): string {
  if (v == null || typeof v !== "number" || !Number.isFinite(v)) return dash
  switch (c.fmt) {
    case "pct": return `${(v * 100).toFixed(c.d ?? 1)}%`
    case "pctraw": return `${v.toFixed(c.d ?? 2)}%`          // already a percent (Yahoo's yield: 0.33 is 0.33%)
    case "money": return `$${compact(v)}`
    case "count": return compact(v)
    default: return v.toFixed(c.d ?? 1)
  }
}

/** Theirs' Comparison Analysis: the chips with the active one's peers
 * beside them when a peer source is keyed, and a metric group picked from
 * a menu. The peers are on this page only — they are not put on the
 * board, and the board's chips are never removed here. */
export function ComparisonMetricsPanel({ symbols, active, peers, showPeers, onTogglePeers, span = 12 }: {
  symbols: string[]; active: string; peers: Peers | undefined; showPeers: boolean; onTogglePeers: () => void; span?: number
}) {
  const [groupId, setGroupId] = useState(GROUPS[0].id)
  const group = GROUPS.find(g => g.id === groupId) ?? GROUPS[0]
  const lineup = useMemo(() => {
    const extra = showPeers ? (peers?.peers ?? []).filter(p => !symbols.includes(p)) : []
    return [...symbols, ...extra]
  }, [symbols, peers, showPeers])
  const q = useQuery({
    queryKey: ["compare-metrics", lineup.join(",")],
    queryFn: ({ signal }) => on(signal).compareMetrics(lineup),
    enabled: lineup.length > 0,
    staleTime: 60 * 60_000,
  })
  const rows = q.data?.rows ?? []
  const peerCount = (peers?.peers ?? []).filter(p => !symbols.includes(p)).length
  const subtitle = showPeers && peerCount
    ? `the strip's chips and ${peerCount} peers of ${active} · ${peers?.source === "finnhub" ? "Finnhub" : ""}`
    : "the strip's chips, active first · the company record"
  return (
    <Widget span={span} title="Comparison analysis" subtitle={subtitle}
            actions={
              <div className="flex items-center gap-1.5">
                <button type="button" onClick={onTogglePeers}
                        disabled={!peers || peers.source == null}
                        title={peers?.source ? `Add ${active}'s peers to the table (not to the board)` : "Peers need a Finnhub key on the service or the Account page"}
                        className={btnCls({ active: showPeers })}>
                  {showPeers ? "Peers on" : "+ Peers"}
                </button>
                <select value={groupId} onChange={e => setGroupId(e.target.value)} aria-label="Metric group"
                        className={`${fieldCls} h-[24px] py-0 text-caption`}>
                  {GROUPS.map(g => <option key={g.id} value={g.id}>{g.label}</option>)}
                </select>
              </div>
            }>
      {lineup.length < 2 ? <Empty>Add more chips to the board to compare{peers?.source ? ", or turn peers on" : ""}.</Empty>
        : q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the company records are unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no company record for these symbols</Empty> : (
        <div className="overflow-x-auto"><div style={{ minWidth: 260 + group.cols.length * 96 }}>
        <Table>
          <THead>
            <TH title="The ticker and company name. Peers you turned on are dimmed and tagged">Name</TH>
            <TH align="right" title="Market capitalisation: the share price times the shares outstanding">Mkt cap</TH>
            {group.cols.map(c => <TH key={c.key} align="right" title={c.title}>{c.label}</TH>)}
          </THead>
          <tbody>
            {rows.map(r => {
              const peer = !symbols.includes(r.symbol)
              return (
                <tr key={r.symbol} className={peer ? "text-muted-foreground" : ""}>
                  <TD title={[r.name, r.industry].filter(Boolean).join(" · ") || undefined}>
                    <span className="font-semibold text-foreground">{r.symbol}</span>
                    {r.name && <span className="ml-1.5 hidden text-caption text-muted-foreground md:inline">{r.name}</span>}
                    {peer && <span className="ml-1.5 text-label uppercase tracking-caps text-muted-foreground/80">peer</span>}
                  </TD>
                  <TD align="right" mono>{r.market_cap == null ? dash : `$${compact(r.market_cap)}`}</TD>
                  {group.cols.map(c => <TD key={c.key} align="right" mono>{cell(r[c.key], c)}</TD>)}
                </tr>
              )
            })}
            {(q.data?.missing ?? []).map(m => (
              <tr key={m} className="text-muted-foreground">
                <TD><span className="font-semibold">{m}</span><span className="ml-1.5 text-caption">no company record</span></TD>
                <TD align="right" mono colSpan={1 + group.cols.length}>{dash}</TD>
              </tr>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}
