/** X'S ADVERTISING PIXEL, ON THE FRONT PAGE AND NOWHERE ELSE (2026-09-26).
 *
 * The owner runs an X campaign pointing at this site and wants to know
 * whether it brings anyone. This is the third-party script that answers it.
 *
 * SCOPED ON PURPOSE. It loads from the landing page only — not from the
 * terminal, not from the legal pages, not from About. An advertisement lands
 * on "/", so that is the only page where the measurement means anything,
 * and confining it there keeps a claim the product actually sells on: once
 * you are signed in, AlphaDesk loads no third-party scripts at all. The
 * Privacy Policy says exactly this; if this file ever moves, that paragraph
 * has to move with it.
 *
 * A SERVER-SIDE ALTERNATIVE EXISTS and was weighed: X's Conversions API
 * takes the same events over HTTP from our own backend, with no script in
 * anyone's browser and no cookies, identified by the `twclid` that X itself
 * puts in the ad's URL. It keeps every privacy claim intact. The owner chose
 * the pixel; this note is here so the swap is a decision rather than a
 * rediscovery.
 *
 * SELF-HOSTED COPIES GET NOTHING. The id is baked in for the operator's own
 * deployment, and the script is only ever injected for the host this site
 * runs on — a fork serving the same code from its own domain will not fire
 * somebody else's advertising pixel.
 */

const PIXEL_ID = "rfhrv"

/** The hosts this pixel may load on: the operator's own deployment. Anyone
 * self-hosting serves the same bundle from a different host and gets no
 * third-party script at all. */
const OPERATOR_HOSTS = ["alphadesk-764298799571.us-east4.run.app"]

let loaded = false

export function loadAdPixel() {
  if (loaded || typeof document === "undefined") return
  if (!OPERATOR_HOSTS.includes(window.location.hostname)) return
  // Respect the browser's own request not to be tracked where it makes one.
  if (navigator.doNotTrack === "1") return
  loaded = true

  // X's snippet, written out rather than eval'd from a minified blob so the
  // next reader can see exactly what it does: define the queue, load the
  // tag, configure the pixel.
  type Twq = {
    (...args: unknown[]): void
    queue: unknown[]
    version: string
    exe?: (...args: unknown[]) => void
  }
  const w = window as unknown as { twq?: Twq }
  if (!w.twq) {
    const queue: unknown[] = []
    const twq = ((...args: unknown[]) => {
      if (twq.exe) twq.exe(...args)
      else queue.push(args)
    }) as Twq
    twq.queue = queue
    twq.version = "1.1"
    w.twq = twq
    const tag = document.createElement("script")
    tag.async = true
    tag.src = "https://static.ads-twitter.com/uwt.js"
    document.head.appendChild(tag)
  }
  w.twq("config", PIXEL_ID)
}
