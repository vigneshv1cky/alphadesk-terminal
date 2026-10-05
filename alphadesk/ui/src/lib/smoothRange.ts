import { useEffect, useRef, useState } from "react"

/** A price axis that glides to its new range instead of jumping (2026-10-05, the
 * owner: the chart jitters and is hard to focus on). Zooming or panning refits
 * the axis to the bars on screen at every step, which moved it in jumps; this
 * eases both ends toward the fitted range over a few frames. */

export interface Range { min: number; max: number }

/** One easing step: both ends move `factor` of the way toward the target, and
 * land on it once within a thousandth of its span. Non-finite numbers snap. Pure. */
export function easeRange(cur: Range, target: Range, factor: number): Range {
  if (![cur.min, cur.max, target.min, target.max].every(Number.isFinite)) return target
  const span = Math.abs(target.max - target.min) || 1
  const near = Math.abs(target.min - cur.min) < span * 0.001 && Math.abs(target.max - cur.max) < span * 0.001
  if (near) return target
  return { min: cur.min + (target.min - cur.min) * factor, max: cur.max + (target.max - cur.max) * factor }
}

/** The range to settle on: it GROWS at once to hold the target, and only SHRINKS
 * when the old range has become much larger than the target needs (2026-10-05,
 * the owner: the chart shakes). The axis used to refit to the bars on screen at
 * every step, so a small change in what was visible stretched and squeezed it.
 * Here a small move leaves the axis where it is; a large one resets it. Pure. */
export function settleRange(held: Range, target: Range, shrinkAbove = 1.35): Range {
  if (![held.min, held.max, target.min, target.max].every(Number.isFinite)) return target
  const need = target.max - target.min
  if (need <= 0) return target
  const union = { min: Math.min(held.min, target.min), max: Math.max(held.max, target.max) }
  return (union.max - union.min) > need * shrinkAbove ? target : union
}

const reduced = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches } catch { return false }
}

/** `target` eased. Snaps at once when `resetKey` changes (another symbol, range
 * or bar size is a new picture, not a movement), when `enabled` is false (a
 * scale the reader is dragging or has set by hand must follow the hand, not lag
 * it), or when the reader asks for reduced motion. */
export function useSmoothedRange(target: Range, resetKey: string, enabled: boolean): Range {
  const [cur, setCur] = useState<Range>(target)
  const curRef = useRef<Range>(target)
  const keyRef = useRef(resetKey)
  const frame = useRef(0)
  const settled = useRef<Range>(target)             // where the axis has settled, before easing
  useEffect(() => {
    if (!enabled || keyRef.current !== resetKey || reduced()) {
      keyRef.current = resetKey
      curRef.current = target
      settled.current = target
      if (enabled) setCur(target)
      return
    }
    const goal = settleRange(settled.current, target)
    settled.current = goal
    const step = () => {
      const next = easeRange(curRef.current, goal, 0.32)
      curRef.current = next
      setCur(next)
      if (next !== goal) frame.current = requestAnimationFrame(step)
    }
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [target.min, target.max, resetKey, enabled])  // eslint-disable-line react-hooks/exhaustive-deps
  return enabled ? cur : target
}
