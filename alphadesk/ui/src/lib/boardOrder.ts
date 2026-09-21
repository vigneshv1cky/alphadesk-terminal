/** The order the symbol strip renders in (2026-09-20, the owner: "show the
 * most recent viewed stocks on left most side").
 *
 * Pure and dependency-free so it can be tested on its own — the strip's own
 * module is a React hook, and this is the only part of it with a rule worth
 * pinning.
 */

/** `symbols` ordered by `order` — the symbols most recently scoped to,
 * newest first. One this browser has never opened has no recency at all, so
 * it keeps its place behind those that do, in the order it was given: that
 * is a shared link's own order, which is the only order it has. */
export function byRecency(symbols: string[], order: string[]): string[] {
  const rank = new Map(order.map((s, i) => [s, i]))
  return symbols
    .map((s, i) => ({ s, seen: rank.get(s) ?? Infinity, i }))
    .sort((a, b) => a.seen - b.seen || a.i - b.i)
    .map(r => r.s)
}
