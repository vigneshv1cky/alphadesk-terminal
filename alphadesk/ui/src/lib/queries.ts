import { useCallback, useEffect } from "react"
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, type ChartRange } from "@/lib/api"
import { loadChartPrefs } from "@/lib/chartPrefs"
import { useLiveEnabled } from "@/lib/liveState"
import { watch } from "@/lib/liveStream"

/** One query key per endpoint, defined once.
 *
 * Keying by endpoint means every caller shares one in-flight request and one
 * cache entry, however many widgets ask for it — before this, two components
 * polling the same endpoint each ran their own timer and kept their own copy.
 *
 * Intervals are per-endpoint and match how fast the data actually moves —
 * prices in seconds, the earnings calendar in minutes.
 */
export const keys = {
  earnings: ["earnings"] as const,
  screener: ["screener"] as const,
  rail: (symbols: string[]) => ["rail", symbols.join(",")] as const,
  news: ["news"] as const,
  system: ["system"] as const,
  tape: ["tape"] as const,
  indices: ["indices"] as const,
  themes: ["themes"] as const,
  optionExpirations: (symbol: string) => ["option-expiries", symbol] as const,
  optionChain: (symbol: string, expiry: string) => ["option-chain", symbol, expiry] as const,
  optionFlow: (symbols: string[], minPremium: number) => ["option-flow", symbols.join(","), minPremium] as const,
  quotes: (symbols: string[]) => ["quotes", symbols.join(",")] as const,
  crypto: ["crypto"] as const,
  movers: ["movers"] as const,
  sectors: ["sectors"] as const,
  sectorBreadth: ["sectors", "breadth"] as const,
  quote: (symbol: string) => ["quote", symbol] as const,
  earningsWeek: (start?: string) => ["earnings-week", start ?? "current"] as const,
  earningsFind: (symbol: string) => ["earnings-find", symbol] as const,
  earningsContext: (symbol: string) => ["earnings-context", symbol] as const,
  earningsHistory: (symbol: string) => ["earnings-history", symbol] as const,
  transcripts: (symbol: string) => ["transcripts", symbol] as const,
  transcript: (symbol: string, id: string) => ["transcript", symbol, id] as const,
  earningsInsights: (symbol: string) => ["earnings-insights", symbol] as const,
  fundamentals: (symbol: string, period: string) => ["fundamentals", symbol, period] as const,
  chart: (symbol: string, range: ChartRange, interval: string | null) =>
    ["chart", symbol, range, interval ?? "auto"] as const,
  company: (symbol: string) => ["company", symbol] as const,
  chartCapabilities: ["chart-capabilities"] as const,
  authMe: ["auth-me"] as const,
  userKeys: ["user-keys"] as const,
  externalWidgets: ["external-widgets"] as const,
  externalWidgetData: (uid: string, symbol: string) =>
    ["external-widget", uid, symbol] as const,
}

export const useEarnings = (enabled = true) =>
  useQuery({ queryKey: keys.earnings, queryFn: api.earnings, refetchInterval: 300_000, enabled })

/** One company's report dates — the calendar's symbol filter. Asked only
 * once a symbol is submitted; kept five minutes like the week. */
export const useEarningsFind = (symbol: string | null) =>
  useQuery({
    queryKey: keys.earningsFind(symbol ?? ""),
    queryFn: () => api.earningsFind(symbol!),
    enabled: !!symbol,
    staleTime: 300_000,
  })

export const useEarningsWeek = (start?: string) =>
  useQuery({
    queryKey: keys.earningsWeek(start),
    queryFn: () => api.earningsWeek(start),
    // A busy week comes back before its background lookups finish; it is
    // asked again every few seconds until they are in.
    refetchInterval: q => ((q.state.data?.pending?.timing ?? 0) + (q.state.data?.pending?.announcements ?? 0) > 0 ? 5_000 : 300_000),
    // Stepping a week keeps the one on screen (dimmed) until the next
    // arrives, instead of blanking the calendar and its arrows.
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })

/** Server caches these for an hour; no poll — a reported quarter does not
 * change while you look at it. */
export const useEarningsContext = (symbol: string) =>
  useQuery({
    queryKey: keys.earningsContext(symbol),
    queryFn: () => api.earningsContext(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
  })

export const useTranscripts = (symbol: string) =>
  useQuery({
    queryKey: keys.transcripts(symbol),
    queryFn: () => api.transcripts(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60_000,
    retry: false,
  })

export const useTranscript = (symbol: string, id: string | null) =>
  useQuery({
    queryKey: keys.transcript(symbol, id ?? ""),
    queryFn: () => api.transcript(symbol, id ?? ""),
    enabled: !!symbol && !!id,
    staleTime: Infinity,    // a published document never changes
    retry: false,
  })

export const useEarningsHistory = (symbol: string) =>
  useQuery({
    queryKey: keys.earningsHistory(symbol),
    queryFn: () => api.earningsHistory(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: false,
  })

export const useEarningsInsights = (symbol: string) =>
  useQuery({
    queryKey: keys.earningsInsights(symbol),
    queryFn: () => api.earningsInsights(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
  })

export const useFundamentals = (symbol: string, period: "quarterly" | "annual") =>
  useQuery({
    queryKey: keys.fundamentals(symbol, period),
    queryFn: () => api.fundamentals(symbol, period),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  })

/** The left rail's counts. One small response a minute, in place of the
 * screener window, the earnings week and the news list, which the rail used
 * to pull on every page for three numbers (2026-09-16). */
export const useRail = (symbols: string[]) =>
  useQuery({
    queryKey: keys.rail(symbols),
    queryFn: () => api.rail(symbols),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

export const useScreener = () =>
  useQuery({ queryKey: keys.screener, queryFn: api.screener, refetchInterval: 60_000 })

/** The reader's news window. Reread when their real-time feed stores a
 * story (the tab's live connection says so, 2026-09-15), and every minute as
 * the backstop for feeds without a stream. */
export const useNews = () => {
  const qc = useQueryClient()
  const live = useLiveEnabled()
  useEffect(() => {
    if (!live) return
    return watch({ news: true, onNews: () => { void qc.invalidateQueries({ queryKey: keys.news }) } })
  }, [live, qc])
  return useQuery({ queryKey: keys.news, queryFn: api.news, refetchInterval: 60_000 })
}

/** One symbol's stories over the whole news window, from the server
 * (2026-09-18): filtering the shared list reached back only as far as its
 * newest 500 stories. Refreshed with the shared list, so a streamed story
 * arrives here on the same beat. */
export const useSymbolNews = (symbol: string) => {
  const { dataUpdatedAt } = useNews()
  return useQuery({
    queryKey: [...keys.news, "symbol", symbol, dataUpdatedAt],
    queryFn: () => api.newsPage({ symbol, limit: 300 }),
    placeholderData: keepPreviousData,
    enabled: !!symbol,
  })
}

export const useTape = () =>
  useQuery({ queryKey: keys.tape, queryFn: api.tape, refetchInterval: 60_000 })

/** The Sectors page's funds. The server keeps them a minute. */
export const useSectors = () =>
  useQuery({ queryKey: keys.sectors, queryFn: api.sectors, refetchInterval: 60_000 })

/** Breadth and each sector's largest companies. The server keeps them a minute. */
export const useSectorBreadth = () =>
  useQuery({ queryKey: keys.sectorBreadth, queryFn: api.sectorBreadth, refetchInterval: 60_000 })

export const useMovers = () =>
  useQuery({ queryKey: keys.movers, queryFn: () => api.movers(20), refetchInterval: 120_000 })

/** Quotes for a whole basket in ONE request.
 *
 * Nine per-symbol requests fired at once made the upstream throttle and hand
 * back 404s for two or three of them at random, so rows rendered as dashes.
 * The server walks the list instead. */
export const useQuotes = (symbols: string[], fill?: string) => {
  // The basket is a map by symbol, so its order means nothing — but the key
  // was built from it, and the Portfolio table (board order) and the returns
  // panel under it (active chip first) asked for the same four stocks as two
  // different requests (2026-09-16). Sorted, one basket is one request.
  const basket = [...new Set(symbols.map(s => s.toUpperCase()))].sort()
  return useQuery({
    queryKey: [...keys.quotes(basket), fill ?? ""],
    queryFn: () => api.quotes(basket, fill),
    enabled: basket.length > 0,
    refetchInterval: 60_000,
  })
}

/** Expiries move once a day at most, so this does not poll. */
export const useOptionExpirations = (symbol: string) =>
  useQuery({
    queryKey: keys.optionExpirations(symbol),
    queryFn: () => api.optionExpirations(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000,
  })

/** The quotes inside a chain do move, so this does. */
export const useOptionChain = (symbol: string, expiry: string) =>
  useQuery({
    queryKey: keys.optionChain(symbol, expiry),
    queryFn: () => api.optionChain(symbol, expiry),
    enabled: !!symbol && !!expiry,
    refetchInterval: 30_000,
    // Flipping expiries keeps the last chain on screen until the next arrives.
    placeholderData: keepPreviousData,
  })

/** Polled every ten seconds while not paused: each poll is what lets the
 * server see new trades close enough to their quotes to know their side. */
export const useOptionFlow = (symbols: string[], minPremium: number, paused: boolean) =>
  useQuery({
    queryKey: keys.optionFlow(symbols, minPremium),
    queryFn: () => api.optionFlow(symbols, minPremium),
    enabled: symbols.length > 0,
    refetchInterval: paused ? false : 10_000,
    placeholderData: keepPreviousData,
  })

/** The external-tile descriptors. Config-like: the server caches them for
 * five minutes, so a slow poll keeps a redeployed backend's new tiles
 * arriving without a page reload. */
export const useExternalWidgets = () =>
  useQuery({
    queryKey: keys.externalWidgets,
    queryFn: api.externalWidgets,
    refetchInterval: 300_000,
    staleTime: 300_000,
  })

/** One external tile's data, polled at the cadence its DESCRIPTOR declares —
 * the backend author knows how fast their data moves; the terminal already
 * clamped the claim to [15s, 1h]. */
export const useExternalWidgetData = (uid: string, symbol: string, refreshS: number) =>
  useQuery({
    queryKey: keys.externalWidgetData(uid, symbol),
    queryFn: () => api.externalWidgetData(uid, symbol || undefined),
    refetchInterval: refreshS * 1000,
  })

/** Who is signed in, and whether this instance asks. Shared by the header
 * chip, the rail and the Account page — one request, one answer. */
export const useAuthMe = () =>
  useQuery({ queryKey: keys.authMe, queryFn: api.authMe, staleTime: 60_000 })
/** The reader's stored keys — hints only; the server never returns a key. */
export const useUserKeys = () =>
  useQuery({ queryKey: keys.userKeys, queryFn: api.keys, staleTime: 30_000 })

/** Server config, so it changes only on redeploy — no refetch interval. */
export const useThemes = () =>
  useQuery({ queryKey: keys.themes, queryFn: api.themes, staleTime: Infinity })

export const useIndices = () =>
  useQuery({ queryKey: keys.indices, queryFn: api.indices, refetchInterval: 60_000 })

export const useCrypto = () =>
  useQuery({ queryKey: keys.crypto, queryFn: () => api.crypto(20), refetchInterval: 120_000 })

/** Quote for one symbol. Disabled when there is no symbol, so a widget can
 * mount before the board has been scoped without firing a bad request. */
export const useQuote = (symbol: string) =>
  useQuery({
    queryKey: keys.quote(symbol),
    queryFn: () => api.quote(symbol),
    enabled: !!symbol,
    refetchInterval: 60_000,
  })

export const useSystem = () =>
  useQuery({ queryKey: keys.system, queryFn: api.system, refetchInterval: 30_000 })

/** The price series, polled like everything else on the board.
 *
 * This was the one panel that fetched once and then sat there: a terminal on a
 * second monitor showing a chart frozen at the moment it was opened. Every
 * other endpoint here already refreshes on the cadence its server cache
 * refreshes at, and this now does too.
 *
 * 30s for the intraday ranges, matching _CHART_TTL_S — asking faster returns
 * the same cached bytes. Daily ranges still move (today's bar is live) but not
 * on that timescale, so they poll at five minutes rather than spending a
 * request a minute to redraw an identical year.
 *
 * The previous series is kept across a range or interval change so the canvas
 * is never torn down mid-swap — but NOT across a symbol change, where holding
 * one company's bars under another company's name is the one version of that
 * which actually misleads.
 */
export const useChartSeries = (symbol: string, range: ChartRange, interval: string | null) =>
  useQuery({
    queryKey: keys.chart(symbol, range, interval),
    queryFn: () => api.chartRange(symbol, range, interval ?? undefined),
    enabled: !!symbol,
    refetchInterval: range === "1D" || range === "5D" ? 30_000 : 300_000,
    placeholderData: (prev, prevQuery) =>
      prevQuery && prevQuery.queryKey[1] === symbol ? prev : undefined,
  })

/** Start fetching a stock's chart before it is opened (2026-09-15): the
 * series the board's chart will ask for — the range and interval the
 * reader last left it on — so the click lands on bars already in hand
 * instead of a blank "loading…". A series fetched in the last 30 seconds
 * is not asked again, the same freshness the chart's own poll keeps. */
export function usePrefetchChart() {
  const qc = useQueryClient()
  return useCallback((symbol: string) => {
    const sym = symbol.toUpperCase()
    if (!sym) return
    const prefs = loadChartPrefs(0)
    const interval = prefs.intervalByRange[prefs.range] ?? null
    void qc.prefetchQuery({
      queryKey: keys.chart(sym, prefs.range, interval),
      queryFn: () => api.chartRange(sym, prefs.range, interval ?? undefined),
      staleTime: 30_000,
    })
  }, [qc])
}

/** The company profile. A day: the server caches it that long, and a
 * registrant record does not move. */
export const useCompany = (symbol: string) =>
  useQuery({
    queryKey: keys.company(symbol),
    queryFn: () => api.company(symbol),
    enabled: !!symbol,
    staleTime: 3_600_000,
    retry: false,
  })

/** The active provider's interval catalogue. Changes only when the reader
 * changes their prices key, which invalidates it explicitly. */
export const useChartCapabilities = () =>
  useQuery({ queryKey: keys.chartCapabilities, queryFn: api.chartCapabilities, staleTime: 3_600_000 })
