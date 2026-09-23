// AlphaDesk API client — same-origin; Basic Auth handled by the browser.

export interface Concern {
  claim: string
  evidence: string
}

export interface Rebuttal {
  rebuttal: string
  revised_score: number
  concede: boolean
}

export interface Debate {
  concerns?: Concern[]
  rebuttal?: Rebuttal
  fact_flags?: string[]
  arbiter_summary?: string
  critic_stance?: string
  counter_direction?: string
  counter?: string
  proposed_direction?: string
  final_direction?: string
  flipped?: boolean
}

export interface Brief {
  kind: string
  summary: string
  key_facts?: { fact: string }[]
}

// Actionable execution levels for a committed call (may be null if the desk
// couldn't set a coherent plan — the directional call still stands).
export interface Plan {
  entry: number
  target: number
  stop: number
  note: string
  hold: string // "single-day" | "multi-day"
}

// One open pick tracked live against the current price.

// One call in a symbol's timeline, with its outcome.


export interface EarningsRow {
  symbol: string
  company_name?: string | null
  report_date: string
  session: string | null
  eps_estimate: number | null
  eps_actual?: number | null
  surprise_pct?: number | null
  market_cap?: number | null // biggest names first within a day group
  low_liquidity?: boolean | null // 20d avg $vol bar; null = unmeasurable
  /** Whether the company has named its report time. False while the date is
   * still the calendar's projection from the prior year. */
  confirmed?: boolean | number | null
  /** Analysts behind the EPS estimate. */
  estimate_count?: number | null
  /** Which calendars listed it, comma-joined: nasdaq, finnhub, alphavantage. */
  sources?: string | null
  /** When the actual EPS was FIRST seen here (ISO) — the surprise's age. */
  actual_at?: string | null
  /** EDGAR's acceptance of the earnings 8-K (ISO) — the report is out. */
  released_at?: string | null
  run_at?: string | null // day-group key for upcoming reporters
  public_at?: string | null // when the report goes public (BMO/DAY 9:30, AMC 16:00 ET)
  pre_report_close?: number | null
  implied_move_pct?: number | null // options-implied move — the market's own expectation
  // NOTE: post-report drift (move_*_pct) and desk engagement are gone. Both
  // came from tables the retired trading engine wrote; nothing populates them.
  /** The report sits on the day its results 8-K was filed, not the vendor's date. */
  date_from_edgar?: boolean
  /** A results 8-K landed days before this still-to-come report — preliminary
   * or restated figures, not this quarter — so the date was left alone. */
  earlier_release_on?: string | null
  /** No calendar vendor listed it; the row is the results 8-K alone. */
  edgar_only?: boolean
  released_on?: string | null
  /** One vendor's "actual" that is exactly its estimate, with no SEC filing
   * behind it: a placeholder, not shown as an actual; the report stays pending. */
  placeholder_actual?: number | null
  placeholder_source?: string | null
  /** "primary" (the company's exchange listing), "secondary" (its warrants,
   * preferreds, another class) or "otc". The calendar hides the last two by default. */
  listing?: "primary" | "secondary" | "otc"
  session_predicted?: "BMO" | "AMC" | null
  /** How many of the company's recent same-day releases the prediction rests on. */
  session_basis?: number | null
  eps_estimate_unadjusted?: number | null
  split_note?: string | null
  actual_basis?: string | null
  actual_source?: string | null
  /** The day and instant EDGAR accepted the results 8-K — later than the
   * release when the company filed days after it. */
  filed_on?: string | null
  filed_at?: string | null
  vendor_date?: string
  /** The session the vendor listed, when the company's announcement named another. */
  vendor_session?: string | null
  /** The company's own press release naming the report date (and, when it
   * says so, the session) — what dated this row over the vendor's projection. */
  announcement?: EarningsAnnouncement | null
  /** Twenty-session annualised volatility, percent, from the user's chart vendor. */
  volatility?: number | null
  /** Twenty-session average dollar volume a day. */
  liquidity?: number | null
}

// A pick as shown in the Sessions view (decision + lifecycle + outcome).
export interface SessionPick {
  id: number
  ts: string
  symbol: string
  direction: "LONG" | "SHORT"
  edge: string | null
  verdict: string | null
  approved: number
  adjusted_score: number | null
  confidence: number
  session: string
  horizon_days: number
  plan_entry: number | null
  plan_target: number | null
  plan_stop: number | null
  plan_note: string | null
  entry_price: number | null
  alpha_net: number | null
  graded_at: string | null
  exit_ts: string | null
  exit_reason: string | null
  exit_return_pct: number | null
}

export interface SessionAgg {
  n: number
  open: number
  graded: number
  wins: number
  avg_alpha: number | null
}

export interface Quote {
  /** Which live feed priced it: "sip" on a real-time plan, "iex" on a free key. */
  feed?: "sip" | "iex"
  realtime?: boolean
  symbol: string
  name: string
  exchange: string | null
  currency: string
  price: number
  change: number
  change_pct: number | null
  previous_close: number | null
  /** What the change above is measured from: the previous close inside the
   * regular session, the session's own close once it has ended and the
   * price is an extended-hours print. */
  change_from?: number | null
  /** The extended-hours print, when one exists: its price, its move from the
   * close it is measured against, and when it was struck. */
  extended_hours?: { price: number; change_pct: number; from_close: number; as_of: string } | null
  open: number | null
  bid: number | null
  ask: number | null
  bid_size: number | null
  ask_size: number | null
  day_low: number | null
  day_high: number | null
  week52_low: number | null
  week52_high: number | null
  volume: number | null
  avg_volume: number | null
  market_cap: number | null
  enterprise_value: number | null
  pe_forward: number | null
  pe_trailing: number | null
  peg: number | null
  price_to_sales: number | null
  price_to_book: number | null
  beta: number | null
  eps_ttm: number | null
  dividend_yield: number | null
  target_mean: number | null
  target_low: number | null
  target_high: number | null
  analyst_rating: string | null
  analyst_count: number | null
  exchange_name?: string | null
  quote_source?: string | null
  as_of?: string | null
  dividend_rate?: number | null
  ex_dividend_date?: string | null
  earnings_date?: string | null
  /** The last fiscal year end, a date; names the fiscal quarters. */
  fiscal_year_end?: string | null
}

export interface MoverRow {
  symbol: string
  /** From the cached Alpaca asset list. Null when unknown — a blank cell beats
   * repeating the ticker that is already in the column beside it. */
  name?: string | null
  price: number | null
  change_pct: number | null
  volume: number
  /** Recent closes, coarse (15-minute bars). Empty when the feed had too
   * little to draw — the row then renders without a spark rather than with a
   * flat line, which would read as "no movement" instead of "no data". */
  spark: number[]
}

export interface Movers {
  most_active: MoverRow[]
  gainers: MoverRow[]
  losers: MoverRow[]
}

/** One day of the week strip. Present even when empty — seven cells is what
 * makes the strip read as a week. */
export interface EarningsDay {
  date: string
  weekday: string
  count: number
  rows: EarningsRow[]
}

export interface EarningsAnnouncement {
  url: string
  published_at: string
  source?: string | null
  /** "stated" when the release names the session, "call time" when a
   * conference call before 9:30 or from 16:00 ET implies it. */
  basis?: string | null
  /** The sentence that names the date, as the release worded it. */
  sentence?: string | null
}

/** One company's reports in the reader's calendar vendors, four months
 * either side of today, dated as the week view dates them — the calendar's
 * symbol filter. `pick` is the report nearest today. */
export interface EarningsFindReport {
  report_date: string
  session: string | null
  confirmed: boolean
  eps_estimate: number | null
  eps_actual: number | null
  released_at: string | null
  released_on: string | null
  vendor_date?: string | null
  edgar_only: boolean
  date_from_edgar?: boolean
  earlier_release_on?: string | null
  announcement?: EarningsAnnouncement | null
}
/** The left rail's three numbers, and the board's story identities — what
 * the rail needs and nothing more (2026-09-16). */
export interface Rail {
  news_symbols: number
  earnings_calls: number | null
  stories: { article_id: string; tickers: string[]; published_at: string | null }[]
}

export interface EarningsFind {
  symbol: string
  company_name: string | null
  listed: boolean
  reports: EarningsFindReport[]
  pick: string | null
  start: string
  end: string
}

export interface EarningsWeek {
  start: string
  end: string
  today: string
  days: EarningsDay[]
  /** Lookups still running in the background for a busy week: companies whose
   * usual report time, and whose press releases, are not in yet. */
  pending?: { timing?: number; announcements?: number }
}


/** One reported quarter — the EPS chart's dots. */
export interface ReportHistoryRow {
  date: string
  period_end?: string | null
  date_kind?: "report" | "period_end"
  eps_estimate: number | null
  eps_actual: number | null
  surprise_pct: number | null
}

/** The company's reported record, all code-fetched facts. Every field is
 * best-effort: a company no connected vendor describes returns just the symbol. */
export interface EarningsContext {
  symbol: string
  report_history?: ReportHistoryRow[]
  beat_streak?: string
  revenue_qoq_pct?: number
  revenue_last4_bn?: number[]
  net_income_last4_bn?: number[]
  next_q_eps_estimate?: number
  estimate_30d_change_pct?: number
  revisions_30d?: { up: number; down: number }
}

/** One report in the record. `upcoming` rows carry estimates only; a past
 * revenue ESTIMATE is not on any free source, so that field is filled for
 * the upcoming report alone. Revenue is raw dollars. */
export interface EarningsHistoryRow {
  /** The report date, or — when `date_kind` is "period_end" — the quarter
   * end a vendor dates its rows by (Finnhub does). */
  date: string
  period_end?: string | null
  date_kind?: "report" | "period_end"
  upcoming: boolean
  eps_estimate: number | null
  eps_actual: number | null
  surprise_pct: number | null
  revenue: number | null
  revenue_estimate: number | null
}

export interface EarningsHistory {
  symbol: string
  reports: EarningsHistoryRow[]
}

/** One earnings document on record. `kind` on the listing says what the
 * source serves: a results press release the company filed (free, EDGAR)
 * or a recorded call from a keyed vendor. */
export interface TranscriptRow {
  id: string
  date: string | null
  title: string
  period_end: string | null
  url: string | null
}

export interface TranscriptList {
  symbol: string
  provider: string
  kind: "release" | "call"
  transcripts: TranscriptRow[]
  error?: string
}

export interface TranscriptDoc extends TranscriptRow {
  symbol: string
  provider: string
  kind: "release" | "call"
  text: string
}

/** Analyst consensus band for one period. These are FORECASTS — the one place
 * the terminal shows one — and render labelled as consensus. */
export interface InsightBand {
  analysts: number | null
  avg: number | null
  low: number | null
  high: number | null
}

export interface EarningsInsights {
  symbol: string
  periods: {
    period: string
    label: string
    eps: InsightBand | null
    revenue: InsightBand | null
  }[]
}

/** One row of the symbol picker. Exchange and asset class come from the cached
 * Alpaca asset list, so they describe what this terminal can actually render. */
export interface SymbolHit {
  symbol: string
  name: string | null
  exchange: string | null
  asset_class: string | null
}

export type MetricPeriod = "quarterly" | "annual"
export type MetricStyle = "bars" | "line" | "area"

export interface FundamentalMetric {
  id: string
  label: string
  group: string
  unit: "currency" | "eps"
}

export interface Fundamentals {
  symbol: string
  period: MetricPeriod
  /** Only metrics upstream actually reports for this company — a menu entry
   * that would draw an empty line is not offered at all. */
  metrics: FundamentalMetric[]
  series: Record<string, { t: string; v: number }[]>
}

/** Crypto rows reuse MoverRow: same columns, same renderer. `all` is the
 * configured order rather than a ranking — the unsorted view. */
export interface CryptoMovers {
  all: MoverRow[]
  most_active: MoverRow[]
  gainers: MoverRow[]
  losers: MoverRow[]
}

/** A curated basket. Server-side config: nothing here is scored or ranked,
 * and `symbols` is in the order it was written. */
export interface Theme {
  id: string
  label: string
  /** The kind of news that moves the basket's members together (2026-09-18). */
  why?: string | null
  symbols: string[]
  /** The reader made it (2026-09-18); curated baskets carry no flag. */
  mine?: boolean
}

/** One contract. No implied_volatility and no greeks: the feed returns both as
 * null on this entitlement, so they are absent rather than columns of dashes.
 * `mid` is null unless BOTH sides quote — a mid off a one-sided book is an
 * invented price, not a wide one. */
export interface OptionRow {
  symbol: string
  strike: number
  bid: number | null
  ask: number | null
  last: number | null
  mid: number | null
  open_interest: number
  bid_size?: number | null
  ask_size?: number | null
  /** Contracts traded in the chain's latest session (0 when none). */
  volume?: number
  /** Last against the previous session's close, percent. */
  change_pct?: number | null
  /** Percent: 32.0 is 32%. */
  implied_volatility?: number | null
  delta?: number | null
  gamma?: number | null
  theta?: number | null
  vega?: number | null
  rho?: number | null
}

/** One big order on the options tape (ingest/options_flow.py): the prints
 * on one contract in the same millisecond, merged. */
export interface OptionFlowTrade {
  t: string
  ticker: string
  contract: string
  underlying: string
  expiry: string
  type: "call" | "put"
  strike: number
  dte: number | null
  price: number
  size: number
  premium: number
  exchange: string | null
  /** At the ask, the bid or between — null when the trade was not seen close
   * enough to its quote to know. */
  side: "ask" | "bid" | "mid" | null
  /** Where the fill sat in the spread, 0 (bid) to 1 (ask). */
  fill: number | null
  bid: number | null
  ask: number | null
  volume: number | null
  open_interest: number | null
  /** The stock's price at the order's minute. */
  stock: number | null
  exchanges: string[]
  /** OPRA condition codes, and the same in words. */
  conditions: string[]
  code: string
  prints: number
  /** sweep, multi-leg, stock-tied, auction, cross, floor, extended, late, size>OI */
  flags: string[]
  /** Of the contract's volume seen live today, the share filled at the ask
   * and at the bid; null until any is seen. */
  ask_share: number | null
  bid_share: number | null
  share_contracts: number
}
export interface OptionFlow {
  symbols: string[]
  trades: OptionFlowTrade[]
  errors?: Record<string, string>
  /** When this reader's capture began: sides are known only after it. */
  live_since: string
  contracts: number
  feed?: "opra" | "indicative"
  session?: string
  min_premium: number
}

export interface OptionChain {
  symbol: string
  expiry: string
  /** "opra" on a real-time options plan, "indicative" (delayed) otherwise. */
  feed?: "opra" | "indicative"
  realtime?: boolean
  calls: OptionRow[]
  puts: OptionRow[]
}

export interface TapeEntry {
  symbol: string
  label: string
  price: number
  change_pct: number
}

export interface SystemInfo {
  /** Reader-scoped since 2026-09-18: the operator's telemetry (uptime, EDGAR
   * pacing, plugin seams, other readers' live connections) is no longer
   * returned, and the System health page that printed it is gone. */
  market: string
  news: {
    last_article_at: string | null
    articles_today: number
  }
  providers?: {
    available: Record<string, string[]>
  }
}

/** A 401 from any DATA route means the session ended (or never was) on a
 * gated instance — one event, and the shell swaps to the login screen. The
 * auth routes themselves are excluded: a wrong password is a form error,
 * not a session ending. */
function noteUnauthorized(path: string, status: number) {
  if (status === 401 && path.startsWith("/api") && !path.startsWith("/api/auth")) {
    window.dispatchEvent(new Event("alphadesk:unauthorized"))
  }
  // 402: the access gate stopped an account whose trial has ended — the
  // shell swaps to the subscribe screen (App.tsx), as a 401 swaps to sign-in.
  if (status === 402 && path.startsWith("/api") && !path.startsWith("/api/billing")) {
    window.dispatchEvent(new Event("alphadesk:payment-required"))
  }
}

/** A failed request, with the status a caller may branch on — a 404 is
 * an answer ("nothing there"), a 503 is not. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** What a panel shows when no data vendor the user connected serves it
 * (HTTP 428 from the server, 2026-09-13): the surface, which vendors would
 * fill it with their plan tier and signup link, and which of the user's own
 * vendors refused it on plan. AlphaDesk carries no market data of its own. */
export interface KeyPromptBody {
  surface: string
  label: string
  signed_in: boolean
  refused: string[]
  /** Labels of the reader's OWN vendors that carry this surface — they were
   * asked, so the panel must not offer them as something to connect. */
  connected?: string[]
  vendors: { name: string; label: string; tier: "free" | "paid"; signup: string; needs_secret: boolean; have?: boolean }[]
}

export interface DataVendors {
  connected: string[]
  vendors: {
    name: string; label: string; signup: string; needs_secret: boolean; note: string
    /** False for a SCRAPED source: read off a public page, no key to paste,
     * switched on with a button, and asked only after every keyed vendor. */
    official?: boolean
    /** Scraped sources only: what switching this on would actually give you,
     * given the vendors you have keyed. A keyed vendor is always asked
     * first, so a source whose every surface is already covered can never
     * answer — and the switch should say so rather than imply otherwise. */
    coverage?: {
      only_source_for: string[]
      already_covered: { surface: string; vendors: string[] }[]
    }
    serves: { surface: string; label: string; tier: "free" | "paid" }[]
    /** What the connected key's plan delivers; Alpaca only. */
    plan?: { realtime: boolean; stocks: "sip" | "iex"; options: "opra" | "indicative" | null; chart_delay_minutes: number } | null
  }[]
}

/** A catalyst: something that happened, with its own clock (2026-09-22).
 * Four feeds share this shape so one tape can show them together. */
export interface CatalystRow {
  /** Which feed it came from: filings, halts, government, social. */
  feed: "filings" | "halts" | "government" | "social"
  /** What kind of thing happened, in the source's own words ("8-K",
   * "SCHEDULE 13D", "Volatility pause", "Proposed Rule", "Post"). */
  kind: string
  /** The one-line record. Never a summary written here. */
  title: string
  /** When, ISO. Read `precision` before comparing two of these. */
  at: string
  /** "second" is a real moment; "day" means the source publishes once a day
   * and the event usually happened earlier. */
  precision: "second" | "day"
  /** Tickers the SOURCE tied to it — never read out of free text. */
  symbols: string[]
  url: string | null
  /** Who published it, for the row's provenance line. */
  via: string | null
  /** Present when the row must not be acted on as stated (social). */
  trust?: string | null
}

export interface CatalystFeed {
  rows: CatalystRow[]
  /** Feeds that could not be read, and why — never shown as "nothing
   * happened". */
  unavailable: Record<string, string>
}

export class NeedsKeyError extends ApiError {
  prompt: KeyPromptBody
  constructor(prompt: KeyPromptBody) {
    super(`${prompt.label} needs a data key`, 428)
    this.prompt = prompt
  }
}

export const isNeedsKey = (err: unknown): err is NeedsKeyError => err instanceof NeedsKeyError

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    noteUnauthorized(path, res.status)
    // The server's own sentence when it wrote one — "Your polygon plan does
    // not include 1 sec bars: …" beats "/api/chart/NVDA: 402".
    let detail = ""
    let body: { detail?: unknown } | null = null
    try { body = await res.json() } catch { /* not JSON */ }
    const needs = (body?.detail as { needs_key?: KeyPromptBody } | undefined)?.needs_key
    if (res.status === 428 && needs) throw new NeedsKeyError(needs)
    if (typeof body?.detail === "string") detail = body.detail
    throw new ApiError(detail || `${path}: ${res.status}`, res.status)
  }
  return res.json() as Promise<T>
}

// ── Human decision support (Phase 0) ────────────────────────────────────────

export interface ChartBar {
  t: string
  o: number
  h: number
  l: number
  c: number
  /** Bar volume. Optional: a response cached before this field existed has no
   * `v`, and the histogram treats that as zero rather than crashing. */
  v?: number
}

/** OHLC + indicator series for the decision chart.
 *
 * `indicators_reliable` is NOT cosmetic. Alpaca's free IEX feed carries a few
 * percent of consolidated volume, so an illiquid name's "1-minute" series can
 * be a handful of prints stretched over days — and it renders identically to a
 * real one. Never draw RSI/MACD without surfacing this. */
/** 1D and 5D come off the minute feed; everything longer off daily bars,
 * because the minute feed only reaches about 30 days. The server owns this
 * mapping (ingest/prices.CHART_RANGES) so the two cannot disagree. */
export type ChartRange = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y" | "MAX"

/** The company behind a symbol — ingest/company. `edgar` is the SEC
 * registrant record; `tenk` carries the latest 10-K's Business and
 * Properties sections verbatim; `profile` and `officers` are the profile
 * feed's. Any of them may be null when that source does not know the symbol. */
export interface CompanyAddress { street: string | null; city: string | null; state: string | null; zip: string | null; country: string | null }
export interface CompanyProfile {
  symbol: string
  name: string
  edgar: {
    cik: string; legal_name: string | null; sic: string | null; sic_description: string | null
    /** Files 20-F/40-F rather than 10-K — on a US exchange, an ADR. */
    foreign_private_issuer: boolean
    state_of_incorporation: string | null; fiscal_year_end: string | null
    entity_type: string | null; filer_category: string | null; phone: string | null
    website: string | null; investor_website: string | null
    exchanges: string[]; tickers: string[]
    former_names: { name: string; from: string | null; to: string | null }[]
    business_address: CompanyAddress | null; mailing_address: CompanyAddress | null
  } | null
  profile: {
    name: string | null; summary: string | null; sector: string | null; industry: string | null
    description: string | null; circulating_supply: number | null; start_date: string | null
    expiry: string | null; open_interest: number | null; underlying: string | null
    employees: number | null; website: string | null; investor_website: string | null; phone: string | null
    address: CompanyAddress; exchange: string | null; currency: string | null
    market_cap: number | null; quote_type: string | null
  } | null
  officers: { name: string; title: string | null; age: number | null; year_born: number | null; total_pay: number | null }[]
  /** The latest ANNUAL report: a 10-K, or a foreign private issuer's 20-F,
   * whose business and property sections carry other item numbers. */
  tenk: {
    accession: string; filing_date: string; url: string
    form?: string
    business_item?: string; properties_item?: string
    business: string | null; business_truncated: boolean
    properties: string | null; properties_truncated: boolean
    /** Set when the ticker moved to a successor registrant that has filed
     * no annual report yet: the report is the predecessor's. */
    predecessor?: { cik: string; name: string } | null
  } | null
  /** Where to read further, for every profile: filings index, official
   * site, investor page, coin trackers, a neutral reference. */
  sources: { label: string; url: string }[]
  /** An authored note for an index, contract or pair no feed describes. */
  reference: { name: string; what: string; publisher: string; url: string; sources: { label: string; url: string }[] } | null
  /** FETCHED outside sources: the SEC's structured facts (registrants),
   * CoinGecko's record (coins). */
  financials: {
    as_of: string | null
    items: Record<string, { val: number; end: string; fy: number | null; accn: string | null; unit: string; concept: string }>
    shares_outstanding: { val: number; end: string; accn: string | null } | null
    source_url: string
    /** The predecessor registrant's facts, for a successor with none yet. */
    predecessor?: { cik: string; name: string } | null
  } | null
  coin: {
    id: string; name: string | null; symbol: string; description: string; categories: string[]
    homepage: string | null; whitepaper: string | null; explorers: string[]
    genesis_date: string | null; hashing_algorithm: string | null; market_cap_rank: number | null
    circulating_supply: number | null; total_supply: number | null; max_supply: number | null
    url: string; attribution: string
  } | null
}

export interface IntervalSpec {
  id: string
  label: string
  unit: "Sec" | "Min" | "Hour" | "Day" | "Week" | "Month"
  n: number
  max_days: number | null
}
export interface ChartCapabilities { provider: string; intervals: IntervalSpec[]; refused: string[] }

export interface ChartSeries {
  symbol: string
  /** The bar interval actually served — may be coarser than the one asked
   * for, when the range outruns it. See ingest/prices.resolve_interval. */
  interval?: string
  interval_label?: string
  interval_requested?: string | null
  /** Which intervals this RANGE may offer. Decided by the server, which owns
   * the range/interval mapping, so the toolbar can render it without keeping a
   * second copy of the policy that could drift. */
  intervals?: string[]
  range?: string | null
  /** Which tape served the bars: the consolidated tape or IEX. Part of the
   * series identity on the client, so a switch is a new series rather than
   * a silent rescale, and sent back on page requests. */
  source?: "tape" | "iex" | null
  /** On a history page: the server cut this page at its source's floor;
   * there is nothing before it. */
  history_end?: boolean
  /** With `history_end`: why — the feed's reach at this interval. */
  history_note?: string
  /** Set when the reader's plan refused the bar asked for and a coarser
   * one was served instead — the sentence to show them. */
  plan_note?: string | null
  /** False when the bars stop short of now: a free Alpaca key's consolidated
   * bars end `delay_minutes` ago. */
  realtime?: boolean
  delay_minutes?: number
  /** While delayed: one exchange's closes after the last bar — a dashed
   * provisional line, never bars. See lib/provisional. */
  provisional?: { t: string; c: number }[]
  bars: ChartBar[]
  rsi_9: (number | null)[]
  macd: (number | null)[]
  macd_signal: (number | null)[]
  macd_hist: (number | null)[]
  thresholds: { rsi_oversold: number; rsi_overbought: number }
  bar_count: number
  sessions: number
  coverage: number
  median_gap_min: number | null
  indicators_reliable: boolean
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    noteUnauthorized(path, r.status)
    const detail = await r.json().catch(() => null)
    throw new Error(detail?.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json() as Promise<T>
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    noteUnauthorized(path, r.status)
    const detail = await r.json().catch(() => null)
    throw new Error(detail?.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json() as Promise<T>
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: "DELETE" })
  if (!r.ok) {
    noteUnauthorized(path, r.status)
    const detail = await r.json().catch(() => null)
    throw new Error(detail?.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json() as Promise<T>
}

/** One numbered item the answer cited, resolved server-side back to the
 * stored record — an article or a calendar row, never a URL the model made
 * up. `url` is empty for earnings citations (they came from our own
 * calendar, not a link). */
export interface ScreenerCitation {
  kind: "article" | "earnings"
  symbol: string
  claim: string
  title: string
  url: string
  source: string
}

export interface ScreenerHeadline {
  title: string
  url: string
  source: string
  published_at: string | null
}

/** One row of the window inventory. Deliberately carries NO score and NO
 * digest: the list is unranked and un-narrated — nothing here writes about
 * it (2026-09-17: no model runs in AlphaDesk at all). */
/** One story from the window's reading list — deduped server-side, with the
 * article's FULL ticker list and the provider's summary text. Sentiment and
 * category come from the enrichment pipeline and are absent until it has
 * processed the article. */
export interface NewsArticle {
  article_id: string
  /** Why the story is listed: on a coin's panel "coin", "crypto stock",
   * "crypto" or "rates" (alphadesk/cryptonews.py); in a search "related" —
   * found by meaning, not by its words (alphadesk/semantic.py). */
  why?: string
  title: string
  summary: string | null
  source: string | null
  url: string
  published_at: string | null
  tickers: string[]
  /** The feed's article image and byline — null on articles stored before
   * the pipeline carried them, and on feeds that don't. */
  image_url?: string | null
  author?: string | null
  /** Full article text, plain (sanitized at ingest) — only from feeds
   * licensed to deliver it. The reader renders it when present and falls
   * back to the summary plus a link out when not. */
  body?: string | null
  /** The list carries no text: whether the story has it, fetched on open. */
  has_body?: boolean
  /** Which of the reader's feeds delivered it ("alpaca", "polygon") — empty
   * on articles stored before 2026-09-14. */
  feeds?: string[]
}

export interface ScreenerRow {
  symbol: string
  report_date: string | null
  session: string | null
  article_count: number
  headlines: ScreenerHeadline[]
}


export interface FilingRow {
  accession: string
  symbol: string
  cik: string
  form: string
  filing_date: string
  report_date: string | null
  primary_doc: string
  url: string
  /** Whether it is a document with text to quote: a narrative form (10-K, 10-Q,
   * 8-K, amendments, 20-F, 6-K, proxy) is readable; an ownership form
   * (3, 4, 5, 144, 13D/13G) is an XML table and only opens on EDGAR. */
  readable: boolean
}

/** A cash dividend on record. Only the ex-date and amount are guaranteed;
 * the other dates are present when a source that carries them contributed
 * (see `CorporateActions.sources`) and null otherwise — never estimated. */
export interface DividendRow {
  ex_date: string
  /** As declared: what a holder was paid per share that day. */
  amount: number | null
  /** Per today's share, restated through every later split. */
  adjusted_amount: number | null
  currency: string | null
  declaration_date: string | null
  record_date: string | null
  payment_date: string | null
}

export interface SplitRow {
  date: string
  /** Shares before and after: 1 → 4 for a four-for-one, 10 → 1 for a reverse. */
  from: number | null
  to: number | null
}

export interface CorporateActions {
  symbol: string
  dividends: DividendRow[]
  splits: SplitRow[]
  /** Every source that contributed, primary first. */
  sources: string[]
}

/** The 13F picture for one symbol, summed across every filer. Position
 * counts come only from the summed source; with the top-ten fallback they
 * are absent, never estimated. */
export interface InstitutionalPositions {
  increased?: { holders: number | null; shares: number | null }
  decreased?: { holders: number | null; shares: number | null }
  held?: { holders: number | null; shares: number | null }
  new?: { holders: number | null; shares: number | null }
  sold_out?: { holders: number | null; shares: number | null }
}
export interface InstitutionalHolder {
  name: string
  date: string | null
  shares: number | null
  change: number | null
  change_pct: number | null
  value: number | null
}
export interface InstitutionalHoldings {
  symbol: string
  source: string | null
  as_of: string | null
  summary: {
    institutional_pct?: number | null
    shares_outstanding?: number | null
    total_value?: number | null
    holders?: number | null
    shares?: number | null
    positions?: InstitutionalPositions
  }
  holders: InstitutionalHolder[]
  total_holders: number | null
}

/** One company's comparison record — ingest/compare. Ratios the vendor states
 * as fractions (a 17.44% margin is 0.1744) arrive as fractions. */
export interface CompareRow {
  symbol: string
  name: string | null
  sector: string | null
  industry: string | null
  market_cap: number | null
  enterprise_value: number | null
  pe: number | null; forward_pe: number | null; peg: number | null
  ps: number | null; pb: number | null; ev_sales: number | null; ev_ebitda: number | null
  dividend_yield: number | null; payout_ratio: number | null
  gross_margin: number | null; operating_margin: number | null; ebitda_margin: number | null; net_margin: number | null
  roe: number | null; roa: number | null
  revenue_growth: number | null; earnings_growth: number | null; earnings_q_growth: number | null
  revenue: number | null; ebitda: number | null; eps: number | null; forward_eps: number | null
  current_ratio: number | null; quick_ratio: number | null; debt_to_equity: number | null
  total_cash: number | null; total_debt: number | null; free_cash_flow: number | null; operating_cash_flow: number | null
  beta: number | null; short_pct_float: number | null; short_ratio: number | null
  avg_volume: number | null; employees: number | null
}
export interface CompareMetrics { rows: CompareRow[]; missing: string[] }
export interface Peers { symbol: string; peers: string[]; source: string | null }

/** Movers by category — ingest/movers. One shape for nine categories. */
export type MoverCategory = "stocks" | "crypto" | "etfs" | "options" | "indices" | "bonds" | "currencies"
export interface CategoryMoverRow {
  symbol: string
  /** Option contracts only: where a click opens the chain. */
  underlying?: string | null
  expiry?: string | null
  /** What the row shows: the plain coin ticker, a contract in words, the symbol otherwise. */
  display: string
  name: string | null
  price: number | null
  change_pct: number | null
  volume: number
  /** Annualised realised volatility over the last twenty sessions, percent. */
  volatility: number | null
  /** Average dollar volume a day over the last twenty sessions (a coin's 24h dollar volume). */
  liquidity: number | null
  /** Dollars traded today: price × volume, or the vendor's own figure (an
   * option's premium; the dollar-volume tab's volume × volume-weighted price). */
  turnover?: number | null
  /** The price was struck outside the regular session; the change is measured
   * from the last close and the volume beside it is that closed session's. */
  extended?: boolean
  /** The closed session's own move, percent — what the row showed before the
   * bell, kept beside the extended-hours figure. */
  regular_pct?: number | null
  /** When the extended-hours price was struck, New York time. */
  extended_at?: string | null
  spark: number[]
}
/** One fund on the Sectors page (/api/sectors). Returns are percent. */
export interface SectorRow {
  symbol: string
  label: string
  name: string | null
  price: number | null
  change_pct: number | null
  w1: number | null; m1: number | null; m3: number | null; ytd: number | null; y1: number | null
  high_52w: number | null
  low_52w: number | null
  /** Dollars traded today: price × volume. */
  turnover: number | null
  /** Return minus SPY's over the same month / three months, in points. */
  rel_m1?: number | null
  rel_m3?: number | null
  rotation?: "leading" | "weakening" | "lagging" | "improving" | null
  /** The closes the returns run from (d1 is the previous close), so live
   * prices can move every return. */
  bases?: { d1?: number | null; w1?: number | null; m1?: number | null; m3?: number | null; ytd?: number | null; y1?: number | null }
}
export interface Sectors {
  benchmark: SectorRow
  sectors: SectorRow[]
  industries: SectorRow[]
  /** Each sector fund's share of the S&P 500, percent; null without a vendor that carries it. */
  weights: Record<string, number> | null
  as_of: string
  source: string | null
}
export interface SectorLeader {
  symbol: string; name: string | null; industry: string | null
  market_cap: number | null; price: number | null; change_pct: number | null
  /** Market value added (negative: lost) today, dollars. */
  value_change: number | null
}
/** /api/sectors/breadth: per sector fund. */
export interface SectorBreadth {
  groups: Record<string, { up: number; down: number; flat: number; companies: number; leaders: SectorLeader[]; drivers: SectorLeader[] }>
  min_market_cap: number
  /** Which companies are counted, in words: "S&P 500 companies", or "US companies over $2B". */
  universe: string
  /** The trading day the changes come from, and whether it is today. */
  session: string | null
  session_is_today: boolean
  as_of: string
}
export interface CategoryMovers {
  category: MoverCategory
  label: string
  change_label: string
  source: string | null
  /** The floors in words, when any apply ("≥ $5 · ≥ $1M turnover"). */
  note: string | null
  /** The floors in force and the category's defaults, so the tile can offer a reset. */
  floors: { min_price: number; min_turnover: number; min_liquidity: number; min_volatility: number; default_min_price: number; default_min_turnover: number }
  as_of: string
  /** The lists are still filling in (the market-wide liquid set is being
   * built for the first time); ask again in a few seconds. */
  filling?: boolean
  /** "venue": liquidity counts only the vendor's own exchange (Alpaca's
   * crypto), not the whole market. */
  liquidity_scope?: "venue"
  /** False when the vendor that answered is a SCRAPED source — read off a
   * public page rather than delivered under a key. The tile says so. */
  official?: boolean
  /** The prices were struck outside the regular session, so the change is
   * measured from the last close while the volume beside it is that closed
   * session's. */
  extended?: boolean
  /** Which session those prices belong to: "Pre-market", "After hours",
   * "Overnight" or "Weekend"; null inside the regular session. */
  session_label?: string | null
  tabs: { id: string; label: string; rows: CategoryMoverRow[] }[]
}

export interface FilingCitation {
  quote: string
}


/** One pre-fetched data section — the ground truth a citation resolves
 * against, not the model's own claim about what it read. */
export interface ResearchSection {
  title: string
  data: unknown
}

export interface ResearchCitation {
  section: number
  title: string
  claim: string
}


/** A declarative external tile — descriptor served by a configured widget
 * backend, validated and cleaned server-side (alphadesk/extwidgets.py). The
 * frontend renders exactly these fields with the house primitives; there is
 * no remote markup or code anywhere in this path. */
export interface ExternalWidgetDef {
  uid: string
  type: "table" | "metrics"
  title: string
  subtitle: string
  params: string[]
  refresh_s: number
  span: number
  columns: { key: string; label: string; align: "left" | "right" }[]
}

export interface ExternalWidgetData {
  uid: string
  type: "table" | "metrics"
  rows?: Record<string, string | number | null>[]
  metrics?: { label: string; value: string | number | null }[]
}

/** Who may use the terminal (alphadesk/billing.py). `expired` only stops
 * the reader when `enforced` is on. */
export interface Access {
  state: "owner" | "subscribed" | "trialing" | "expired"
  trial_ends_at: string | null
  days_left: number | null
  plan_status: string | null
  plan_period_end: string | null
  enforced: boolean
  /** A payment processor is configured. */
  can_subscribe: boolean
}

export interface AdminUser {
  user_id: string
  email: string
  disabled: boolean
  created_at: string | null
  last_seen_at: string | null
  sign_ins: string[]
  access: Access
  /** What the account holds, for the admin page's detail. */
  counts?: { keys: number; views: number; baskets: number; agent_tokens: number; agent_apps: number }
}

export interface AdminUsers {
  users: AdminUser[]
  totals: Record<"accounts" | "disabled" | "owner" | "subscribed" | "trialing" | "expired", number>
  enforced: boolean
  trial_days: number
  payments: boolean
}

export interface AuthMe {
  auth_required: boolean
  /** The configured identity providers, in the order the login screen
   * should offer them. Empty means the password gate (self-host, dev). */
  providers: { id: string; label: string }[]
  /** Legacy flag, kept while cached bundles exist. */
  google: boolean
  /** `sign_ins`: the methods this account has signed in with, latest
   * first — recorded from 2026-09-18 (2026-09-18). */
  user: {
    email: string
    sign_ins?: { method: string; first_at: string | null; last_at: string | null }[]
    /** Trial or subscription (alphadesk/billing.py), 2026-09-18. */
    access?: Access | null
    /** Owners open the admin page. */
    owner?: boolean
  } | null
  /** Where a signed-in reader must go first: the agent-app consent page they
   * left to sign in. Given once. */
  next?: string | null
}

export interface ServerView {
  view_id: string
  name: string
  layout: string
  position: number
}

export interface InsiderTrade {
  transaction_date: string
  filing_date: string
  owner_name: string
  owner_title: string | null
  officer: boolean
  director: boolean
  transaction_type: string
  acquisition_or_disposition: string
  securities_transacted: number | null
  transaction_price: number | null
  transaction_value: number | null
  filing_url: string
}

export interface OwnershipInfo {
  symbol: string
  breakdown?: Record<string, unknown>
  top_holders?: { holder: string | null; shares: number | null; value: number | null;
                  pct_change: number | null; date_reported: string | null }[]
}

export type KeySeam = "news" | "prices" | "transcripts"

export interface UserKeyRow {
  seam: KeySeam
  provider: string
  key_hint: string
  created_at: string
  last_used_at: string | null
  /** News feeds only: stories this feed delivered into the window in the
   * last 24 hours (a story two feeds delivered counts for both). */
  stories_24h?: number
  /** News feeds only: over a held real-time socket, or on the poll. */
  delivery?: "stream" | "poll"
}

/** A token a reader issued so their own agent can call AlphaDesk's tools. */
export interface AgentAccessToken {
  token_id: string
  name: string
  hint: string
  created_at: string
  last_used_at: string | null
}

export const api = {
  authMe: () => get<AuthMe>("/api/auth/me"),
  billing: () => get<Access>("/api/billing"),
  billingCheckout: (plan: "monthly" | "yearly" = "monthly") => post<{ url: string }>("/api/billing/checkout", { plan }),
  billingPortal: () => post<{ url: string }>("/api/billing/portal", {}),
  adminUsers: () => get<AdminUsers>("/api/admin/users"),
  adminSetDisabled: (userId: string, disabled: boolean) =>
    post<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(userId)}/disabled`, { disabled }),
  adminSignOut: (userId: string) =>
    post<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(userId)}/sign-out`, {}),
  deleteMyAccount: (confirm: string) => post<{ ok: boolean }>("/api/account/delete", { confirm }),
  adminDeleteUser: (userId: string, confirm: string) =>
    post<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(userId)}/delete`, { confirm }),
  adminExtendTrial: (userId: string, days: number) =>
    post<{ ok: boolean; trial_ends_at: string }>(`/api/admin/users/${encodeURIComponent(userId)}/trial`, { days }),
  saveBoard: (symbols: string[], active: string) => put<{ ok: boolean }>("/api/board", { symbols, active }),
  /** The strip this account last had, from whichever browser arranged it. */
  getBoard: () => get<{ symbols: string[]; active: string; updated_at: string | null }>("/api/board"),
  /** Every board this account has arranged, as {page key: tiles}. */
  getLayouts: () =>
    get<{ layouts: Record<string, { tiles: string; updated_at: string | null }> }>("/api/layouts"),
  /** Keep one page's layout; an empty string forgets it. */
  saveLayout: (page: string, tiles: string) =>
    put<{ ok: boolean }>(`/api/layouts/${encodeURIComponent(page)}`, { tiles }),
  agentAccessTokens: () => get<{ url: string; tokens: AgentAccessToken[] }>("/api/agent/access-tokens"),
  issueAgentAccessToken: (name: string) =>
    post<AgentAccessToken & { token: string; url: string }>("/api/agent/access-tokens", { name }),
  agentConnections: () =>
    get<{ connections: { grant_id: string; client_name: string; created_at: string; last_used_at: string | null }[] }>(
      "/api/agent/connections"),
  revokeAgentConnection: (id: string) =>
    del<{ ok: boolean }>(`/api/agent/connections/${encodeURIComponent(id)}`),
  revokeAgentAccessToken: (id: string) =>
    del<{ ok: boolean }>(`/api/agent/access-tokens/${encodeURIComponent(id)}`),
  keys: () => get<{
    vault: boolean
    keys: UserKeyRow[]
    /** Feeds with stories still in the store that you no longer have a key
     * for — they age out at `news_keep_days`. Named so a publisher in the
     * news list is never unaccountable. */
    orphan_feeds?: { provider: string; stories: number }[]
    news_keep_days?: number
    news_poll_minutes?: number
  }>("/api/keys"),
  views: () => get<{ views: ServerView[] }>("/api/views"),
  setView: (id: string, body: { name: string; layout: string; position?: number }) =>
    put<{ ok: boolean }>(`/api/views/${id}`, body),
  deleteView: (id: string) => del<{ ok: boolean }>(`/api/views/${id}`),
  saveBasket: (id: string, body: { label: string; why: string; symbols: string }) =>
    put<{ ok: boolean; id: string; symbols: string[] }>(`/api/baskets/${encodeURIComponent(id)}`, body),
  deleteBasket: (id: string) => del<{ ok: boolean }>(`/api/baskets/${encodeURIComponent(id)}`),
  dataVendors: () => get<DataVendors>("/api/data/vendors"),
  catalysts: (limit = 60) => get<CatalystFeed>(`/api/catalysts?limit=${limit}`),
  /** Switch a scraped source on. There is no key, so this is the whole of
   * connecting one; switching off is the ordinary key removal. */
  enableSource: (name: string) =>
    put<{ ok: boolean }>(`/api/sources/${encodeURIComponent(name)}`, {}),
  setKey: (seam: KeySeam, body: { provider: string; api_key: string; api_secret?: string; base_url?: string; model?: string }) =>
    put<{ ok: boolean; key_hint: string }>(`/api/keys/${seam}`, body),
  deleteKey: (seam: KeySeam, provider?: string) =>
    del<{ ok: boolean }>(provider
      ? `/api/keys/${seam}/${encodeURIComponent(provider)}`
      : `/api/keys/${seam}`),
  login: (email: string, password: string) =>
    post<{ user: { email: string } }>("/api/auth/login", { email, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout", {}),
  logoutAll: () => post<{ ok: boolean }>("/api/auth/logout-all", {}),
  externalWidgets: () =>
    get<{ widgets: ExternalWidgetDef[] }>("/api/widgets/external"),
  externalWidgetData: (uid: string, symbol?: string) =>
    get<ExternalWidgetData>(
      `/api/widgets/external/data?uid=${encodeURIComponent(uid)}` +
      (symbol ? `&symbol=${encodeURIComponent(symbol)}` : "")),
  filings: (symbol: string) =>
    get<{ symbol: string; filings: FilingRow[] }>(`/api/filings/${encodeURIComponent(symbol)}`),
  /** The reader opening a calendar row is the ask. */
  chart: (symbol: string, days = 2) =>
    get<ChartSeries>(`/api/chart/${encodeURIComponent(symbol)}?days=${days}`),
  company: (symbol: string) => get<CompanyProfile>(`/api/company/${encodeURIComponent(symbol)}`),
  /** The active price provider's interval catalogue — what the toolbar
   * offers, fine to coarse, with how far back each reaches. */
  chartCapabilities: () => get<ChartCapabilities>("/api/chart/capabilities"),
  chartRange: (symbol: string, range: ChartRange, interval?: string, before?: string, source?: string,
               need?: number) =>
    get<ChartSeries>(
      `/api/chart/${encodeURIComponent(symbol)}?range=${range}` +
      (interval ? `&interval=${interval}` : "") +
      // A HISTORY PAGE: the bars before this instant, one range-span deep,
      // from the SOURCE the first page came from — never the other tape.
      (before ? `&before=${encodeURIComponent(before)}` : "") +
      (source ? `&source=${source}` : "") +
      // How many bars of BLANK the view has to the left of the oldest one.
      // The server reaches further back until one page covers it, so a
      // zoomed-out chart fills in a step rather than creeping.
      (before && need ? `&need=${Math.round(need)}` : "")),
  screener: () => get<{ symbols: ScreenerRow[] }>("/api/screener"),
  rail: (symbols: string[]) =>
    get<Rail>(`/api/rail${symbols.length ? `?symbols=${encodeURIComponent(symbols.join(","))}` : ""}`),
  news: () => get<{ articles: NewsArticle[] }>("/api/news"),
  /** One story with its full text where the reader's feed delivers it. */
  newsStory: (id: string) => get<NewsArticle>(`/api/news/${encodeURIComponent(id)}/story`),
  /** Older stories (published before `before`), or a search of everything
   * stored (`q`). */
  newsTerms: (q: string) =>
    get<{ tickers: string[]; names: string[] }>(`/api/news/terms?q=${encodeURIComponent(q)}`),
  /** Window stories related in MEANING to `q` (the self-hosted embedding
   * model, 2026-09-19); empty until the model is ready. */
  newsRelated: (q: string) =>
    get<{ articles: NewsArticle[]; ready: boolean }>(`/api/news/related?q=${encodeURIComponent(q)}`),
  newsPage: (opts: { before?: string; q?: string; limit?: number; symbol?: string }) => {
    const p = new URLSearchParams()
    if (opts.before) p.set("before", opts.before)
    if (opts.q) p.set("q", opts.q)
    if (opts.symbol) p.set("symbol", opts.symbol)
    p.set("limit", String(opts.limit ?? 100))
    return get<{ articles: NewsArticle[] }>(`/api/news?${p.toString()}`)
  },
  system: () => get<SystemInfo>("/api/system"),
  fundamentals: (symbol: string, period: MetricPeriod) =>
    get<Fundamentals>(`/api/fundamentals/${encodeURIComponent(symbol)}?period=${period}`),
  search: (q: string, limit = 50) =>
    get<{ results: SymbolHit[]; trending: boolean }>(
      `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  earningsFind: (symbol: string) =>
    get<EarningsFind>(`/api/earnings/find?symbol=${encodeURIComponent(symbol)}`),
  earningsWeek: (start?: string) =>
    get<EarningsWeek>(`/api/earnings/week${start ? `?start=${start}` : ""}`),
  earningsContext: (symbol: string) =>
    get<EarningsContext>(`/api/earnings/context/${encodeURIComponent(symbol)}`),
  earningsHistory: (symbol: string) =>
    get<EarningsHistory>(`/api/earnings/history/${encodeURIComponent(symbol)}`),
  transcripts: (symbol: string) =>
    get<TranscriptList>(`/api/transcripts/${encodeURIComponent(symbol)}`),
  transcript: (symbol: string, id: string) =>
    get<TranscriptDoc>(`/api/transcripts/${encodeURIComponent(symbol)}/${encodeURIComponent(id)}`),
  earningsInsights: (symbol: string) =>
    get<EarningsInsights>(`/api/earnings/insights/${encodeURIComponent(symbol)}`),
  tape: () => get<{ tape: TapeEntry[] }>("/api/tape"),
  indices: () => get<{ indices: TapeEntry[] }>("/api/indices"),
  themes: () => get<{ themes: Theme[] }>("/api/themes"),
  optionExpirations: (symbol: string) =>
    get<{ symbol: string; expirations: string[] }>(
      `/api/options/${encodeURIComponent(symbol)}`),
  optionChain: (symbol: string, expiry: string) =>
    get<OptionChain>(
      `/api/options/${encodeURIComponent(symbol)}/chain?expiry=${encodeURIComponent(expiry)}`),
  optionFlow: (symbols: string[], minPremium: number) =>
    get<OptionFlow>(`/api/options-flow?symbols=${encodeURIComponent(symbols.join(","))}&min_premium=${minPremium}`),
  /** `fill` asks the server for fields a quote vendor may not carry —
   * "range" for the 52-week high and low, "cap" for market capitalisation.
   * Each costs one request for the whole basket, so only a page that shows
   * those columns asks. */
  quotes: (symbols: string[], fill?: string) =>
    get<{ quotes: Record<string, Quote | null> }>(
      `/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}${fill ? `&fill=${encodeURIComponent(fill)}` : ""}`),
  crypto: (top = 20) => get<CryptoMovers>(`/api/crypto?top=${top}`),
  quote: (symbol: string) => get<Quote>(`/api/quote/${encodeURIComponent(symbol)}`),
  movers: (top = 20) => get<Movers>(`/api/movers?top=${top}`),
  sectors: () => get<Sectors>("/api/sectors"),
  sectorBreadth: () => get<SectorBreadth>("/api/sectors/breadth"),
  categoryMovers: (category: MoverCategory, top = 20, floors?: { min_price: number; min_turnover: number; min_liquidity: number; min_volatility: number } | null) =>
    get<CategoryMovers>(`/api/movers/${category}?top=${top}${floors
      ? `&min_price=${floors.min_price}&min_turnover=${floors.min_turnover}&min_liquidity=${floors.min_liquidity}&min_volatility=${floors.min_volatility}` : ""}`),
  earnings: () =>
    get<{ upcoming: EarningsRow[]; reported: EarningsRow[] }>("/api/earnings"),
  insider: (symbol: string) =>
    get<{ symbol: string; trades: InsiderTrade[] }>(`/api/insider/${encodeURIComponent(symbol)}`),
  ownership: (symbol: string) =>
    get<OwnershipInfo>(`/api/ownership/${encodeURIComponent(symbol)}`),
  compareMetrics: (symbols: string[]) =>
    get<CompareMetrics>(`/api/compare/metrics?symbols=${encodeURIComponent(symbols.join(","))}`),
  peers: (symbol: string) => get<Peers>(`/api/peers/${encodeURIComponent(symbol)}`),
  institutional: (symbol: string, limit = 25) =>
    get<InstitutionalHoldings>(`/api/institutional/${encodeURIComponent(symbol)}?limit=${limit}`),
  corporateActions: (symbol: string) =>
    get<CorporateActions>(`/api/corporate-actions/${encodeURIComponent(symbol)}`),
  analysts: (symbol: string) => get<AnalystView | null>(`/api/analysts/${encodeURIComponent(symbol)}`),
  fund: (symbol: string) => get<FundProfile | null>(`/api/fund/${encodeURIComponent(symbol)}`),
  relatedFunds: (symbol: string) => get<RelatedFunds>(`/api/funds/related/${encodeURIComponent(symbol)}`),
  keyStats: (symbol: string) => get<KeyStats | null>(`/api/stats/${encodeURIComponent(symbol)}`),
  economic: (start?: string, end?: string) =>
    get<EconomicCalendar>(`/api/economic?start=${start ?? ""}&end=${end ?? ""}`),
  dividendCalendar: (start: string, end: string) =>
    get<CorporateCalendar<DividendEvent>>(`/api/calendars/dividends?start=${start}&end=${end}`),
  splitCalendar: (start: string, end: string) =>
    get<CorporateCalendar<SplitEvent>>(`/api/calendars/splits?start=${start}&end=${end}`),
  ipoCalendar: (start: string, end: string) =>
    get<CorporateCalendar<IpoEvent>>(`/api/calendars/ipos?start=${start}&end=${end}`),
}

/** Market-wide corporate calendars — ingest/corporate_calendars.py. */
export interface CorporateCalendar<T> {
  start: string; end: string; rows: T[]; source: string | null
  /** The vendors that answered, in catalogue order (splits only). */
  vendors?: string[]
  /** Whether a chart vendor was asked if past listings traded (IPOs only). */
  checked?: boolean
}
export interface DividendEvent {
  symbol: string; company_name: string | null
  ex_date: string; record_date: string | null; payment_date: string | null; declaration_date: string | null
  amount: number | null; adjusted_amount: number | null
  /** Already a percent: 0.8 is 0.8%. */
  yield_pct: number | null
  frequency: string | null
  /** Average daily dollar volume over twenty sessions, from the chart vendor. */
  liquidity: number | null; low_liquidity: boolean | null
  /** Market capitalisation today, from the company data vendor. */
  market_cap?: number | null
}
export interface SplitEvent {
  symbol: string; company_name: string | null; date: string
  /** New shares for old: `to` for every `from` (1 for 20 is a reverse split). */
  to: number | null; from: number | null; reverse: boolean; kind: string | null
  /** The vendors listing it. */
  sources?: string[]
  /** True when two vendors list the same ratio, false when only one of the
   * answering vendors does, null when a single vendor answered. */
  corroborated?: boolean | null
  /** Each vendor's date when they listed it days apart. */
  vendor_dates?: Record<string, string>
}
export interface IpoEvent {
  symbol: string | null; date: string; company: string | null; exchange: string | null; status: string | null
  shares: number | null; price_low: number | null; price_high: number | null; market_cap: number | null
  /** Shares times the middle of the price range, when both are known. */
  deal_size: number | null
  /** Read from the name: a company IPO, a blank-check company or its units,
   * rights and warrants, an ETF or fund, or another company's warrants. */
  kind?: "company" | "blank_check" | "fund" | "other_security"
  /** Once the date has passed, from the reader's chart vendor: it traded from
   * `first_trade`, it was already trading (an uplisting or rename), or it has
   * no trades. Null for a date still ahead or when nothing was checked. */
  listing?: "listed" | "already_trading" | "no_trades" | null
  first_trade?: string | null
}

export interface EconomicEvent {
  /** ISO datetime in UTC, or a bare date when the source gives no time. */
  time: string | null
  country: string | null
  event: string
  impact: "low" | "medium" | "high" | null
  actual: number | null; estimate: number | null; previous: number | null
  unit: string | null
  /** The row is on the AGENCY's own release clock, because the vendor's
   * time disagreed with it; `vendor_time` is what the vendor said. */
  time_source?: "agency" | null
  time_agency?: string | null
  vendor_time?: string | null
}
export interface EconomicCalendar {
  start: string; end: string
  rows: EconomicEvent[]
  /** The vendor that answered, or null with `note` naming the key that would. */
  source: string | null
  note: string | null
}

/** The summary block. Fractions stay fractions (profit_margin 0.276) except
 * dividend_yield, which the vendors already state as a percent. */
export interface KeyStats {
  symbol: string; name: string | null; currency: string | null; quote_type: string | null
  vendor?: string | null
  price: number | null; previous_close: number | null; open: number | null; day_low: number | null; day_high: number | null
  volume: number | null; avg_volume: number | null; avg_volume_10d: number | null
  week52_low: number | null; week52_high: number | null; week52_position: number | null
  avg_50d: number | null; avg_200d: number | null
  market_cap: number | null; enterprise_value: number | null; shares_outstanding: number | null; float_shares: number | null
  beta: number | null; trailing_pe: number | null; forward_pe: number | null; peg: number | null
  price_to_book: number | null; price_to_sales: number | null; ev_to_ebitda: number | null
  trailing_eps: number | null; forward_eps: number | null; book_value: number | null
  dividend_rate: number | null; dividend_yield: number | null; payout_ratio: number | null
  held_insiders: number | null; held_institutions: number | null
  revenue: number | null; profit_margin: number | null; return_on_equity: number | null
  total_cash: number | null; total_debt: number | null; free_cash_flow: number | null
  ex_dividend_date: string | null; earnings_date: string | null; fiscal_year_end: string | null
}

/** The sell side on one symbol: the target range, the rating distribution by
 * month (periods: "0m" this month, "-1m" the last…), the recent
 * rating changes, and the twice-monthly short-interest report. */
/** A fund built ON a company: a leveraged or inverse single-stock product,
 * an option-income fund, a buffered one. `kind` and `leverage` are read
 * from the fund's own name, which is all the listing carries. */
export interface RelatedFund {
  symbol: string
  name: string
  kind: "leveraged" | "inverse" | "income" | "buffered" | "paired" | "other"
  leverage: number | null
  matched: "ticker" | "name"
  price: number | null
  change_pct: number | null
  /** Shares traded this session, from the same quote as the price. The
   * panel shows it in dollars, which is what compares across funds. */
  volume: number | null
}

export interface RelatedFunds {
  symbol: string
  company: string | null
  funds: RelatedFund[]
  /** The symbol is itself a fund: nothing is built on it. */
  is_fund: boolean
  source: string | null
}

export interface AnalystView {
  symbol: string
  targets: { current: number | null; low: number | null; mean: number | null; median: number | null; high: number | null; analysts?: number | null
    /** FMP: how many targets were set in the last month and three months. */
    published_month?: number | null; published_quarter?: number | null
    /** FMP: the average of those recent targets, and which window it counts. */
    recent_mean?: number | null; recent_window?: "month" | "quarter" | null }
  /** mean: 1 strong buy … 5 strong sell. */
  recommendation: { mean: number | null; key: string | null; analysts: number | null }
  distribution: { period: string; strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number
    /** The day the vendor recorded that month's count, where it says. */
    as_of?: string | null }[]
  changes: {
    date: string | null; firm: string | null; to_grade: string | null; from_grade: string | null
    action: string | null; target_action: string | null; target: number | null; prior_target: number | null
    /** The day the prior target was set — it can be months before the change. */
    prior_target_date?: string | null
  }[]
  short_interest: {
    shares_short: number | null; prior_month: number | null; days_to_cover: number | null
    pct_float: number | null; float_shares: number | null; as_of: string | null
  }
  /** Which of the user's vendors served each section. */
  sources?: Record<string, string>
  /** The key prompt for each section no connected vendor serves. */
  needs?: Partial<Record<"analyst_ratings" | "price_targets" | "rating_changes" | "short_interest", KeyPromptBody>>
}

/** What an ETF or mutual fund holds. Percentages are percents (8.08, not 0.0808). */
export interface FundProfile {
  symbol: string
  vendor?: string | null
  quote_type: string | null
  category: string | null; family: string | null; legal_type: string | null; description: string | null
  expense_ratio: number | null; turnover: number | null; net_assets: number | null
  holdings: { symbol: string | null; name: string | null; weight: number | null }[]
  top_weight: number | null
  sectors: { key: string; label: string; weight: number | null }[]
  assets: { key: string; label: string; weight: number | null }[]
  /** The vendor answered the profile but its plan refuses the holdings list. */
  holdings_needs_key?: KeyPromptBody | null
  /** The vendor the holdings LIST came from, when it is not the one that
   * answered the rest of the fund record (2026-09-18). */
  holdings_vendor?: string | null
  /** When the holdings source last refreshed them, as it states it. */
  as_of?: string | null
}

// The market runs on US Eastern; show all decision timestamps there.
const ET = "America/New_York"

// "YYYY-MM-DD" in ET — used as a stable grouping key.
export function etDateKey(ts: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: ET,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(ts))
}

// "Tue 07-21" in ET — a compact day-group header.
export function etDayLabel(ts: string): string {
  const wd = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "short" }).format(
    new Date(ts),
  )
  return `${wd} ${etDateKey(ts).slice(5)}`
}

// Group items by their ET day (newest day first), preserving each item's incoming
// order within a day. `ts` picks the timestamp to group on.
export function groupByDayKey<T>(
  items: T[],
  ts: (x: T) => string,
): { key: string; label: string; items: T[] }[] {
  const map = new Map<string, T[]>()
  for (const it of items) {
    const k = etDateKey(ts(it))
    ;(map.get(k) ?? map.set(k, []).get(k)!).push(it)
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([key, group]) => ({ key, label: etDayLabel(ts(group[0])), items: group }))
}

// "Jul 18, 14:23" in ET.
export function etDateTime(ts: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: ET,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(ts))
}

