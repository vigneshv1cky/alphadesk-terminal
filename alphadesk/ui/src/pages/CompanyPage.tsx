import { Link, useSearchParams } from "react-router-dom"
import { ComposedBoard } from "@/components/ComposedBoard"
import { Empty, Stat, Table, TD, TH, THead, TR, Widget } from "@/components/terminal"
import { DEFAULT_SYMBOL } from "@/lib/boardSymbols"
import { useCompany } from "@/lib/queries"
import { isNeedsKey } from "@/lib/api"
import { KeyPrompt } from "@/components/KeyPrompt"
import type { CompanyProfile } from "@/lib/api"
import { FundBreakdownPanel, FundHoldingsPanel, useFund } from "@/components/FundPanels"
import { useKeyStats } from "@/components/KeyStatistics"

/** The company behind the symbol (2026-09-10): who it is, what it does,
 * where it is, who runs it.
 *
 * Two kinds of fact, kept visibly apart. The registrant record — legal
 * name, SIC, incorporation, fiscal year, addresses, former names — comes
 * from EDGAR, filed by the company. "What it does" and "where it is" are
 * the latest 10-K's Item 1 and Item 2, quoted VERBATIM with the filing they
 * came from; the plain-English summary, headcount, website and officers
 * come from the profile feed and are labelled as such. Nothing on this page
 * is paraphrased by a model.
 *
 * Scoped by the strip like every other page: ?symbol= is the input.
 */

const compact = (n: number | null | undefined) => {
  if (n == null) return "—"
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return n.toLocaleString()
}
const money = (n: number | null | undefined) => (n == null ? "—" : `$${compact(n)}`)
const addr = (a: { street?: string | null; city?: string | null; state?: string | null; zip?: string | null; country?: string | null } | null | undefined) =>
  a ? [a.street, [a.city, a.state].filter(Boolean).join(", "), a.zip, a.country].filter(Boolean).join(" · ") : null
const host = (u: string | null | undefined) => (u ? u.replace(/^https?:\/\//, "").replace(/\/$/, "") : null)

/** The citation, and nothing quoted: which item of which 10-K, opening
 * the document on EDGAR. What the company does and where it is are read
 * in the filing itself. */
function Cite({ item, filing }: {
  item: string
  filing: { accession: string; filing_date: string; url: string; form?: string; predecessor?: { name: string } | null } | null | undefined
}) {
  if (!filing) return <p className="px-3 py-2.5 text-caption text-muted-foreground">No annual report on file for this registrant.</p>
  return (
    <p className="px-3 py-2.5 text-caption text-muted-foreground">
      Source:{" "}
      <a href={filing.url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">
        {item}, Form {filing.form ?? "10-K"} filed {filing.filing_date}
      </a>
      {filing.predecessor
        ? <> by {filing.predecessor.name}, the predecessor registrant, on EDGAR. The ticker's current registrant has filed no annual report yet.</>
        : " on EDGAR."}
    </p>
  )
}

/** What this thing IS — said in the words for it, whatever it is.
 *
 * The profile feed's quote type separates funds, indices, currencies,
 * crypto and futures from equities; among equities the SEC's own signals
 * name the rest: SIC 6798 is a real estate investment trust, SIC 6770 a
 * blank-check company, a name ending in "LP" a limited partnership, a
 * name carrying "ADR" or "Depositary" an American depositary receipt, a
 * "Trust" a trust, a "Holdings" a holding company. Anything else is a
 * company, and only then is it called one. */
function kindOf(c: CompanyProfile): { noun: string; label: string } {
  const q = (c.profile?.quote_type ?? "").toUpperCase()
  const name = ` ${c.name} ${c.edgar?.legal_name ?? ""} `
  const sic = c.edgar?.sic ?? ""
  if (q === "ETF") return { noun: "fund", label: "Exchange-traded fund" }
  if (q === "MUTUALFUND") return { noun: "fund", label: "Mutual fund" }
  if (q === "MONEYMARKET") return { noun: "fund", label: "Money-market fund" }
  if (q === "INDEX") return { noun: "index", label: "Index" }
  if (q === "CURRENCY") return { noun: "pair", label: "Currency pair" }
  if (q === "CRYPTOCURRENCY") return { noun: "asset", label: "Cryptocurrency" }
  if (q === "FUTURE") return { noun: "contract", label: "Futures contract" }
  if (q === "OPTION") return { noun: "contract", label: "Option contract" }
  if (sic === "6798" || /\bREIT\b/i.test(name)) return { noun: "trust", label: "Real estate investment trust" }
  if (sic === "6770") return { noun: "company", label: "Blank-check company (SPAC)" }
  if (/\b(ADR|ADS|Depositary)\b/i.test(name) || c.edgar?.foreign_private_issuer) return { noun: "company", label: "American depositary receipt" }
  if (/\b(L\.?P\.?|Limited Partnership)\s*$/i.test(c.name.trim()) || /\bL\.?P\.?\b/.test(c.edgar?.legal_name ?? "")) return { noun: "partnership", label: "Limited partnership" }
  if (/\bTrust\b/i.test(name) && !/\bTrust (Bank|Co)/i.test(name)) return { noun: "trust", label: "Trust" }
  if (/\bHoldings?\b/i.test(name)) return { noun: "company", label: "Holding company" }
  if (/^60(2|3)/.test(sic)) return { noun: "bank", label: "Bank" }
  if (/^63/.test(sic)) return { noun: "insurer", label: "Insurance company" }
  return { noun: "company", label: "Company" }
}

/** A FUND IS NOT A COMPANY (2026-09-17). The company tile led with employees,
 * SIC, state of incorporation and fiscal year end — four dashes and two
 * irrelevancies for an ETF — while the facts a fund is judged on (who runs
 * it, what it costs, how big it is, when it started, what it pays) were
 * either further down the page or fetched and never shown. */
function FundIdentity({ c }: { c: CompanyProfile }) {
  const p = c.profile
  const fund = useFund(c.symbol).data
  const stats = useKeyStats(c.symbol).data
  const kind = kindOf(c)
  const site = p?.website ?? null
  const W = "text-body font-semibold"
  const pct = (n: number | null | undefined, digits = 2) => (n == null ? "—" : `${n.toFixed(digits)}%`)
  // The yield a holder actually receives: the trailing twelve months of
  // distributions over the current price. Shown only when both are known —
  // never a ratio built from one real number and one guess.
  const yieldPct = stats?.dividend_rate != null && stats?.price ? (stats.dividend_rate / stats.price) * 100 : null
  const subtitle = [kind.label, fund?.category, fund?.family].filter(Boolean).join(" · ") || undefined
  return (
    <Widget span={12} title={c.name} symbol={c.symbol} subtitle={subtitle}>
      <div className="grid grid-cols-2 sm:grid-cols-4">
        <Stat wrap label="Issuer" value={<span className={W}>{fund?.family ?? "—"}</span>} sub={fund?.legal_type ?? p?.quote_type ?? undefined} />
        <Stat wrap label="Listed" value={<span className={W}>{p?.exchange ?? "—"}</span>} sub={c.symbol} />
        <Stat label="Expense ratio" value={pct(fund?.expense_ratio)} sub="a year, of assets" />
        <Stat label="Net assets" value={money(fund?.net_assets)} sub={p?.currency ?? undefined} />
        <Stat wrap label="Inception" value={<span className={W}>{p?.start_date ?? "—"}</span>} sub={p?.start_date ? "first traded" : undefined} />
        <Stat label="Distribution yield" value={pct(yieldPct)} sub={stats?.dividend_rate != null ? `$${stats.dividend_rate.toFixed(2)} a share, trailing` : undefined} />
        <Stat wrap label="52-week range" value={<span className={W}>
          {stats?.week52_low != null && stats?.week52_high != null
            ? `${stats.week52_low.toFixed(2)} – ${stats.week52_high.toFixed(2)}` : "—"}</span>}
          sub={stats?.week52_position != null ? `${stats.week52_position.toFixed(0)}% of the range` : undefined} />
        <Stat label="Average volume" value={stats?.avg_volume != null ? compact(stats.avg_volume) : "—"}
              sub={stats?.beta != null ? `beta ${stats.beta.toFixed(2)}` : undefined} />
      </div>
      {site && (
        <p className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
          Fund page:{" "}
          <a href={site} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{host(site)}</a>
          {fund?.vendor ? ` · profile from ${fund.vendor}` : ""}
        </p>
      )}
    </Widget>
  )
}

function Identity({ c }: { c: CompanyProfile }) {
  const e = c.edgar, p = c.profile
  const site = p?.website || e?.website
  const phone = p?.phone ?? e?.phone ?? null
  const kind = kindOf(c)
  const subtitle = [kind.label, p?.sector, p?.industry].filter(Boolean).join(" · ") || undefined
  const W = "text-body font-semibold"
  return (
    <Widget span={12} title={c.name} symbol={c.symbol} subtitle={subtitle}>
      {/* Four to a row: eight cells on one row truncated every phrase. A
          thing with no SEC record — a cryptocurrency, an index — shows only
          the cells that have something in them rather than a row of dashes. */}
      <div className="grid grid-cols-2 sm:grid-cols-4">
        {e && <Stat wrap label="Legal name" value={<span className={W}>{e.legal_name ?? "—"}</span>} sub={`CIK ${e.cik}`} />}
        <Stat wrap label="Listed" value={<span className={W}>{(e?.exchanges?.[0] ?? p?.exchange) ?? "—"}</span>} sub={e?.tickers?.join(", ")} />
        {(e || p?.employees != null) && <Stat label="Employees" value={p?.employees != null ? p.employees.toLocaleString() : "—"} sub={p?.employees != null ? "full-time" : undefined} />}
        {p?.market_cap != null && <Stat label="Market cap" value={money(p.market_cap)} sub={p.currency ?? undefined} />}
        {!e && p?.currency && p.market_cap == null && <Stat label="Currency" value={<span className={W}>{p.currency}</span>} />}
        {p?.circulating_supply != null && <Stat label="Circulating supply" value={compact(p.circulating_supply)} sub={p.start_date ? `since ${p.start_date}` : undefined} />}
        {p?.expiry && <Stat label="Front month expires" value={<span className={W}>{p.expiry}</span>} sub={p.underlying ?? undefined} />}
        {p?.open_interest != null && <Stat label="Open interest" value={compact(p.open_interest)} sub="contracts" />}
        {e && <Stat wrap label="Incorporated" value={<span className={W}>{e.state_of_incorporation ?? "—"}</span>} sub={e.entity_type ?? undefined} />}
        {e && <Stat wrap label="Fiscal year end" value={<span className={W}>{e.fiscal_year_end ?? "—"}</span>} sub={e.filer_category ?? undefined} />}
        {e && <Stat wrap label="SIC" value={<span className={W}>{e.sic ?? "—"}</span>} sub={e.sic_description ?? undefined} />}
        {/* Website when there is one; otherwise the phone stands on its
            own under its own label, instead of a dash with a number under it. */}
        {site
          ? <Stat wrap label="Website" value={<a href={site} target="_blank" rel="noreferrer" className={`${W} text-accent-700 hover:underline`}>{host(site)}</a>} sub={phone ?? undefined} />
          : phone ? <Stat wrap label="Phone" value={<span className={W}>{phone}</span>} /> : null}
      </div>
      {e?.former_names?.length ? (
        <p className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
          Formerly {e.former_names.map(f => `${f.name}${f.from ? ` (${f.from.slice(0, 4)}–${f.to?.slice(0, 4) ?? ""})` : ""}`).join("; ")}.
        </p>
      ) : null}
      {c.sources.length > 0 && (
        <p className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
          Sources:{" "}
          {c.sources.map((x, i) => (
            <span key={x.url}>
              {i > 0 && " · "}
              <a href={x.url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{x.label}</a>
            </span>
          ))}
        </p>
      )}
    </Widget>
  )
}

/** What a non-registrant IS: the feed's description for a cryptocurrency,
 * an authored reference note for an index, a contract or a pair — each
 * labelled as what it is, with the publisher to read further. */
function WhatItIs({ c }: { c: CompanyProfile }) {
  const kind = kindOf(c)
  const p = c.profile
  // The feed fills `summary` for funds and `description` for coins; reading
  // only one of them printed "No description on file" over a description
  // that was right there (2026-09-17, every ETF without an SEC record).
  const text = p?.description || p?.summary || null
  const ref = c.reference
  return (
    <Widget span={7} title={`What the ${kind.noun} is`} subtitle={ref ? "reference note, with its sources" : "from the profile feed"}>
      {text && (
        <div className="border-b border-row-rule px-3 py-3">
          <p className="text-body leading-[1.6] text-foreground/90">{text}</p>
          <p className="mt-1.5 text-caption text-muted-foreground">Profile feed description.</p>
        </div>
      )}
      {ref && (
        <div className="px-3 py-3">
          <p className="text-body leading-[1.6] text-foreground/90">{ref.what}</p>
          <p className="mt-1.5 text-caption text-muted-foreground">
            Reference note. Sources:{" "}
            {ref.sources.map((x, i) => (
              <span key={x.url}>
                {i > 0 && " · "}
                <a href={x.url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{x.label}</a>
              </span>
            ))}.
          </p>
        </div>
      )}
      {!text && !ref && (
        <p className="px-3 py-3 text-body text-muted-foreground">No description on file for this {kind.noun}.</p>
      )}
    </Widget>
  )
}

const FIN_ROWS: { key: string; label: string }[] = [
  { key: "revenue", label: "Revenue" },
  { key: "net_income", label: "Net income" },
  { key: "eps_diluted", label: "EPS, diluted" },
  { key: "assets", label: "Total assets" },
  { key: "equity", label: "Shareholders' equity" },
  { key: "cash", label: "Cash and equivalents" },
  { key: "long_term_debt", label: "Long-term debt" },
]
const fmtFin = (v: number, unit: string) =>
  unit === "USD/shares" ? `$${v.toFixed(2)}` : unit === "USD" ? money(v) : compact(v)

/** The SEC's structured facts — the latest full-year figures as the
 * company tagged them in its own 10-K, each with the period and the
 * filing it came from. Not the feed's numbers: the filing's. */
export function Financials({ c, span = 7 }: { c: CompanyProfile; span?: number }) {
  const f = c.financials
  if (!f || (!Object.keys(f.items).length && !f.shares_outstanding)) return null
  const rows = FIN_ROWS.filter(r => f.items[r.key])
  return (
    <Widget span={span} title="Financials, as filed" subtitle={f.as_of ? `latest full year · period ended ${f.as_of}` : undefined}>
      <Table>
        <THead>
          <TH className="w-[44%]" title="The financial line as the company tagged it in its annual report">Line</TH>
          <TH align="right" title="The figure as filed">Value</TH>
          <TH align="right" className="w-[30%]" title="The last day of the period the figure covers">Period end</TH>
        </THead>
        <tbody>
          {rows.map(r => {
            const it = f.items[r.key]
            return (
              <TR key={r.key}>
                <TD className="font-semibold">{r.label}</TD>
                <TD align="right" mono className={r.key === "net_income" ? (it.val >= 0 ? "text-gain" : "text-loss") : ""}>{fmtFin(it.val, it.unit)}</TD>
                <TD align="right" mono className="text-muted-foreground">{it.end}</TD>
              </TR>
            )
          })}
          {f.shares_outstanding && (
            <TR>
              <TD className="font-semibold">Shares outstanding</TD>
              <TD align="right" mono>{compact(f.shares_outstanding.val)}</TD>
              <TD align="right" mono className="text-muted-foreground">{f.shares_outstanding.end}</TD>
            </TR>
          )}
        </tbody>
      </Table>
      <p className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
        Source: the SEC's XBRL company facts, as tagged in the filings
        {f.predecessor ? ` of ${f.predecessor.name}, the predecessor registrant` : ""} ·{" "}
        <a href={f.source_url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">the record on data.sec.gov</a>.
      </p>
    </Widget>
  )
}

/** CoinGecko's record for a coin: what it is, its categories, links,
 * supply and launch, with attribution and the coin's page. */
function CoinPanel({ c, span = 7 }: { c: CompanyProfile; span?: number }) {
  const k = c.coin
  if (!k) return null
  const links = [
    k.homepage ? { label: "Homepage", url: k.homepage } : null,
    k.whitepaper ? { label: "Whitepaper", url: k.whitepaper } : null,
    ...k.explorers.map((u, i) => ({ label: i === 0 ? "Explorer" : `Explorer ${i + 1}`, url: u })),
  ].filter((x): x is { label: string; url: string } => !!x)
  return (
    <Widget span={span} title={`What ${k.name ?? k.symbol} is`} subtitle={k.categories.join(" · ") || undefined}>
      {k.description && (
        <div className="border-b border-row-rule px-3 py-3">
          <p className="text-body leading-[1.6] text-foreground/90">{k.description}</p>
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4">
        {k.market_cap_rank != null && <Stat label="Market cap rank" value={`#${k.market_cap_rank}`} />}
        {k.circulating_supply != null && <Stat label="Circulating" value={compact(k.circulating_supply)} sub={k.symbol} />}
        {k.max_supply != null && <Stat label="Max supply" value={compact(k.max_supply)} sub={k.symbol} />}
        {k.genesis_date && <Stat label="Genesis" value={<span className="text-body font-semibold">{k.genesis_date}</span>} sub={k.hashing_algorithm ?? undefined} />}
      </div>
      <p className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">
        <a href="https://www.coingecko.com" target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{k.attribution}</a> ·{" "}
        <a href={k.url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{k.name ?? k.symbol} on CoinGecko</a>
        {links.map(l => (
          <span key={l.url}> · <a href={l.url} target="_blank" rel="noreferrer" className="font-semibold text-accent-700 underline decoration-dotted hover:text-foreground">{l.label}</a></span>
        ))}
      </p>
    </Widget>
  )
}

function Business({ c }: { c: CompanyProfile }) {
  return (
    <Widget span={7} title={`What the ${kindOf(c).noun} does`} subtitle="the profile feed's summary, and where the filing says it">
      {c.profile?.summary && (
        <div className="border-b border-row-rule px-3 py-3">
          <p className="text-body leading-[1.6] text-foreground/90">{c.profile.summary}</p>
          <p className="mt-1.5 text-caption text-muted-foreground">Profile feed summary.</p>
        </div>
      )}
      <Cite item={c.tenk?.business_item ?? "Item 1, Business"} filing={c.tenk} />
    </Widget>
  )
}

function Locations({ c }: { c: CompanyProfile }) {
  const hq = addr(c.edgar?.business_address) ?? addr(c.profile?.address)
  const mail = addr(c.edgar?.mailing_address)
  return (
    <Widget span={5} title={`Where the ${kindOf(c).noun} is`}
            subtitle={`headquarters on record, and the ${c.tenk?.form ?? "10-K"}'s properties`}>
      <div className="border-b border-row-rule px-3 py-3 text-body">
        <div className="text-label font-medium uppercase tracking-caps text-muted-foreground">Headquarters</div>
        <div className="mt-0.5 font-semibold">{hq ?? "—"}</div>
        {mail && mail !== hq && (
          <div className="mt-1 text-caption text-muted-foreground">Mailing: {mail}</div>
        )}
        <div className="mt-1 text-caption text-muted-foreground">Business address as filed with the SEC.</div>
      </div>
      <Cite item={c.tenk?.properties_item ?? "Item 2, Properties"} filing={c.tenk} />
    </Widget>
  )
}

function Officers({ c }: { c: CompanyProfile }) {
  if (!c.officers.length) return null
  return (
    <Widget span={12} title="Who runs it" subtitle="officers as listed by the profile feed" scroll={360}>
      <Table>
        <THead>
          <TH className="w-[36%]" title="The officer's name">Name</TH>
          <TH title="Their role at the company">Title</TH>
          <TH align="right" className="w-[10%]" title="Age as the profile feed lists it">Age</TH>
          <TH align="right" className="w-[16%]" title="Total compensation for the latest reported year, as the profile feed lists it">Total pay</TH>
        </THead>
        <tbody>
          {c.officers.map(o => (
            <TR key={`${o.name}-${o.title}`}>
              <TD className="font-semibold">{o.name}</TD>
              <TD className="text-muted-foreground">{o.title ?? "—"}</TD>
              <TD align="right" mono>{o.age ?? "—"}</TD>
              <TD align="right" mono>{money(o.total_pay)}</TD>
            </TR>
          ))}
        </tbody>
      </Table>
    </Widget>
  )
}

/** The filed financials for a symbol, self-loading — so a page other than
 * the Profile (Analysis, 2026-09-12) can place the same panel. Nothing
 * while the record loads or when the registrant has no statements. */
/** A coin's CoinGecko record as a board tile (Analysis, 2026-09-19); the
 * key prompt when no coin vendor is connected. */
export function CoinRecordPanel({ symbol, span = 12 }: { symbol: string; span?: number }) {
  const { data, error } = useCompany(symbol)
  if (isNeedsKey(error)) {
    return <Widget span={span} title={symbol}><KeyPrompt prompt={error.prompt} /></Widget>
  }
  if (!data?.coin) return null
  return <CoinPanel c={data} span={span} />
}

export function FinancialsPanel({ symbol, span = 7 }: { symbol: string; span?: number }) {
  const { data } = useCompany(symbol)
  if (!data?.financials) return null
  return <Financials c={data} span={span} />
}

export default function CompanyPage() {
  const [params] = useSearchParams()
  // Wider than the strip's cleaner: the cross-asset board's symbols carry
  // ^ (indices), = (futures, FX) and - (crypto pairs).
  const symbol = (params.get("symbol") || "").toUpperCase().replace(/[^A-Z0-9.\-^=]/g, "").slice(0, 14) || DEFAULT_SYMBOL
  const { data, isPending, error } = useCompany(symbol)

  if (isPending) {
    return <div className="p-3"><Widget span={12} title={symbol}><Empty>reading the registrant record and the latest 10-K…</Empty></Widget></div>
  }
  // A COIN has no registrant anywhere; what it needs is a vendor that
  // carries coins, and the server says which (2026-09-15).
  if (isNeedsKey(error)) {
    return (
      <div className="p-3">
        <Widget span={12} title={symbol}>
          <KeyPrompt prompt={error.prompt} />
        </Widget>
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="p-3">
        <Widget span={12} title={symbol}>
          <Empty>No registrant record for {symbol} — it may be an index or a foreign listing without an SEC registrant. See its <Link to={`/analysis?symbol=${symbol}`} className="underline">filings</Link>.</Empty>
        </Widget>
      </div>
    )
  }
  const registrant = !!data.edgar
  const hasAddress = !!(data.edgar?.business_address || data.profile?.address?.city)
  const qt = (data.profile?.quote_type ?? "").toUpperCase()
  const isFund = qt === "ETF" || qt === "MUTUALFUND"
  return (
    <ComposedBoard
      page="company"
      panels={[
        { id: "identity", label: "Identity",
          node: isFund ? <FundIdentity c={data} /> : <Identity c={data} /> },
        // A fund is what it holds: the positions and the breakdown sit
        // where a company's business description would.
        ...(isFund ? [
          { id: "fund-holdings", label: "Holdings", node: <FundHoldingsPanel symbol={symbol} span={6} /> },
          { id: "fund-breakdown", label: "Fund breakdown", node: <FundBreakdownPanel symbol={symbol} span={6} /> },
        ] : []),
        registrant
          ? { id: "business", label: "What it does", node: <Business c={data} /> }
          : data.coin
            ? { id: "business", label: "What it is", node: <CoinPanel c={data} /> }
            : { id: "business", label: "What it is", node: <WhatItIs c={data} /> },
        // The record panels — financials, dividends, splits, ownership,
        // insiders — moved to Analysis (2026-09-12); the Profile is who the
        // company is, where it is and who runs it.
        // A fund's address on file is its filing agent's (SPY's is the
        // NYSE's own 11 Wall Street), which says nothing about the fund.
        ...(hasAddress && !isFund ? [{ id: "locations", label: "Where it is", node: <Locations c={data} /> }] : []),
        ...(data.officers.length ? [{ id: "officers", label: "Who runs it", node: <Officers c={data} /> }] : []),
      ]}
    />
  )
}
