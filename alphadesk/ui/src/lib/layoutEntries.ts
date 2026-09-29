/** A board layout string, read and written (2026-09-15).
 *
 * `?tiles=` names the visible panels in render order, `id` or `id:span`.
 * A layout that named ONLY the visible panels could not tell a panel the
 * reader hid from one the page added after the layout was saved, so every
 * panel shipped later stayed hidden behind any saved layout (the Analysis
 * page's Price performance and Key statistics behind a three-panel layout
 * saved when the page had three). So a layout now also names what the
 * reader hid, as `-id`, and a panel it names neither way is NEW: it shows,
 * next to the panel it follows on the page.
 *
 * Layouts saved before hidden panels were recorded read the same way, so
 * whatever they left out shows once; the next edit records the hides.
 *
 * Pure, so it is tested without a page. */

/** Where a tile narrower than the row sits in it (2026-09-18): left is the
 * grid's own flow and is not written; `@c` centres it, `@r` puts it right. */
export type TileAlign = "center" | "right"

/** HOW TALL A TILE IS (2026-09-29, the owner: "include height customization
 * too in customize board").
 *
 * This REVERSES a stated call — "heights stay uniform on purpose; the board
 * reads as composed because its bottom edge is straight" — taken with the
 * trade in view: a chart and a news list side by side want different heights,
 * and a straight bottom edge was buying tidiness at the cost of the
 * arrangement actually wanted.
 *
 * Steps rather than free pixels, because a free number invites a board of 41
 * different heights and the point is a composed board, not a ransom note.
 * WHAT a step is worth in pixels is lib/tileHeight, per screen band; this file
 * only carries how it is written down.
 *
 * THERE IS NO FILL AND NO FIT (2026-09-29, the owner: first "remove fill in
 * customize, it just cause confusions", then "I am also thinking of removing
 * fill since its also a percentage"). Both were window-relative, which is the
 * property that made a tile's height depend on measuring the page — the cause
 * of every height that moved under a reader that day. Three fixed sizes have
 * no such input. A layout that still names an old step, or none at all, gets
 * the default (lib/tileHeight): an unreadable step is DROPPED rather than
 * clamped, because a step this build does not know came from a deployment
 * with more of them, and the tile's own default is a better answer than the
 * nearest one we happen to have. */
export const TILE_HEIGHT_STEPS = [0, 1, 2, 3, 4] as const
export type TileHeight = (typeof TILE_HEIGHT_STEPS)[number]

export type LayoutEntry = {
  id: string
  span: number | null
  align?: TileAlign | null
  height?: TileHeight | null
}

export type LayoutPanel = { id: string; optIn?: boolean }

/** `id`, `id:span`, either with `@c` or `@r` for its place in the row, and
 * `~0`–`~4` for its height (XS to XL); a span is 3–12 grid columns.
 *
 * The height is read LAST so it may follow either form — `id~3`, `id:6~3`
 * and `id:6@c~3` all parse — and an unreadable step is dropped rather than
 * clamped, because a step this build does not know is a link from a
 * deployment with more of them, and the tile's own default is a better answer
 * than the nearest one we happen to have. */
function parseEntry(s: string): LayoutEntry | null {
  const [rest, rawHeight] = s.trim().split("~")
  const [body, at] = rest.split("@")
  const [id, rawSpan] = body.split(":")
  if (!id) return null
  const n = rawSpan ? parseInt(rawSpan, 10) : NaN
  const h = rawHeight ? parseInt(rawHeight, 10) : NaN
  const align: TileAlign | null = at === "c" ? "center" : at === "r" ? "right" : null
  const height = (TILE_HEIGHT_STEPS as readonly number[]).includes(h) ? (h as TileHeight) : null
  return {
    id,
    span: Number.isFinite(n) ? Math.max(3, Math.min(12, n)) : null,
    ...(align ? { align } : {}),
    ...(height != null ? { height } : {}),
  }
}

/** The visible entries a layout string names (known panels only, first
 * mention wins) and every id it marks hidden, known or not. */
export function parseLayout(raw: string, all: LayoutPanel[]): { visible: LayoutEntry[]; hidden: Set<string> } {
  const known = new Set(all.map(p => p.id))
  const seen = new Set<string>()
  const visible: LayoutEntry[] = []
  const hidden = new Set<string>()
  for (const part of raw.split(",")) {
    const s = part.trim()
    if (s.startsWith("-")) {
      if (s.length > 1) hidden.add(s.slice(1))
      continue
    }
    const e = parseEntry(s)
    if (e && known.has(e.id) && !seen.has(e.id)) {
      seen.add(e.id)
      visible.push(e)
    }
  }
  return { visible, hidden }
}

/** What a saved layout renders. Empty means the page's default board: no
 * layout, or none of its panels exist here.
 *
 * With `addNew`, a default panel (not opt-in) the layout neither shows nor
 * hides is inserted after the nearest panel before it in page order, or
 * first. A reader-built view passes false: it is a hand-picked set, and a
 * new tile joining it would be the app choosing for the reader. */
export function resolveLayout(raw: string, all: LayoutPanel[], addNew: boolean): LayoutEntry[] {
  const { visible, hidden } = parseLayout(raw, all)
  if (!visible.length || !addNew) return visible
  const out = [...visible]
  all.forEach((p, i) => {
    if (p.optIn || hidden.has(p.id) || out.some(e => e.id === p.id)) return
    let at = 0
    for (let j = i - 1; j >= 0; j--) {
      const k = out.findIndex(e => e.id === all[j].id)
      if (k >= 0) { at = k + 1; break }
    }
    out.splice(at, 0, { id: p.id, span: null })
  })
  return out
}

/** The layout string for `visible`. With `recordHidden`, every default
 * panel not shown is written as `-id`, and so is every hidden id `keep`
 * carries that this page does not know (a link from a deployment with a
 * panel this one lacks keeps its hide). */
export function serializeLayout(
  visible: LayoutEntry[], all: LayoutPanel[], recordHidden: boolean, keep: Set<string> = new Set(),
): string {
  const parts = visible.map(e =>
    `${e.span ? `${e.id}:${e.span}` : e.id}`
    + `${e.align === "center" ? "@c" : e.align === "right" ? "@r" : ""}`
    // `!= null`: Extra small is step 0, and truthiness dropped it silently.
    + `${e.height != null ? `~${e.height}` : ""}`)
  if (recordHidden) {
    const shown = new Set(visible.map(e => e.id))
    const known = new Set(all.map(p => p.id))
    for (const p of all) if (!p.optIn && !shown.has(p.id)) parts.push(`-${p.id}`)
    for (const id of keep) if (!known.has(id)) parts.push(`-${id}`)
  }
  return parts.join(",")
}
