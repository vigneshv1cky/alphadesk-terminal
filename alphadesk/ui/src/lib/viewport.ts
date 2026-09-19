import { useEffect, useState } from "react"

/** Whether the viewport is a phone's (under 640px). One hook for every
 * surface that lays itself out differently there — the rail's drawer, the
 * chart's volume pane — so the breakpoint is written once. */
export function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(() => {
    try { return window.matchMedia("(max-width: 639px)").matches } catch { return false }
  })
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)")
    const on = () => setNarrow(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return narrow
}
