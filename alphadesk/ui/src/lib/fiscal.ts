/** Fiscal quarter labels — "Q3 FY26" the way the company and its call say
 * it, not the calendar quarter (2026-09-12: theirs labels Apple's June
 * quarter Q3 FY26 and GameStop's July quarter Q2 FY27).
 *
 * The fiscal year is named for the calendar year it ENDS in, which is how
 * Apple, NVIDIA and GameStop all say it. A 52/53-week calendar puts
 * a quarter's end a few days either side of a month boundary (GameStop's
 * July quarter ended 1 August), so the month is read fifteen days before
 * the period end — well inside the quarter, never on its edge. */

const MS_DAY = 86_400_000

/** The month (1–12) a fiscal year ends in, from the stamp of the last
 * fiscal year end; null when unknown. */
export function fiscalYearEndMonth(lastFiscalYearEnd: string | null | undefined): number | null {
  if (!lastFiscalYearEnd) return null
  const d = new Date(`${lastFiscalYearEnd.slice(0, 10)}T12:00:00Z`)
  return Number.isNaN(d.getTime()) ? null : d.getUTCMonth() + 1
}

/** {q, fy} for a period that ENDED on `periodEnd`, given the month the
 * fiscal year ends in. Null when either is unknown. */
export function fiscalQuarter(periodEnd: string, fyEndMonth: number | null): { q: number; fy: number } | null {
  if (!fyEndMonth) return null
  const end = new Date(`${periodEnd.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(end.getTime())) return null
  const inside = new Date(end.getTime() - 15 * MS_DAY)
  const m = inside.getUTCMonth() + 1, y = inside.getUTCFullYear()
  const monthsIn = ((m - fyEndMonth - 1 + 12) % 12) + 1      // 1..12 from the fiscal year's first month
  const q = Math.ceil(monthsIn / 3)
  const fy = m > fyEndMonth ? y + 1 : y
  return { q, fy }
}

/** "Q3 FY26" for a quarter, "FY26" for a year; the calendar fallback when
 * the fiscal year end is unknown ("Q2 '26", "2026"). */
export function periodLabel(periodEnd: string, period: "quarterly" | "annual", fyEndMonth: number | null): string {
  const d = new Date(`${periodEnd.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return periodEnd
  const fq = fiscalQuarter(periodEnd, fyEndMonth)
  if (fq) return period === "annual" ? `FY${String(fq.fy).slice(2)}` : `Q${fq.q} FY${String(fq.fy).slice(2)}`
  if (period === "annual") return String(d.getUTCFullYear())
  return `Q${Math.floor(d.getUTCMonth() / 3) + 1} '${String(d.getUTCFullYear()).slice(2)}`
}

/** The fiscal quarter a report on `reportDate` is FOR: companies report
 * four to six weeks after the quarter closes, so the period is taken to
 * have ended forty-five days before. */
export function reportedQuarterLabel(reportDate: string, fyEndMonth: number | null): string | null {
  const d = new Date(`${reportDate.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  const end = new Date(d.getTime() - 45 * MS_DAY).toISOString().slice(0, 10)
  const fq = fiscalQuarter(end, fyEndMonth)
  return fq ? `Q${fq.q} FY${String(fq.fy).slice(2)}` : null
}

/** The reported quarters an EPS chart draws: the LAST `n`, oldest first, so
 * the chart reads left to right into the present (2026-09-18).
 *
 * The vendors send the record oldest first, but it was reversed on the
 * belief it arrived newest first, and never capped: while the feed carried
 * four quarters that went unnoticed; FMP carries a company's whole record,
 * and NVIDIA's chart drew 110 quarters back to 1999, newest on the LEFT,
 * with the readout on Q1 FY00. Sorting here makes the order independent of
 * whichever vendor answered. */
export function lastQuarters<T extends { date: string }>(rows: readonly T[], n = 4): T[] {
  return [...rows].sort((a, b) => a.date.localeCompare(b.date)).slice(-n)
}
