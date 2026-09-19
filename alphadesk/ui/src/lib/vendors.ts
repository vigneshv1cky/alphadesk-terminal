/** Display names for the data vendors a user connects (2026-09-13). Every
 * market figure on the board comes from one of these on the user's own key;
 * SEC EDGAR is the keyless public source. */
export const VENDOR_LABELS: Record<string, string> = {
  alpaca: "Alpaca", finnhub: "Finnhub", polygon: "Polygon", alphavantage: "Alpha Vantage",
  fmp: "Financial Modeling Prep", coingecko: "CoinGecko", "sec-edgar": "SEC EDGAR", edgar: "SEC EDGAR",
  treasury: "US Treasury", benzinga: "Benzinga", tiingo: "Tiingo", marketaux: "Marketaux",
}

/** "via Alpaca and Polygon" — the reader's feeds that delivered a story. */
export const viaFeeds = (feeds: string[] | null | undefined): string | null =>
  feeds && feeds.length
    ? `via ${feeds.map(f => vendorLabel(f)).join(feeds.length === 2 ? " and " : ", ")}`
    : null

export const vendorLabel = (name: string | null | undefined): string | undefined =>
  name ? VENDOR_LABELS[name] ?? name : undefined
