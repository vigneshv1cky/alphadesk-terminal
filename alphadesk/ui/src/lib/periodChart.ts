import type { ChartRange } from "./api"

/** The chart panel's daily ranges a period opens on, each with the days back
 * it is taken to cover. A year's period (252 sessions) starts a few days
 * more than a year back, and opening the 5-year chart for it would bury the
 * period, so the year is given a week's slack. */
const RANGES: { range: ChartRange; days: number }[] = [
  { range: "1M", days: 28 }, { range: "3M", days: 88 }, { range: "6M", days: 178 },
  { range: "1Y", days: 372 }, { range: "5Y", days: 1820 },
]

/** The shortest daily chart range covering a period starting at `from`. Pure. */
export function rangeReaching(from: string, today = new Date()): ChartRange {
  const back = (today.getTime() - new Date(`${from}T12:00:00Z`).getTime()) / 86_400_000
  return (RANGES.find(r => back <= r.days) ?? RANGES[RANGES.length - 1]).range
}

