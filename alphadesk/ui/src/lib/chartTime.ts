/** Time zones the chart can display in, and the countdown to a bar's close
 * (2026-09-05).
 *
 * The bars are stamped in exchange time — New York for everything the
 * platform charts — and the SESSION math (pre-market shading, day breaks)
 * stays there whatever the display zone is, because a session is a fact
 * about the exchange. What the reader can change is how the axis and the
 * readouts LABEL those instants.
 */

export const DEFAULT_TIME_ZONE = "America/New_York"

export const TIME_ZONES: { id: string; label: string }[] = [
  { id: "America/New_York", label: "New York (exchange)" },
  { id: "UTC", label: "UTC" },
  { id: "America/Chicago", label: "Chicago" },
  { id: "America/Los_Angeles", label: "Los Angeles" },
  { id: "America/Sao_Paulo", label: "São Paulo" },
  { id: "Europe/London", label: "London" },
  { id: "Europe/Berlin", label: "Frankfurt" },
  { id: "Europe/Zurich", label: "Zurich" },
  { id: "Asia/Dubai", label: "Dubai" },
  { id: "Asia/Kolkata", label: "Mumbai" },
  { id: "Asia/Singapore", label: "Singapore" },
  { id: "Asia/Hong_Kong", label: "Hong Kong" },
  { id: "Asia/Shanghai", label: "Shanghai" },
  { id: "Asia/Tokyo", label: "Tokyo" },
  { id: "Australia/Sydney", label: "Sydney" },
]

/** Whether the runtime knows a zone — the guard on a persisted value. */
export function validTimeZone(id: unknown): id is string {
  if (typeof id !== "string" || !id) return false
  try { new Intl.DateTimeFormat("en-US", { timeZone: id }); return true } catch { return false }
}

/** The zone's current UTC offset as "UTC-4" / "UTC+5:30". */
export function offsetLabel(timeZone: string, at = new Date()): string {
  const part = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "shortOffset" })
    .formatToParts(at).find(p => p.type === "timeZoneName")?.value ?? "UTC"
  return part.replace("GMT", "UTC")
}

/** An interval id's length in seconds: "10s", "3m", "2h". Null for daily
 * and coarser, which have no fixed close here except the daily one. */
export function intervalSeconds(id: string): number | null {
  const m = /^(\d+)(s|m|h)$/.exec(id)
  if (!m) return null
  return Number(m[1]) * ({ s: 1, m: 60, h: 3600 } as Record<string, number>)[m[2]]
}

/** Seconds until the bar that started at `lastT` closes, or null when the
 * interval has no fixed close (weekly, monthly), the bar is already over,
 * or the timestamp cannot be read. A daily bar closes at 16:00 exchange
 * time, and the daily stamps carry the exchange offset, so that is sixteen
 * hours after the bar's midnight. */
export function barCloseCountdown(lastT: string, interval: string | undefined, now = Date.now()): number | null {
  const start = Date.parse(lastT)
  if (!Number.isFinite(start) || !interval) return null
  let span: number
  const secs = intervalSeconds(interval)
  if (secs) span = secs * 1000
  else if (interval === "1d") span = 16 * 3_600_000
  else return null
  const remaining = start + span - now
  if (remaining <= 0 || remaining > span) return null
  return Math.floor(remaining / 1000)
}

export function countdownLabel(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0")
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/** The time axis, the way theirs reads it (2026-09-10).
 *
 * Labels sit at BOUNDARIES, not every n-th bar: within a day the hour, at a
 * day change the day number, at a month change the month, at a year change
 * the year — each coarser level drawn heavier. A boundary label says what
 * changed, so a minute chart no longer reads "Sep 8, Sep 8, Sep 8, Sep 9"
 * and a five-year chart no longer reads five Augusts.
 *
 * The density comes from a budget: the coarse boundaries (year, month, day)
 * are placed first, and the finest level that still fits takes the rest,
 * from a ladder of nice steps — minutes 1…720 inside a day, then every
 * k-th day, k-th month, k-th year when even the day changes will not fit.
 *
 * Bars are indexed, not timed: an overnight gap is one bar wide, so the
 * boundary is found by comparing each bar's calendar parts with the bar
 * before it, and the tick lands on the first bar past the boundary.
 */
export type AxisTick = { i: number; label: string; major: boolean; level: 1 | 2 | 3 | 4 }

export type TimeParts = { y: number; mo: number; d: number; m: number }

/** Calendar parts of each bar in the display zone. Built once per series,
 * so the per-frame tick placement is arithmetic on integers. */
export function timeParts(times: string[], timeZone: string): TimeParts[] {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone, hour12: false, year: "numeric", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  })
  return times.map(t => {
    const p = fmt.formatToParts(new Date(t))
    const get = (k: string) => Number(p.find(x => x.type === k)?.value ?? 0)
    // Intl renders midnight as hour 24 under hour12:false.
    return { y: get("year"), mo: get("month"), d: get("day"), m: (get("hour") % 24) * 60 + get("minute") }
  })
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const MINUTE_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 240, 360, 720]
const DAY_STEPS = [2, 3, 5, 10, 15]
const MONTH_STEPS = [2, 3, 6]
const YEAR_STEPS = [2, 5, 10, 20, 50]

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`)

/** Ticks for the visible bars [lo, hi], at most about `budget` of them.
 * `thisYear` is the reader's year: a month label in another year carries
 * the year, so a window scrolled into the past can still be placed. */
export function timeAxisTicks(parts: TimeParts[], lo: number, hi: number, budget: number,
                              thisYear = new Date().getFullYear()): AxisTick[] {
  lo = Math.max(1, lo)
  hi = Math.min(parts.length - 1, hi)
  if (hi < lo || budget < 1) return []

  // Level of the boundary crossed INTO bar i: 4 year, 3 month, 2 day, 1 none.
  const level = (i: number) => {
    const a = parts[i - 1], b = parts[i]
    if (a.y !== b.y) return 4
    if (a.mo !== b.mo) return 3
    if (a.d !== b.d) return 2
    return 1
  }
  const levels: number[] = []
  let years = 0, months = 0, days = 0
  for (let i = lo; i <= hi; i++) {
    const l = level(i)
    levels.push(l)
    if (l === 4) years++
    else if (l === 3) months++
    else if (l === 2) days++
  }
  const monthLabel = (p: TimeParts) => (p.y === thisYear ? MONTHS[p.mo - 1] : `${MONTHS[p.mo - 1]} ${p.y}`)
  const out: AxisTick[] = []
  const push = (i: number, l: number, step = 1) => {
    const p = parts[i]
    // The hour label names the BOUNDARY crossed, not the bar's own minute:
    // on a sparse series the first bar past 12:00 may be 12:06, and the
    // axis should still read 12:00.
    const m = Math.floor(p.m / step) * step
    out.push(l === 4 ? { i, label: `${p.y}`, major: true, level: 4 }
      : l === 3 ? { i, label: monthLabel(p), major: true, level: 3 }
      : l === 2 ? { i, label: `${p.d}`, major: true, level: 2 }
      : { i, label: `${pad(Math.floor(m / 60))}:${pad(m % 60)}`, major: false, level: 1 })
  }

  if (years + months + days <= budget) {
    // Every calendar boundary fits; the hours take what is left.
    const left = budget - years - months - days
    // The hour step is bounded below by the bars themselves: on a sparse
    // series a one-minute step "fits" the budget and labels every print
    // with its own minute. The step is at least the typical gap between
    // bars and at least the visible session-time divided by the budget,
    // so the labels name round times whatever the density.
    const gaps: number[] = []
    for (let i = lo; i <= hi; i++) if (levels[i - lo] === 1) gaps.push(parts[i].m - parts[i - 1].m)
    const sorted = [...gaps].sort((a, b) => a - b)
    const median = sorted.length ? sorted[sorted.length >> 1] : 1
    const sessionMin = gaps.reduce((a, b) => a + b, 0)
    const minStep = Math.max(median, sessionMin / Math.max(1, left))
    let step: number | null = null
    for (const s of MINUTE_STEPS) {
      if (s < minStep) continue
      let n = 0
      for (let i = lo; i <= hi; i++) {
        if (levels[i - lo] !== 1) continue
        if (Math.floor(parts[i - 1].m / s) !== Math.floor(parts[i].m / s)) n++
      }
      if (n <= left) { step = s; break }
    }
    for (let i = lo; i <= hi; i++) {
      const l = levels[i - lo]
      if (l > 1) push(i, l)
      else if (step != null && Math.floor(parts[i - 1].m / step) !== Math.floor(parts[i].m / step)) push(i, 1, step)
    }
    return out
  }
  if (years + months <= budget) {
    // Day changes do not all fit: every k-th day of the month.
    const left = budget - years - months
    const k = DAY_STEPS.find(s => count(2, i => (parts[i].d - 1) % s === 0) <= left) ?? Infinity
    for (let i = lo; i <= hi; i++) {
      const l = levels[i - lo]
      if (l > 2) push(i, l)
      else if (l === 2 && (parts[i].d - 1) % k === 0) push(i, 2)
    }
    return out
  }
  if (years <= budget) {
    const left = budget - years
    const k = MONTH_STEPS.find(s => count(3, i => (parts[i].mo - 1) % s === 0) <= left) ?? Infinity
    for (let i = lo; i <= hi; i++) {
      const l = levels[i - lo]
      if (l > 3) push(i, l)
      else if (l === 3 && (parts[i].mo - 1) % k === 0) push(i, 3)
    }
    return out
  }
  const k = YEAR_STEPS.find(s => count(4, i => parts[i].y % s === 0) <= budget) ?? Infinity
  for (let i = lo; i <= hi; i++) {
    if (levels[i - lo] === 4 && parts[i].y % k === 0) push(i, 4)
  }
  return out

  function count(l: number, keep: (i: number) => boolean): number {
    let n = 0
    for (let i = lo; i <= hi; i++) if (levels[i - lo] === l && keep(i)) n++
    return n
  }
}

/** Keep labels from colliding: ticks closer than `minGap` pixels lose the
 * finer one — a day beats an hour, a month beats a day. Sparse series put
 * several boundaries within a few bars, and the budget alone cannot see
 * that, since it counts ticks rather than measuring them. */
export function thinTicks<T extends { x: number; level: number }>(ticks: T[], minGap: number): T[] {
  const kept: T[] = []
  for (const t of [...ticks].sort((a, b) => a.x - b.x)) {
    const last = kept[kept.length - 1]
    if (last && t.x - last.x < minGap) {
      if (t.level > last.level) kept[kept.length - 1] = t
      continue
    }
    kept.push(t)
  }
  return kept
}

/** Where a RANGE's view starts, as a bar index, in exchange time — the
 * span the reader chose, not the buffer the server fetched around it
 * (2026-09-10). 1D is the last session's day; 5D the last five trading
 * days; the calendar ranges count back from the last bar; YTD from its
 * January 1st; All from the first bar. What lies before the index is
 * history the reader can pan into. */
export function focusIndex(times: string[], range: string, exchangeZone = DEFAULT_TIME_ZONE): number {
  const n = times.length
  if (n < 2 || range === "MAX") return 0
  const last = new Date(times[n - 1])
  if (range === "1D" || range === "5D") {
    const want = range === "1D" ? 1 : 5
    const fmt = new Intl.DateTimeFormat("en-CA", { timeZone: exchangeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    let days = 0, day = ""
    for (let i = n - 1; i >= 0; i--) {
      const d = fmt.format(new Date(times[i]))
      if (d !== day) {
        day = d
        days++
        // A day that is only a few overnight prints is not the session the
        // reader asked to see; take the one before it as well.
        if (days > want && !(want === 1 && days === 2 && n - 1 - i < 30)) return i + 1
      }
    }
    return 0
  }
  const cutoff = new Date(last)
  if (range === "YTD") {
    const y = Number(new Intl.DateTimeFormat("en-US", { timeZone: exchangeZone, year: "numeric" }).format(last))
    cutoff.setTime(Date.parse(`${y}-01-01T00:00:00-05:00`))
  } else {
    const months = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60 }[range]
    if (months == null) return 0
    cutoff.setUTCMonth(cutoff.getUTCMonth() - months)
  }
  const t0 = cutoff.getTime()
  for (let i = 0; i < n; i++) if (Date.parse(times[i]) >= t0) return i
  return 0
}
