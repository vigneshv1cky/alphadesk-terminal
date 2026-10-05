/** The Filings page's reader: what it needs that is not drawing (2026-10-05, the
 * owner picked option B, "Reader", from four drafts). Pure, so it is tested.
 *
 * NOTHING HERE RANKS OR COLOURS A FILING BY IMPORTANCE. The page's own rule (and
 * invariant 3) is that which event matters is the reader's call; the order is
 * the SEC's acceptance time, and an item list is the registrant's own wording. */

export interface ReaderFiling {
  form: string
  company: string
  cik: string | null
  role: string | null
  filed_at: string
  accession: string | null
  url: string | null
  symbols: string[]
  items?: { number: string; label: string }[]
}

/** What each form IS, for a filing that carries no list of events (a stake report
 * names no event; it is the form's own kind of report). Plain definitions of the
 * SEC's forms, not readings of any one filing. */
const FORM_NAME: Record<string, string> = {
  "8-K": "Material event report",
  "SCHEDULE 13G": "Passive stake report (a holder of 5% or more)",
  "SCHEDULE 13G/A": "Passive stake report, amended",
  "SCHEDULE 13D": "Active stake report (a holder of 5% or more)",
  "SCHEDULE 13D/A": "Active stake report, amended",
  "SC TO-I": "Issuer tender offer",
  "SC TO-I/A": "Issuer tender offer, amended",
  "SC TO-T": "Third-party tender offer",
  "SC TO-T/A": "Third-party tender offer, amended",
  "SC 14D9": "Target's response to a tender offer",
  "SC 14D9/A": "Target's response to a tender offer, amended",
}

/** One filing's identity across polls: its accession number, else what makes it
 * unique when the SEC row has none. */
export function filingKey(f: Pick<ReaderFiling, "accession" | "form" | "cik" | "filed_at">): string {
  return f.accession ?? `${f.form}|${f.cik ?? ""}|${f.filed_at}`
}

export interface FilingLine { n: string; label: string }

/** What to show under the heading: the registrant's own declared items, else the
 * form's plain name. `declared` says which, so the heading can too. */
export function describeFiling(f: Pick<ReaderFiling, "form" | "items">): { declared: boolean; lines: FilingLine[] } {
  const items = f.items ?? []
  if (items.length) return { declared: true, lines: items.map(i => ({ n: i.number, label: i.label })) }
  return { declared: false, lines: [{ n: "", label: FORM_NAME[f.form.toUpperCase()] ?? f.form }] }
}

const ET = "America/New_York"

/** "10:55 AM", in the exchange's own clock (the SEC stamps acceptance in New York). */
export function timeLabel(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" }).format(d)
}

const dayKey = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" }).format(d)

/** "Today", "Yesterday", else "Fri Oct 2", all by the New York calendar. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "Earlier"
  const k = dayKey(d)
  if (k === dayKey(now)) return "Today"
  if (k === dayKey(new Date(now.getTime() - 86_400_000))) return "Yesterday"
  return new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "short", month: "short", day: "numeric" }).format(d)
}

/** Rows in the order given, grouped into runs of the same day. */
export function groupByDay<T extends { filed_at: string }>(rows: T[], now: Date = new Date()): { label: string; rows: T[] }[] {
  const out: { label: string; rows: T[] }[] = []
  for (const r of rows) {
    const label = dayLabel(r.filed_at, now)
    const last = out[out.length - 1]
    if (last && last.label === label) last.rows.push(r)
    else out.push({ label, rows: [r] })
  }
  return out
}

/** The index to move to from `current` by `delta`, staying inside the list. */
export function moveSelection(count: number, current: number, delta: number): number {
  if (count <= 0) return -1
  const from = current < 0 ? 0 : current
  return Math.min(count - 1, Math.max(0, from + delta))
}

/** The tickers of a filing other than the first, for "also listed as". */
export function otherTickers(symbols: string[] | undefined): string[] {
  return (symbols ?? []).slice(1)
}
