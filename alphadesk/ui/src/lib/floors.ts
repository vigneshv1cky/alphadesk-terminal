/** The movers floors' money fields: "1000000" reads as "1M" in the input,
 * and "1.5M", "$2,000", "250k" read back as numbers. Pure, tested in
 * lib/__tests__/floors.test.mts. */

/** A number for the filter input: 1e9 -> "1B", 1e6 -> "1M", 1e3 -> "1K". */
export const moneyIn = (v: number): string =>
  v >= 1e9 ? `${v / 1e9}B` : v >= 1e6 ? `${v / 1e6}M` : v >= 1e3 ? `${v / 1e3}K` : String(v)

/** The input back to a number; null when it is not one. Dollar signs,
 * commas and spaces are ignored; K, M and B scale, any case. */
export const moneyOut = (t: string): number | null => {
  const m = t.trim().replace(/[$,\s]/g, "").match(/^(\d*\.?\d+)([kmb])?$/i)
  if (!m) return null
  const n = parseFloat(m[1]); const u = (m[2] || "").toLowerCase()
  return n * (u === "b" ? 1e9 : u === "m" ? 1e6 : u === "k" ? 1e3 : 1)
}
