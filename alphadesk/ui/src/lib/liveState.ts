import { useSyncExternalStore } from "react"

/** ALWAYS LIVE (decision 2026-09-02): the header's pause toggle is gone and
 * the streams simply run. The hook stays as the seam every streaming
 * consumer already reads, so a future per-widget or bandwidth-saver switch
 * has one place to land — but today it answers true, always.
 */

export function isLive(): boolean {
  return true
}

function subscribe() {
  return () => {}
}

export function useLiveEnabled(): boolean {
  return useSyncExternalStore(subscribe, isLive, () => true)
}
