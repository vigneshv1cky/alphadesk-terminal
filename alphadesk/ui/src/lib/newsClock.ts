/** When a story published, as a headline row shows it (2026-09-17).
 *
 * The rows carried a TIME and no date — "4:38 PM ET" — while the window
 * holds 36 hours by default and pages back further than that, so a row
 * from yesterday or last week read as if it had just arrived.
 *
 * The day is added only when it is not today's, because most rows in a
 * live window ARE today's and repeating the date on every one of them
 * spends width the headline needs. Everything is New York time, which is
 * the clock the rest of the terminal keeps; a reader in another zone sees
 * the market's day, not their own.
 */

const ET = "America/New_York"

/** The New York calendar date of an instant, as YYYY-MM-DD. */
export function etDay(d: Date): string {
  // en-CA gives ISO order, which sorts and compares as a plain string.
  return d.toLocaleDateString("en-CA", { timeZone: ET })
}

export function newsTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const time = d.toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" })
  const day = etDay(d)
  if (day === etDay(now)) return `${time} ET`
  // Yesterday by name: a reader scanning an overnight window should not
  // have to work out what date yesterday was.
  const yesterday = new Date(now.getTime() - 86_400_000)
  if (day === etDay(yesterday)) return `Yesterday ${time} ET`
  const sameYear = d.toLocaleDateString("en-US", { timeZone: ET, year: "numeric" })
    === now.toLocaleDateString("en-US", { timeZone: ET, year: "numeric" })
  const date = d.toLocaleDateString("en-US", {
    timeZone: ET, month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }),
  })
  return `${date} · ${time} ET`
}
