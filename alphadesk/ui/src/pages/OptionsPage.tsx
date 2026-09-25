import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import type { OptionFlowTrade, OptionRow } from "@/lib/api"
import { useOptionChain, useOptionExpirations, useOptionFlow, useQuote } from "@/lib/queries"
import { Btn, Empty, Widget, btnCls, menuItemCls } from "@/components/terminal"
import { Menu } from "@/components/ChartToolbar"
import { cn } from "@/lib/utils"
import { ComposedBoard } from "@/components/ComposedBoard"
import { normalize } from "@/lib/symbols"
import { DEFAULT_SYMBOL, useBoardSymbols } from "@/lib/boardSymbols"
import { todayInEt } from "@/lib/earningsClock"
import {
  breakEven, daysToExpiry, expectedMove, extremes, payoffCurve, profitChance, yearsToExpiry,
  type Direction, type OptionType, type Position,
} from "@/lib/optionMath"

/** One underlying's options (2026-09-14, rebuilt after the owner's AlphaSpace
 * reference): the chain with calls and puts either side of the strikes, the
 * contract a reader picks laid out at expiry, and the day's big trades.
 *
 * Read-only, like everything else here — the contract panel shows what a
 * position's numbers ARE at expiry; it does not suggest one. AlphaDesk books
 * nothing.
 *
 * Rows stay in STRIKE order. A chain is a price ladder; sorting it by volume or
 * moneyness destroys the only structure it has. */

const dash = "—"
const num = (n: number | null | undefined, d = 2) => (n == null ? dash : n.toFixed(d))
const money = (n: number | null | undefined, d = 2) => (n == null ? dash : `$${n.toFixed(d)}`)
const compact = (n: number | null | undefined, prefix = ""): string => {
  if (n == null) return dash
  const a = Math.abs(n)
  const s = n < 0 ? "-" : ""
  if (a >= 1e6) return `${s}${prefix}${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${s}${prefix}${(a / 1e3).toFixed(1)}K`
  return `${s}${prefix}${a.toFixed(prefix ? 0 : 0)}`
}
const shortDay = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" })
const longDay = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" })
const etTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })

type Pick = { symbol: string; type: OptionType }

/** Colour is the side: calls green, puts red (the owner's call, 2026-09-14),
 * and it is STRONG (2026-09-18: "show green and red but high contrast" —
 * the 8% tints read as washed-out pastel). In the money is a clear tint of
 * the side's colour, the picked contract a deeper one, the volume bars
 * near full strength. */
const sideBg = (side: OptionType, picked: boolean, itm: boolean) =>
  side === "call"
    ? (picked ? "bg-gain/40" : itm ? "bg-gain/[0.18]" : "")
    : (picked ? "bg-loss/40" : itm ? "bg-loss/[0.18]" : "")

// ── the chain ────────────────────────────────────────────────────────────

function VolCell({ vol, max, side, onClick, picked, itm }: {
  vol: number | undefined; max: number; side: OptionType; onClick: () => void; picked: boolean; itm: boolean
}) {
  const w = vol && max ? Math.max(3, Math.round((vol / max) * 100)) : 0
  return (
    <td onClick={onClick}
        className={`relative cursor-pointer px-2 py-1.5 ${side === "call" ? "text-right" : "text-left"} ${sideBg(side, picked, itm)}`}>
      {w > 0 && (
        <span aria-hidden
              className={`absolute inset-y-[5px] ${side === "call" ? "right-0 bg-gain/60" : "left-0 bg-loss/60"}`}
              style={{ width: `${w}%` }} />
      )}
      <span className="tnum relative">{vol ? compact(vol) : "0"}</span>
    </td>
  )
}

function Chain({ symbol, expiry, expiries, onExpiry, rows, spot, feed, pick, onPick, loading }: {
  symbol: string
  expiry: string
  expiries: string[]
  onExpiry: (d: string) => void
  rows: { calls: OptionRow[]; puts: OptionRow[] }
  spot: number | null
  feed?: "opra" | "indicative"
  pick: Pick | null
  onPick: (p: Pick) => void
  loading: boolean
}) {
  const today = todayInEt()
  const strikes = useMemo(() => {
    const m = new Map<number, { call?: OptionRow; put?: OptionRow }>()
    for (const c of rows.calls) m.set(c.strike, { ...(m.get(c.strike) ?? {}), call: c })
    for (const p of rows.puts) m.set(p.strike, { ...(m.get(p.strike) ?? {}), put: p })
    return [...m.entries()].sort((a, b) => a[0] - b[0])
  }, [rows])
  const maxVol = useMemo(() => Math.max(0, ...rows.calls.map(r => r.volume ?? 0), ...rows.puts.map(r => r.volume ?? 0)), [rows])
  const spotRef = useRef<HTMLTableRowElement | null>(null)
  const pickedRef = useRef<HTMLTableRowElement | null>(null)
  // Open on the money: the spot line (or a linked contract) centred once per expiry.
  const centred = useRef<string>("")
  useEffect(() => {
    const key = `${symbol}:${expiry}`
    // Wait for what to centre on: the spot line needs the quote, which can
    // arrive after the chain.
    const target = pickedRef.current ?? spotRef.current
    if (!strikes.length || centred.current === key || !target) return
    // Scroll the chain's own body, not the page: scrollIntoView moves every
    // scrolling ancestor, and took the chain's header off screen with it.
    let box: HTMLElement | null = target.parentElement
    while (box && !(box.scrollHeight > box.clientHeight && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) box = box.parentElement
    if (box) box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 2
    centred.current = key
  }, [strikes, symbol, expiry, spot])

  const strip = (
    <div className="flex items-center gap-0.5 overflow-x-auto px-2 py-1">
      {expiries.map(d => {
        const on = d === expiry
        return (
          <button key={d} type="button" onClick={() => onExpiry(d)} aria-pressed={on}
                  className={btnCls({ variant: "ghost", active: on })}>
            {d.slice(0, 4) === today.slice(0, 4) ? shortDay(d) : `${shortDay(d)}, ${d.slice(0, 4)}`}
            <span className="ml-1 text-label font-normal text-muted-foreground">{daysToExpiry(d, today)}D</span>
          </button>
        )
      })}
    </div>
  )

  const cls = "tnum cursor-pointer px-2 py-1.5 text-right"
  let spotDrawn = false
  return (
    <Widget span={8} symbol={symbol} title="Options chain" scroll={520} toolbar={strip}
            subtitle={`${strikes.length} strikes · ${longDay(expiry)}${feed === "opra" ? " · real-time OPRA" : feed === "indicative" ? " · indicative, delayed" : ""}`}
            bodyClassName="overflow-x-auto">
      {loading && !strikes.length ? <Empty>loading chain…</Empty> : !strikes.length ? <Empty>no contracts listed for this expiry</Empty> : (
        <table className="w-full min-w-[720px] border-collapse text-body">
          {/* One sticky block for both header rows: per-cell offsets drift
              with the first row's height and the rows overlapped. */}
          <thead className="sticky top-0 z-10 bg-panel">
            <tr className="text-label font-semibold uppercase tracking-caps">
              <th colSpan={5} className="bg-panel px-2 pt-2 text-center text-gain" data-tip="Calls: the right to buy 100 shares at the strike before expiry. Shaded rows are in the money, strike below the stock price" aria-description="Calls: the right to buy 100 shares at the strike before expiry. Shaded rows are in the money, strike below the stock price">Calls</th>
              <th className="bg-panel" />
              <th colSpan={5} className="bg-panel px-2 pt-2 text-center text-loss" data-tip="Puts: the right to sell 100 shares at the strike before expiry. Shaded rows are in the money, strike above the stock price" aria-description="Puts: the right to sell 100 shares at the strike before expiry. Shaded rows are in the money, strike above the stock price">Puts</th>
            </tr>
            <tr className="text-label font-medium uppercase tracking-caps text-muted-foreground">
              {["IV", "Last", "Bid", "Ask", "Vol"].map(h => <th key={`c${h}`} data-tip={CHAIN_TIPS[h]} aria-description={CHAIN_TIPS[h]} className="border-b border-row-rule bg-panel px-2 py-1.5 text-right font-medium">{h}</th>)}
              <th data-tip={CHAIN_TIPS.Strike} aria-description={CHAIN_TIPS.Strike} className="border-b border-row-rule bg-panel px-2 py-1.5 text-center font-medium">Strike</th>
              {["Vol", "Bid", "Ask", "Last", "IV"].map(h => <th key={`p${h}`} data-tip={CHAIN_TIPS[h]} aria-description={CHAIN_TIPS[h]} className={`border-b border-row-rule bg-panel px-2 py-1.5 font-medium ${h === "Vol" ? "text-left" : "text-right"}`}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {strikes.map(([strike, { call, put }]) => {
              const callItm = spot != null && strike < spot
              const putItm = spot != null && strike > spot
              const callPicked = !!call && pick?.symbol === call.symbol
              const putPicked = !!put && pick?.symbol === put.symbol
              const pickCall = () => call && onPick({ symbol: call.symbol, type: "call" })
              const pickPut = () => put && onPick({ symbol: put.symbol, type: "put" })
              const cBg = sideBg("call", callPicked, callItm)
              const pBg = sideBg("put", putPicked, putItm)
              // The spot line sits between the last strike below spot and the first above it.
              const showSpot = spot != null && !spotDrawn && strike >= spot
              if (showSpot) spotDrawn = true
              return (
                <Fragment key={strike}>
                  {showSpot && (
                    <tr ref={spotRef} aria-label={`Spot ${spot!.toFixed(2)}`}>
                      <td colSpan={11} className="relative h-[20px] p-0">
                        <span className="absolute inset-x-0 top-1/2 border-t border-dashed border-foreground/40" />
                        <span className="tnum absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground px-2 py-[1px] text-label font-semibold text-background">
                          ${spot!.toFixed(2)}
                        </span>
                      </td>
                    </tr>
                  )}
                  <tr ref={callPicked || putPicked ? pickedRef : undefined} className="row-rule hover:bg-foreground/[0.04]">
                    <td onClick={pickCall} className={`${cls} text-muted-foreground ${cBg}`}>{call?.implied_volatility != null ? `${call.implied_volatility.toFixed(1)}%` : dash}</td>
                    <td onClick={pickCall} className={`${cls} ${cBg}`}>{money(call?.last)}</td>
                    <td onClick={pickCall} className={`${cls} ${cBg}`}>{money(call?.bid)}</td>
                    <td onClick={pickCall} className={`${cls} ${cBg}`}>{money(call?.ask)}</td>
                    <VolCell vol={call?.volume} max={maxVol} side="call" onClick={pickCall} picked={callPicked} itm={callItm} />
                    <td className="tnum border-x border-row-rule bg-panel px-2 py-1.5 text-center font-semibold">{money(strike)}</td>
                    <VolCell vol={put?.volume} max={maxVol} side="put" onClick={pickPut} picked={putPicked} itm={putItm} />
                    <td onClick={pickPut} className={`${cls} ${pBg}`}>{money(put?.bid)}</td>
                    <td onClick={pickPut} className={`${cls} ${pBg}`}>{money(put?.ask)}</td>
                    <td onClick={pickPut} className={`${cls} ${pBg}`}>{money(put?.last)}</td>
                    <td onClick={pickPut} className={`${cls} text-muted-foreground ${pBg}`}>{put?.implied_volatility != null ? `${put.implied_volatility.toFixed(1)}%` : dash}</td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
      )}
    </Widget>
  )
}

// ── the contract at expiry ───────────────────────────────────────────────

function Payoff({ position, spot, width }: { position: Position; spot: number; width: number }) {
  const W = 360, H = 170, L = 44, R = 8, T = 8, B = 22
  const pts = payoffCurve(position, spot, width)
  const lo = pts[0].price, hi = pts[pts.length - 1].price
  const pnls = pts.map(p => p.pnl)
  let yMin = Math.min(0, ...pnls), yMax = Math.max(0, ...pnls)
  if (yMax - yMin < 1) { yMax += 1; yMin -= 1 }
  const pad = (yMax - yMin) * 0.08
  yMin -= pad; yMax += pad
  const x = (p: number) => L + ((p - lo) / (hi - lo)) * (W - L - R)
  const y = (v: number) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B)
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.pnl).toFixed(1)}`).join("")
  const zero = y(0)
  const area = `${line}L${x(hi).toFixed(1)},${zero.toFixed(1)}L${x(lo).toFixed(1)},${zero.toFixed(1)}Z`
  const be = breakEven(position)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => lo + (hi - lo) * f)
  const yTicks = [yMax - pad, (yMax + yMin) / 2, yMin + pad]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
         aria-label={`Profit and loss at expiry: break-even ${be.toFixed(2)}`}>
      <defs>
        <clipPath id="pnl-up"><rect x={L} y={T} width={W - L - R} height={Math.max(zero - T, 0)} /></clipPath>
        <clipPath id="pnl-down"><rect x={L} y={zero} width={W - L - R} height={Math.max(H - B - zero, 0)} /></clipPath>
      </defs>
      {yTicks.map(v => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="stroke-border" strokeDasharray="2 3" />
          <text x={L - 4} y={y(v) + 3} textAnchor="end" className="fill-muted-foreground text-[9px]">{compact(v)}</text>
        </g>
      ))}
      <path d={area} clipPath="url(#pnl-up)" className="fill-gain/25" />
      <path d={area} clipPath="url(#pnl-down)" className="fill-loss/20" />
      <path d={line} clipPath="url(#pnl-up)" fill="none" className="stroke-gain" strokeWidth={1.6} />
      <path d={line} clipPath="url(#pnl-down)" fill="none" className="stroke-loss" strokeWidth={1.6} />
      <line x1={L} x2={W - R} y1={zero} y2={zero} className="stroke-muted-foreground" strokeWidth={0.8} />
      <line x1={x(spot)} x2={x(spot)} y1={T} y2={H - B} className="stroke-foreground/50" strokeDasharray="3 3" />
      {be > lo && be < hi && <circle cx={x(be)} cy={zero} r={3} className="fill-foreground" />}
      {ticks.map(p => (
        <text key={p} x={x(p)} y={H - 6} textAnchor="middle" className="fill-muted-foreground text-[9px]">{p.toFixed(p >= 1000 ? 0 : 2)}</text>
      ))}
    </svg>
  )
}

function Contract({ symbol, expiry, row, type, spot }: {
  symbol: string; expiry: string; row: OptionRow | null; type: OptionType | null; spot: number | null
}) {
  const [direction, setDirection] = useState<Direction>("long")
  const toggle = (
    <div className="flex overflow-hidden rounded-sm border border-border text-label">
      {(["long", "short"] as const).map(d => (
        <button key={d} type="button" onClick={() => setDirection(d)} aria-pressed={direction === d}
                className={btnCls({ variant: "ghost", size: "sm", active: direction === d }, "rounded-none normal-case capitalize tracking-normal")}>
          {d}
        </button>
      ))}
    </div>
  )
  if (!row || !type || spot == null) {
    return <Widget span={4} title="Contract"><Empty>pick a contract in the chain</Empty></Widget>
  }
  // Priced at the mid when both sides quote, else the last trade.
  const premium = row.mid ?? row.last
  const iv = row.implied_volatility != null ? row.implied_volatility / 100 : null
  const years = yearsToExpiry(expiry)
  const position: Position | null = premium != null ? { type, direction, strike: row.strike, premium } : null
  const ext = position ? extremes(position) : null
  const chance = position ? profitChance(position, spot, iv, years) : null
  const move = expectedMove(spot, iv, years)
  const sign = direction === "short" ? -1 : 1
  const width = Math.min(0.6, Math.max(0.12, move ? (2.5 * move) / spot : 0.2, Math.abs(row.strike - spot) / spot * 1.4))
  const stat = (label: string, value: React.ReactNode, title?: string) => (
    <div className="min-w-0" title={title}>
      <div className="truncate text-label font-medium uppercase tracking-caps text-muted-foreground">{label}</div>
      <div className="tnum truncate text-body font-semibold">{value}</div>
    </div>
  )
  const greek = (label: string, v: number | null | undefined, note: string) => (
    <div className="row-rule flex items-center justify-between px-1 py-1.5 text-body" title={note}>
      <span className="text-muted-foreground">{label}</span>
      <span className="tnum font-medium">{v == null ? dash : (v * sign).toFixed(4)}</span>
    </div>
  )
  return (
    <Widget span={4} title="Contract" actions={toggle}
            subtitle={premium != null ? `${direction === "long" ? "paid" : "received"} ${money(premium)} a share (${row.mid != null ? "mid" : "last"})` : "no price to lay out"}>
      <div className="px-3 py-2">
        <div className="text-figure font-bold">
          {symbol} {money(row.strike, row.strike % 1 ? 2 : 0)}{" "}
          <span className={type === "call" ? "text-gain" : "text-loss"}>{type === "call" ? "Call" : "Put"}</span>
          <span className="ml-1.5 text-body font-medium text-muted-foreground">· {longDay(expiry)}</span>
        </div>
        {position && <div className="mt-2"><Payoff position={position} spot={spot} width={width} /></div>}
        <div className="mt-2 grid grid-cols-4 gap-x-3 gap-y-2">
          {stat("Spot", num(spot))}
          {stat("Break even", position ? num(breakEven(position)) : dash)}
          {stat("Max gain", ext ? (ext.maxGain == null ? "Unlimited" : compact(ext.maxGain, "$")) : dash, "Per contract, 100 shares")}
          {stat("Max loss", ext ? (ext.maxLoss == null ? "Unlimited" : compact(ext.maxLoss, "$")) : dash, "Per contract, 100 shares")}
          {stat("Chance", chance == null ? dash : `${(chance * 100).toFixed(0)}%`,
                "The chance it finishes past break-even, under this contract's implied volatility (lognormal, no rate or dividend) — what the price implies, not a forecast")}
          {stat("Exp. move", move == null ? dash : `±${move.toFixed(2)}`, "One standard deviation of the underlying by expiry, from implied volatility")}
          {stat("IV", row.implied_volatility != null ? `${row.implied_volatility.toFixed(1)}%` : dash)}
          {stat("Volume", compact(row.volume ?? 0), `Open interest ${compact(row.open_interest)}`)}
        </div>
        <div className="mt-3 text-label font-semibold uppercase tracking-caps text-muted-foreground">
          Greeks <span className="font-normal normal-case tracking-normal">· per share, {direction}</span>
        </div>
        {greek("Delta", row.delta, "Change in the option's price for a $1 move in the underlying")}
        {greek("Gamma", row.gamma, "Change in delta for a $1 move in the underlying")}
        {greek("Theta", row.theta, "Change in the option's price per day, all else equal")}
        {greek("Vega", row.vega, "Change in the option's price per 1 point of implied volatility")}
        {greek("Rho", row.rho, "Change in the option's price per 1 point of interest rates")}
      </div>
    </Widget>
  )
}

// ── the tape's big trades ────────────────────────────────────────────────

const PREMIUMS = [
  { v: 10_000, label: "$10K+" }, { v: 25_000, label: "$25K+" }, { v: 100_000, label: "$100K+" }, { v: 500_000, label: "$500K+" },
]

/** The option chain's column descriptions. */
const CHAIN_TIPS: Record<string, string> = {
  IV: "Implied volatility: the annualised move the contract's price implies for the stock",
  Last: "The contract's last traded price, per share; one contract covers 100 shares",
  Bid: "The highest price a buyer is bidding now",
  Ask: "The lowest price a seller is asking now",
  Vol: "Contracts traded today",
  Strike: "The price the option lets its holder buy (call) or sell (put) the stock at. The dashed line marks the stock's price",
}

const FLAG_TONE: Record<string, string> = {
  sweep: "border-gain/50 text-gain", "multi-leg": "border-border text-foreground", "size>OI": "border-foreground/40 text-foreground",
}
const FLAG_NOTE: Record<string, string> = {
  sweep: "Split across two or more exchanges in the same millisecond, or marked an intermarket sweep: urgency to fill",
  "multi-leg": "Part of a spread or other multi-leg order — one leg of a larger position",
  "stock-tied": "Traded together with shares of the stock",
  auction: "Filled in an exchange price-improvement auction",
  cross: "A crossed order: both sides arranged by one broker",
  floor: "Traded on an exchange floor",
  extended: "Traded outside regular hours",
  late: "Reported late",
  "size>OI": "This order alone is larger than last night's open interest: at least part of it opened new positions",
}

type SortKey = "t" | "ticker" | "dte" | "stock" | "size" | "premium" | "volume" | "open_interest"

function Flow({ symbols, onPick }: { symbols: string[]; onPick: (t: OptionFlowTrade) => void }) {
  const [minPremium, setMinPremium] = useState(25_000)
  const [paused, setPaused] = useState(false)
  const [ticker, setTicker] = useState<string>("all")
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "t", desc: true })
  const q = useOptionFlow(symbols, minPremium, paused)
  const liveSince = q.data?.live_since
  const shown = useMemo(() => {
    const rows = (q.data?.trades ?? []).filter(t => ticker === "all" || t.ticker === ticker)
    const val = (t: OptionFlowTrade) => (t[sort.key] ?? (sort.desc ? -Infinity : Infinity)) as number | string
    return [...rows].sort((x, y) => {
      const a = val(x), b = val(y)
      const c = a < b ? -1 : a > b ? 1 : 0
      return sort.desc ? -c : c
    })
  }, [q.data, ticker, sort])
  useEffect(() => { if (ticker !== "all" && !symbols.includes(ticker)) setTicker("all") }, [symbols, ticker])

  const toolbar = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1 text-caption">
      {/* TWO PICKERS, NOT FOURTEEN BUTTONS (2026-09-25, #75, the reader:
          "can you include dropdowns here too"). A board of nine symbols put
          ten ticker buttons beside four premium buttons and a Pause, and the
          row wrapped to two lines — the same fault as the news header in #68
          and the news page in #73, and it grows with the board: every chip
          added another button here.
          Two AXES, so two pickers rather than one: which company, and how
          big an order. Unlike the news views they do not exclude each other,
          so they cannot collapse into one list. */}
      {symbols.length > 1 && (
        <Menu label={ticker === "all" ? "All tickers" : ticker} title="Which company's orders">
          {close => (
            <>
              {["all", ...symbols].map(s => (
                <button key={s} type="button" role="menuitemradio" aria-checked={ticker === s}
                        onClick={() => { setTicker(s); close() }}
                        className={cn(menuItemCls, "justify-between gap-3")}>
                  <span>{s === "all" ? "All tickers" : s}</span>
                  <span className="text-muted-foreground">{ticker === s ? "✓" : ""}</span>
                </button>
              ))}
            </>
          )}
        </Menu>
      )}
      <Menu label={PREMIUMS.find(p => p.v === minPremium)?.label ?? "Any size"}
            title="The smallest order worth showing, by premium paid">
        {close => (
          <>
            {PREMIUMS.map(p => (
              <button key={p.v} type="button" role="menuitemradio" aria-checked={minPremium === p.v}
                      onClick={() => { setMinPremium(p.v); close() }}
                      className={cn(menuItemCls, "justify-between gap-3")}>
                <span>{p.label}</span>
                <span className="text-muted-foreground">{minPremium === p.v ? "✓" : ""}</span>
              </button>
            ))}
          </>
        )}
      </Menu>
      <Btn onClick={() => setPaused(v => !v)} title={paused ? "Resume the live capture" : "Pause: while paused, new orders are not seen live, so their side stays unknown"}>
        {paused ? "Resume" : "Pause"}
      </Btn>
      <span className="ml-auto text-muted-foreground">
        {liveSince && <>side known for orders since {etTime(liveSince)} ET</>}
      </span>
    </div>
  )
  const sideTag = (t: OptionFlowTrade) =>
    t.side == null ? <span className="text-muted-foreground" title="Traded before this page began watching: no quote from that moment, so the side is not known">{dash}</span>
      : <span className={`font-semibold uppercase ${t.side === "ask" ? "text-gain" : t.side === "bid" ? "text-loss" : "text-muted-foreground"}`}
              title={t.side === "ask" ? "Filled at or above the ask: a buyer paid up" : t.side === "bid" ? "Filled at or below the bid: a seller hit it" : "Filled between the bid and the ask"}>{t.side}</span>
  const head = (label: string, key: SortKey | null, align: "left" | "right" = "right", title?: string) => (
    <th key={label} data-tip={title} aria-description={title}
        className={`sticky top-0 z-10 whitespace-nowrap border-b border-row-rule bg-panel px-2 py-1.5 font-medium ${align === "left" ? "text-left" : "text-right"}`}>
      {key ? (
        <button type="button" onClick={() => setSort(s => ({ key, desc: s.key === key ? !s.desc : true }))}
                className={`uppercase tracking-caps hover:text-foreground ${sort.key === key ? "text-foreground" : ""}`}>
          {label}{sort.key === key ? (sort.desc ? " ▾" : " ▴") : ""}
        </button>
      ) : label}
    </th>
  )
  const errors = Object.entries(q.data?.errors ?? {})
  // Side, the quote and the fill are only known for orders seen live, and the
  // ask/bid share only once some are. Columns with nothing to show are left
  // out — after the close every order on screen predates the page, and four
  // columns of dashes read as broken (2026-09-14).
  const hasLive = shown.some(t => t.side != null)
  const hasShare = shown.some(t => t.ask_share != null)
  return (
    <Widget span={12} title="Options flow" toolbar={toolbar} toolbarWraps scroll={440}
            subtitle={q.data ? `big orders on the most active contracts of ${symbols.join(", ")}${q.data.feed === "opra" ? " · OPRA" : ""}` : undefined}
            bodyClassName="overflow-x-auto">
      {errors.length > 0 && (
        <div className="border-b border-row-rule px-3 py-1 text-caption text-warn">
          could not read {errors.map(([s]) => s).join(", ")}
        </div>
      )}
      {!q.isPending && shown.length > 0 && !hasLive && (
        <div className="border-b border-row-rule px-3 py-1.5 text-caption text-muted-foreground">
          Side, bid–ask and fill show for orders seen live while this page is open in market hours (9:30 AM–4:00 PM ET).
          These traded before it started watching.
        </div>
      )}
      {q.isPending ? <Empty>reading today's trades…</Empty>
        : q.isError ? <Empty>the options tape could not be read</Empty>
        : !shown.length ? <Empty>no orders of {PREMIUMS.find(p => p.v === minPremium)?.label} today on the most active contracts</Empty> : (
        <table className={`w-full border-collapse text-body ${hasLive ? "min-w-[1180px]" : "min-w-[900px]"}`}>
          <thead>
            <tr className="text-label font-medium uppercase tracking-caps text-muted-foreground">
              {head("Time (ET)", "t", "left", "When the order printed, New York time. Click a sortable heading to sort")}
              {head("Ticker", "ticker", "left", "The underlying stock or fund")}
              {hasLive && head("Side", null, "left", "Where the order filled against the quote seen live: ASK, a buyer paid up; BID, a seller hit the bid; MID, between the two. A dash: it traded before this page began watching")}
              {head("Contract", null, "left", "The strike, call or put, and expiry. Click a row to open it in the chain")}
              {head("DTE", "dte", "right", "Days to expiry")}
              {head("Stock", "stock", "right", "The stock's price at the order's minute")}
              {head("Price", null, "right", "The order's price per share of the contract, averaged across its prints. Hover a price for how many prints and exchanges")}
              {hasLive && head("Bid–Ask", null, "right", "The quote when the order was seen live")}
              {hasLive && head("Fill vs spread", null, "left", "Where the fill sat between the bid (left end) and the ask (right end) at that moment")}
              {head("Size", "size", "right", "Contracts in the order")}
              {head("Premium", "premium", "right", "Dollars paid for the order: contracts times price times 100 shares a contract")}
              {head("Volume", "volume", "right", "Contracts of this contract traded today")}
              {head("OI", "open_interest", "right", "Open interest: contracts outstanding as of last night's count")}
              {hasShare && head("Ask / bid", null, "left", "Of this contract's volume seen live today: the share filled at the ask (green) and at the bid (red)")}
              {head("Flags", null, "left", "How the order traded: a sweep across exchanges, one leg of a multi-leg order, larger than open interest and so on. Hover a flag for its meaning")}
            </tr>
          </thead>
          <tbody>
            {shown.map(t => (
              <tr key={`${t.contract}${t.t}`} onClick={() => onPick(t)} className="row-rule cursor-pointer hover:bg-foreground/[0.04]">
                <td className="tnum px-2 py-1.5 text-muted-foreground">{etTime(t.t)}</td>
                <td className="px-2 py-1.5 font-semibold">{t.ticker}</td>
                {hasLive && <td className="px-2 py-1.5 text-label">{sideTag(t)}</td>}
                <td className="whitespace-nowrap px-2 py-1.5">
                  <span className="tnum font-semibold">{t.strike % 1 ? t.strike.toFixed(2) : t.strike}</span>{" "}
                  <span className={t.type === "call" ? "text-gain" : "text-loss"}>{t.type}</span>{" "}
                  <span className="text-muted-foreground">{shortDay(t.expiry)}</span>
                </td>
                <td className="tnum px-2 py-1.5 text-right text-muted-foreground">{t.dte ?? dash}d</td>
                <td className="tnum px-2 py-1.5 text-right">{money(t.stock)}</td>
                <td className="tnum px-2 py-1.5 text-right" title={t.prints > 1 ? `${t.prints} prints across ${t.exchanges.length} exchange${t.exchanges.length === 1 ? "" : "s"}` : undefined}>{money(t.price)}</td>
                {hasLive && <td className="tnum whitespace-nowrap px-2 py-1.5 text-right text-muted-foreground">{t.bid != null && t.ask != null ? `${money(t.bid)} – ${money(t.ask)}` : dash}</td>}
                {hasLive && <td className="px-2 py-1.5">
                  {t.fill != null ? (
                    <span className="relative block h-[3px] w-[72px] rounded-full bg-muted" title={`${(t.fill * 100).toFixed(0)}% of the way from bid to ask`}>
                      <span className="absolute top-1/2 h-[8px] w-[8px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground" style={{ left: `${t.fill * 100}%` }} />
                    </span>
                  ) : <span className="text-muted-foreground">{dash}</span>}
                </td>}
                <td className="tnum px-2 py-1.5 text-right">{t.size.toLocaleString()}</td>
                <td className="tnum px-2 py-1.5 text-right font-semibold">{compact(t.premium, "$")}</td>
                <td className="tnum px-2 py-1.5 text-right text-muted-foreground">{compact(t.volume)}</td>
                <td className="tnum px-2 py-1.5 text-right text-muted-foreground">{compact(t.open_interest)}</td>
                {hasShare && <td className="px-2 py-1.5">
                  {t.ask_share != null ? (
                    <span className="flex items-center gap-1.5" title={`Of ${t.share_contracts.toLocaleString()} contracts seen live today: ${Math.round(t.ask_share * 100)}% at the ask, ${Math.round((t.bid_share ?? 0) * 100)}% at the bid`}>
                      <span className="flex h-[5px] w-[64px] overflow-hidden rounded-full bg-muted">
                        <span className="bg-gain" style={{ width: `${t.ask_share * 100}%` }} />
                        <span className="ml-auto bg-loss" style={{ width: `${(t.bid_share ?? 0) * 100}%` }} />
                      </span>
                      <span className="tnum text-label text-muted-foreground">{Math.round(t.ask_share * 100)}%</span>
                    </span>
                  ) : <span className="text-muted-foreground" title="No volume on this contract seen live yet">{dash}</span>}
                </td>}
                <td className="px-2 py-1.5">
                  <span className="flex flex-wrap gap-1" title={t.code ? `Conditions: ${t.code}` : undefined}>
                    {t.flags.map(f => (
                      <span key={f} title={FLAG_NOTE[f]}
                            className={`whitespace-nowrap rounded-sm border px-1 text-label font-semibold uppercase leading-[15px] tracking-caps ${FLAG_TONE[f] ?? "border-border text-muted-foreground"}`}>
                        {f}
                      </span>
                    ))}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Widget>
  )
}

// ── the page ─────────────────────────────────────────────────────────────

export default function OptionsPage() {
  const [params, setParams] = useSearchParams()
  // Scoped by the board's marked chip, like every other page: one place to
  // pick the symbol (the owner's call, 2026-09-14 — the page's own symbol box
  // was a second, disagreeing control).
  const board = useBoardSymbols()
  const symbol = normalize(params.get("symbol") || "") || DEFAULT_SYMBOL
  const flowSymbols = board.symbols.length ? board.symbols.slice(0, 8) : [symbol]

  const exp = useOptionExpirations(symbol)
  const listed = exp.data?.expirations ?? []
  // A link (a movers row, a flow row) may name an expiry past the listed
  // ones; it joins the strip in date order, since the chain serves any date.
  const wanted = params.get("expiry") || ""
  const expiries = wanted && /^\d{4}-\d{2}-\d{2}$/.test(wanted) && listed.length && !listed.includes(wanted)
    ? [...listed, wanted].sort() : listed
  const active = wanted && expiries.includes(wanted) ? wanted : expiries[0] ?? ""
  const contract = (params.get("contract") || "").toUpperCase()

  const chain = useOptionChain(symbol, active)
  const quote = useQuote(symbol)
  // Only this symbol's price: right after a chip switch the previous
  // symbol's quote is still loaded, and its spot line centred the new chain
  // at the wrong strike.
  const spot = quote.data && normalize(quote.data.symbol) === symbol ? quote.data.price : null
  const rows: { calls: OptionRow[]; puts: OptionRow[] } = chain.data && chain.data.expiry === active ? chain.data : { calls: [], puts: [] }

  const setParam = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next, { replace: true })
  }
  const pickRow = contract
    ? rows.calls.find(r => r.symbol === contract) ?? rows.puts.find(r => r.symbol === contract) ?? null : null
  const pick: Pick | null = pickRow ? { symbol: pickRow.symbol, type: rows.calls.includes(pickRow) ? "call" : "put" } : null

  const scopeForm = (
    <div className="col-span-12 flex flex-wrap items-baseline gap-1.5 border-b border-row-rule pb-2">
      <span className="num text-emph font-semibold">{symbol}</span>
      {spot != null && <span className="tnum text-body">{spot.toFixed(2)}</span>}
      {spot != null && quote.data?.change_pct != null && (
        <span className={`tnum text-body ${quote.data.change_pct >= 0 ? "text-gain" : "text-loss"}`}>
          {quote.data.change_pct >= 0 ? "+" : ""}{quote.data.change_pct.toFixed(2)}%
        </span>
      )}
      {spot != null && quote.data?.name && <span className="truncate text-body text-muted-foreground">{quote.data.name}</span>}
    </div>
  )

  const noChain = exp.isPending ? "loading expiries…" : !expiries.length ? `no listed options for ${symbol}` : null

  return (
    <ComposedBoard
      page="options"
      before={scopeForm}
      panels={[
        { id: "chain", label: "Options chain",
          node: noChain ? <Widget span={8} symbol={symbol} title="Options chain"><Empty>{noChain}</Empty></Widget> : (
            <Chain symbol={symbol} expiry={active} expiries={expiries} onExpiry={d => setParam({ expiry: d, contract: null })}
                   rows={rows} spot={spot} feed={chain.data?.feed} pick={pick} loading={chain.isPending || chain.isPlaceholderData}
                   onPick={p => setParam({ contract: p.symbol, expiry: active })} />
          ) },
        { id: "contract", label: "Contract",
          node: <Contract symbol={symbol} expiry={active} row={pickRow} type={pick?.type ?? null} spot={spot} /> },
        { id: "flow", label: "Options flow",
          // An order on another chip's stock switches the board to it, in the
          // same write as its expiry and contract.
          node: <Flow symbols={flowSymbols} onPick={t => setParam({ symbol: t.ticker, expiry: t.expiry, contract: t.contract })} /> },
      ]}
    />
  )
}
