import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { on, type Quote } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { useEarnings, useFundamentals, useQuote, useQuotes, useThemes } from "@/lib/queries"
import { ComparisonPanel } from "@/components/ComparisonPanel"
import { DividendsPanel, SplitsPanel } from "@/components/CorporateActions"
import { InsiderTradesPanel, InstitutionalOwnershipPanel, StockOwnershipPanel } from "@/components/Ownership"
import { EarningsHistoryPanel } from "@/components/EarningsPanels"
import { EarningsTranscriptPanel } from "@/components/EarningsTranscript"
import { compact } from "@/components/Treemap"
import { QueryFailure } from "@/components/KeyPrompt"
import { Empty, Widget, btnCls } from "@/components/terminal"
import { TabStrip } from "@/widgets/market"
import { registerWidget } from "@/widgets/registry"
import { TILE_BODY_HEIGHT } from "@/widgets/tile"

/** The third wave of board tiles (2026-09-02, "add all") — the rest of the
 * menu that AlphaDesk's own endpoints already back, with a few shapes
 * borrowed from OpenBB's widget catalog: key metrics, analyst consensus,
 * reporting-soon, earnings context, comparison, fundamentals, the window,
 * filings, insider trades, ownership, and a basket strip. Everything scopes
 * to the symbol strip like every tile before it; forecasts render labelled
 * as consensus, and nothing here ranks anything.
 */

const dash = "—"
const n2 = (v: number | null | undefined, d = 2) => (v == null ? dash : v.toFixed(d))
const pct = (v: number | null | undefined) => (v == null ? dash : `${(v * 100).toFixed(2)}%`)

function NeedsSymbol({ title, span = 4 }: { title: string; span?: number }) {
  return (
    <Widget span={span} title={title}>
      <Empty>mark a symbol on the strip</Empty>
    </Widget>
  )
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-3">
      <div className="truncate text-label font-medium uppercase tracking-caps text-muted-foreground">{label}</div>
      <div className="num truncate text-emph font-extrabold leading-tight">{value}</div>
    </div>
  )
}

/* ── Key metrics ──────────────────────────────────────────────────────── */

function KeyMetricsTile() {
  const { active } = useBoardSymbols()
  const { data: q } = useQuote(active)
  if (!active) return <NeedsSymbol title="Key metrics" />
  return (
    <Widget span={4} symbol={active} title="Key metrics" scroll={TILE_BODY_HEIGHT}>
      {!q ? <Empty>loading…</Empty> : (
        <div className="grid grid-cols-3 [&>div]:border-row-rule [&>div:not(:nth-child(3n))]:border-r">
          <MetricCell label="Mkt cap" value={compact(q.market_cap)} />
          <MetricCell label="P/E fwd" value={n2(q.pe_forward, 1)} />
          <MetricCell label="P/E ttm" value={n2(q.pe_trailing, 1)} />
          <MetricCell label="PEG" value={n2(q.peg)} />
          <MetricCell label="P/S" value={n2(q.price_to_sales)} />
          <MetricCell label="P/B" value={n2(q.price_to_book)} />
          <MetricCell label="Beta" value={n2(q.beta)} />
          <MetricCell label="EPS ttm" value={n2(q.eps_ttm)} />
          <MetricCell label="Div yield" value={q.dividend_yield == null ? dash : pct(q.dividend_yield)} />
        </div>
      )}
    </Widget>
  )
}

/* ── Analyst consensus ────────────────────────────────────────────────── */

function TargetBar({ q }: { q: Quote }) {
  const lo = q.target_low, hi = q.target_high, mean = q.target_mean, px = q.price
  if (lo == null || hi == null || hi <= lo) return null
  const span = hi - lo
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / span) * 100))}%`
  return (
    <div className="px-3 pb-1 pt-3">
      <div className="relative h-[6px] rounded-full bg-muted">
        {mean != null && (
          <span className="absolute top-[-3px] h-[12px] w-[2px] bg-foreground" style={{ left: pos(mean) }} />
        )}
        {px != null && (
          <span className="absolute top-[-3px] h-[12px] w-[2px] bg-accent" style={{ left: pos(px) }} />
        )}
      </div>
      <div className="mt-1 flex justify-between text-label text-muted-foreground">
        <span className="num">{n2(lo)}</span>
        <span>mean {mean == null ? dash : n2(mean)} · <span className="text-accent-700">price {n2(px)}</span></span>
        <span className="num">{n2(hi)}</span>
      </div>
    </div>
  )
}

function AnalystConsensusTile() {
  const { active } = useBoardSymbols()
  const { data: q } = useQuote(active)
  if (!active) return <NeedsSymbol title="Analyst consensus" />
  const upside = q?.target_mean != null && q?.price
    ? ((q.target_mean - q.price) / q.price) * 100 : null
  return (
    <Widget span={4} symbol={active} title="Analyst consensus"
            subtitle="forecasts, labelled as such" scroll={TILE_BODY_HEIGHT}>
      {!q ? <Empty>loading…</Empty>
        : q.target_mean == null && !q.analyst_rating ? <Empty>no analyst coverage in the feed</Empty> : (
        <>
          <TargetBar q={q} />
          <div className="grid grid-cols-3 [&>div]:border-row-rule [&>div:not(:nth-child(3n))]:border-r">
            <MetricCell label="Rating" value={(q.analyst_rating ?? dash).toUpperCase()} />
            <MetricCell label="Analysts" value={q.analyst_count == null ? dash : String(q.analyst_count)} />
            <MetricCell label="To mean" value={upside == null ? dash : `${upside >= 0 ? "+" : ""}${upside.toFixed(1)}%`} />
          </div>
        </>
      )}
    </Widget>
  )
}

/* ── Reporting soon ───────────────────────────────────────────────────── */

function ReportingSoonTile() {
  const { data } = useEarnings()
  const rows = (data?.upcoming ?? []).slice(0, 14)
  return (
    <Widget span={4} title="Reporting soon" subtitle="from the earnings calendar" scroll={TILE_BODY_HEIGHT}>
      {!data ? <Empty>loading…</Empty>
        : rows.length === 0 ? <Empty>nothing on the calendar</Empty> : (
        <ul>
          {rows.map(r => (
            <li key={`${r.symbol}:${r.report_date}`} className="row-rule">
              <Link to={`/analysis?symbol=${encodeURIComponent(r.symbol)}`}
                    className="flex items-center gap-2 px-3 py-2.5 hover:bg-foreground/5">
                <span className="num w-[64px] shrink-0 text-body font-extrabold">{r.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-caption text-muted-foreground">
                  {r.company_name ?? ""}
                </span>
                <span className="num shrink-0 text-caption">{r.report_date.slice(5)}</span>
                <span className="w-[34px] shrink-0 text-right text-label uppercase text-muted-foreground">
                  {r.session ?? ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Widget>
  )
}

/* ── Earnings context ─────────────────────────────────────────────────── */

function EarningsContextTile() {
  const { active } = useBoardSymbols()
  const ctx = useQuery({
    queryKey: ["earnings-context", active],
    queryFn: ({ signal }) => on(signal).earningsContext(active),
    enabled: !!active,
    staleTime: 10 * 60_000,
  })
  if (!active) return <NeedsSymbol title="Earnings context" />
  const d = ctx.data
  const hist = (d?.report_history ?? []).slice(-4).reverse()
  return (
    <Widget span={4} symbol={active} title="Earnings context" scroll={TILE_BODY_HEIGHT}>
      {ctx.isPending ? <Empty>loading…</Empty>
        : !d || (!d.report_history?.length && !d.beat_streak) ? <Empty>no reported history in the feed</Empty> : (
        <>
          <div className="grid grid-cols-2 border-b border-row-rule [&>div]:border-row-rule [&>div:nth-child(odd)]:border-r">
            <MetricCell label="Beat streak" value={d.beat_streak ?? dash} />
            <MetricCell label="Next Q est" value={d.next_q_eps_estimate == null ? dash : n2(d.next_q_eps_estimate)} />
          </div>
          <ul>
            {hist.map(h => {
              const beat = h.eps_actual != null && h.eps_estimate != null && h.eps_actual >= h.eps_estimate
              return (
                <li key={h.date} className="row-rule flex items-center gap-2 px-3 py-2.5 text-caption">
                  <span className="num w-[76px] shrink-0 text-muted-foreground">{h.date}</span>
                  <span className="num min-w-0 flex-1">est {n2(h.eps_estimate)} → act {n2(h.eps_actual)}</span>
                  <span className={`num shrink-0 ${beat ? "text-gain" : "text-loss"}`}>
                    {h.surprise_pct == null ? dash : `${h.surprise_pct >= 0 ? "+" : ""}${h.surprise_pct.toFixed(1)}%`}
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Widget>
  )
}

/* ── Comparison (the analysis page's strip, over the board's chips) ───── */

function ComparisonTile() {
  const { ordered } = useBoardSymbols()
  return <ComparisonPanel symbols={ordered} />
}

/* ── Fundamentals ─────────────────────────────────────────────────────── */

function FundamentalsTile() {
  const { active } = useBoardSymbols()
  const { data } = useFundamentals(active, "quarterly")
  const [metricId, setMetricId] = useState<string | null>(null)
  if (!active) return <NeedsSymbol title="Fundamentals" span={6} />
  const metrics = data?.metrics ?? []
  const chosen = metricId && metrics.some(m => m.id === metricId) ? metricId : metrics[0]?.id
  const series = (chosen ? data?.series[chosen] ?? [] : []).slice(-8)
  const max = Math.max(...series.map(p => Math.abs(p.v)), 1)
  const spec = metrics.find(m => m.id === chosen)
  return (
    <Widget
      span={6} symbol={active} title="Fundamentals" subtitle="quarterly, as reported"
      scroll={TILE_BODY_HEIGHT}
      toolbar={metrics.length > 1 ? (
        <>
          {metrics.slice(0, 5).map(m => (
            <button key={m.id} onClick={() => setMetricId(m.id)} aria-pressed={m.id === chosen}
              className={btnCls({ variant: "ghost", active: m.id === chosen })}>
              {m.label}
            </button>
          ))}
        </>
      ) : undefined}
    >
      {!data ? <Empty>loading…</Empty>
        : series.length === 0 ? <Empty>upstream reports nothing chartable for {active}</Empty> : (
        <div className="flex flex-col">
          <div className="flex h-[330px] items-end gap-2 px-4 pb-7 pt-4">
            {series.map(p => (
              <div key={p.t} className="relative flex min-w-0 flex-1 flex-col items-center justify-end self-stretch">
                <span className="num mb-1 text-label text-muted-foreground">{compact(p.v)}</span>
                <div className={`w-full max-w-[46px] rounded-t-xs ${p.v >= 0 ? "bg-gain" : "bg-loss"}`}
                     style={{ height: `${(Math.abs(p.v) / max) * 100}%`, minHeight: 2 }} />
                <span className="num absolute -bottom-5 truncate text-label text-muted-foreground">
                  {p.t.slice(2, 7)}
                </span>
              </div>
            ))}
          </div>
          {spec && <div className="shrink-0 px-4 pb-2 text-label uppercase tracking-caps text-muted-foreground">{spec.label}</div>}
        </div>
      )}
    </Widget>
  )
}

/* ── Recent filings ───────────────────────────────────────────────────── */

/** THE COMPANY'S FILINGS, AND THE MARKET'S (2026-09-23).
 *
 * This tile answered "what has this company filed", which is indexed by
 * ticker. "What did the market just file" is a different question and had no
 * home — the second tab is it, with EDGAR's own acceptance time on each row,
 * to the second. Both are keyless: EDGAR is public government data.
 *
 * The market tab keeps registrants the SEC lists a ticker for and counts
 * what that drops, because securitisation trusts and Federal Home Loan Banks
 * file constantly and trade nowhere — a list without that reads as noise.
 */
function MarketFilings() {
  const { add } = useBoardSymbols()
  const q = useQuery({
    queryKey: ["filing-feed"],
    queryFn: ({ signal }) => on(signal).filingFeed(40),
    staleTime: 60_000,
    refetchInterval: 3 * 60_000,
    refetchIntervalInBackground: true,
  })
  const rows = q.data?.filings ?? []
  const off = Object.entries(q.data?.unavailable ?? {})
  if (q.isPending) return <Empty>loading…</Empty>
  if (q.isError) return <QueryFailure error={q.error}>the market's filings are unavailable right now</QueryFailure>
  return (
    <>
      {off.length > 0 && (
        <p className="px-3 py-2 text-caption text-muted-foreground">
          {off.map(([g, why]) => `${q.data?.groups[g] ?? g}: ${why}`).join(" · ")}
        </p>
      )}
      {rows.length === 0 && off.length === 0 ? <Empty>nothing filed in this window</Empty> : (
        <ul>
          {rows.map((f, i) => {
            // Defensive: a row without the field is a shape this tile did
            // not expect, and it should lose a ticker rather than the page
            // (2026-09-23 — a route collision served the wrong shape here
            // and `symbols[0]` blanked the whole board).
            const symbol = (f.symbols ?? [])[0]
            const at = new Date(f.filed_at)
            return (
              <li key={f.accession ?? `${f.form}-${i}`} className="row-rule">
                <a href={f.url ?? undefined} target="_blank" rel="noopener noreferrer"
                   title={`${f.form} — ${f.company}${f.role ? ` (${f.role})` : ""}`}
                   className="flex items-center gap-2 px-3 py-2.5 hover:bg-foreground/5">
                  <span className="num w-[52px] shrink-0 text-caption text-muted-foreground">
                    {Number.isNaN(at.getTime()) ? "—"
                      : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <span className="w-[56px] shrink-0 truncate text-body font-extrabold"
                        title={symbol ? undefined : "the SEC lists no ticker for this registrant"}>
                    {symbol
                      ? <button type="button" className="hover:text-accent-700"
                                onClick={e => { e.preventDefault(); add(symbol) }}>{symbol}</button>
                      : "—"}
                  </span>
                  <span className="w-[76px] shrink-0 truncate text-caption text-muted-foreground">{f.form}</span>
                  <span className="min-w-0 flex-1 truncate text-caption">{f.company}</span>
                  <span className="shrink-0 text-label uppercase tracking-caps text-muted-foreground">edgar →</span>
                </a>
              </li>
            )
          })}
        </ul>
      )}
      {(q.data?.unlisted_hidden ?? 0) > 0 && (
        <p className="px-3 py-2 text-caption text-muted-foreground">
          {q.data!.unlisted_hidden} more from registrants the SEC lists no ticker for — trusts and
          agency banks, which file constantly and trade nowhere.
        </p>
      )}
    </>
  )
}

function FilingsTile() {
  const { active } = useBoardSymbols()
  const [scope, setScope] = useState<"symbol" | "market">("symbol")
  const filings = useQuery({
    queryKey: ["filings", active],
    queryFn: ({ signal }) => on(signal).filings(active),
    enabled: !!active && scope === "symbol",
    staleTime: 10 * 60_000,
  })
  const tabs = (
    <TabStrip tabs={[{ id: "symbol" as const, label: active || "Symbol" },
                     { id: "market" as const, label: "Market" }]}
              value={scope} onChange={setScope} />
  )
  if (scope === "market") {
    return (
      <Widget span={4} title="Recent filings" subtitle="what the market just filed · SEC EDGAR"
              scroll={TILE_BODY_HEIGHT} toolbar={tabs}>
        <MarketFilings />
      </Widget>
    )
  }
  if (!active) return <NeedsSymbol title="Recent filings" />
  const rows = (filings.data?.filings ?? []).slice(0, 12)
  return (
    <Widget span={4} symbol={active} title="Recent filings" subtitle="SEC EDGAR"
            scroll={TILE_BODY_HEIGHT} toolbar={tabs}>
      {filings.isPending ? <Empty>loading…</Empty>
        : rows.length === 0 ? <Empty>no filings found</Empty> : (
        <ul>
          {rows.map(f => (
            <li key={f.accession} className="row-rule">
              {f.readable ? (
                <Link to={`/analysis?symbol=${encodeURIComponent(active)}&accession=${encodeURIComponent(f.accession)}`}
                      className="flex items-center gap-2 px-3 py-2.5 hover:bg-foreground/5">
                  <span className="w-[64px] shrink-0 text-body font-extrabold">{f.form}</span>
                  <span className="min-w-0 flex-1 truncate text-caption text-muted-foreground">
                    filed {f.filing_date}
                  </span>
                  <span className="shrink-0 text-label uppercase tracking-caps text-accent-700">read →</span>
                </Link>
              ) : (
                // An ownership form is a table, not a document to read: it
                // opens on EDGAR.
                <a href={f.url} target="_blank" rel="noopener noreferrer"
                   title={`Form ${f.form} on SEC EDGAR`}
                   className="flex items-center gap-2 px-3 py-2.5 hover:bg-foreground/5">
                  <span className="w-[64px] shrink-0 text-body font-medium text-muted-foreground">{f.form}</span>
                  <span className="min-w-0 flex-1 truncate text-caption text-muted-foreground">
                    filed {f.filing_date}
                  </span>
                  <span className="shrink-0 text-label uppercase tracking-caps text-muted-foreground">edgar →</span>
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </Widget>
  )
}

/* ── Insider trades ───────────────────────────────────────────────────── */

function InsiderTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Insider trades" span={6} />
  return <InsiderTradesPanel symbol={active} span={6} scroll={TILE_BODY_HEIGHT} limit={12} />
}

function InstitutionalTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Institutional ownership" span={4} />
  return <InstitutionalOwnershipPanel symbol={active} span={4} scroll={TILE_BODY_HEIGHT} />
}

function HoldersTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Stock ownership" span={6} />
  return <StockOwnershipPanel symbol={active} span={6} scroll={TILE_BODY_HEIGHT} />
}

/* ── Ownership ────────────────────────────────────────────────────────── */

function OwnershipTile() {
  const { active } = useBoardSymbols()
  const own = useQuery({
    queryKey: ["ownership", active],
    queryFn: ({ signal }) => on(signal).ownership(active),
    enabled: !!active,
    staleTime: 30 * 60_000,
    retry: false,
  })
  if (!active) return <NeedsSymbol title="Ownership" span={6} />
  const breakdown = Object.entries(own.data?.breakdown ?? {})
  const holders = (own.data?.top_holders ?? []).slice(0, 6)
  return (
    <Widget span={6} symbol={active} title="Ownership" subtitle="major holders · top institutions"
            scroll={TILE_BODY_HEIGHT}>
      {own.isPending ? <Empty>loading…</Empty>
        : breakdown.length === 0 && holders.length === 0 ? <Empty>no ownership data in the feed</Empty> : (
        <>
          {breakdown.length > 0 && (
            <div className={`grid grid-cols-${Math.min(breakdown.length, 3)} border-b border-row-rule`}
                 style={{ gridTemplateColumns: `repeat(${Math.min(breakdown.length, 3)}, minmax(0, 1fr))` }}>
              {breakdown.slice(0, 3).map(([label, value]) => (
                <MetricCell key={label} label={label}
                            value={typeof value === "number" ? pct(value) : String(value ?? dash)} />
              ))}
            </div>
          )}
          <ul>
            {holders.map((h, i) => (
              <li key={`${h.holder}:${i}`} className="row-rule flex items-center gap-2 px-3 py-2.5 text-caption">
                <span className="min-w-0 flex-1 truncate font-semibold">{h.holder ?? dash}</span>
                <span className="num shrink-0 text-muted-foreground">{compact(h.shares)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Widget>
  )
}

/* ── Dividends and splits ─────────────────────────────────────────────── */

function DividendsTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Dividend payments" span={6} />
  return <DividendsPanel symbol={active} span={6} scroll={TILE_BODY_HEIGHT} />
}

function SplitsTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Stock splits" />
  return <SplitsPanel symbol={active} span={4} scroll={TILE_BODY_HEIGHT} />
}

/* ── Earnings history ─────────────────────────────────────────────────── */

function EarningsHistoryTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Earnings history" span={6} />
  return <EarningsHistoryPanel symbol={active} span={6} scroll={TILE_BODY_HEIGHT} />
}

/* ── Earnings transcript ──────────────────────────────────────────────── */

function EarningsTranscriptTile() {
  const { active } = useBoardSymbols()
  if (!active) return <NeedsSymbol title="Earnings transcript" span={6} />
  return <EarningsTranscriptPanel symbol={active} span={6} scroll={TILE_BODY_HEIGHT * 2} />
}

/* ── Basket strip ─────────────────────────────────────────────────────── */

function BasketTile() {
  const { data } = useThemes()
  const themes = data?.themes ?? []
  const [id, setId] = useState<string | null>(null)
  const theme = themes.find(t => t.id === id) ?? themes[0] ?? null
  const quotes = useQuotes(theme?.symbols ?? [])
  return (
    <Widget
      span={4} title="Basket" subtitle={theme?.label ?? ""} scroll={TILE_BODY_HEIGHT}
      toolbar={themes.length > 1 ? (
        <select value={theme?.id ?? ""} onChange={e => setId(e.target.value)}
                className="h-[24px] border border-border bg-card px-1 text-caption">
          {themes.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
        </select>
      ) : undefined}
    >
      {!theme ? <Empty>no baskets configured</Empty> : (
        <ul>
          {theme.symbols.map(s => {
            const q = quotes.data?.quotes?.[s]
            const chg = q?.change_pct ?? null
            const up = (chg ?? 0) >= 0
            return (
              <li key={s} className="row-rule">
                <Link to={`/themes/${theme.id}?symbol=${encodeURIComponent(s)}`}
                      className="flex items-center gap-2 px-3 py-2.5 hover:bg-foreground/5">
                  <span className="num w-[64px] shrink-0 text-body font-extrabold">{s}</span>
                  <span className="num min-w-0 flex-1 text-right text-body">
                    {q?.price == null ? dash : q.price.toFixed(2)}
                  </span>
                  <span className={`num w-[68px] shrink-0 text-right text-caption ${
                    chg == null ? "text-muted-foreground" : up ? "text-gain" : "text-loss"}`}>
                    {chg == null ? dash : `${up ? "+" : ""}${chg.toFixed(2)}%`}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}

registerWidget({ id: "key-metrics", label: "Key metrics", order: 15, component: KeyMetricsTile, optIn: true })
registerWidget({ id: "reporting-soon", label: "Reporting soon", order: 20, component: ReportingSoonTile, optIn: true })
registerWidget({ id: "analyst-consensus", label: "Analyst consensus", order: 21, component: AnalystConsensusTile, optIn: true })
registerWidget({ id: "earnings-context", label: "Earnings context", order: 22, component: EarningsContextTile, optIn: true })
registerWidget({ id: "comparison", label: "Comparison", order: 23, component: ComparisonTile, optIn: true })
registerWidget({ id: "fundamentals", label: "Fundamentals", order: 24, component: FundamentalsTile, optIn: true })
registerWidget({ id: "basket", label: "Basket", order: 25, component: BasketTile, optIn: true })
registerWidget({ id: "filings", label: "Recent filings", order: 32, component: FilingsTile, optIn: true })
registerWidget({ id: "insider-trades", label: "Insider trades", order: 33, component: InsiderTile, optIn: true })
registerWidget({ id: "ownership", label: "Ownership", order: 34, component: OwnershipTile, optIn: true })
registerWidget({ id: "institutional", label: "Institutional ownership", order: 37, component: InstitutionalTile, optIn: true })
registerWidget({ id: "holders", label: "Stock ownership", order: 38, component: HoldersTile, optIn: true })
registerWidget({ id: "earnings-history", label: "Earnings history", order: 26, component: EarningsHistoryTile, optIn: true })
registerWidget({ id: "earnings-transcript", label: "Earnings transcript", order: 27, component: EarningsTranscriptTile, optIn: true })
registerWidget({ id: "dividends", label: "Dividend payments", order: 35, component: DividendsTile, optIn: true })
registerWidget({ id: "splits", label: "Stock splits", order: 36, component: SplitsTile, optIn: true })
