/** WHICH REPORT A STORY IS ABOUT (2026-09-16).
 *
 * A feed can publish an earnings call weeks after the call: Benzinga posted
 * ZTO Express's second-quarter transcript on September 16 for a quarter
 * announced on August 18, and with only its own date on it the story reads
 * as today's news. The reader names the last report the company had actually
 * made by the time the story was published, and says how far back it was
 * once that is more than a couple of days.
 */

export interface StoryReport {
  report_date: string
  eps_actual: number | null
}

/** The last report a company had made when the story was published: the
 * newest one dated on or before it that has an actual. Null when the company
 * had not reported, or when the story's tickers are not one company. */
export function reportBehindStory(reports: StoryReport[] | undefined, publishedAt: string | null): StoryReport | null {
  const day = (publishedAt ?? "").slice(0, 10) || "9999-12-31"
  const past = (reports ?? [])
    .filter(r => !!r.report_date && r.report_date <= day && r.eps_actual !== null)
    .sort((a, b) => a.report_date.localeCompare(b.report_date))
  return past.length ? past[past.length - 1] : null
}

/** "Reported Aug 18, 2026 — 4 weeks before this story", or just the date
 * when the story followed within a couple of days. */
export function reportedLine(reportDate: string, publishedAt: string | null): string | null {
  const d = new Date(`${reportDate}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  const day = d.toLocaleDateString("en-US", {
    timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric",
  })
  const pub = publishedAt ? new Date(publishedAt) : null
  const days = pub && !Number.isNaN(pub.getTime())
    ? Math.round((pub.getTime() - d.getTime()) / 86_400_000)
    : 0
  if (days < 3) return `Reported ${day}`
  const gap = days < 14 ? `${days} days`
    : days < 60 ? `${Math.round(days / 7)} weeks`
    : `${Math.round(days / 30)} months`
  return `Reported ${day} — ${gap} before this story`
}
