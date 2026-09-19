import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { api } from "@/lib/api"
import { compact } from "@/components/Treemap"
import { Empty, Table, TD, TH, THead, Widget } from "@/components/terminal"

/** Who holds ONE symbol — the 13F picture summed across every filer, the
 * filers themselves, and the insiders' own share trades.
 *
 * Three panels any page can place (the Profile page carries them by
 * default; the Markets board offers them as tiles):
 *
 *   Institutional ownership — the sum: holders, shares, value, the share of
 *   the float, and the positions that grew, shrank, opened and closed this
 *   quarter. Comes only from the summed source; with the top-ten fallback
 *   the position rows are absent, never estimated, and the header says so.
 *   Stock ownership — the largest filers by value with each one's shares,
 *   quarter change and value.
 *   Insider trades — SEC Form 4 share trades, from EDGAR directly. */

const dash = "—"

export function useInstitutional(symbol: string, limit = 25) {
  return useQuery({
    queryKey: ["institutional", symbol, limit],
    queryFn: () => api.institutional(symbol, limit),
    enabled: !!symbol,
    staleTime: 60 * 60_000,   // 13F data moves as filings land, not intraday
    retry: false,
  })
}

const SOURCE_LABEL: Record<string, string> = { finnhub: "13F filers · Finnhub", fmp: "13F filers · Financial Modeling Prep" }
const n0 = (v: number | null | undefined) => (v == null ? dash : Math.round(v).toLocaleString("en-US"))
const pct = (v: number | null | undefined, d = 2) => (v == null ? dash : `${v.toFixed(d)}%`)
const signed = (v: number | null | undefined) =>
  v == null ? dash : `${v > 0 ? "+" : ""}${compact(v)}`
const tone = (v: number | null | undefined) =>
  v == null || v === 0 ? "text-muted-foreground" : v > 0 ? "text-gain" : "text-loss"

type PanelProps = { symbol: string; span?: number; scroll?: number | string }

export function InstitutionalOwnershipPanel({ symbol, span = 5, scroll = 420 }: PanelProps) {
  const q = useInstitutional(symbol)
  const s = q.data?.summary ?? {}
  const p = s.positions ?? {}
  const summed = !!q.data?.summary?.positions
  // Two row shapes: a position row has a holder count and a share count;
  // a value row (dollars, a percentage) has ONE figure and spans both
  // columns, so a dollar total never sits under a "Shares" heading.
  type Row = { label: string; holders?: string; shares?: string; value?: string; tone?: 1 | -1 }
  const rows: Row[] = summed ? [
    { label: "Investors holding", holders: n0(s.holders), shares: compact(s.shares ?? null) },
    { label: "Total invested", value: s.total_value ? `$${compact(s.total_value)}` : dash },
    { label: "Ownership percent", value: s.institutional_pct == null ? dash
        : `${pct(s.institutional_pct)}${s.shares_outstanding ? ` of ${compact(s.shares_outstanding)} shares` : ""}` },
    { label: "New positions", holders: n0(p.new?.holders), shares: compact(p.new?.shares ?? null), tone: 1 },
    { label: "Increased positions", holders: n0(p.increased?.holders), shares: compact(p.increased?.shares ?? null), tone: 1 },
    { label: "Held positions", holders: n0(p.held?.holders), shares: compact(p.held?.shares ?? null) },
    { label: "Reduced positions", holders: n0(p.decreased?.holders), shares: compact(p.decreased?.shares ?? null), tone: -1 },
    { label: "Closed positions", holders: n0(p.sold_out?.holders), shares: compact(p.sold_out?.shares ?? null), tone: -1 },
  ] : [
    { label: "Investors holding", value: n0(s.holders) },
    { label: "Ownership percent", value: pct(s.institutional_pct) },
  ]
  const subtitle = !q.data ? "loading…"
    : q.data.source ? `${SOURCE_LABEL[q.data.source] ?? q.data.source}${q.data.as_of ? ` · as of ${q.data.as_of}` : ""}${summed ? "" : " · this vendor reports holders, not position counts"}`
    : "no ownership source answered"
  return (
    <Widget span={span} symbol={symbol} title="Institutional ownership" subtitle={subtitle} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the ownership record is unavailable right now</QueryFailure>
        : !q.data?.source ? <Empty>no institutional ownership on record for {symbol}</Empty> : (
        <div className="overflow-x-auto"><div className="min-w-[360px]">
        <Table>
          <THead>
            <TH title="What the row counts, across the institutions that file quarterly 13F holdings reports">Index</TH>
            <TH align="right" className="w-[104px]" title="How many institutions">Holders</TH>
            <TH align="right" className="w-[112px]" title="The shares in those institutions' positions">Shares</TH>
          </THead>
          <tbody>
            {rows.map(r => (
              <tr key={r.label}>
                <TD>{r.label}</TD>
                {r.value != null ? (
                  <TD align="right" mono colSpan={2}>{r.value}</TD>
                ) : (<>
                  <TD align="right" mono className={r.tone ? (r.tone > 0 ? "text-gain" : "text-loss") : ""}>{r.holders}</TD>
                  <TD align="right" mono className="text-muted-foreground">{r.shares}</TD>
                </>)}
              </tr>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}

export function StockOwnershipPanel({ symbol, span = 7, scroll = 420 }: PanelProps) {
  const q = useInstitutional(symbol)
  const rows = q.data?.holders ?? []
  const summed = (q.data?.holders ?? []).some(h => h.change != null)
  const subtitle = !q.data ? "loading…"
    : q.data.source ? `${SOURCE_LABEL[q.data.source] ?? q.data.source}${q.data.total_holders ? ` · ${n0(q.data.total_holders)} filers, largest ${rows.length} by value` : ""}`
    : "no ownership source answered"
  return (
    <Widget span={span} symbol={symbol} title="Stock ownership" subtitle={subtitle} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the holder record is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no institutional holders on record for {symbol}</Empty> : (
        // Six columns need ~600px; narrower than that the table scrolls
        // sideways inside the panel rather than letting headers overlap.
        <div className="overflow-x-auto"><div className="min-w-[600px]">
        <Table>
          <THead>
            <TH title="The institution that reported the position">Investor</TH>
            <TH align="right" className="w-[88px]" title="The date the position was reported as of">Reported</TH>
            <TH align="right" className="w-[84px]" title="Shares held on that date">Shares</TH>
            <TH align="right" className="w-[88px]" title="Shares added or sold since the institution's previous report">Change</TH>
            <TH align="right" className="w-[72px]" title="That change as a percent of the previous position">%</TH>
            <TH align="right" className="w-[84px]" title="The position's market value as reported">Value</TH>
          </THead>
          <tbody>
            {rows.map((h, i) => (
              <tr key={`${h.name}:${i}`}>
                <TD className="font-medium" title={h.name}>{h.name}</TD>
                <TD align="right" mono className="text-muted-foreground">{h.date ?? dash}</TD>
                <TD align="right" mono>{compact(h.shares)}</TD>
                <TD align="right" mono className={tone(h.change)}>{summed ? signed(h.change) : dash}</TD>
                <TD align="right" mono className={tone(h.change_pct)}>{h.change_pct == null ? dash : `${h.change_pct > 0 ? "+" : ""}${h.change_pct.toFixed(2)}%`}</TD>
                <TD align="right" mono className="text-muted-foreground">{h.value == null ? dash : `$${compact(h.value)}`}</TD>
              </tr>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}

export function InsiderTradesPanel({ symbol, span = 12, scroll = 420, limit = 40 }: PanelProps & { limit?: number }) {
  const trades = useQuery({
    queryKey: ["insider", symbol],
    queryFn: () => api.insider(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60_000,   // EDGAR walks are slow; the server caches too
    retry: false,
  })
  const rows = (trades.data?.trades ?? []).slice(0, limit)
  return (
    <Widget span={span} symbol={symbol} title="Insider trades" subtitle="SEC Form 4 · share trades only, derivatives excluded"
            scroll={scroll}>
      {trades.isPending ? <Empty>reading EDGAR…</Empty>
        : trades.isError ? <QueryFailure error={trades.error}>EDGAR is unavailable right now</QueryFailure>
        : rows.length === 0 ? <Empty>no recent Form 4 share trades for {symbol}</Empty> : (
        <Table>
          <THead>
            <TH className="w-[92px]" title="The day the trade took place">Traded</TH>
            <TH title="The officer, director or 10% owner who traded, with their role">Insider</TH>
            <TH className="w-[72px]" title="Whether the insider acquired or disposed of the shares, as the Form 4 codes it">Side</TH>
            <TH align="right" className="w-[92px]" title="Shares in the trade">Shares</TH>
            <TH align="right" className="w-[84px]" title="Price per share as reported">Price</TH>
            <TH align="right" className="w-[92px]" title="Shares times the price">Value</TH>
            <TH align="right" className="w-[92px]" title="The day the Form 4 was filed with the SEC. Click it to open the filing on EDGAR">Filed</TH>
          </THead>
          <tbody>
            {rows.map((t, i) => {
              const buy = t.acquisition_or_disposition === "acquired"
              return (
                <tr key={`${t.filing_url}:${i}`}>
                  <TD mono className="text-muted-foreground">{t.transaction_date}</TD>
                  <TD title={t.owner_title ?? undefined}>
                    <span className="font-medium">{t.owner_name}</span>
                    {t.owner_title ? <span className="text-muted-foreground"> · {t.owner_title}</span> : null}
                  </TD>
                  <TD className={`text-label font-extrabold uppercase ${buy ? "text-gain" : "text-loss"}`}>{buy ? "bought" : "sold"}</TD>
                  <TD align="right" mono>{compact(t.securities_transacted)}</TD>
                  <TD align="right" mono className="text-muted-foreground">{t.transaction_price == null ? dash : t.transaction_price.toFixed(2)}</TD>
                  <TD align="right" mono className="text-muted-foreground">{t.transaction_value == null ? dash : `$${compact(t.transaction_value)}`}</TD>
                  <TD align="right" mono>
                    <a href={t.filing_url} target="_blank" rel="noopener noreferrer" className="text-accent-700 hover:underline">{t.filing_date}</a>
                  </TD>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}
