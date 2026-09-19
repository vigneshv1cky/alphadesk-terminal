/** The day the earnings calendar opens on when the reader has not picked one
 * (2026-09-18, the reader's ask): TODAY, or on a weekend or a market holiday
 * the most recent earlier day that has reports — Saturday opens on Friday,
 * Thanksgiving on the Wednesday before it.
 *
 * When the current week has no such day yet (a Monday holiday, a quiet
 * Monday before its first report), the calendar steps back ONE week and
 * opens on that week's last reporting day. A week the reader moved to with
 * the arrows opens whole, as before. Pure, so it is tested without a page. */

export type DayCount = { date: string; count: number }

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function defaultDay(
  days: readonly DayCount[], weekStart: string, weekEnd: string, today: string, stepped: boolean,
): { day: string | null; stepBack: boolean } {
  // Saturday and Sunday still belong to the week just ended.
  const current = today >= weekStart && today <= addDays(weekEnd, 2)
  if (!current && !stepped) return { day: null, stepBack: false }
  const latest = [...days].filter(d => d.count > 0 && d.date <= today).sort((a, b) => b.date.localeCompare(a.date))[0]
  if (latest) return { day: latest.date, stepBack: false }
  return { day: null, stepBack: current && !stepped }
}
