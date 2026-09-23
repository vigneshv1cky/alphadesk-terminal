import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { api, type CategoryMoverRow, type MoverCategory } from "@/lib/api"
import { usePrefetchChart, useQuote } from "@/lib/queries"
import { useCryptoTicks } from "@/lib/liveCrypto"
import { QueryFailure } from "@/components/KeyPrompt"
import { isNeedsKey } from "@/lib/api"
import { useLiveQuotes } from "@/lib/liveQuotes"
import { useNavigate } from "react-router-dom"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { KeyStatisticsPanel } from "@/components/KeyStatistics"
import { moneyIn, moneyOut } from "@/lib/floors"
import { useLiveTrade } from "@/lib/live"
import { Empty, Flash, Table, TD, TH, THead, TR, Widget, btnCls, menuHeadCls } from "@/components/terminal"
import { registerWidget } from "@/widgets/registry"
import { RelatedFundsTile } from "@/components/RelatedFunds"
import { Menu } from "@/components/ChartToolbar"
import { useNarrowViewport } from "@/lib/viewport"

/** Equity Overview and Movers — the two tiles that make a markets board feel
 * like a quote terminal rather than a news reader.
 *
 * None of these four tiles takes a scroll box. Their content is a FIXED
 * length — the quote's stat list, ten cross-asset rows, twenty movers — so a
 * clipped body would hide rows that are always the same rows, behind a
 * scrollbar that always scrolls the same distance. They render whole and the
 * grid row takes the height of the tallest. */

function compact(n: number | null | undefined): string {
  if (n == null) return "—"
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return n.toFixed(2)
}

const num = (n: number | null | undefined, d = 2) =>
  n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })

/** A mover's figures must never be cut to "…" (2026-09-19, the owner: "these
 * things should never be ..."). Their columns are sized for the widest
 * two-decimal value; beyond it the decimals go instead of the digits: a move
 * of 1,000% or more is whole ("+2,968%" — "+2967.61%" was cut), and a price
 * of 10,000 or more loses its cents — but only in the 84px price column a
 * name column leaves (Berkshire's class A). The crypto list has no name
 * column, and without cents Bitcoin's ticks, mostly under a dollar, looked
 * frozen. Under 1, three significant figures: SHIB and PEPE read "0.0000". */
function moveText(pct: number): string {
  const sign = pct >= 0 ? "+" : ""
  return Math.abs(pct) >= 1000 ? `${sign}${num(pct, 0)}%` : `${sign}${pct.toFixed(2)}%`
}
function priceDecimals(price: number, narrow: boolean): number {
  const abs = Math.abs(price)
  if (abs > 0 && abs < 0.001) return Math.ceil(-Math.log10(abs)) + 2
  return abs < 10 ? 4 : narrow && abs >= 10_000 ? 0 : 2
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="row-rule flex items-baseline justify-between gap-3 px-3 py-1.5">
      <span className="shrink-0 text-caption text-muted-foreground">{label}</span>
      <span className="num truncate text-body">{value}</span>
    </div>
  )
}

/** The quote block. Scoped by ?symbol= like every other widget, so changing
 * the chip in the view header re-points it along with the rest of the board. */
export function EquityOverview() {
  const [params] = useSearchParams()
  const symbol = (params.get("symbol") || "").toUpperCase()
  const { data: q, isPending, error } = useQuote(symbol)
  const { tick } = useLiveTrade(symbol)

  if (!symbol) {
    return (
      <Widget span={4} title="Equity Overview">
        <Empty>Pick a symbol to scope this board — use the chip in the header, or open a chart.</Empty>
      </Widget>
    )
  }
  if (error) {
    // A 428 is "connect a vendor", not "this stock has no price": the plain
    // "no quote" line read as though the symbol did not trade (2026-09-19,
    // the first-run check on a keyless instance).
    return (
      <Widget span={4} symbol={symbol} title="Equity Overview">
        <QueryFailure error={error}>no quote for {symbol}</QueryFailure>
      </Widget>
    )
  }
  if (isPending || !q) {
    return <Widget span={4} symbol={symbol} title="Equity Overview"><Empty>loading…</Empty></Widget>
  }

  /** The headline price rides the live feed; everything below it stays on the
   * quote. Change is RECOMPUTED against the previous close rather than left as
   * the quote reported it — showing a moved price beside a change that has not
   * moved would be the two disagreeing on screen. Only the fields a trade
   * actually determines are touched; the ranges, multiples and targets are the
   * quote's to state. */
  const fresh = tick && !tick.stale && tick.symbol === q.symbol ? tick.price : null
  const price = fresh ?? q.price
  // What the quote itself measured from — the previous close in the session,
  // the session's own close once it has ended (2026-09-22). Measuring a
  // live after-hours print against the previous close would disagree with
  // the figure the quote states.
  const prev = q.change_from ?? q.previous_close
  const change = fresh != null && prev ? fresh - prev : q.change
  const changePct = fresh != null && prev ? ((fresh - prev) / prev) * 100 : q.change_pct

  const up = (change ?? 0) >= 0
  return (
    <Widget span={4} symbol={q.symbol} title="Equity Overview">
      {/* pt, because the quote block opens with prose rather than a ruled
          row — text sitting flush against the header's 2px rule reads as
          clipped, where a table head brings its own padding. */}
      <div className="px-3 pb-2 pt-2.5">
        <div className="text-caption text-muted-foreground">
          {[q.exchange_name || q.exchange, q.quote_source].filter(Boolean).join(" - ")} · {q.currency}
        </div>
        <div className="text-emph font-medium">{q.name} ({q.symbol})</div>
        <Flash value={price} className="num mt-1 inline-block text-display font-semibold leading-none">
          {num(price)}
        </Flash>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
          <Flash value={change} className={`num text-body ${up ? "text-gain" : "text-loss"}`}>
            {up ? "+" : ""}{num(change)} ({up ? "+" : ""}{num(changePct)}%)
          </Flash>
          {/* When this price was struck. A quote panel with no time on it looks
              identical whether it is a second old or an hour — the same reason
              the live ticks carry their age. */}
          {(tick?.at || q.as_of) && (
            <span className="text-caption text-muted-foreground">
              As of {new Date(tick?.at || q.as_of!).toLocaleTimeString("en-US", {
                timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit",
              })} ET
            </span>
          )}
        </div>
      </div>
      <Row label="Previous Close" value={num(q.previous_close)} />
      <Row label="Open" value={num(q.open)} />
      <Row label="Bid" value={q.bid ? `${num(q.bid)} x ${q.bid_size ?? 0}` : "—"} />
      <Row label="Ask" value={q.ask ? `${num(q.ask)} x ${q.ask_size ?? 0}` : "—"} />
      <Row label="Day's Range" value={q.day_low ? `${num(q.day_low)} - ${num(q.day_high)}` : "—"} />
      <Row label="52 Week Range" value={q.week52_low ? `${num(q.week52_low)} - ${num(q.week52_high)}` : "—"} />
      <Row label="Volume" value={q.volume?.toLocaleString() ?? "—"} />
      <Row label="Avg. Volume" value={q.avg_volume?.toLocaleString() ?? "—"} />
      <Row label="Market Cap" value={compact(q.market_cap)} />
      <Row label="Enterprise Value" value={compact(q.enterprise_value)} />
      <Row label="PE Ratio (Forward)" value={num(q.pe_forward)} />
      <Row label="PE Ratio (TTM)" value={num(q.pe_trailing)} />
      <Row label="PEG Ratio" value={num(q.peg)} />
      <Row label="Price/Sales (TTM)" value={num(q.price_to_sales)} />
      <Row label="Price/Book" value={num(q.price_to_book)} />
      <Row label="Beta (5Y Monthly)" value={num(q.beta)} />
      <Row label="EPS (TTM)" value={num(q.eps_ttm)} />
      <Row label="Earnings Date" value={q.earnings_date ?? "—"} />
      <Row
        label="Forward Dividend & Yield"
        value={q.dividend_rate
          ? `${num(q.dividend_rate)} (${num(q.dividend_yield)}%)`
          : q.dividend_yield ? `${num(q.dividend_yield)}%` : "—"}
      />
      <Row label="Ex-Dividend Date" value={q.ex_dividend_date ?? "—"} />
      <Row label="1y Target Est" value={num(q.target_mean)} />
      <Row
        label="Analyst Target Range"
        value={q.target_low ? `${num(q.target_low)} - ${num(q.target_high)}` : "—"}
      />
      <Row
        label="Analyst Rating"
        value={q.analyst_rating
          ? <span className="capitalize">{q.analyst_rating}{q.analyst_count ? ` (${q.analyst_count})` : ""}</span>
          : "—"}
      />
    </Widget>
  )
}

export function TabStrip<T extends string>({ tabs, value, onChange }: {
  tabs: readonly { id: T; label: string }[]
  value: T
  onChange: (id: T) => void
}) {
  return (
    <>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          aria-pressed={value === t.id}
          className={btnCls({ size: "lg", active: value === t.id })}
        >
          {t.label}
        </button>
      ))}
    </>
  )
}

/** The movers table: what to show · last · a change column. Three plain
 * columns and no spark, so a span-3 panel survives without a horizontal
 * scroll; direction is already stated by the change figure.
 *
 * A row SCOPES THE BOARD, the way the watchlist's rows do: the symbol
 * joins the strip and becomes the active chip, and every tile follows. An
 * option contract is not a board symbol, so its row is inert. */
/** TRADING HALTS, beside the movers (2026-09-23). A halt IS market activity
 * on a symbol, which is what this tile is for — and unlike everything else
 * on it, no vendor in the catalogue sells it, so this tab is the scraped
 * Nasdaq source or nothing.
 *
 * The columns are the exchange's own record: its reason CODE with the
 * published wording beside it, the time it stopped the stock, and when it
 * said quoting and trading would resume. Nothing here is computed. */
function HaltsTable() {
  const { add } = useBoardSymbols()
  const q = useQuery({
    queryKey: ["halts"],
    queryFn: () => api.halts(60),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  })
  const rows = q.data?.halts ?? null
  const clock = (iso: string | null) => {
    if (!iso) return "—"
    const at = new Date(iso)
    return Number.isNaN(at.getTime()) ? "—"
      : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
  }
  if (q.isPending) return <Empty>loading…</Empty>
  // The source answers nothing when it is not switched on, and raises when
  // it is on and unreachable — the second is an error, so the two read
  // differently here rather than both as a quiet day (2026-09-23).
  if (q.isError) return <QueryFailure error={q.error}>the halt feed could not be read</QueryFailure>
  if (!rows || rows.length === 0) {
    return (
      <Empty>
        No halts today — or the Nasdaq source is off. No vendor sells halts, so
        it is the one thing that source is for: switch it on from the Account page.
      </Empty>
    )
  }
  return (
    <Table>
      <THead>
        <TH className="w-[80px]" title="The halted stock. Click to put it on your board">Symbol</TH>
        <TH className="w-[76px]" title="When the exchange stopped it, New York time">Halted</TH>
        <TH className="w-[68px]" title="The exchange's own code. Read the code, not the prose: LUDP says only that the price moved fast, T1 is news pending, H10 an SEC suspension">Code</TH>
        <TH title="The exchange's published wording for that code, where it publishes one">Reason</TH>
        <TH align="right" className="w-[104px]" title="When trading was set to resume. A halt that began on an earlier day and has not resumed is a SUSPENSION, not a pause — most unresumed rows are those, some for years">Resumes</TH>
      </THead>
      <tbody>
        {rows.map((h, i) => (
          <TR key={`${h.symbol}-${h.halted_at}-${i}`} onClick={() => add(h.symbol)}>
            <TD mono className="truncate font-semibold" title={h.name ?? undefined}>{h.symbol}</TD>
            <TD mono className="text-muted-foreground" title={`${h.halted_at} (${h.timezone})`}>
              {/* A halt from an earlier day shows its DATE: a time alone
                  would read as this morning, and some of these are years
                  old (2026-09-23). */}
              {h.today ? clock(h.halted_at)
                : new Date(h.halted_at).toLocaleDateString([], { year: "2-digit", month: "short", day: "numeric" })}
            </TD>
            <TD mono className="text-muted-foreground">{h.reason_code ?? "—"}</TD>
            <TD className="truncate" title={h.reason ?? "the exchange publishes no wording for this code"}>
              {h.reason ?? <span className="text-muted-foreground">code only</span>}
            </TD>
            <TD align="right" mono
                className={h.resumed ? "text-muted-foreground"
                  : h.standing ? "text-muted-foreground" : "font-semibold text-warn"}
                title={h.standing
                  ? "Stopped on an earlier day and never resumed — a suspension, not a pause in today's trading"
                  : undefined}>
              {h.resumed ? clock(h.resumption_trade_at) : h.standing ? "suspended" : "still halted"}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  )
}

function MoversTable({ rows, empty, changeHead = "1D", changeTip, linkable = true, options = false, rank = null, nameHead = "Name",
  volTip = "Annualised volatility of daily returns over the last twenty sessions",
  liqTip = "Average dollar volume a day over the last twenty sessions", liquidity = true, session = null }: {
  rows: CategoryMoverRow[]; empty?: string; changeHead?: string; linkable?: boolean
  /** The session these prices were struck in when it is not the regular one
   * ("Pre-market", "After hours", "Overnight", "Weekend"): the change is
   * then measured from the last close, and the volume beside it is that
   * closed session's, so both columns say so (2026-09-22). */
  session?: string | null
  /** What the Volatility and Liquidity columns measure, when not a stock's
   * twenty sessions: a coin's twenty days, a venue's own volume. */
  volTip?: string; liqTip?: string
  /** False where no traded volume exists to measure (2026-09-19): a
   * currency pair has no consolidated volume, a point on the yield curve
   * none at all. The column goes rather than standing empty. */
  liquidity?: boolean
  /** The name column's header: "Company" for stocks, "Currency" for pairs. */
  nameHead?: string
  /** The change column's description: what the change is measured from. */
  changeTip?: string
  /** What the tab ranks by, shown as an extra column so the order reads off
   * the table (2026-09-15): today's shares on an Active tab, contracts on
   * the options Active tab, today's dollars on a Dollar volume tab (and on a
   * coin list whose volume is already dollars). Null: no extra column. */
  rank?: "shares" | "contracts" | "dollars" | null
  /** Option contracts: the figures are the chain's — implied volatility and
   * the day's premium traded — so the headers say so. */
  options?: boolean
}) {
  const { add } = useBoardSymbols()
  const navigate = useNavigate()
  const prefetchChart = usePrefetchChart()
  const narrow = useNarrowViewport()
  // A stock, ETF or coin row joins the board; an option row opens the
  // chain at its underlying and expiry with the contract marked.
  const open = (r: CategoryMoverRow) => {
    if (options) {
      if (r.underlying && r.expiry) {
        navigate(`/options?symbol=${encodeURIComponent(r.underlying)}&expiry=${encodeURIComponent(r.expiry)}&contract=${encodeURIComponent(r.symbol)}`)
      }
      return
    }
    add(r.symbol)
  }
  if (!rows.length) {
    return <Empty>{empty ?? "nothing to list right now"}</Empty>
  }
  const bonds = changeHead.includes("bp")
  // The name as the vendor gives it, between the symbol and the price
  // (2026-09-19, the owner's request). Not for an option or a Treasury
  // tenor, whose name only restates the symbol, nor a list with no names
  // (the crypto feed carries none).
  const named = !options && !bonds && rows.some(r => r.name && r.name !== r.display)
  // Column shares are set at the table's minimum width. With a name column
  // the figures keep fixed pixels and the name takes every pixel left: at
  // least 96 on a desktop, because a half-width tile at 1440 is 573px and a
  // wider floor pushed Liquidity out of sight; 160 on a phone, where the
  // table scrolls sideways anyway. Symbol and Last narrow to 80 and 84 there
  // (the widest ticker and stock price measured 78 and 75 with padding).
  // Without a name column, the shares grow together.
  const base = rank ? (options ? 570 : 500) : 420
  const nameW = !named ? 0 : narrow ? 160 : 96
  // Without Liquidity (18% of a five-column table) the other shares grow to
  // fill its place, and the minimum width loses its pixels.
  const liqPct = liquidity ? 0 : 18
  const share = (pct: number) => named ? `${Math.round(pct * base / 100)}px` : `${(pct * 100 / (100 - liqPct)).toFixed(2)}%`
  const figures = (named ? base - Math.round((rank ? 18 : 22) * base / 100) + 80
    - Math.round((rank ? 20 : 22) * base / 100) + 84 : base) - Math.round(liqPct * base / 100)
  return (
    // Five columns need ~420px, six ~500px (~570px for options, the half-width tile at 1440); with a name column see below;
    // a narrower panel scrolls them
    // sideways rather than overlapping the headers. Each share is set so its header and figures
    // fit at the minimum: "Volatility" is 76px wide in caps, "Liquidity" 68, "Contracts" 90, and
    // a three-digit move ("+804.49%") 78 (measured 2026-09-19 — at 360px the headers got 54 and
    // 61 and ran into each other on a phone, and a two-digit move was cut to "+16.8…").
    <div className="overflow-x-auto"><div style={{ minWidth: figures + nameW }}>
    <Table>
      <THead>
        {/* Six columns: an option's name ("SPY 757P 09-15") and its longer
            headers ("Contracts", "Implied vol.") need their own widths, and
            Last, the narrowest figure, gives them the room. */}
        <TH width={named ? "80px" : share(!rank ? 22 : options ? 22 : 18)} title={
          options ? "The contract: underlying, strike, call (C) or put (P), and expiry. Click a row to open it in the option chain"
          : bonds ? "The Treasury maturity on the par yield curve"
          : !linkable ? "The currency pair: the price of one unit of the first currency in the second"
          : "The ticker. Hover a row for the full name; click it to add the symbol to the board"}>Symbol</TH>
        {named && <TH
          title="The name the data vendor lists for the symbol. Hover a row for the whole of it">{nameHead}</TH>}
        <TH align="right" width={named ? "84px" : undefined} title={bonds ? "The par yield at that maturity, in percent, from the latest curve the Treasury published"
          : options ? "The contract's last traded price, per share; one contract covers 100 shares"
          : "The latest price"}>Last</TH>
        <TH align="right" width={share(!rank ? 19 : options ? 14 : 16)} title={
          changeTip ?? (bonds ? "Change in yield since the previous business day's curve, in basis points: one basis point is 0.01 percentage point"
          : changeHead === "24h" ? "Change over the last 24 hours. Crypto trades around the clock, so there is no daily close to measure from"
          : session ? `Change since the last close. These prices were struck in the ${session.toLowerCase()} session; a row that has not traded since the bell shows the closed session's own move`
          : "Change since the previous session's close")}>{changeHead}</TH>
        {/* The figure the tab ranks by, beside the day's change (2026-09-15):
            an extra column, so Liquidity and Premium stay on every tab. */}
        {rank && (
          <TH align="right" width={share(options ? 16 : 15)} title={
            session ? `${rank === "shares" ? "Shares" : rank === "contracts" ? "Contracts" : "Dollars"} traded in the last regular session — what this tab is ranked by. Extended-hours volume is not counted`
            : rank === "shares" ? "Shares traded today — what this tab is ranked by"
            : rank === "contracts" ? "Contracts traded today — what this tab is ranked by"
            : "Dollars traded — what this tab is ranked by"}>
            {rank === "shares" ? "Volume" : rank === "contracts" ? "Contracts" : "Traded"}
          </TH>
        )}
        {/* Spelled out: "Vol" reads as volume on every other grid. */}
        <TH align="right" width={share(!rank ? 19 : 16)} title={options ? "Implied volatility: the annualised move the option's price implies for the stock, from the chain snapshot" : volTip}>{options ? "Implied vol." : "Volatility"}</TH>
        {liquidity && <TH align="right" width={share(!rank ? 18 : 15)} title={options ? "Premium traded today: contracts × price × 100"
          : liqTip}>{options ? "Premium" : "Liquidity"}</TH>}
      </THead>
      <tbody>
        {rows.map(r => {
          const up = (r.change_pct ?? 0) >= 0
          const decimals = r.price != null ? priceDecimals(r.price, named) : 2
          return (
            <TR key={r.symbol} onClick={linkable || (options && !!r.underlying) ? () => open(r) : undefined}
                onRest={linkable && !options ? () => prefetchChart(r.symbol) : undefined}>
              <TD className="truncate font-semibold" title={r.name ?? undefined}>{r.display}</TD>
              {named && <TD className="truncate text-muted-foreground" title={r.name ?? undefined}>{r.name && r.name !== r.display ? r.name : "—"}</TD>}
              <TD align="right" mono>
                {r.price != null ? <Flash value={r.price}>{bonds ? `${num(r.price, 2)}%` : num(r.price, decimals)}</Flash> : "—"}
              </TD>
              <TD align="right" mono className={`font-semibold ${up ? "text-gain" : "text-loss"}`}
                  title={!session ? undefined
                    : r.extended ? `${session}, since the last close${r.extended_at ? ` · ${new Date(r.extended_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}${r.regular_pct != null ? ` · the closed session itself: ${moveText(r.regular_pct)}` : ""}`
                    : "No trade since the closing bell — this is the closed session's own move"}>
                {r.change_pct == null ? "—" : bonds
                  ? `${up ? "+" : ""}${r.change_pct.toFixed(1)}`
                  : moveText(r.change_pct)}
              </TD>
              {rank && (
                <TD align="right" mono>
                  {rank === "dollars" ? (r.turnover ? `$${compact(r.turnover)}` : "—")
                    : r.volume ? compact(r.volume).replace(/\.00(?=[KMBT]?$)/, "") : "—"}
                </TD>
              )}
              <TD align="right" mono className="text-muted-foreground">{r.volatility == null ? "—" : `${r.volatility.toFixed(0)}${bonds ? "bp" : "%"}`}</TD>
              {liquidity && <TD align="right" mono className="text-muted-foreground">{r.liquidity == null ? "—" : `$${compact(r.liquidity)}`}</TD>}
            </TR>
          )
        })}
      </tbody>
    </Table>
    </div></div>
  )
}

const CATEGORY_LABELS: Record<MoverCategory, string> = {
  stocks: "Stocks", crypto: "Crypto", etfs: "ETFs", options: "Options",
  indices: "Market ETFs", bonds: "Treasury yields", currencies: "Currencies",
}
const SOURCE_LABELS: Record<string, string> = {
  coingecko: "CoinGecko", alpaca: "Alpaca", treasury: "US Treasury",
  polygon: "Polygon", finnhub: "Finnhub", alphavantage: "Alpha Vantage", fmp: "FMP",
}

/** ONE movers tile, seven categories, with a category picker (2026-09-12).
 * A tile starts on its registered category and the reader can switch it
 * from the header; the board keeps as many tiles as it likes, each on its
 * own category. Every category but Treasury yields answers from the
 * reader's own data key (2026-09-13); a category none of their vendors
 * carries shows a prompt naming the vendors that do. Treasury yields are
 * the US Treasury's public par curve, keyless. */
type Floors = { min_price: number; min_turnover: number; min_liquidity: number; min_volatility: number }

/** The reader's floors for one tile and category, kept in the browser. */
function floorsKey(tile: string, category: MoverCategory) { return `alphadesk.movers.${tile}.${category}` }
function readFloors(tile: string, category: MoverCategory): Floors | null {
  try {
    const raw = localStorage.getItem(floorsKey(tile, category))
    if (!raw) return null
    const p = JSON.parse(raw)
    return typeof p?.min_price === "number" && typeof p?.min_turnover === "number"
      ? { min_price: p.min_price, min_turnover: p.min_turnover, min_liquidity: p.min_liquidity ?? 0, min_volatility: p.min_volatility ?? 0 } : null
  } catch { return null }
}
function writeFloors(tile: string, category: MoverCategory, f: Floors | null) {
  try { f ? localStorage.setItem(floorsKey(tile, category), JSON.stringify(f)) : localStorage.removeItem(floorsKey(tile, category)) } catch { /* private mode */ }
}


/** The filter row: a price floor and a turnover floor, applied to the
 * tile's category and remembered per tile (2026-09-12: "let's have that
 * filter option in the UI too"). Reset returns the category's defaults. */
/** The floors, as a popover hung from the Filter button in the same
 * style as the chart toolbar's menus (2026-09-13, after two inline forms
 * the reader did not like): four rows, label left and a unit-marked
 * field right, a footer with Reset and Apply. Enter applies, Escape
 * closes. Module-level row component, so the input keeps its cursor. */
function FloorRow({ label, hint, unit, value, onChange, onKey, bad }: {
  label: string; hint: string; unit: "$" | "%"; value: string; onChange: (v: string) => void
  onKey: (e: React.KeyboardEvent) => void; bad: boolean
}) {
  return (
    <label className="flex items-center justify-between gap-3 px-3 py-1.5" title={hint}>
      <span className="text-caption text-muted-foreground">{label}</span>
      <span className={`flex h-[24px] w-[96px] items-center rounded-md border bg-panel ${bad ? "border-loss" : "border-border"} focus-within:border-foreground/60`}>
        {unit === "$" && <span className="pl-2 text-label text-muted-foreground">$</span>}
        <input value={value} onChange={e => onChange(e.target.value)} onKeyDown={onKey} inputMode="decimal"
               className="num min-w-0 flex-1 bg-transparent px-2 text-right text-caption text-foreground outline-none" aria-label={`${label} floor`} />
        {unit === "%" && <span className="pr-2 text-label text-muted-foreground">%</span>}
      </span>
    </label>
  )
}

function FloorsPopover({ floors, defaults, onApply, onClose }: {
  floors: Floors; defaults: Floors; onApply: (f: Floors | null) => void; onClose: () => void
}) {
  const [price, setPrice] = useState(String(floors.min_price))
  const [turn, setTurn] = useState(moneyIn(floors.min_turnover))
  const [liq, setLiq] = useState(moneyIn(floors.min_liquidity))
  const [vol, setVol] = useState(String(floors.min_volatility))
  const parsed = { p: moneyOut(price), t: moneyOut(turn), l: moneyOut(liq), v: moneyOut(vol.replace("%", "")) }
  const valid = parsed.p != null && parsed.t != null && parsed.l != null && parsed.v != null
  const apply = () => {
    if (!valid) return
    onApply({ min_price: parsed.p!, min_turnover: parsed.t!, min_liquidity: parsed.l!, min_volatility: parsed.v! }); onClose()
  }
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") apply(); if (e.key === "Escape") onClose() }
  const defaultsNote = [defaults.min_price ? `$${defaults.min_price}` : null,
                        defaults.min_turnover ? `$${moneyIn(defaults.min_turnover)} turnover` : null].filter(Boolean).join(" · ") || "none"
  return (
    <div className="w-[264px]">
      <div className={menuHeadCls}>Floors · at least</div>
      <FloorRow label="Price" hint="Last price" unit="$" value={price} onChange={setPrice} onKey={onKey} bad={parsed.p == null} />
      <FloorRow label="Turnover" hint="Today's dollar turnover" unit="$" value={turn} onChange={setTurn} onKey={onKey} bad={parsed.t == null} />
      <FloorRow label="Liquidity" hint="Average dollar volume a day over the last twenty sessions" unit="$" value={liq} onChange={setLiq} onKey={onKey} bad={parsed.l == null} />
      <FloorRow label="Volatility" hint="Annualised volatility over the last twenty sessions" unit="%" value={vol} onChange={setVol} onKey={onKey} bad={parsed.v == null} />
      <div className="mt-1 flex items-center gap-1.5 border-t border-row-rule px-3 pb-1.5 pt-2">
        <span className="mr-auto text-label text-muted-foreground" title={`Reset returns the category's defaults: ${defaultsNote}`}>K, M, B accepted</span>
        <button type="button" onClick={() => { onApply(null); onClose() }}
                className={btnCls()}>Reset</button>
        <button type="button" onClick={apply} disabled={!valid}
                className={btnCls({ variant: "accent" })}>Apply</button>
      </div>
    </div>
  )
}

/** Every list asks for fifty, the server's own cap, and the tile grows to
 * hold all of them (2026-09-17, the owner's call — it went 20, then 30 for
 * stocks with a button for the rest, then fifty in a scrolling tile, then
 * this). No inner scroller: at 31px a row the tile runs to about 1,600px
 * and the reader scrolls the BOARD, which is the one scrollbar the page
 * already had. A category with less to show, like the twelve Treasury
 * tenors, sizes to what it has. */
const MOVERS_TOP = 50

function CategoryMoversTile({ initial, title }: { initial: MoverCategory; title: string }) {
  const category = initial
  const [tab, setTab] = useState<string | null>(null)
  const [floors, setFloorsState] = useState<Floors | null>(() => readFloors(initial, initial))
  const setFloors = (f: Floors | null) => { setFloorsState(f); writeFloors(initial, category, f) }
  const q = useQuery({
    queryKey: ["movers", category, floors?.min_price ?? "d", floors?.min_turnover ?? "d"],
    queryFn: () => api.categoryMovers(category, MOVERS_TOP, floors),
    staleTime: 20_000,
    // The server rebuilds behind a cached payload every 30s for stocks,
    // crypto and indices, so the tile asks on the same cycle; the listed
    // lists and options every two minutes, Treasury yields every fifteen
    // (the curve is published once a day).
    // While the server says the lists are still filling in, every few
    // seconds until the full lists arrive (2026-09-17).
    refetchInterval: query => query.state.data?.filling ? 3_000
      : category === "bonds" ? 900_000
      : category === "stocks" || category === "crypto" || category === "indices" ? 30_000 : 120_000,
    refetchIntervalInBackground: true,
  })
  // HALTS SIT BESIDE THE MOVERS FOR STOCKS (2026-09-23). A halt is market
  // activity on a symbol, which is this tile's subject — and it is the one
  // thing here no vendor sells, so the tab is always offered and says how to
  // switch the source on rather than hiding when it is off.
  const vendorTabs = q.data?.tabs ?? []
  const tabs = category === "stocks"
    ? [...vendorTabs, { id: "halts", label: "Halts", rows: [] as CategoryMoverRow[] }]
    : vendorTabs
  const halted = tab === "halts" && category === "stocks"
  const active = tabs.find(t => t.id === tab) ?? tabs[0]
  const rows = useMemo(() => (halted ? [] : active?.rows ?? []), [active, halted])
  // Live prices where a stream exists: the equity stream for stocks and
  // ETFs, the crypto stream for coins. A tick moves the price AND the
  // day's change: the snapshot's price and change fix the previous close,
  // and the change is re-read against it from the live price. The rank
  // stays the server's until its next cycle — rows never reshuffle under
  // the cursor on a tick.
  const streamable = category === "stocks" || category === "etfs"
  const symbols = useMemo(() => (streamable ? rows.map(r => r.symbol) : []), [rows, streamable])
  const live = useLiveQuotes(symbols)
  // The coins on screen, and none for any other category.
  const coins = useMemo(() => (category === "crypto" ? rows.map(r => r.symbol) : []), [rows, category])
  const cryptoTicks = useCryptoTicks(coins)
  const priced = useMemo(() => rows.map(r => {
    const livePrice = streamable
      ? (live[r.symbol] && !live[r.symbol].stale ? live[r.symbol].price : null)
      : category === "crypto" ? (cryptoTicks[r.symbol] && !cryptoTicks[r.symbol].stale ? cryptoTicks[r.symbol].price : null)
      : null
    if (livePrice == null) return r
    const prev = r.price != null && r.change_pct != null && r.change_pct > -100
      ? r.price / (1 + r.change_pct / 100) : null
    return { ...r, price: livePrice,
      change_pct: prev ? Math.round((livePrice / prev - 1) * 10000) / 100 : r.change_pct }
  }), [rows, live, cryptoTicks, streamable, category])
  const subtitle = q.data?.source
    ? `${q.data.change_label === "24h" ? "rolling 24h" : q.data.change_label === "1D bp" ? "daily curve · change in bp"
        : category === "currencies" ? "since 5pm New York"
        : q.data.session_label ? `${q.data.session_label.toLowerCase()} · since the last close` : "session"} · ${SOURCE_LABELS[q.data.source] ?? q.data.source}${q.data.official === false ? " · scraped" : ""}${q.data.filling ? " · filling in…" : ""}`
    : q.isPending ? "loading…" : isNeedsKey(q.error) ? "needs a data key" : "unavailable right now"
  return (
    <Widget
      // Two tiles to a row: five columns at a third of the board truncated
      // the liquidity figures (the reader's call, 2026-09-13).
      span={6}
      title={title}
      subtitle={subtitle}
      actions={q.data ? (
        <Menu label="Filter" align="right" chevron={false} active={!!floors}
              title={q.data.note ? `Floors: ${q.data.note}` : "Floors: none — set a price, turnover, liquidity or volatility floor"}>
          {close => (
            <FloorsPopover floors={{ min_price: q.data!.floors.min_price, min_turnover: q.data!.floors.min_turnover,
                                     min_liquidity: q.data!.floors.min_liquidity, min_volatility: q.data!.floors.min_volatility }}
                           defaults={{ min_price: q.data!.floors.default_min_price, min_turnover: q.data!.floors.default_min_turnover, min_liquidity: 0, min_volatility: 0 }}
                           onApply={setFloors} onClose={close} />
          )}
        </Menu>
      ) : undefined}
      toolbar={tabs.length > 1 ? <TabStrip tabs={tabs.map(t => ({ id: t.id, label: t.label }))} value={active?.id ?? ""} onChange={setTab} /> : undefined}
    >
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the {CATEGORY_LABELS[category].toLowerCase()} list is unavailable right now</QueryFailure>
        // A currency pair or a Treasury tenor is not a symbol the board can
        // chart, so those rows do not open anything.
        : <>
        {halted ? <HaltsTable /> : <MoversTable rows={priced} changeHead={q.data?.change_label ?? "1D"} session={q.data?.session_label ?? null}
                       changeTip={category === "currencies" ? "Change since the 5pm New York rollover, where the currency trading day begins" : undefined}
                       {...(category === "crypto" ? {
                         volTip: "Annualised volatility of daily returns over the last twenty days — coins trade every day, so a year is 365 of them",
                         liqTip: q.data?.liquidity_scope === "venue"
                           ? `Average dollar volume a day over the last twenty days on ${SOURCE_LABELS[q.data.source ?? ""] ?? q.data.source}'s own exchange only — worldwide volume is far larger`
                           : "Dollar volume traded worldwide over the last 24 hours",
                       } : category === "currencies" ? {
                         volTip: "Annualised volatility of daily returns over the last twenty trading days",
                         liquidity: false,
                       } : category === "bonds" ? {
                         volTip: "How much the yield moves in a year, in basis points: the standard deviation of its last twenty daily changes, annualised",
                         liquidity: false,
                       } : {})}
                       nameHead={category === "stocks" ? "Company" : category === "currencies" ? "Currency" : "Name"}
                       linkable={category !== "options" && category !== "currencies" && category !== "bonds"} options={category === "options"}
                       rank={active?.id === "dollar_volume" ? "dollars"
                         : active?.id === "most_active"
                           // A coin list's volume is dollars (CoinGecko) or one venue's coins (Alpaca, no Active tab).
                           ? (category === "options" ? "contracts" : category === "crypto" ? "dollars" : "shares")
                           : null}
                       empty={active?.id === "losers" ? "nothing is down" : active?.id === "gainers" ? "nothing is up" : `no ${CATEGORY_LABELS[category].toLowerCase()} quotes right now`} />}
        {/* CoinGecko's paid plans require the credit wherever their data
            shows (2026-09-19); the coin list is theirs when they answered. */}
        {q.data?.source === "coingecko" && (
          <p className="order-last border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
            <a href="https://www.coingecko.com" target="_blank" rel="noreferrer"
               className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">Powered by CoinGecko</a>
          </p>
        )}
        </>}
    </Widget>
  )
}

function KeyStatsTile() {
  const [params] = useSearchParams()
  const symbol = (params.get("symbol") || "").toUpperCase()
  if (!symbol) return <Widget span={12} title="Key statistics"><Empty>Pick a symbol to scope this board.</Empty></Widget>
  return <KeyStatisticsPanel symbol={symbol} span={12} />
}
registerWidget({ id: "key-stats", label: "Key statistics", order: 12.5, optIn: true, component: KeyStatsTile })

const StockMovers = () => <CategoryMoversTile initial="stocks" title="Stock Movers" />
/** The Sectors page's Market ETFs panel. Not a Markets board tile since
 * 2026-09-15 (the reader's call): it lives on Sectors only, and a saved
 * board or view that named it simply no longer shows it. */
export const IndexMovers = () => <CategoryMoversTile initial="indices" title="Market ETFs" />
const CryptoMovers = () => <CategoryMoversTile initial="crypto" title="Crypto Movers" />
const CurrencyMovers = () => <CategoryMoversTile initial="currencies" title="Currency Movers" />
const EtfMovers = () => <CategoryMoversTile initial="etfs" title="ETF Movers" />
const OptionMovers = () => <CategoryMoversTile initial="options" title="Option Movers" />
const BondMovers = () => <CategoryMoversTile initial="bonds" title="Treasury Yields" />

registerWidget({ id: "equity-overview", label: "Equity overview", order: 13, component: EquityOverview })
registerWidget({ id: "stock-movers", label: "Stock movers", order: 17, component: StockMovers })
registerWidget({ id: "crypto-movers", label: "Crypto movers", order: 18, component: CryptoMovers })
registerWidget({ id: "currency-movers", label: "Currency movers", order: 18.1, component: CurrencyMovers })
// In the place Market ETFs held, beside Stock movers (2026-09-15).
registerWidget({ id: "related-funds", label: "Funds on this stock", order: 14.5, component: RelatedFundsTile })
registerWidget({ id: "etf-movers", label: "ETF movers", order: 16, component: EtfMovers })
registerWidget({ id: "option-movers", label: "Option movers", order: 18.5, component: OptionMovers })
registerWidget({ id: "bond-movers", label: "Treasury yields", order: 18.6, component: BondMovers })
