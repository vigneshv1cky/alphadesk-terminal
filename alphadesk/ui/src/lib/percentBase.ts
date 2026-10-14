/** The percent scale's default zero on a one-day chart (2026-10-12, the owner:
 * "the 0 percent shows opening on October 12"). It was the close of the first
 * bar loaded, which on a 15-minute chart was Sunday evening's overnight bar,
 * two and a half days back, so the scale read -4.34% beside a header that said
 * -0.12%. The header measures from the quote's previous close, the session
 * before the latest one that traded; this finds that session's last regular
 * bar, so comparison lines start from the same moment. */

type Clock = { day: string; weekday: string; minutes: number }

function clock(t: string, tz: string): Clock | null {
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return null
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(d).map(p => [p.type, p.value]))
  return {
    day: `${parts.year}-${parts.month}-${parts.day}`,
    weekday: parts.weekday,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  }
}

/** Index of the last regular-session bar (09:30 to 16:00 New York, a bar
 * starting inside it) of the session BEFORE the latest one in `bars`, or -1
 * when the bars hold fewer than two sessions. Pure. */
export function previousSessionLastIndex(bars: readonly { t: string }[], tz = "America/New_York"): number {
  const lastOf = new Map<string, number>()
  bars.forEach((b, i) => {
    const c = clock(b.t, tz)
    if (!c || c.weekday === "Sat" || c.weekday === "Sun") return
    if (c.minutes >= 9 * 60 + 30 && c.minutes < 16 * 60) lastOf.set(c.day, i)
  })
  const days = [...lastOf.keys()].sort()
  return days.length >= 2 ? lastOf.get(days[days.length - 2])! : -1
}
