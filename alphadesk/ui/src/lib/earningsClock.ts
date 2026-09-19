/** The earnings calendar's clock rules — pure, so they are testable off the
 * DOM (lib/__tests__/earningsClock.test.mts). Everything here reads time in
 * New York, the market's clock.
 *
 * A report row carries up to two instants: `released_at`, when EDGAR
 * accepted the results 8-K, and `actual_at`, when the actual EPS was first
 * seen on the calendar here. The When cell is built from them by
 * `whenLabel`; the rules for which instant may stand as the report's
 * clock (`timely`) and which counts as a sighting (`inBackfillWindow`)
 * are the ones the reader settled on 2026-09-12: precise, and never a
 * claim about when the company reported that the evidence does not
 * support. */

export type WhenRow = {
  report_date: string
  session: string | null
  confirmed?: boolean | number | null
  eps_actual?: number | null
  released_at?: string | null
  /** The day a results 8-K was filed when its acceptance instant is not known. */
  released_on?: string | null
  actual_at?: string | null
  /** The company's usual session from its SEC history, when no vendor has
   * confirmed one ("BMO" / "AMC"). A prediction, shown with an asterisk. */
  session_predicted?: string | null
}

const ET = "America/New_York"

/** The ISO date of an instant in New York. */
export function etDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-CA", { timeZone: ET })
}

/** The hour of an instant in New York, 0–23. */
export function etHour(iso: string): number {
  const d = new Date(iso)
  return Number(d.toLocaleTimeString("en-US", { hour: "numeric", hour12: false, timeZone: ET }).split(":")[0]) % 24
}

/** A clock time in New York for an instant, "8:31 AM". With `withDate`,
 * the date too when it is not the row's own day (for a tooltip; the cell
 * has no room for it). */
export function etClock(iso: string, day: string, withDate = false): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const t = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: ET })
  const onDay = etDate(iso) === day
  return onDay || !withDate ? t : `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: ET })} ${t}`
}

/** "Sat 1:47 AM" — the weekday and the minute, for a sighting that is not
 * on the report's own day. */
export function etDayClock(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return `${d.toLocaleDateString("en-US", { weekday: "short", timeZone: ET })} ${etClock(iso, "")}`
}

/** Whether a sighting can stand as the report's CLOCK: on the report day
 * itself, during the hours the report-day loop runs (06:00 ET to midnight).
 * The nightly sweep at ~01:47 ET stamps the actuals the calendar backfilled
 * after the loop stopped, and that time is when WE saw the number, not when
 * the company reported — it reads as "Out", with the sighting in the
 * tooltip (2026-09-12: a Friday's rows all read "Out 1:47 AM"). A row from
 * last week whose actual was first stamped today must not read as today's
 * report either. */
export function timely(iso: string, day: string): boolean {
  if (etDate(iso) !== day) return false
  return etHour(iso) >= 6
}

/** The ISO date after `day`. */
export function nextDay(day: string): string {
  const next = new Date(`${day}T12:00:00Z`)
  next.setUTCDate(next.getUTCDate() + 1)
  return next.toISOString().slice(0, 10)
}

/** Whether a sighting falls in the BACKFILL window for a report — on its
 * day, or the next day before noon ET, which is when the calendar's
 * overnight backfill and our sweep land an after-close number. A later
 * stamp says when the ledger learned the figure (the column's own arrival,
 * a rebuild), not when the number came out, and is not shown as one. */
export function inBackfillWindow(iso: string, day: string): boolean {
  const seen = etDate(iso)
  if (!seen) return false
  if (seen === day) return true
  if (seen !== nextDay(day)) return false
  return etHour(iso) < 12
}

/** Today's date in New York, the calendar's clock. */
export function todayInEt(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: ET })
}

/** How old an instant is, in words. */
export function ago(iso: string, now: number = Date.now()): string {
  const s = (now - new Date(iso).getTime()) / 1000
  if (!Number.isFinite(s) || s < 0) return ""
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

/** When the report lands, in words — theirs says "During trading". */
export function sessionLabel(r: Pick<WhenRow, "session" | "confirmed" | "eps_actual">): string {
  const sure = !!r.confirmed || r.eps_actual != null
  if (!sure) return "Time to be announced"
  return r.session === "BMO" ? "Before the open" : r.session === "AMC" ? "After the close" : "During trading"
}

/** The When cell. Once the report is OUT the cell says so, with the clock:
 * EDGAR's acceptance of the 8-K, or a same-day sighting of the actual
 * ("Out 6:59 AM"); a later sighting in the backfill window is named for
 * what it is, with its day ("Seen Sat 1:47 AM"); a sighting outside the
 * window just says "Out" — with the session the vendor names when it names
 * one ("Out pre-mkt"), because before-the-open or after-the-close is what a
 * reader acts on, and a results 8-K filed days later has no clock of its own
 * (2026-09-14: Optical Cable, released the 9th, filed the 11th). A day that has passed with nothing seen is not
 * "to be announced": the company either named the time and the number has
 * not reached the calendar yet (Pending), or the date was only a
 * projection and nothing came out (Not seen). Ahead of the day: the
 * session once the company has named it, "TBA" while the date is only a
 * projection. `todayEt` is injectable for tests. */
export function whenLabel(r: WhenRow, todayEt: string = todayInEt()): string {
  const out = r.eps_actual != null || !!r.released_at || !!r.released_on
  const sure = !!r.confirmed || out
  const clockAt = r.released_at ?? (r.actual_at && timely(r.actual_at, r.report_date) ? r.actual_at : null)
  const sighted = !!r.actual_at && inBackfillWindow(r.actual_at, r.report_date)
  const past = r.report_date < todayEt
  return out
    ? clockAt ? `Out ${etClock(clockAt, r.report_date)}`
      : sighted ? `Seen ${etDayClock(r.actual_at!)}`
      : r.session === "BMO" ? "Out pre-mkt" : r.session === "AMC" ? "Out after" : "Out"
    : past ? (sure ? "Pending" : "Not seen")
    : sure && (r.session === "BMO" || r.session === "AMC") ? (r.session === "BMO" ? "Pre-mkt" : "After")
    : r.session_predicted === "BMO" ? "Pre-mkt*" : r.session_predicted === "AMC" ? "After*"
    : sure ? "Day" : "TBA"
}
