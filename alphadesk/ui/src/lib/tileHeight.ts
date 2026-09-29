/** HOW TALL A TILE IS: A PIXEL COUNT, CHOSEN PER SCREEN BAND (2026-09-29, the
 * owner's call, replacing the shares of 2026-09-29 the same day).
 *
 * THREE SIZES, NO FIT AND NO FILL. Every tile on a board is Small, Medium or
 * Large, and each is an exact number of pixels. Nothing is measured from the
 * page, so a tile's height does not depend on what sits above it, what has
 * finished loading, where the page was scrolled, or when the measurement
 * happened to run — which is every cause of every height that moved under a
 * reader today.
 *
 * WHY NOT A SHARE OF THE SCREEN, which is what this replaces: a percentage is
 * still a measurement of the window, so it changes continuously as the window
 * changes and the same named size is a different number of pixels on every
 * screen. The owner's objection is the right one.
 *
 * WHY PIXELS WORK NOW WHEN THEY FAILED THREE TIMES BEFORE (260/402/620, then
 * 360/540/720, then 420/660/900): each of those was ONE number asked to serve
 * a 900px laptop and a 1,300px monitor, so Large was the entire window on one
 * and under half on the other. The missing dimension was never "pixels are
 * wrong" — it was the screen. A band per screen supplies it.
 *
 * THE BAND IS PICKED BY BOTH DIMENSIONS, the owner's call: WIDTH decides phone
 * or desktop, because a phone is a different kind of screen rather than a
 * short one, and HEIGHT decides among the rest, because the thing being chosen
 * is a height. A short wide window therefore gets short-screen heights, and a
 * phone gets phone heights whatever its length.
 *
 * Pure, and in its own file, so the table can be read and changed without
 * touching a component and so the bands are tested without a browser.
 */

export const TILE_STEPS = [1, 2, 3] as const
export type TileStep = (typeof TILE_STEPS)[number]

export type ScreenBand = "phone" | "short" | "standard" | "tall"

/** The label a reader sees for each step. */
export const STEP_LABEL: Record<TileStep, string> = { 1: "S", 2: "M", 3: "L" }
export const STEP_NAME: Record<TileStep, string> = { 1: "Small", 2: "Medium", 3: "Large" }

/** WHAT EACH SIZE IS, IN PIXELS, PER BAND — the whole tile, header included.
 *
 * The standard row is deliberately close to what the shares it replaces
 * produced at 1440x900 (350 / 528 / 664), so no existing board jumps when this
 * lands. The phone row keeps Large under a 812px phone so a tile is still
 * whole on screen. The tall row is a desktop monitor, where the old shares
 * gave 530 / 800 / 1024.
 *
 * These are the numbers to change when a size reads wrong — not a formula
 * somewhere else. */
export const TILE_PX: Record<ScreenBand, Record<TileStep, number>> = {
  phone:    { 1: 260, 2: 380, 3: 500 },
  short:    { 1: 280, 2: 400, 3: 520 },
  standard: { 1: 350, 2: 520, 3: 680 },
  tall:     { 1: 440, 2: 660, 3: 880 },
}

/** A phone is a KIND of screen, not a short one: below this width the phone
 * row applies whatever the window's length. Matches the app's own phone
 * breakpoint (lib/useNarrowViewport, index.css). */
export const PHONE_MAX_WIDTH = 640
/** Among desktops, the window's own height picks the row. */
export const SHORT_MAX_HEIGHT = 800
export const STANDARD_MAX_HEIGHT = 1100

/** Which band a window falls in. Width first, then height — see the note. */
export function bandFor(width: number, height: number): ScreenBand {
  if (width < PHONE_MAX_WIDTH) return "phone"
  if (height <= SHORT_MAX_HEIGHT) return "short"
  if (height <= STANDARD_MAX_HEIGHT) return "standard"
  return "tall"
}

/** The tile height a step means on this window, in pixels. */
export function tilePx(step: TileStep, width: number, height: number): number {
  return TILE_PX[bandFor(width, height)][step]
}

/** THE STEP A TILE HAS WHEN ITS LAYOUT DOES NOT NAME ONE.
 *
 * With Fit gone every tile must have a size, so a layout saved before this —
 * and every tile a reader has never touched — needs one. Medium, because it is
 * the middle of the three and because it is closest to the height those tiles
 * had under the shares it replaces. A panel may still declare a FLOOR
 * (`minStep`), which is how the chart refuses to be drawn small. */
export const DEFAULT_STEP: TileStep = 2

/** The step to render for a saved entry: the one it names, or the default,
 * never below the panel's own floor. */
export function stepFor(named: number | null | undefined, floor?: number | null): TileStep {
  const base = (TILE_STEPS as readonly number[]).includes(named ?? 0) ? (named as TileStep) : DEFAULT_STEP
  const lifted = floor ? Math.max(base, floor) : base
  return Math.min(3, Math.max(1, lifted)) as TileStep
}
