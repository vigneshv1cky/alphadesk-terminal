import { useMemo, useState } from "react"
import { ComposedBoard } from "@/components/ComposedBoard"
import { QueryFailure } from "@/components/KeyPrompt"
import { Empty, Table, TD, TH, THead, TR, Widget, btnCls } from "@/components/terminal"
import { compact, Treemap } from "@/components/Treemap"
import { RelativePerformancePanel } from "@/components/Compare"
import type { SectorRow, Sectors } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { useLiveQuotes } from "@/lib/liveQuotes"
import { useSectorBreadth, useSectors } from "@/lib/queries"
import { liveGroup } from "@/lib/sectorsLive"
import { IndexMovers, TabStrip } from "@/widgets/market"

/** The Sectors page (2026-09-15): how the market's parts are doing, from
 * the funds that trade them — the eleven S&P sector funds and a set of
 * industry-group funds (ingest/sectors.py), beside the Market ETFs tile the
 * Markets board also carries.
 *
 * A row or a tile puts the fund on the board, so the chart and Analysis
 * follow it. Tables keep the page's order until the reader sorts a column.
 * Prices stream; breadth and leaders come from the reader's company
 * screener (US companies over $2B) and refresh each minute. */

const dash = "—"
const pct = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? dash : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`
const pts = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? dash : `${v > 0 ? "+" : ""}${v.toFixed(2)}`
const tone = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "text-muted-foreground" : v > 0 ? "text-gain" : v < 0 ? "text-loss" : ""

type Key = "change_pct" | "w1" | "m1" | "m3" | "ytd" | "y1" | "pos" | "turnover" | "rel_m1" | "rel_m3"

/** Where the price sits between the 52-week low and high, 0-100. */
const position = (r: SectorRow) =>
  r.price != null && r.high_52w != null && r.low_52w != null && r.high_52w > r.low_52w
    ? ((r.price - r.low_52w) / (r.high_52w - r.low_52w)) * 100 : null

const value = (r: SectorRow, k: Key) => (k === "pos" ? position(r) : (r[k] ?? null))

/** Click a header: largest first, then smallest first, then the page's order. */
function useSort(rows: SectorRow[]) {
  const [sort, setSort] = useState<{ key: Key; dir: -1 | 1 } | null>(null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    return [...rows].sort((a, b) => {
      const va = value(a, sort.key), vb = value(b, sort.key)
      if (va == null) return 1
      if (vb == null) return -1
      return (va - vb) * sort.dir
    })
  }, [rows, sort])
  const cycle = (key: Key) => setSort(s => (s?.key !== key ? { key, dir: -1 } : s.dir === -1 ? { key, dir: 1 } : null))
  const mark = (key: Key) => (sort?.key === key ? (sort.dir === -1 ? " ↓" : " ↑") : "")
  return { sorted, cycle, mark }
}

function SortTH({ k, label, title, cycle, mark, className }: {
  k: Key; label: string; title: string; cycle: (k: Key) => void; mark: (k: Key) => string; className?: string
}) {
  return (
    <TH align="right" title={`${title} · click to sort`} className={className}>
      <button type="button" onClick={() => cycle(k)} className="uppercase tracking-caps hover:text-foreground">
        {label}{mark(k)}
      </button>
    </TH>
  )
}

/** The page's figures at live prices: every fund's price streams over the
 * tab's live connection, and its returns, its return against SPY and its
 * standing move with it (lib/sectorsLive). */
function useSectorData(): { q: ReturnType<typeof useSectors>; data: Sectors | undefined } {
  const q = useSectors()
  const symbols = useMemo(() => (q.data
    ? [q.data.benchmark.symbol, ...q.data.sectors.map(r => r.symbol), ...q.data.industries.map(r => r.symbol)]
    : []), [q.data])
  const ticks = useLiveQuotes(symbols)
  const data = useMemo(() => {
    if (!q.data) return undefined
    const sec = liveGroup(q.data.sectors, q.data.benchmark, ticks)
    const ind = liveGroup(q.data.industries, q.data.benchmark, ticks)
    return { ...q.data, benchmark: sec.bench, sectors: sec.rows, industries: ind.rows }
  }, [q.data, ticks])
  return { q, data }
}

function PerformanceTable({ title, rows, benchmark, subtitle }: {
  title: string; rows: SectorRow[]; benchmark?: SectorRow; subtitle: string
}) {
  const { add } = useBoardSymbols()
  const { sorted, cycle, mark } = useSort(rows)
  const cols: [Key, string, string][] = [
    ["change_pct", "1D", "Today's change"], ["w1", "1W", "Return over a week"], ["m1", "1M", "Return over a month"],
    ["m3", "3M", "Return over three months"], ["ytd", "YTD", "Return since the last close of last year"],
    ["y1", "1Y", "Return over a year"], ["pos", "52w pos.", "Where the price sits between the 52-week low and high"],
  ]
  const line = (r: SectorRow, muted = false) => (
    <TR key={r.symbol} onClick={() => add(r.symbol)} className={muted ? "bg-foreground/[0.03]" : undefined}>
      <TD className="truncate" title={r.name ?? undefined}>
        <span className="font-semibold">{r.label}</span>
        <span className="ml-1.5 text-label text-muted-foreground">{r.symbol}</span>
      </TD>
      <TD align="right" mono>{r.price == null ? dash : r.price.toFixed(2)}</TD>
      {cols.map(([k]) => k === "pos"
        ? <TD key={k} align="right" mono className="text-muted-foreground">{position(r) == null ? dash : `${position(r)!.toFixed(0)}%`}</TD>
        : <TD key={k} align="right" mono className={tone(value(r, k))}>{pct(value(r, k))}</TD>)}
    </TR>
  )
  return (
    <Widget span={12} title={title} subtitle={subtitle}>
      <div className="overflow-x-auto"><div className="min-w-[720px]">
        <Table>
          <THead>
            <TH className="w-[26%]" title="The sector or industry and the fund that tracks it. SPY, the S&P 500 fund, is the shaded row for comparison">Group</TH>
            <TH align="right" title="The fund's latest price, updating live">Last</TH>
            {cols.map(([k, label, t]) => <SortTH key={k} k={k} label={label} title={t} cycle={cycle} mark={mark} />)}
          </THead>
          <tbody>
            {benchmark && line(benchmark, true)}
            {sorted.map(r => line(r))}
          </tbody>
        </Table>
      </div></div>
    </Widget>
  )
}

function SectorPerformance() {
  const { q, data } = useSectorData()
  if (!data) {
    return (
      <Widget span={12} title="Sector performance">
        {q.isError ? <QueryFailure error={q.error}>sector figures are unavailable right now</QueryFailure> : <Empty>loading…</Empty>}
      </Widget>
    )
  }
  return <PerformanceTable title="Sector performance" rows={data.sectors} benchmark={data.benchmark}
                           subtitle="the S&P sector funds · SPY first for reference · a row puts the fund on the board" />
}

function IndustryGroups() {
  const { q, data } = useSectorData()
  if (!data) {
    return (
      <Widget span={12} title="Industry groups">
        {q.isError ? <QueryFailure error={q.error}>industry figures are unavailable right now</QueryFailure> : <Empty>loading…</Empty>}
      </Widget>
    )
  }
  return <PerformanceTable title="Industry groups" rows={data.industries} benchmark={data.benchmark}
                           subtitle="industry funds a level below the sectors" />
}

function SectorHeatmap() {
  const { q, data } = useSectorData()
  const { active, add } = useBoardSymbols()
  const rows = data?.sectors ?? []
  const weights = data?.weights ?? null
  // Sized by each sector's share of the S&P 500 when a connected vendor
  // carries the weights; by the fund's dollars traded today otherwise.
  const [by, setBy] = useState<"weight" | "turnover">("weight")
  const size = weights ? by : "turnover"
  const priced = useMemo(() => Object.fromEntries(rows.map(r => [r.symbol, { ...r, weight: weights?.[r.symbol] ?? null }])), [rows, weights])
  const labels = useMemo(() => Object.fromEntries(rows.map(r => [r.symbol, r.label])), [rows])
  return (
    <Widget span={12} title="Sector heatmap"
            subtitle={`sized by ${size === "weight" ? "share of the S&P 500" : "the fund's dollars traded today"} · coloured by today's move`}
            toolbar={weights ? <TabStrip tabs={[{ id: "weight", label: "S&P weight" }, { id: "turnover", label: "Traded today" }] as const}
                                         value={by} onChange={setBy} /> : undefined}>
      {!data
        ? (q.isError ? <QueryFailure error={q.error}>sector figures are unavailable right now</QueryFailure> : <Empty>loading…</Empty>)
        : (
          <div className="p-2">
            <Treemap symbols={rows.map(r => r.symbol)} priced={priced} metric={size} labels={labels}
                     fmt={n => (n == null ? dash : size === "weight" ? `${n.toFixed(1)}% of S&P` : `$${compact(n)}`)}
                     picked={active} onPick={add} />
          </div>
        )}
    </Widget>
  )
}

/** Lines drawn on the history chart beside SPY; the chart has six colours. */
const HISTORY_MAX = 5

function SectorHistory() {
  const { data } = useSectorData()
  const rows = data?.sectors ?? []
  const [picked, setPicked] = useState<string[]>(["XLK", "XLF", "XLV", "XLY", "XLC"])
  const toggle = (sym: string) => setPicked(p => (p.includes(sym) ? p.filter(x => x !== sym)
    : [...p, sym].slice(-HISTORY_MAX)))
  return (
    <RelativePerformancePanel
      title="Sector history"
      symbols={["SPY", ...picked]}
      toolbar={(
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Sectors on the chart">
          {rows.map(r => (
            <button key={r.symbol} type="button" onClick={() => toggle(r.symbol)} aria-pressed={picked.includes(r.symbol)}
                    title={`${r.label} (${r.symbol}) · up to ${HISTORY_MAX} beside SPY`}
                    className={btnCls({ active: picked.includes(r.symbol) }, "px-1.5")}>
              {r.symbol}
            </button>
          ))}
        </div>
      )}
    />
  )
}

/** "up and down today", or which session the figures are from before the
 * day's first trades. */
function sessionWords(session: string | null | undefined, isToday: boolean | undefined, today: string) {
  if (isToday || !session) return today
  const d = new Date(`${session}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })
  return `last session, ${d} · not yet traded today`
}

function SectorBreadthPanel() {
  const { data } = useSectorData()
  const b = useSectorBreadth()
  const { add } = useBoardSymbols()
  const rows = data?.sectors ?? []
  return (
    <Widget span={6} title="Sector breadth"
            subtitle={b.data ? `${b.data.universe} · ${sessionWords(b.data.session, b.data.session_is_today, "up and down today")}` : undefined}>
      {!b.data
        ? (b.isError ? <QueryFailure error={b.error}>breadth is unavailable right now</QueryFailure> : <Empty>loading…</Empty>)
        : (
          <div className="overflow-x-auto"><div className="min-w-[360px]">
          <Table>
            <THead>
              <TH title="The sector. Hover a row for how many S&P 500 companies it holds">Sector</TH>
              <TH align="right" className="w-[12%]" title="Companies up today">Up</TH>
              <TH align="right" className="w-[12%]" title="Companies down today">Down</TH>
              <TH className="w-[26%]" title="Share of the sector's companies up today">% up</TH>
              <TH align="right" className="w-[14%]" title="The sector fund's change today, for comparison">Fund 1D</TH>
            </THead>
            <tbody>
              {rows.map(r => {
                const g = b.data!.groups[r.symbol]
                const counted = g ? g.up + g.down + g.flat : 0
                const share = counted ? (g.up / counted) * 100 : null
                return (
                  <TR key={r.symbol} onClick={() => add(r.symbol)}>
                    <TD className="truncate" title={g ? `${g.companies} companies, ${counted} with a price today` : undefined}>
                      <span className="font-semibold">{r.label}</span>
                    </TD>
                    <TD align="right" mono className="text-gain">{g ? g.up : dash}</TD>
                    <TD align="right" mono className="text-loss">{g ? g.down : dash}</TD>
                    <TD>
                      {share == null ? <span className="text-muted-foreground">{dash}</span> : (
                        <span className="flex items-center gap-1.5">
                          <span className="relative h-[8px] flex-1 overflow-hidden bg-loss/25" aria-hidden>
                            <span className="absolute inset-y-0 left-0 bg-gain" style={{ width: `${share}%` }} />
                          </span>
                          <span className="num w-[34px] text-right text-caption">{share.toFixed(0)}%</span>
                        </span>
                      )}
                    </TD>
                    <TD align="right" mono className={tone(r.change_pct)}>{pct(r.change_pct)}</TD>
                  </TR>
                )
              })}
            </tbody>
          </Table>
          </div></div>
        )}
    </Widget>
  )
}

function SectorLeaders() {
  const { data } = useSectorData()
  const b = useSectorBreadth()
  const { add } = useBoardSymbols()
  const rows = data?.sectors ?? []
  const [fund, setFund] = useState("XLK")
  // Largest by market cap, or the drivers: the companies that moved the most
  // market value today, either way.
  const [view, setView] = useState<"largest" | "drivers">("largest")
  const g = b.data?.groups[fund]
  const list = (view === "drivers" ? g?.drivers : g?.leaders) ?? []
  const signed = (n: number | null) => (n == null ? dash : `${n > 0 ? "+" : n < 0 ? "−" : ""}$${compact(Math.abs(n))}`)
  return (
    <Widget span={6} title="Sector leaders"
            subtitle={view === "drivers"
              ? `the market value each added or lost · ${sessionWords(b.data?.session, b.data?.session_is_today, "today")}`
              : `the sector's largest${b.data ? ` · ${b.data.universe}` : ""} · ${sessionWords(b.data?.session, b.data?.session_is_today, "today's move")}`}
            toolbar={(
              <div className="flex flex-wrap items-center gap-2">
                <TabStrip tabs={[{ id: "largest", label: "Largest" }, { id: "drivers", label: "Drivers" }] as const}
                          value={view} onChange={setView} />
                <label className="flex items-center gap-2 text-caption text-muted-foreground">
                  Sector
                  <select value={fund} onChange={e => setFund(e.target.value)}
                          className="h-[28px] border border-border bg-panel px-1.5 text-caption font-semibold text-foreground">
                    {rows.map(r => <option key={r.symbol} value={r.symbol}>{r.label}</option>)}
                  </select>
                </label>
              </div>
            )}>
      {!b.data
        ? (b.isError ? <QueryFailure error={b.error}>leaders are unavailable right now</QueryFailure> : <Empty>loading…</Empty>)
        : !list.length ? <Empty>{view === "drivers" ? "no company in this sector has a change yet" : "no companies listed for this sector"}</Empty> : (
          <div className="overflow-x-auto"><div className="min-w-[360px]">
          <Table>
            <THead>
              <TH title="An S&P 500 company in the sector. Hover a row for its industry">Company</TH>
              <TH align="right" className="w-[17%]" title="Market capitalisation: the share price times the shares outstanding">Mkt cap</TH>
              <TH align="right" className="w-[14%]" title="Change since the previous session's close">1D</TH>
              {view === "drivers"
                ? <TH align="right" className="w-[19%]" title="Market value added or lost today">Value moved</TH>
                : <TH align="right" className="w-[15%]" title="The latest price">Last</TH>}
            </THead>
            <tbody>
              {list.map(l => (
                <TR key={l.symbol} onClick={() => add(l.symbol)}>
                  <TD className="truncate" title={[l.name, l.industry].filter(Boolean).join(" · ")}>
                    <span className="font-semibold">{l.symbol}</span>
                    <span className="ml-1.5 text-label text-muted-foreground">{l.name}</span>
                  </TD>
                  <TD align="right" mono className="text-muted-foreground">{l.market_cap == null ? dash : `$${compact(l.market_cap)}`}</TD>
                  <TD align="right" mono className={tone(l.change_pct)}>{pct(l.change_pct)}</TD>
                  {view === "drivers"
                    ? <TD align="right" mono className={`font-semibold ${tone(l.value_change)}`}>{signed(l.value_change)}</TD>
                    : <TD align="right" mono>{l.price == null ? dash : l.price.toFixed(2)}</TD>}
                </TR>
              ))}
            </tbody>
          </Table>
          </div></div>
        )}
    </Widget>
  )
}

const STANDING: Record<NonNullable<SectorRow["rotation"]>, { label: string; cls: string; title: string }> = {
  leading: { label: "Leading", cls: "text-gain", title: "Ahead of SPY over three months and over the last month" },
  weakening: { label: "Weakening", cls: "text-warn", title: "Ahead of SPY over three months, behind it over the last month" },
  lagging: { label: "Lagging", cls: "text-loss", title: "Behind SPY over three months and over the last month" },
  improving: { label: "Improving", cls: "text-info", title: "Behind SPY over three months, ahead of it over the last month" },
}

function SectorRotation() {
  const { q, data } = useSectorData()
  const [group, setGroup] = useState<"sectors" | "industries">("sectors")
  const { add } = useBoardSymbols()
  const rows = data?.[group] ?? []
  const { sorted, cycle, mark } = useSort(rows)
  return (
    <Widget
      span={6}
      title="Sector rotation"
      subtitle="return against SPY, in percentage points"
      toolbar={<TabStrip tabs={[{ id: "sectors", label: "Sectors" }, { id: "industries", label: "Industries" }] as const}
                         value={group} onChange={setGroup} />}
    >
      {!data
        ? (q.isError ? <QueryFailure error={q.error}>sector figures are unavailable right now</QueryFailure> : <Empty>loading…</Empty>)
        : (
          <div className="overflow-x-auto"><div className="min-w-[360px]">
          <Table>
            <THead>
              <TH title="The sector or industry and the fund that tracks it">Group</TH>
              {/* Narrow number columns: the group names are the long strings
                  ("Consumer discretionary XLY") and were cut at half width. */}
              <SortTH k="rel_m1" label="1M vs SPY" title="One-month return minus SPY's" cycle={cycle} mark={mark} className="w-[18%]" />
              <SortTH k="rel_m3" label="3M vs SPY" title="Three-month return minus SPY's" cycle={cycle} mark={mark} className="w-[18%]" />
              <TH align="right" className="w-[17%]" title="Three months sets the trend, the last month the turn">Standing</TH>
            </THead>
            <tbody>
              {sorted.map(r => {
                const s = r.rotation ? STANDING[r.rotation] : null
                return (
                  <TR key={r.symbol} onClick={() => add(r.symbol)}>
                    <TD className="truncate">
                      <span className="font-semibold">{r.label}</span>
                      <span className="ml-1.5 text-label text-muted-foreground">{r.symbol}</span>
                    </TD>
                    <TD align="right" mono className={tone(r.rel_m1)}>{pts(r.rel_m1)}</TD>
                    <TD align="right" mono className={tone(r.rel_m3)}>{pts(r.rel_m3)}</TD>
                    <TD align="right" className={`font-semibold ${s?.cls ?? "text-muted-foreground"}`} title={s?.title}>{s?.label ?? dash}</TD>
                  </TR>
                )
              })}
            </tbody>
          </Table>
          </div></div>
        )}
    </Widget>
  )
}

export default function SectorsPage() {
  return (
    <ComposedBoard
      page="sectors"
      panels={[
        { id: "market-etfs", label: "Market ETFs", node: <IndexMovers /> },
        { id: "rotation", label: "Sector rotation", node: <SectorRotation /> },
        { id: "heatmap", label: "Sector heatmap", node: <SectorHeatmap /> },
        { id: "breadth", label: "Sector breadth", node: <SectorBreadthPanel /> },
        { id: "leaders", label: "Sector leaders", node: <SectorLeaders /> },
        { id: "performance", label: "Sector performance", node: <SectorPerformance /> },
        { id: "history", label: "Sector history", node: <SectorHistory /> },
        { id: "industries", label: "Industry groups", node: <IndustryGroups /> },
      ]}
    />
  )
}
