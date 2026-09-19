import { useSearchParams } from "react-router-dom"
import { ComposedBoard } from "@/components/ComposedBoard"
import { MarketChart } from "@/widgets/chart"
import { SymbolFilings } from "@/components/SymbolFilings"
import { RelatedFundsPanel } from "@/components/RelatedFunds"
import { SymbolNews } from "@/components/SymbolNews"
import { CoinRecordPanel, FinancialsPanel } from "@/pages/CompanyPage"
import { EarningsHistoryPanel, EarningsInsightsPanel } from "@/components/EarningsPanels"
import { DividendsPanel, SplitsPanel } from "@/components/CorporateActions"
import { InsiderTradesPanel, InstitutionalOwnershipPanel, StockOwnershipPanel } from "@/components/Ownership"
import { AnalystPanel, RatingChangesPanel } from "@/components/Analysts"
import { FundBreakdownPanel, FundHoldingsPanel, useFund } from "@/components/FundPanels"
import { KeyStatisticsPanel } from "@/components/KeyStatistics"
import { PricePerformancePanel } from "@/components/Compare"
import { DEFAULT_SYMBOL } from "@/lib/boardSymbols"
import { normalize } from "@/lib/symbols"

/** Everything about ONE company: chart, filings, a side-by-side against the
 * rest of the strip, and headlines.
 *
 * No symbol input on the page — the symbol strip is the input, on every
 * screen: the marked chip scopes this page the same way it scopes the Markets
 * board and the agent panel. The page reads ?symbol= (which the strip
 * writes), so every old link still lands correctly.
 */
export default function AnalysisPage() {
  const [params] = useSearchParams()
  // The seed effect fills ?symbol= almost immediately; this fallback covers
  // only the first render frame, and it matches the board's default so the
  // page never flashes a different company than the strip is about to show.
  const symbol = normalize(params.get("symbol") || "") || DEFAULT_SYMBOL
  // A fund gets its holdings and breakdown on this page too; the record
  // answers null for a company, and the panels stay out.
  const fund = useFund(symbol)
  const isFund = !!fund.data
  // A COIN has no filings, earnings, analysts, splits, dividends, holders or
  // insiders: no key fills those, and each asked for one (2026-09-19, the
  // owner: "analysis page also has this issue"). A coin gets the chart, its
  // performance, its CoinGecko record and its news.
  const isCoin = /-(USD|USDT|USDC|BTC)$/.test(symbol)
  const STOCK_ONLY = new Set(["filings", "stats", "history", "consensus", "related-funds", "analysts", "ratings",
    "financials", "splits", "dividends", "institutional", "holders", "insiders"])

  const panels = [
        // The full chart — the same component the Markets board registers,
        // so intervals, indicators, drawings and the live edge all work here
        // and every fix lands once.
        { id: "chart", label: "Chart", node: <MarketChart symbol={symbol} span={8} /> },
        { id: "filings", label: "Filings", node: <SymbolFilings symbol={symbol} /> },
        // The same returns table the Compare page draws, for this one stock
        // (2026-09-14, the owner's call).
        { id: "performance", label: "Price performance", node: <PricePerformancePanel symbols={[symbol]} minSymbols={1} span={12} /> },
        { id: "stats", label: "Key statistics", node: <KeyStatisticsPanel symbol={symbol} span={12} /> },
        // The company's record, the same panels the Profile and Earnings
        // pages carry (2026-09-12: "bring the data from profile to
        // analysis") — one place to read a name end to end.
        { id: "history", label: "Earnings history", node: <EarningsHistoryPanel symbol={symbol} span={6} /> },
        { id: "consensus", label: "Consensus estimates", node: <EarningsInsightsPanel symbol={symbol} span={6} /> },
        ...(isFund ? [
          { id: "fund-holdings", label: "Holdings", node: <FundHoldingsPanel symbol={symbol} span={6} /> },
          { id: "fund-breakdown", label: "Fund breakdown", node: <FundBreakdownPanel symbol={symbol} span={6} /> },
        ] : []),
        // What trades off this company: the leveraged, inverse and income
        // funds built on it (2026-09-15).
        { id: "related-funds", label: "Funds on this stock", node: <RelatedFundsPanel symbol={symbol} span={12} /> },
        { id: "analysts", label: "Analyst view", node: <AnalystPanel symbol={symbol} span={5} /> },
        { id: "ratings", label: "Rating changes", node: <RatingChangesPanel symbol={symbol} span={7} /> },
        { id: "financials", label: "Financials", node: <FinancialsPanel symbol={symbol} span={7} /> },
        { id: "splits", label: "Stock splits", node: <SplitsPanel symbol={symbol} span={5} /> },
        { id: "dividends", label: "Dividend payments", node: <DividendsPanel symbol={symbol} span={12} /> },
        { id: "institutional", label: "Institutional ownership", node: <InstitutionalOwnershipPanel symbol={symbol} span={5} /> },
        { id: "holders", label: "Stock ownership", node: <StockOwnershipPanel symbol={symbol} span={7} /> },
        { id: "insiders", label: "Insider trades", node: <InsiderTradesPanel symbol={symbol} span={12} /> },
        { id: "news", label: "Symbol news", node: <SymbolNews symbol={symbol} span={12} /> },
  ]
  return (
    <ComposedBoard
      page="analysis"
      panels={isCoin
        ? [...panels.filter(p => !STOCK_ONLY.has(p.id)).slice(0, 2),
           { id: "coin", label: "What it is", node: <CoinRecordPanel symbol={symbol} span={12} /> },
           ...panels.filter(p => !STOCK_ONLY.has(p.id)).slice(2)]
        : panels}
    />
  )
}
