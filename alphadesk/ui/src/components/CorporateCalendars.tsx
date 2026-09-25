import { Fragment, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { compact } from "@/components/Treemap"
import { api, type CorporateCalendar, type DividendEvent, type IpoEvent, type SplitEvent } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { vendorLabel } from "@/lib/vendors"
import { Btn, Empty, Table, TD, TH, THead, TR, Widget } from "@/components/terminal"

/** Market-wide corporate calendars (2026-09-14): who goes ex-dividend,
 * who splits, who lists — a week at a time, like the economic calendar
 * beside them. Each is a KEYED surface (FMP's corporate calendars, Premium
 * and up): without a vendor that carries it the panel shows the key
 * prompt. A symbol click puts the company on the board. */

const dash = "—"
const isoDate = (d: Date) => d.toISOString().slice(0, 10)
const shift = (day: string, days: number) => { const d = new Date(day + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + days); return isoDate(d) }
/** The Monday of the week holding `day`. */
const weekStart = (day: string) => { const d = new Date(day + "T12:00:00Z"); const off = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - off); return isoDate(d) }
const dayLabel = (day: string) => new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { timeZone: "UTC", weekday: "long", month: "short", day: "numeric" })
const shortDay = (day: string | null) => day ? new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" }) : dash
const money = (v: number | null, d = 2) => v == null ? dash : `$${v.toFixed(v < 1 ? 4 : d).replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1")}`

function useWeek() {
  const [start, setStart] = useState(() => weekStart(isoDate(new Date())))
  const end = shift(start, 6)
  const nav = (
    <div className="flex items-center gap-1">
      <Btn onClick={() => setStart(s => shift(s, -7))} title="Previous week">‹</Btn>
      {/* THE WEEK ON SCREEN, NOT A BUTTON PRETENDING TO BE ONE (2026-09-25,
          #77). It was labelled "Today" (#75 made it "This week"), and the
          reader's second look found the real fault: "as i go left and right,
          it just shows this weak thats why". A fixed label between two
          arrows reads as a STATEMENT about what is displayed — so paging to
          October still said "This week", and every row felt like today's.
          The dates shown are the honest label, and the way back only exists
          when there is somewhere to come back FROM: its presence is itself
          the sign that this is not the current week. */}
      <span className="px-1 text-caption tabular-nums text-muted-foreground">
        {shortDay(start)} – {shortDay(shift(start, 6))}
      </span>
      <Btn onClick={() => setStart(s => shift(s, 7))} title="Next week">›</Btn>
      {start !== weekStart(isoDate(new Date())) && (
        <Btn onClick={() => setStart(weekStart(isoDate(new Date())))}
             title="Jump back to the week containing today">This week</Btn>
      )}
    </div>
  )
  return { start, end, nav }
}

function useCalendar<T>(kind: string, start: string, end: string, fetcher: (s: string, e: string) => Promise<CorporateCalendar<T>>) {
  return useQuery({
    queryKey: ["calendar", kind, start, end],
    queryFn: () => fetcher(start, end),
    staleTime: 30 * 60_000,
    refetchInterval: 30 * 60_000,
    refetchIntervalInBackground: true,
    retry: false,
  })
}

function groupBy<T>(rows: T[], day: (r: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>()
  for (const r of rows) m.set(day(r), [...(m.get(day(r)) ?? []), r])
  return [...m.entries()]
}

function subtitle(start: string, end: string, n: number | undefined, noun: string, source: string | null | undefined) {
  const range = `${shortDay(start)} – ${shortDay(end)}`
  return n == null ? range : `${range} · ${n} ${noun}${source ? ` · ${vendorLabel(source)}` : ""}`
}

function DayRow({ day, cols }: { day: string; cols: number }) {
  return (
    <tr>
      <TD colSpan={cols} className="bg-card pt-4 text-caption font-extrabold uppercase tracking-caps text-foreground">{dayLabel(day)}</TD>
    </tr>
  )
}

export function DividendCalendarPanel({ span = 12 }: { span?: number }) {
  const { start, end, nav } = useWeek()
  const q = useCalendar("dividends", start, end, api.dividendCalendar)
  const { add } = useBoardSymbols()
  const rows = q.data?.rows ?? []
  const groups = useMemo(() => groupBy<DividendEvent>(rows, r => r.ex_date), [rows])
  return (
    <Widget span={span} title="Dividend calendar" scroll={380} fitViewport={false} actions={nav}
            subtitle={subtitle(start, end, q.data?.rows.length, "ex-dividends, largest companies first", q.data?.source)}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the dividend calendar is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no ex-dividend dates in this week</Empty> : (
        <div className="overflow-x-auto"><div className="min-w-[800px]">
        <Table>
          <THead>
            <TH className="w-[76px]" title="The ticker. Click a row to add it to the board">Symbol</TH>
            <TH title="The company name">Company</TH>
            <TH align="right" className="w-[80px]" title="Market capitalisation today, from your company data vendor. Each day lists the largest companies first">Mkt cap</TH>
            <TH align="right" className="w-[80px]" title="Cash per share for this payment">Amount</TH>
            <TH align="right" className="w-[64px]" title="Annualised yield at the vendor's last price">Yield</TH>
            <TH className="w-[84px]" title="How often the company pays a dividend">Frequency</TH>
            <TH className="w-[70px]" title="Holders of record on this date receive the dividend">Record</TH>
            <TH className="w-[70px]" title="The day the cash is paid">Paid</TH>
            <TH align="right" className="w-[80px]" title="Average dollar volume a day over the last twenty sessions, from your chart vendor">Liquidity</TH>
          </THead>
          <tbody>
            {groups.map(([day, evs]) => (
              <Fragment key={day}>
                <DayRow day={day} cols={9} />
                {evs.map(r => (
                  <TR key={`${day}:${r.symbol}`} onClick={() => add(r.symbol)}>
                    <TD className="font-semibold">{r.symbol}</TD>
                    <TD className="truncate text-muted-foreground" title={r.company_name ?? undefined}>{r.company_name ?? dash}</TD>
                    <TD align="right" mono>{r.market_cap == null ? dash : `$${compact(r.market_cap)}`}</TD>
                    <TD align="right" mono>{money(r.amount)}</TD>
                    <TD align="right" mono>{r.yield_pct == null ? dash : `${r.yield_pct.toFixed(2)}%`}</TD>
                    <TD className="text-muted-foreground">{r.frequency ?? dash}</TD>
                    <TD mono className="text-muted-foreground">{shortDay(r.record_date)}</TD>
                    <TD mono className="text-muted-foreground">{shortDay(r.payment_date)}</TD>
                    <TD align="right" mono className={r.low_liquidity ? "text-warn" : "text-muted-foreground"}
                        title={r.low_liquidity ? "Under $10M a day" : undefined}>
                      {r.liquidity == null ? dash : `$${compact(r.liquidity)}`}
                    </TD>
                  </TR>
                ))}
              </Fragment>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}

const ratio = (r: SplitEvent) => {
  if (!r.to || !r.from) return dash
  const n = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(2))
  return `${n(r.to)}-for-${n(r.from)}`
}

/** Why a split one vendor lists alone is hidden until asked for. */
function singleSourceTitle(r: SplitEvent, vendors: string[]): string {
  const who = vendorLabel(r.sources?.[0]) ?? "One vendor"
  const others = vendors.filter(v => !r.sources?.includes(v)).map(v => vendorLabel(v) ?? v).join(" and ")
  return `Only ${who} lists this split; ${others || "your other vendor"} does not. When checked, some splits only one vendor listed never took effect, so this one is hidden by default and does not rescale earnings estimates`
}

export function SplitCalendarPanel({ span = 6 }: { span?: number }) {
  const { start, end, nav } = useWeek()
  const q = useCalendar("splits", start, end, api.splitCalendar)
  const { add } = useBoardSymbols()
  // A split only one of two vendors lists is a claim, not an event: hidden
  // until the reader asks. With one vendor nothing is checked or hidden.
  const [showSingle, setShowSingle] = useState(false)
  const vendors = q.data?.vendors ?? []
  const all = q.data?.rows ?? []
  const single = all.filter(r => r.corroborated === false).length
  const rows = showSingle ? all : all.filter(r => r.corroborated !== false)
  const groups = useMemo(() => groupBy<SplitEvent>(rows, r => r.date), [rows])
  const toggle = single > 0 && (
    <button type="button" onClick={() => setShowSingle(v => !v)}
            className="whitespace-nowrap text-label text-accent-700 hover:underline"
            title={showSingle ? "Hide the splits only one of your split vendors lists" : "Show the splits only one of your split vendors lists"}>
      {showSingle ? "hide 1-source" : `+${single} 1-source`}
    </button>
  )
  return (
    <Widget span={span} title="Stock splits" scroll={420} actions={<div className="flex items-center gap-2">{toggle}{nav}</div>}
            subtitle={subtitle(start, end, rows.length, vendors.length > 1 ? "splits both vendors list" : "splits",
                               vendors.length > 1 ? null : q.data?.source)}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the split calendar is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>{single ? `no split both vendors list this week; ${single} listed by one vendor` : "no splits in this week"}</Empty> : (
        <Table>
          <THead>
            <TH className="w-[76px]" title="The ticker. Click a row to add it to the board">Symbol</TH>
            <TH title="The company name">Company</TH>
            <TH className="w-[150px] sm:w-[210px]" title="New shares for old: a 2-for-1 split doubles the share count; a reverse split combines shares into fewer">Ratio</TH>
          </THead>
          <tbody>
            {groups.map(([day, evs]) => (
              <Fragment key={day}>
                <DayRow day={day} cols={3} />
                {evs.map(r => (
                  <TR key={`${day}:${r.symbol}:${r.to}:${r.from}`} onClick={() => add(r.symbol)}>
                    <TD className={`font-semibold ${r.corroborated === false ? "text-muted-foreground" : ""}`}>{r.symbol}</TD>
                    <TD className="truncate text-muted-foreground" title={r.company_name ?? undefined}>{r.company_name ?? dash}</TD>
                    <TD mono>
                      {ratio(r)}
                      {r.reverse && <span className="ml-1.5 text-label font-medium uppercase tracking-caps text-warn">reverse</span>}
                      {r.corroborated === false && (
                        <span className="ml-1.5 text-label font-medium uppercase tracking-caps text-muted-foreground"
                              title={singleSourceTitle(r, vendors)}>1 src</span>
                      )}
                      {r.vendor_dates && (
                        <span className="ml-1.5 text-label font-medium uppercase tracking-caps text-muted-foreground"
                              title={`The vendors date it days apart; shown on Alpaca's date. ${Object.entries(r.vendor_dates).map(([v, d]) => `${vendorLabel(v) ?? v}: ${shortDay(d)}`).join(" · ")}`}>±date</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </Fragment>
            ))}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}

const KIND_TAG: Record<string, string> = { blank_check: "SPAC", fund: "Fund", other_security: "Other" }

/** FMP's status while the date is ahead; once it has passed, what the
 * reader's chart vendor shows — FMP left 119 of 134 past rows "Expected"
 * though they had started trading (2026-09-14). */
function IpoStatus({ r }: { r: IpoEvent }) {
  const vendorSaid = r.status ? `Your IPO calendar vendor lists it as ${r.status}.` : ""
  if (r.listing === "listed") {
    return <TD className="text-gain" title={`First traded ${shortDay(r.first_trade ?? null)}, on your chart vendor. ${vendorSaid}`}>Listed {shortDay(r.first_trade ?? null)}</TD>
  }
  if (r.listing === "no_trades") {
    return <TD className="text-warn" title={`The date has passed and your chart vendor shows no trades under this symbol: postponed, withdrawn, or listed under another symbol. ${vendorSaid}`}>No trades</TD>
  }
  if (r.listing === "already_trading") {
    return <TD className="text-muted-foreground" title={`It traded well before this date: an uplisting or a symbol change, not a new listing. ${vendorSaid}`}>Traded before</TD>
  }
  return <TD className="text-muted-foreground">{r.status ?? dash}</TD>
}

export function IpoCalendarPanel({ span = 6 }: { span?: number }) {
  const { start, end, nav } = useWeek()
  const q = useCalendar("ipos", start, end, api.ipoCalendar)
  const { add } = useBoardSymbols()
  // ETF launches and blank-check units, rights and warrants were 112 of 162
  // rows over six weeks (2026-09-14); company IPOs show by default.
  const [showAll, setShowAll] = useState(false)
  const all = q.data?.rows ?? []
  const others = all.filter(r => r.kind && r.kind !== "company").length
  const rows = showAll ? all : all.filter(r => !r.kind || r.kind === "company")
  const groups = useMemo(() => groupBy<IpoEvent>(rows, r => r.date), [rows])
  const toggle = others > 0 && (
    <button type="button" onClick={() => setShowAll(v => !v)}
            className="whitespace-nowrap text-label text-accent-700 hover:underline"
            title={showAll ? "Show company IPOs only" : "Also show ETF launches, blank-check companies and listed warrants or rights"}>
      {showAll ? "cos. only" : `+${others} ETF/SPAC`}
    </button>
  )
  const range = (r: IpoEvent) => r.price_low == null ? dash
    : r.price_high == null || r.price_high === r.price_low ? money(r.price_low) : `${money(r.price_low)}–${money(r.price_high)}`
  return (
    <Widget span={span} title="IPO calendar" scroll={420} actions={<div className="flex items-center gap-2">{toggle}{nav}</div>}
            subtitle={subtitle(start, end, rows.length, showAll ? "offerings" : "company offerings", q.data?.source)}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the IPO calendar is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>{others ? `no company offerings this week; ${others} ETFs and SPAC listings` : "no offerings scheduled in this week"}</Empty> : (
        <div className="overflow-x-auto"><div className="min-w-[560px]">
        <Table>
          <THead>
            <TH className="w-[70px]" title="The ticker the shares will trade under. Click a row to add it to the board">Symbol</TH>
            <TH title="The company name">Company</TH>
            <TH className="w-[70px]" title="The exchange the shares list on">Exchange</TH>
            <TH align="right" className="w-[92px]" title="The expected offer price per share, or the price once set">Price range</TH>
            <TH align="right" className="w-[72px]" title="Shares offered">Shares</TH>
            <TH align="right" className="w-[76px]" title="Shares times the middle of the price range">Deal size</TH>
            <TH className="w-[96px]" title="Once the date has passed, whether the symbol traded on your chart vendor">Status</TH>
          </THead>
          <tbody>
            {groups.map(([day, evs]) => (
              <Fragment key={day}>
                <DayRow day={day} cols={7} />
                {evs.map((r, i) => (
                  <TR key={`${day}:${r.symbol ?? i}`} onClick={r.symbol ? () => add(r.symbol!) : undefined}>
                    <TD className="font-semibold">{r.symbol ?? dash}</TD>
                    <TD className="truncate text-muted-foreground" title={r.company ?? undefined}>
                      {r.kind && r.kind !== "company" && (
                        <span className="mr-1.5 text-label font-medium uppercase tracking-caps">{KIND_TAG[r.kind]}</span>
                      )}
                      {r.company ?? dash}
                    </TD>
                    <TD className="text-muted-foreground">{r.exchange ?? dash}</TD>
                    <TD align="right" mono>{range(r)}</TD>
                    <TD align="right" mono className="text-muted-foreground">{r.shares == null ? dash : compact(r.shares)}</TD>
                    <TD align="right" mono>{r.deal_size == null ? dash : `$${compact(r.deal_size)}`}</TD>
                    <IpoStatus r={r} />
                  </TR>
                ))}
              </Fragment>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}
