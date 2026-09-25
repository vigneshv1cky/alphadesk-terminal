import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { on } from "@/lib/api"
import { Empty, Table, TD, TH, THead, Widget } from "@/components/terminal"

/** Dividend payments and stock splits for ONE symbol — the corporate-action
 * record OpenBB's "Company Calendar" board shows, drawn here as two panels
 * any page can place (the Profile and Earnings pages carry them by default;
 * the Markets board offers them as tiles).
 *
 * Every row comes from the reader's own vendors (Polygon, FMP, Alpha
 * Vantage, Finnhub); the record, payment and declaration dates fill in
 * when a vendor that carries them contributed, and stay blank
 * otherwise — the header names the sources, so an empty column reads as
 * absent, never as zero. */

const dash = "—"
/** A per-share amount: two decimals, four when it is under a dollar, with
 * trailing zeros trimmed. */
const money = (v: number | null | undefined) =>
  v == null ? dash : v.toFixed(v < 1 ? 4 : 2).replace(/0+$/, "").replace(/\.$/, "")

export function useCorporateActions(symbol: string) {
  return useQuery({
    queryKey: ["corporate-actions", symbol],
    queryFn: ({ signal }) => on(signal).corporateActions(symbol),
    enabled: !!symbol,
    staleTime: 60 * 60_000,   // declared once a quarter; the server holds it six hours
    retry: false,
  })
}

const SOURCE_LABEL: Record<string, string> = {
  polygon: "Polygon", alphavantage: "Alpha Vantage", finnhub: "Finnhub", fmp: "Financial Modeling Prep",
}
export const sourceLine = (sources: string[] | undefined) =>
  sources && sources.length ? sources.map(s => SOURCE_LABEL[s] ?? s).join(" · ") : undefined

type PanelProps = { symbol: string; span?: number; scroll?: number | string }

export function DividendsPanel({ symbol, span = 6, scroll = 420 }: PanelProps) {
  const q = useCorporateActions(symbol)
  const rows = q.data?.dividends ?? []
  const dated = rows.some(r => r.payment_date || r.record_date || r.declaration_date)
  const sub = sourceLine(q.data?.sources)
  return (
    <Widget span={span} symbol={symbol} title="Dividend payments"
            subtitle={sub ? `${sub}${dated ? "" : " · ex-date and amount only"}` : "cash dividends on record"}
            scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the dividend record is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no dividends on record</Empty> : (
        <Table>
          <THead>
            <TH className="w-[92px]" title="The first day the stock trades without this dividend: a buyer from this day on does not receive it">Ex-date</TH>
            <TH align="right" className="w-[76px]" title="As declared: what a holder was paid per share that day">Dividend</TH>
            <TH align="right" className="w-[76px]" title="Per today's share, restated through every later split">Adjusted</TH>
            <TH align="right" className="w-[92px]" title="Holders on the company's books on this day receive the dividend">Record</TH>
            <TH align="right" className="w-[92px]" title="The day the cash is paid">Payment</TH>
            <TH align="right" className="w-[92px]" title="The day the board announced the dividend">Declared</TH>
          </THead>
          <tbody>
            {rows.map(r => (
              <tr key={r.ex_date}>
                <TD mono>{r.ex_date}</TD>
                <TD align="right" mono className="text-gain">{money(r.amount)}</TD>
                <TD align="right" mono className="text-muted-foreground">{money(r.adjusted_amount)}</TD>
                <TD align="right" mono className="text-muted-foreground">{r.record_date ?? dash}</TD>
                <TD align="right" mono className="text-muted-foreground">{r.payment_date ?? dash}</TD>
                <TD align="right" mono className="text-muted-foreground">{r.declaration_date ?? dash}</TD>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}

export function SplitsPanel({ symbol, span = 4, scroll = 420 }: PanelProps) {
  const q = useCorporateActions(symbol)
  const rows = q.data?.splits ?? []
  return (
    <Widget span={span} symbol={symbol} title="Stock splits"
            subtitle={sourceLine(q.data?.sources) ?? "splits on record"} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the split record is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no splits on record</Empty> : (
        <Table>
          <THead>
            <TH className="w-[96px]" title="The day the split took effect">Executed</TH>
            <TH align="right" title="Shares before the split">From</TH>
            <TH align="right" title="Shares after the split, for the From count">To</TH>
          </THead>
          <tbody>
            {rows.map(r => (
              <tr key={r.date}>
                <TD mono>{r.date}</TD>
                <TD align="right" mono>{r.from ?? dash}</TD>
                <TD align="right" mono>{r.to ?? dash}</TD>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}
