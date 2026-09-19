/** The economic calendar's filter (2026-09-14): a minimum impact and a set
 * of countries, applied in the browser to the week the panel already holds.
 * A global vendor lists ~500 releases a week, holidays with no impact
 * among them; the reader narrows it, the server does not decide for them.
 * Pure, so the rules are tested. */

export type ImpactFloor = "all" | "low" | "medium" | "high"
export type EconomicFilter = { impact: ImpactFloor; countries: string[] }

/** Hides only releases the vendor marks as having no market impact
 * (holidays, observances); every country shows. */
export const DEFAULT_FILTER: EconomicFilter = { impact: "low", countries: [] }

const RANK: Record<string, number> = { none: 0, low: 1, medium: 2, high: 3 }

export function passes(row: { impact: string | null; country: string | null }, f: EconomicFilter): boolean {
  if (f.impact !== "all" && (RANK[row.impact ?? "none"] ?? 0) < RANK[f.impact]) return false
  if (f.countries.length && !f.countries.includes((row.country ?? "").toUpperCase())) return false
  return true
}

/** Countries in the week with their release counts, most releases first —
 * the filter's checklist. Rows without a country are left out of it. */
export function countryCounts(rows: { country: string | null }[]): { code: string; count: number }[] {
  const m = new Map<string, number>()
  for (const r of rows) {
    const c = (r.country ?? "").toUpperCase()
    if (c) m.set(c, (m.get(c) ?? 0) + 1)
  }
  return [...m.entries()].map(([code, count]) => ({ code, count }))
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code))
}

export function isDefault(f: EconomicFilter): boolean {
  return f.impact === DEFAULT_FILTER.impact && f.countries.length === 0
}

/** Read back a stored filter, falling back to the default on anything
 * malformed — a stored value is the browser's, not trusted shape. */
export function parseFilter(raw: string | null): EconomicFilter {
  try {
    const v = raw ? JSON.parse(raw) : null
    const impact = ["all", "low", "medium", "high"].includes(v?.impact) ? v.impact as ImpactFloor : DEFAULT_FILTER.impact
    const countries = Array.isArray(v?.countries) ? v.countries.filter((c: unknown) => typeof c === "string").map((c: string) => c.toUpperCase()) : []
    return { impact, countries }
  } catch {
    return DEFAULT_FILTER
  }
}
