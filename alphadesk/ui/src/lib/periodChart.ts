import type { ChartRange } from "./api"

/** The daily chart ranges a period chart can ask for, each with the days it
 * is sure to reach back: a month can be 28 days, and the margins leave room
 * for a start that falls on a weekend. */
const RANGES: { range: ChartRange; days: number }[] = [
  { range: "1M", days: 28 }, { range: "3M", days: 88 }, { range: "6M", days: 178 },
  { range: "1Y", days: 360 }, { range: "5Y", days: 1820 },
]

/** The shortest daily chart range reaching back to `from`. Pure. */
export function rangeReaching(from: string, today = new Date()): ChartRange {
  const back = (today.getTime() - new Date(`${from}T12:00:00Z`).getTime()) / 86_400_000
  return (RANGES.find(r => back <= r.days) ?? RANGES[RANGES.length - 1]).range
}

