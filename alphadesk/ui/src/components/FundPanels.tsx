import { useQuery } from "@tanstack/react-query"
import { vendorLabel } from "@/lib/vendors"
import { KeyPrompt, QueryFailure } from "@/components/KeyPrompt"
import { on } from "@/lib/api"
import { usePrefetchChart } from "@/lib/queries"
import { compact } from "@/components/Treemap"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { Empty, Table, TD, TH, THead, TR, Widget } from "@/components/terminal"

/** What an ETF or mutual fund HOLDS — two panels the Profile and Analysis
 * pages place when the symbol is a fund (the fund record answers) and
 * leave out otherwise:
 *
 *   Holdings — the largest positions with their weights, each row a click
 *   that puts that name on the board.
 *   Breakdown — category, family, expense ratio, net assets, turnover, the
 *   asset-class split and the sector weights. */

const dash = "—"
const pct = (v: number | null | undefined, d = 2) => (v == null ? dash : `${v.toFixed(d)}%`)

export function useFund(symbol: string) {
  return useQuery({
    queryKey: ["fund", symbol],
    queryFn: ({ signal }) => on(signal).fund(symbol),
    enabled: !!symbol,
    staleTime: 6 * 60 * 60_000,
    retry: false,
  })
}

type PanelProps = { symbol: string; span?: number; scroll?: number | string }

function WeightBar({ v, max }: { v: number | null; max: number }) {
  if (v == null || max <= 0) return null
  return <div className="h-[6px] rounded-[2px] bg-accent-700/70" style={{ width: `${Math.max(2, (v / max) * 100)}%` }} />
}

export function FundHoldingsPanel({ symbol, span = 6, scroll = 420 }: PanelProps) {
  const q = useFund(symbol)
  const { add } = useBoardSymbols()
  const prefetchChart = usePrefetchChart()
  const rows = q.data?.holdings ?? []
  const max = rows.reduce((m, r) => Math.max(m, r.weight ?? 0), 0)
  const subtitle = q.data && rows.length ? `top ${rows.length}${q.data.top_weight != null ? ` · ${pct(q.data.top_weight, 1)} of the fund` : ""}${(q.data.holdings_vendor ?? q.data.vendor) ? ` · ${vendorLabel(q.data.holdings_vendor ?? q.data.vendor!)}` : ""}${q.data.as_of ? ` · as of ${q.data.as_of.slice(0, 10)}` : ""}` : undefined
  return (
    <Widget span={span} symbol={symbol} title="Holdings" subtitle={subtitle} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the fund record is unavailable right now</QueryFailure>
        : rows.length === 0 && q.data?.holdings_needs_key ? <KeyPrompt prompt={q.data.holdings_needs_key} />
        : rows.length === 0 ? <Empty>no holdings on record for {symbol}</Empty> : (
        <Table>
          <THead>
            <TH className="w-[84px]" title="The holding's ticker. Click a row to add it to the board">Symbol</TH>
            <TH title="The holding's name">Name</TH>
            <TH className="w-[30%]" title="The holding's weight drawn as a bar, measured against the fund's largest holding">Weight</TH>
            <TH align="right" className="w-[64px]" title="Share of the fund's assets in this holding, as the vendor last reported it">%</TH>
          </THead>
          <tbody>
            {rows.map((r, i) => (
              <TR key={`${r.symbol}:${i}`} onClick={r.symbol ? () => add(r.symbol!) : undefined}
                  onRest={r.symbol ? () => prefetchChart(r.symbol!) : undefined}>
                <TD className="font-semibold">{r.symbol ?? dash}</TD>
                <TD className="truncate text-muted-foreground" title={r.name ?? undefined}>{r.name ?? dash}</TD>
                <TD><WeightBar v={r.weight} max={max} /></TD>
                <TD align="right" mono>{pct(r.weight)}</TD>
              </TR>
            ))}
          </tbody>
        </Table>
      )}
    </Widget>
  )
}

export function FundBreakdownPanel({ symbol, span = 6, scroll = 420 }: PanelProps) {
  const q = useFund(symbol)
  const d = q.data
  const facts: [string, string][] = d ? [
    ["Category", d.category ?? dash],
    ["Family", d.family ?? dash],
    ["Expense ratio", pct(d.expense_ratio)],
    ["Net assets", d.net_assets == null ? dash : `$${compact(d.net_assets)}`],
    ["Turnover", pct(d.turnover, 0)],
  ] : []
  const sectorMax = (d?.sectors ?? []).reduce((m, s) => Math.max(m, s.weight ?? 0), 0)
  return (
    <Widget span={span} symbol={symbol} title="Fund breakdown" subtitle={d ? `${d.legal_type ?? (d.quote_type === "MUTUALFUND" ? "Mutual fund" : "Fund")}${d.vendor ? ` · ${vendorLabel(d.vendor)}` : ""}` : undefined} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the fund record is unavailable right now</QueryFailure>
        : !d ? <Empty>{symbol} is not a fund</Empty> : (
        <div className="px-3 py-2 text-body">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {facts.map(([l, v]) => (
              <div key={l} className="flex items-baseline justify-between gap-2 border-b border-row-rule py-1">
                <span className="text-muted-foreground">{l}</span>
                <span className="truncate text-right font-medium tnum" title={v}>{v}</span>
              </div>
            ))}
          </div>
          {d.assets.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">Asset classes</div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 tnum">
                {d.assets.map(a => <span key={a.key}><span className="text-muted-foreground">{a.label}</span> {pct(a.weight)}</span>)}
              </div>
            </div>
          )}
          {d.sectors.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">Sectors</div>
              {d.sectors.map(s => (
                <div key={s.key} className="mb-1 flex items-center gap-2">
                  <span className="w-[150px] shrink-0 truncate text-muted-foreground">{s.label}</span>
                  <div className="flex-1"><WeightBar v={s.weight} max={sectorMax} /></div>
                  <span className="w-[52px] shrink-0 text-right tnum">{pct(s.weight, 1)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Widget>
  )
}
