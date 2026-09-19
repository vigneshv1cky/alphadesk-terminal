/** How a typed symbol becomes the one the API and the board agree on.
 *
 * This file used to hold a second saved list — the watchlist — beside the
 * board's own symbols. Two lists meant two gestures for one idea, and the
 * app teaches the board everywhere: the strip scopes every page, and the
 * Portfolio page is that board priced (2026-09-16, the owner's call). The
 * board lives in the URL and localStorage (lib/boardSymbols); this module
 * is now just the normaliser both it and the search boxes share.
 */

export function normalize(raw: string): string {
  return raw
    .toUpperCase()
    .split("")
    // ^ for an index (^GSPC), = for a future or a pair (CL=F, EURUSD=X):
    // the cross-asset board's rows scope the board like any other symbol.
    .filter(c => /[A-Z0-9.^=-]/.test(c))
    .join("")
    .slice(0, 14)
}
