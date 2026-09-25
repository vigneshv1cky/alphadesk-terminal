import { useCallback, useEffect, useRef, useState } from "react"

/** RENDER ONLY THE ROWS ON SCREEN (2026-09-25, #81).
 *
 * WHY. The news list put every story in the DOM. Measured on the owner's
 * machine with only 800 stories: 7,394 nodes, 82,853px of content in a
 * 778px box, and arriving on the page blocked the main thread for 676ms
 * across four long tasks — the worst 243ms. The reader's live window runs
 * to thousands of stories over three days, and the page keeps fetching
 * older pages in the background, re-rendering the whole list each time one
 * lands. That is the ten-second freeze seen in the reader's own screen
 * recording: the page stuck on News while the cursor moved across seven
 * rail items, hover still repainting between the blocking tasks.
 *
 * Windowing makes the cost constant: thirty rows render whether the reader
 * holds eight hundred stories or eight thousand.
 *
 * NO DEPENDENCY, deliberately. A virtualiser would have been one import,
 * but this repo hand-rolls its primitives and every dependency has to stay
 * permissive for the commercial licence to be worth anything. Sixty lines
 * of arithmetic is a smaller commitment than a package, and the arithmetic
 * is the part worth testing anyway — see windowedRows.test.mts.
 *
 * ROWS ARE NOT A FIXED HEIGHT. A headline with a summary is taller than one
 * without, so each row starts at an estimate and is corrected to its real
 * height once it has been on screen. Offsets are a running total of those
 * heights, so the scrollbar is honest about what it is scrolling through
 * and never jumps once a row has been seen.
 */

/** Where each row starts, plus the total. One more entry than there are rows. */
export function runningOffsets(heights: number[]): number[] {
  const out = new Array(heights.length + 1)
  out[0] = 0
  for (let i = 0; i < heights.length; i++) out[i + 1] = out[i] + heights[i]
  return out
}

/** The last row starting at or before `y`. Offsets ascend, so this is a
 * binary search — a linear scan here is run on every scroll frame. */
export function rowAt(offsets: number[], y: number): number {
  let lo = 0, hi = offsets.length - 2
  if (hi < 0) return 0
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (offsets[mid] <= y) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** The rows overlapping [top, top + height), widened by `overscan` either
 * side so a scroll does not reveal a gap before React has filled it. */
export function visibleRange(offsets: number[], top: number, height: number, overscan: number, count: number) {
  if (count === 0) return { start: 0, end: 0 }
  const first = rowAt(offsets, Math.max(0, top))
  let last = first
  const bottom = top + height
  while (last + 1 < count && offsets[last + 1] < bottom) last++
  return {
    start: Math.max(0, first - overscan),
    end: Math.min(count, last + 1 + overscan),
  }
}

export function useWindowedRows({ count, estimate, overscan = 6, resetKey }: {
  count: number
  /** A row's assumed height until it has been measured. */
  estimate: number
  overscan?: number
  /** Changing this throws away every measurement — for when the list becomes
   * a different list (a filter, a search) rather than simply longer. */
  resetKey?: unknown
}) {
  const scroller = useRef<HTMLElement | null>(null)
  const heights = useRef<number[]>([])
  const offsets = useRef<number[]>([0])
  const [range, setRange] = useState({ start: 0, end: Math.min(count, overscan * 2) })
  const [total, setTotal] = useState(count * estimate)

  // Keep the height table the same length as the list. A page of older
  // stories arriving appends estimates; nothing already measured is lost,
  // which is what stops the scrollbar jumping as the backfill runs.
  if (heights.current.length !== count) {
    const h = heights.current
    if (count > h.length) for (let i = h.length; i < count; i++) h.push(estimate)
    else h.length = count
    offsets.current = runningOffsets(h)
  }

  const recompute = useCallback(() => {
    const el = scroller.current
    if (!el) return
    const next = visibleRange(offsets.current, el.scrollTop, el.clientHeight, overscan, count)
    setRange(cur => (cur.start === next.start && cur.end === next.end ? cur : next))
    setTotal(offsets.current[count])
  }, [count, overscan])

  /** Attach to the scrolling element. */
  const attach = useCallback((el: HTMLElement | null) => {
    scroller.current = el
    if (el) recompute()
  }, [recompute])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    // STRAIGHT THROUGH, NOT VIA AN ANIMATION FRAME. Batching this into a
    // frame callback looks tidier and is a trap: frame callbacks are paused
    // in a background tab, so a scroll that happened without one left the
    // window parked where it was — the rows stranded tens of thousands of
    // pixels below a list scrolled back to its top. Browsers already fire
    // scroll events at most once a frame, and the work is a binary search
    // and a render of about twenty rows, so there is nothing to save.
    const onScroll = () => recompute()
    el.addEventListener("scroll", onScroll, { passive: true })
    const ro = new ResizeObserver(() => recompute())
    ro.observe(el)
    return () => {
      el.removeEventListener("scroll", onScroll)
      ro.disconnect()
    }
  }, [recompute])

  useEffect(() => { recompute() }, [recompute, count])

  // A different list, so every measurement is about rows that are gone.
  const lastReset = useRef(resetKey)
  if (lastReset.current !== resetKey) {
    lastReset.current = resetKey
    heights.current = new Array(count).fill(estimate)
    offsets.current = runningOffsets(heights.current)
  }

  /** Put on each rendered row: records what it really measured. */
  const measure = useCallback((index: number) => (el: HTMLElement | null) => {
    if (!el) return
    const h = el.offsetHeight
    if (!h || Math.abs(h - heights.current[index]) < 1) return
    heights.current[index] = h
    offsets.current = runningOffsets(heights.current)
    // Correcting a row above the viewport moves everything below it, so the
    // range and the total are both stale until this runs again.
    recompute()
  }, [recompute])

  /** Scroll a row into view by ARITHMETIC, not by element.
   *
   * A row outside the window has no element to call scrollIntoView on — the
   * whole point of this hook. The offsets know where it would be, which
   * works whether or not it is currently rendered. */
  const scrollToIndex = useCallback((index: number, block: "start" | "center" = "center") => {
    const el = scroller.current
    if (!el || index < 0 || index >= count) return
    const top = offsets.current[index]
    const h = heights.current[index] ?? estimate
    el.scrollTop = block === "center" ? Math.max(0, top - (el.clientHeight - h) / 2) : top
    recompute()
  }, [count, estimate, recompute])

  return {
    ...range,
    attach,
    measure,
    scrollToIndex,
    /** Blank space standing in for the rows above and below the window, so
     * the scrollbar reflects the whole list rather than what is rendered. */
    padTop: offsets.current[Math.min(range.start, count)] ?? 0,
    padBottom: Math.max(0, total - (offsets.current[Math.min(range.end, count)] ?? 0)),
  }
}
