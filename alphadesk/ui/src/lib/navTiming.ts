/** HOW LONG A PAGE TAKES, MEASURED WHERE THE READER IS (2026-09-25, #78).
 *
 * TEMPORARY. The reader reported "when pressing and changing the tabs
 * quickly, there is a noticable lag" and it could not be measured from the
 * agent's side at all: the automation browser reports its tab hidden, which
 * throttles timers to ~1000ms and pauses frame callbacks, so every reading
 * came back either a flat 1000ms or wild noise. Rather than report a number
 * nobody should trust, the app measures itself on the machine that feels
 * the lag.
 *
 * THREE MOMENTS, NOT TWO (extended 2026-09-25 after the first twelve
 * presses). The first round measured the press, the route change and the
 * first paint, and reported a median of 175ms — reassuring, and possibly
 * beside the point, because A PAGE THAT PAINTS ITS FRAME INSTANTLY AND THEN
 * SITS EMPTY FOR TWO SECONDS SCORED AS FAST. Lag that is felt as "it came
 * up but there was nothing on it" was invisible to the instrument. So a
 * fourth moment is timed: when the page's panels have stopped fetching and
 * actually hold something.
 *
 *   press → route changes → first paint → the page stops fetching
 *
 * SETTLED means the number of requests in flight reached zero and STAYED
 * there for a quiet window, and the time recorded is the moment it went
 * quiet, not the moment we noticed. A page that ripples — one panel's
 * answer starting the next panel's request — must not be called finished
 * during the gap between them.
 *
 * EVERY PRESS YIELDS EXACTLY ONE SAMPLE, whatever happens to it. Pressing
 * away mid-load, or hiding the tab, finalises what was measured and marks
 * it left rather than discarding it: a page abandoned before it filled is
 * evidence about the wait, not an absence of evidence. A page still
 * fetching at the cap is marked slow and kept for the same reason.
 *
 * WHAT IS SENT: a page name, four millisecond counts and one word for how
 * it ended. No symbols, no query, nothing about the reader.
 *
 * REMOVE THIS once the lag is understood. It is diagnostic scaffolding, not
 * telemetry: there is no consent flow for it because it collects nothing
 * about a person, and it should not outlive the question it answers.
 */

export type NavSample = {
  to: string
  clickToRoute: number
  routeToPaint: number
  total: number
  /** Press to the moment the page stopped fetching. 0 when it never did. */
  settleMs: number
  /** settled | left | slow — how the measurement ended. */
  settle: "settled" | "left" | "slow"
  /** The most requests in flight at once during this press, and how many
   * were STILL in flight when it ended. Cycling pages faster than they can
   * fill is exactly a pile-up of abandoned requests, so if that is what the
   * lag is, it is these two numbers that will say so. */
  peakInflight: number
  leftInflight: number
}

/** In-flight request count, handed in from the app so this module needs no
 * opinion about how data is fetched. */
type Fetching = { isFetching: () => number; subscribe: (cb: () => void) => () => void }

/** Zero in flight must HOLD this long to count as finished. A page whose
 * panels fetch in waves goes quiet for a moment between them. */
const QUIET_MS = 300
/** Past this the page is not going to settle, and saying so is the answer. */
const CAP_MS = 20000

let pressedAt = 0
let pressedTo = ""
let fetching: Fetching | null = null
const queue: NavSample[] = []
let flushing: number | null = null

/** The press being measured right now, from paint until it finishes. */
type Pending = {
  to: string
  started: number
  clickToRoute: number
  routeToPaint: number
  quietTimer: number | null
  capTimer: number | null
  stop: (() => void) | null
  done: boolean
  peak: number
}
let pending: Pending | null = null

let watching = false

/** One listener for every internal link, rather than touching each one. */
export function watchNavPresses(source?: Fetching) {
  if (source) fetching = source
  if (typeof document === "undefined") return
  // Development mounts every effect twice, and a second listener would
  // record every press twice — doubling the sample count while leaving each
  // number looking perfectly reasonable, which is the worst way for an
  // instrument to be wrong.
  if (watching) return
  watching = true
  document.addEventListener("click", e => {
    const a = (e.target as HTMLElement | null)?.closest?.("a")
    const href = a?.getAttribute("href")
    if (!href || !href.startsWith("/") || a!.getAttribute("target") === "_blank") return
    pressedAt = performance.now()
    pressedTo = href.split("?")[0]
  }, true)
  // A tab put away stops painting and stops being waited on, so whatever is
  // half-measured is finalised rather than left to time out against a clock
  // the browser is no longer running honestly.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") finish("left")
  })
}

/** Called when the router has settled on a new path. */
export function noteRouteChange(path: string) {
  // A second press before the first page filled ends the first measurement
  // where it stood. That is the case the reader described, so it is the one
  // case that must not be thrown away.
  finish("left")
  if (!pressedAt) return
  const started = pressedAt, to = pressedTo || path
  const routedAt = performance.now()
  pressedAt = 0
  // Two frames: the first schedules the paint, the second runs after it.
  //
  // A HIDDEN TAB RECORDS NOTHING, deliberately. Frame callbacks are paused
  // when a tab is in the background, so a press made there is simply never
  // completed — which is correct, because no paint happened and there was
  // no wait for anyone to feel. It is also the exact trap that made this
  // instrument necessary, so it is worth saying out loud: a measurement
  // taken in a background tab is not a small measurement, it is no
  // measurement at all.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const painted = performance.now()
    // Two presses inside one frame reach their frame callbacks in order,
    // so the earlier one is still current here. Close it as left rather
    // than overwriting it, or it survives only as its own timeout twenty
    // seconds later and reports as never settling.
    finish("left")
    pending = {
      to,
      started,
      clickToRoute: Math.round(routedAt - started),
      routeToPaint: Math.round(painted - routedAt),
      quietTimer: null,
      capTimer: null,
      stop: null,
      done: false,
      peak: fetching?.isFetching() ?? 0,
    }
    watchUntilQuiet(pending)
  }))
}

/** Wait for the page's panels to stop asking for things. */
function watchUntilQuiet(p: Pending) {
  if (!fetching) { finish("settled", p, p.started + p.clickToRoute + p.routeToPaint); return }
  p.capTimer = window.setTimeout(() => finish("slow", p), CAP_MS)
  const check = () => {
    if (p.done) return
    const n = fetching!.isFetching()
    if (n > p.peak) p.peak = n
    if (n > 0) {
      // Something is in flight again: whatever quiet we had did not hold.
      if (p.quietTimer != null) { clearTimeout(p.quietTimer); p.quietTimer = null }
      return
    }
    if (p.quietTimer != null) return
    // The page went quiet HERE. If it stays quiet, this is the moment that
    // counts — not the moment the confirming timer happens to fire.
    const quietAt = performance.now()
    p.quietTimer = window.setTimeout(() => finish("settled", p, quietAt), QUIET_MS)
  }
  p.stop = fetching.subscribe(check)
  check()
}

/** Record a press, however it ended, and send it on.
 *
 * A TIMER FINALISES THE PRESS IT BELONGS TO, never "whatever is current".
 * Two presses inside one frame can start the second before the first has
 * reached its frame callback, leaving the first's 20-second timer running
 * with the second's measurement in hand — and it would have stamped the
 * second press as never settling, twenty seconds after the reader had
 * moved on. Cycling pages quickly is the case being measured here, so the
 * race is not hypothetical.
 */
function finish(how: NavSample["settle"], target?: Pending, quietAt?: number) {
  const p = target ?? pending
  if (!p || p.done) return
  p.done = true
  if (pending === p) pending = null
  if (p.quietTimer != null) clearTimeout(p.quietTimer)
  if (p.capTimer != null) clearTimeout(p.capTimer)
  p.stop?.()
  const end = how === "settled" ? (quietAt ?? performance.now()) : performance.now()
  queue.push({
    to: p.to,
    clickToRoute: p.clickToRoute,
    routeToPaint: p.routeToPaint,
    total: p.clickToRoute + p.routeToPaint,
    settleMs: Math.round(end - p.started),
    settle: how,
    peakInflight: p.peak,
    leftInflight: how === "settled" ? 0 : (fetching?.isFetching() ?? 0),
  })
  if (queue.length > 40) queue.splice(0, queue.length - 40)
  schedule()
}

function schedule() {
  if (flushing != null) return
  // Batched, so a burst of tab presses is one request rather than six.
  flushing = window.setTimeout(() => {
    flushing = null
    const batch = queue.splice(0, queue.length)
    if (!batch.length) return
    void fetch("/api/perf/nav", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples: batch }),
      keepalive: true,
    }).catch(() => {})
  }, 3000)
}
