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
 * WHAT IS MEASURED: the press of an internal link, to the route changing,
 * to the next two animation frames — which is the first moment the new page
 * has actually been painted. That is the span the reader experiences, not
 * a synthetic render timing.
 *
 * WHAT IS SENT: a page name and three millisecond counts. No symbols, no
 * query, no identifiers — nothing that says anything about the reader
 * beyond how long their browser took.
 *
 * REMOVE THIS once the lag is understood. It is diagnostic scaffolding, not
 * telemetry: there is no consent flow for it because it collects nothing
 * about a person, and it should not outlive the question it answers.
 */

export type NavSample = { to: string; clickToRoute: number; routeToPaint: number; total: number }

let pressedAt = 0
let pressedTo = ""
const queue: NavSample[] = []
let flushing: number | null = null

let watching = false

/** One listener for every internal link, rather than touching each one. */
export function watchNavPresses() {
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
}

/** Called when the router has settled on a new path. */
export function noteRouteChange(path: string) {
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
    const done = performance.now()
    queue.push({
      to,
      clickToRoute: Math.round(routedAt - started),
      routeToPaint: Math.round(done - routedAt),
      total: Math.round(done - started),
    })
    if (queue.length > 40) queue.splice(0, queue.length - 40)
    schedule()
  }))
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
