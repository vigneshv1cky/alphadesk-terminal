import { useQuery } from "@tanstack/react-query"
import { api, type RelatedFund } from "@/lib/api"
import { QueryFailure } from "@/components/KeyPrompt"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { usePrefetchChart } from "@/lib/queries"
import { vendorLabel } from "@/lib/vendors"
import { Empty, Table, TD, TH, THead, TR, Widget } from "@/components/terminal"

/** The funds built ON this company (2026-09-15) — "what else trades off
 * NVIDIA": the 2x long, the inverse, the option-income fund, the buffered
 * one. Twenty-three carry NVIDIA's name, twenty-six Tesla's, two
 * CrowdStrike's.
 *
 * NOT the funds that HOLD the stock: per-stock fund exposure is on no
 * vendor a reader here can reach, so the panel says what it covers in its
 * subtitle rather than reading as a complete picture of fund ownership.
 *
 * A row opens the fund on the board like any other symbol, so the 2x and
 * the stock can be charted side by side. */

const dash = "—"

/** Two significant steps, the earnings calendar's shape so the two tables
 * read alike. What trades on one company spans four orders of magnitude —
 * $288m through NVIDIA's 2x long against a few thousand through the thinnest
 * line — so the step matters more than the digits. */
function money(n: number | null | undefined): string {
  if (n == null || n === 0) return dash
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return `${(n / 1e3).toFixed(0)}K`
}

/** What changed hands this session, in money: the share count times the
 * price. Shares alone do not compare — these funds are priced from about $4
 * to $135, so a share count ranks the cheap ones first and says nothing
 * about how much you could move through them. */
function traded(f: RelatedFund): number | null {
  return f.volume == null || f.price == null ? null : f.volume * f.price
}

/** What each group is, in the reader's words rather than the issuer's —
 * short, because the column is narrow on a phone: "Leveraged 2×" and
 * "Inverse −2×" were cut to "Leveraged …" (2026-09-19). The tip keeps the
 * whole explanation. */
const KINDS: Record<string, { label: string; tip: string }> = {
  leveraged: { label: "Long", tip: "Leveraged: aims for a multiple of the stock's move, reset daily. Held longer than a day, its return drifts from the multiple" },
  inverse: { label: "Short", tip: "Inverse: aims to move against the stock, reset daily. Held longer than a day, its return drifts from the multiple" },
  income: { label: "Income", tip: "Sells options on the stock and pays the premium out; the payout caps how much of a rally it keeps" },
  buffered: { label: "Buffer", tip: "A defined-outcome fund: part of a fall is absorbed in exchange for a cap on the rise" },
  paired: { label: "Paired", tip: "Holds this company alongside another in one fund" },
  other: { label: "Other", tip: "Named for the company; the listing does not say what it does" },
}

function Row({ f }: { f: RelatedFund }) {
  const { add } = useBoardSymbols()
  const prefetchChart = usePrefetchChart()
  const kind = KINDS[f.kind] ?? KINDS.other
  const up = (f.change_pct ?? 0) >= 0
  return (
    <TR onClick={() => add(f.symbol)} onRest={() => prefetchChart(f.symbol)}>
      <TD className="font-semibold">{f.symbol}</TD>
      <TD className="truncate text-muted-foreground" title={f.name}>{f.name}</TD>
      <TD>
        <span className="text-label uppercase tracking-caps text-muted-foreground" data-tip={kind.tip}>
          {/* The side is the label, so the multiple needs no sign: "Short 2×". */}
          {kind.label}{f.leverage != null ? ` ${Math.abs(f.leverage)}×` : ""}
        </span>
      </TD>
      <TD align="right" mono className="text-muted-foreground">{money(traded(f))}</TD>
      <TD align="right" mono>{f.price == null ? dash : f.price.toFixed(2)}</TD>
      <TD align="right" mono className={`font-semibold ${up ? "text-gain" : "text-loss"}`}>
        {f.change_pct == null ? dash : `${up ? "+" : ""}${f.change_pct.toFixed(2)}%`}
      </TD>
    </TR>
  )
}

/** No scroll cap on purpose (2026-09-15, the owner's call): the list is
 * short and finite — 23 funds on NVIDIA, 2 on CrowdStrike — and the point
 * of the panel is to see what exists, so the tile grows to its rows rather
 * than hiding most of them behind a scroll and a Show all. */
export function RelatedFundsPanel({ symbol, span = 6, scroll }: {
  symbol: string; span?: number; scroll?: number | string
}) {
  const q = useQuery({
    queryKey: ["related-funds", symbol],
    queryFn: () => api.relatedFunds(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: false,
  })
  const funds = q.data?.funds ?? []
  const geared = funds.filter(f => f.kind === "leveraged" || f.kind === "inverse").length
  const subtitle = q.data?.is_fund ? "a fund, not a company"
    : funds.length
    ? `${funds.length} built on ${symbol}${geared ? ` · ${geared} leveraged or inverse` : ""}${q.data?.source ? ` · ${vendorLabel(q.data.source) ?? q.data.source}` : ""}`
    : undefined
  return (
    <Widget span={span} symbol={symbol} title="Funds on this stock" subtitle={subtitle} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the fund listing is unavailable right now</QueryFailure>
        // A fund is a wrapper, not a company: nothing is built on it, and
        // what it holds is the holdings panel's question (2026-09-15).
        : q.data?.is_fund ? <Empty>{symbol} is itself a fund — see its holdings for what it owns.</Empty>
        : !funds.length ? <Empty>no fund is built on {symbol}</Empty> : (
        <>
          <div className="overflow-x-auto"><div className="min-w-[524px]">
            <Table>
              <THead>
                <TH className="w-[72px]" title={`The fund's ticker. Click a row to put it on the board beside ${symbol}`}>Symbol</TH>
                <TH title="The fund's name, as its issuer registered it">Name</TH>
                <TH className="w-[88px]" title="What the fund does with the stock: a daily multiple, an inverse, options written for income, or a defined outcome. Read from the fund's own name">Type</TH>
                <TH align="right" className="w-[76px]" title="How much of the fund changed hands this session, in dollars — its share volume times its price. It says whether a line is one you could actually get in and out of: two funds of the same size can differ several times over. Dollars rather than shares because these prices differ thirtyfold, and a share count would rank the cheap ones first">Traded</TH>
                <TH align="right" className="w-[76px]" title="The fund's latest price">Last</TH>
                <TH align="right" className="w-[80px]" title="The fund's change since the previous session's close — a geared fund should move about its multiple of the stock's">1D</TH>
              </THead>
              <tbody>{funds.map(f => <Row key={f.symbol} f={f} />)}</tbody>
            </Table>
          </div></div>
          {/* Said plainly: this is what is BUILT on the company, and the
              ordinary funds that hold it are on no vendor here. */}
          <div className="border-t border-row-rule px-3 py-2 text-label leading-[1.45] text-muted-foreground">
            Funds named for {q.data?.company ?? symbol}, matched on the fund's own name and priced on your data key.
            Which ordinary funds hold the stock is on no vendor here, so it is not shown.
          </div>
        </>
      )}
    </Widget>
  )
}

/** The Markets board's copy: the board's active symbol, at two thirds of
 * the row beside the equity overview — the arrangement the owner settled on
 * and asked to become the default (2026-09-16). */
export function RelatedFundsTile() {
  const { active } = useBoardSymbols()
  if (!active) {
    return (
      <Widget span={8} title="Funds on this stock">
        <Empty>Pick a symbol on the strip to see the funds built on it.</Empty>
      </Widget>
    )
  }
  return <RelatedFundsPanel symbol={active} span={8} />
}
