import { useQuery } from "@tanstack/react-query"
import { vendorLabel } from "@/lib/vendors"
import { QueryFailure } from "@/components/KeyPrompt"
import { api, type KeyStats } from "@/lib/api"
import { compact } from "@/components/Treemap"
import { Empty, Widget } from "@/components/terminal"

/** The summary block for ONE symbol — the figures a quote page and
 * OpenBB's overview put in one place, in four columns: where the price
 * sits, how big and how traded it is, what it earns and what it pays. A
 * figure the record lacks reads as a dash, never as zero. */

const dash = "—"
const n2 = (v: number | null | undefined, d = 2) => (v == null ? dash : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }))
const big = (v: number | null | undefined, cur = "") => (v == null ? dash : `${cur}${compact(v)}`)
const pct = (v: number | null | undefined, d = 2) => (v == null ? dash : `${(v * 100).toFixed(d)}%`)
const x = (v: number | null | undefined) => (v == null ? dash : `${v.toFixed(2)}×`)

export function useKeyStats(symbol: string) {
  return useQuery({
    queryKey: ["keystats", symbol],
    queryFn: () => api.keyStats(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    refetchInterval: 10 * 60_000,
    refetchIntervalInBackground: true,
    retry: false,
  })
}

type Cell = [string, string, string?]   // label, value, tooltip

function Column({ title, cells }: { title: string; cells: Cell[] }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">{title}</div>
      {cells.map(([l, v, tip]) => (
        <div key={l} className="flex items-baseline justify-between gap-2 border-b border-row-rule py-1 text-body" title={tip}>
          <span className="truncate text-muted-foreground">{l}</span>
          <span className="shrink-0 font-medium tnum">{v}</span>
        </div>
      ))}
    </div>
  )
}

/** The 52-week range as a bar with the price on it. */
function RangeBar({ s }: { s: KeyStats }) {
  if (s.week52_low == null || s.week52_high == null || s.week52_position == null) return null
  return (
    <div className="mt-2 flex items-center gap-2 text-label tnum text-muted-foreground">
      <span>{n2(s.week52_low)}</span>
      <div className="relative h-[6px] flex-1 rounded-[3px] bg-muted/50">
        <div className="absolute top-[-3px] h-[12px] w-[2px] bg-foreground" style={{ left: `${s.week52_position}%` }} title={`${s.week52_position}% of the way from the 52-week low to the high`} />
      </div>
      <span>{n2(s.week52_high)}</span>
    </div>
  )
}

/** WHY SOME FIGURES HERE CARRY A DASH, AND WHY OTHERS LOOK ENORMOUS
 * (2026-09-23, #65). A company that has reverse-split repeatedly restates
 * every historical per-share figure retroactively, so a 52-week high of
 * $94,608 beside a $6.26 price is the vendor being FAITHFUL — Wheeler's own
 * SEC filings carry a diluted loss of $346,484 a share for 2024. Those stay,
 * and say what they are. What goes is the share count that contradicts the
 * enterprise value, and every ratio that divides today's price by one of
 * those restated per-share figures, which is two different share counts in
 * one fraction rather than a cheap stock. */
function BasisNote({ s }: { s: KeyStats }) {
  const b = s.basis
  if (!b || (!b.pre_split.length && !b.share_count.length)) return null
  const split = b.split
  return (
    <div className="mt-3 border-t border-row-rule px-0 pt-2 text-caption leading-[1.5] text-muted-foreground">
      <span className="font-semibold text-warn">Figures on this page do not share one basis.</span>{" "}
      {split && (
        <>
          {/* The convention is new-for-old: a 1-for-9 reverse split is one
              new share for every nine held. */}
          A {split.to}-for-{split.from} {split.reverse ? "reverse split" : "split"}
          {split.date ? ` took effect ${split.date}` : " took effect recently"}
          {/* The vendors' proper names, as everywhere else on the page —
              a bare "fmp and alpaca" is the wire name, not a label. */}
          {split.sources.length > 1
            ? `, listed by ${split.sources.map(vendorLabel).join(" and ")}`
            : ""}.{" "}
        </>
      )}
      {b.pre_split.length > 0 && (
        <>
          The 52-week range, the moving averages, earnings per share and book value are the
          vendor&rsquo;s own figures restated to an older share count — they are not wrong, but they
          cannot be compared with today&rsquo;s price. Measured here: {b.pre_split.join("; ")}. Every
          ratio between a current price and one of them has been withheld rather than shown.{" "}
        </>
      )}
      {b.share_count.length > 0 && (
        <>
          Market capitalisation, shares outstanding and float are withheld: the vendor reports{" "}
          {b.share_count.join("; ")}.
        </>
      )}
    </div>
  )
}

export function KeyStatisticsPanel({ symbol, span = 12, scroll = 420 }: { symbol: string; span?: number; scroll?: number | string }) {
  const q = useKeyStats(symbol)
  const s = q.data
  const cur = s?.currency === "USD" ? "$" : ""
  return (
    <Widget span={span} symbol={symbol} title="Key statistics" subtitle={s ? `${s.name ?? ""}${s.vendor ? ` · ${vendorLabel(s.vendor)}` : ""}` : undefined} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the summary record is unavailable right now</QueryFailure>
        : !s ? <Empty>no summary record for {symbol}</Empty> : (
        <div className="px-3 py-2">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
            <div className="min-w-0">
              <Column title="Price" cells={[
                ["Previous close", n2(s.previous_close)],
                ["Open", n2(s.open)],
                ["Day range", s.day_low != null && s.day_high != null ? `${n2(s.day_low)} – ${n2(s.day_high)}` : dash],
                ["50-day average", n2(s.avg_50d)],
                ["200-day average", n2(s.avg_200d)],
                ["Beta", n2(s.beta), "Sensitivity to the market over five years: 1 moves with it, 2 twice as much"],
              ]} />
              <div className="mt-2 text-label uppercase tracking-caps text-muted-foreground">52-week range</div>
              <RangeBar s={s} />
            </div>
            <Column title="Size and trading" cells={[
              ["Market cap", big(s.market_cap, cur)],
              ["Enterprise value", big(s.enterprise_value, cur), "Market cap plus debt, less cash"],
              ["Shares outstanding", big(s.shares_outstanding)],
              ["Float", big(s.float_shares), "Shares available to trade, insiders' holdings excluded"],
              ["Volume", big(s.volume)],
              ["Avg volume (3 mo)", big(s.avg_volume)],
              ["Avg volume (10 d)", big(s.avg_volume_10d)],
              ["Held by institutions", pct(s.held_institutions)],
              ["Held by insiders", pct(s.held_insiders)],
            ]} />
            <Column title="Valuation" cells={[
              ["P/E, trailing", x(s.trailing_pe)],
              ["P/E, forward", x(s.forward_pe)],
              ["PEG", n2(s.peg), "Forward P/E over expected earnings growth; 1 is fairly priced for its growth"],
              ["Price to sales", x(s.price_to_sales)],
              ["Price to book", x(s.price_to_book)],
              ["EV to EBITDA", x(s.ev_to_ebitda)],
              ["EPS, trailing", n2(s.trailing_eps)],
              ["EPS, forward", n2(s.forward_eps)],
              ["Book value / share", n2(s.book_value)],
            ]} />
            <Column title="Earnings and dividend" cells={[
              ["Revenue (ttm)", big(s.revenue, cur)],
              ["Profit margin", pct(s.profit_margin)],
              ["Return on equity", pct(s.return_on_equity)],
              ["Free cash flow", big(s.free_cash_flow, cur)],
              ["Cash", big(s.total_cash, cur)],
              ["Debt", big(s.total_debt, cur)],
              ["Dividend / yield", s.dividend_rate != null ? `${n2(s.dividend_rate)} · ${s.dividend_yield == null ? dash : `${s.dividend_yield.toFixed(2)}%`}` : dash],
              ["Payout ratio", pct(s.payout_ratio, 0)],
              ["Ex-dividend", s.ex_dividend_date ?? dash],
              ["Next earnings", s.earnings_date ?? dash],
            ]} />
          </div>
          <BasisNote s={s} />
        </div>
      )}
    </Widget>
  )
}
