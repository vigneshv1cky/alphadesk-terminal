import { useEffect, useState } from "react"

/** A value a panel keeps while the reader moves between pages (2026-09-18):
 * the earnings calendar's week and picked day were lost every time its page
 * unmounted, so returning to Earnings reopened this week with no day picked.
 *
 * Kept in sessionStorage — this browser tab, until it closes — and stamped
 * with the New York day it was set on, so a tab left open overnight opens on
 * today's week rather than yesterday's pick. */
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" })

/** The stored value, or `fallback` when there is none, it is unreadable, or
 * it was set on another day. Exported for the tests. */
export function readKept<T>(raw: string | null, day: string, fallback: T): T {
  if (!raw) return fallback
  try {
    const got = JSON.parse(raw) as { day?: string; value?: T }
    return got && got.day === day && "value" in got ? (got.value as T) : fallback
  } catch {
    return fallback
  }
}

export function useKeptState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try { return readKept(sessionStorage.getItem(key), today(), initial) } catch { return initial }
  })
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify({ day: today(), value })) } catch { /* private mode */ }
  }, [key, value])
  return [value, setValue]
}
