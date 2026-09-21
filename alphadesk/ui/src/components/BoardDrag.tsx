import React from "react"

/** MOVING AND SIZING TILES BY DRAGGING THEM (2026-09-21).
 *
 * This was built once before, shipped, and reverted the same day. The revert
 * said why: "the list editor read better than overlays on every tile". The
 * objection was the CHROME, not the gesture — an edit mode that put handles,
 * outlines and a hide corner on every tile turned a board you read into a
 * form you operate.
 *
 * So there is no edit mode and no chrome here. A board is always draggable,
 * and when nothing is being dragged it looks exactly as it did:
 *
 *   * the tile's own HEADER is the handle — it already exists, so nothing is
 *     added to carry the gesture; the cursor is the only hint, and only on
 *     hover;
 *   * the right EDGE is a six-pixel seam that resizes, the same gesture the
 *     chart's pane dividers already use and nobody objected to — a seam has
 *     one degree of freedom and cannot be dropped in the wrong place;
 *   * while a drag is live, one accent line marks where the tile would land.
 *     Nothing else changes.
 *
 * The list editor stays. Dragging is for arranging by eye; the list is for
 * saying exactly twelve columns, and for a reader who would rather not drag
 * anything. They write to the same layout, which is still order plus width
 * in the URL, so a shared link is unaffected by which one was used.
 */

export type BoardDragApi = {
  /** Attach to the `.collage` element: the grid is measured for a resize. */
  gridRef: React.RefObject<HTMLDivElement | null>
  /** Pointer-down on a tile header. */
  grab: (id: string, e: React.PointerEvent) => void
  /** Pointer-down on a tile's right seam. */
  startResize: (id: string, e: React.PointerEvent) => void
  /** The tile being carried, so it can draw as lifted. */
  dragging: string | null
  /** The tile the drop line sits BEFORE, while a drag is live. */
  dropBefore: string | null
  /** Set instead when the drop is past the last tile, naming that tile so
   * the line can be drawn on its far side. */
  dropAfter: string | null
}

export const BoardDragContext = React.createContext<BoardDragApi | null>(null)
/** The tile a slot holds, so its Widget can name itself to the drag layer. */
export const TileId = React.createContext<string | null>(null)

export function useTileDrag() {
  const api = React.useContext(BoardDragContext)
  const id = React.useContext(TileId)
  return api && id ? { api, id } : null
}

/** How far the pointer must travel before a press on a header becomes a
 * drag. Below this it is a click, and headers hold buttons. */
const DRAG_SLOP = 6
const COLUMNS = 12
const GRID_GAP = 16
const MIN_SPAN = 3

type Layout = {
  ids: string[]
  spanOf: (id: string) => number
  moveTo: (id: string, to: number) => void
  setSpan: (id: string, span: number | null) => void
}

/** The board's drag behaviour, for a page that composes tiles. */
export function useBoardDrag(layout: Layout, enabled = true): BoardDragApi {
  const gridRef = React.useRef<HTMLDivElement | null>(null)
  const [dragging, setDragging] = React.useState<string | null>(null)
  const [dropAt, setDropAt] = React.useState<number | null>(null)
  // The live gesture, off React state: a pointermove must not wait for a
  // render to know what it is doing.
  const gesture = React.useRef<
    | { kind: "grab"; id: string; x: number; y: number; live: boolean }
    | { kind: "resize"; id: string; x: number; span: number; col: number }
    | null
  >(null)

  /** Where the pointer says the tile would land, counted in the board as it
   * looks NOW — the index before the dragged tile is taken out. */
  const dropIndex = React.useCallback((clientX: number, clientY: number) => {
    const grid = gridRef.current
    if (!grid) return null
    const tiles = [...grid.querySelectorAll<HTMLElement>("[data-tile-id]")]
    for (let i = 0; i < tiles.length; i++) {
      const box = tiles[i].getBoundingClientRect()
      if (clientY < box.bottom && clientX < box.left + box.width / 2) return i
      if (clientY < box.bottom && clientX < box.right) return i + 1
    }
    return tiles.length
  }, [])

  // The layout and the live drop index, read by the window listeners. Held
  // in refs because those listeners are bound ONCE: with the layout object
  // in the effect's dependencies — it is rebuilt every render — the board
  // would add and remove three window listeners on every keystroke
  // anywhere on the page, and a gesture in flight would lose its handlers
  // mid-drag.
  const layoutRef = React.useRef(layout)
  layoutRef.current = layout
  const dropRef = React.useRef<number | null>(null)

  const end = React.useCallback(() => {
    gesture.current = null
    dropRef.current = null
    setDragging(null)
    setDropAt(null)
  }, [])

  React.useEffect(() => {
    if (!enabled) return
    const onMove = (e: PointerEvent) => {
      const g = gesture.current
      if (!g) return
      if (g.kind === "grab") {
        if (!g.live && Math.hypot(e.clientX - g.x, e.clientY - g.y) < DRAG_SLOP) return
        if (!g.live) { g.live = true; setDragging(g.id) }
        e.preventDefault()
        const at = dropIndex(e.clientX, e.clientY)
        dropRef.current = at
        setDropAt(at)
        return
      }
      e.preventDefault()
      const moved = Math.round((e.clientX - g.x) / g.col)
      const span = Math.max(MIN_SPAN, Math.min(COLUMNS, g.span + moved))
      if (span !== layoutRef.current.spanOf(g.id)) layoutRef.current.setSpan(g.id, span)
    }
    const onUp = () => {
      const g = gesture.current
      const at = dropRef.current
      if (g?.kind === "grab" && g.live && at != null) layoutRef.current.moveTo(g.id, at)
      end()
    }
    window.addEventListener("pointermove", onMove, { passive: false })
    window.addEventListener("pointerup", onUp)
    window.addEventListener("pointercancel", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      window.removeEventListener("pointercancel", onUp)
    }
  }, [enabled, dropIndex, end])

  const grab = React.useCallback((id: string, e: React.PointerEvent) => {
    if (!enabled || e.button !== 0) return
    // A header holds buttons — the expand control, a tile's own menu. A
    // press that starts on one of them belongs to it.
    if ((e.target as Element).closest("button, a, input, select, [role='button']")) return
    gesture.current = { kind: "grab", id, x: e.clientX, y: e.clientY, live: false }
  }, [enabled])

  const startResize = React.useCallback((id: string, e: React.PointerEvent) => {
    if (!enabled || e.button !== 0) return
    const grid = gridRef.current
    if (!grid) return
    // One column plus one gap: what a tile grows by when its span goes up by
    // one. The grid's own side padding comes out of the width first.
    const col = (grid.clientWidth - 2 * GRID_GAP - GRID_GAP * (COLUMNS - 1)) / COLUMNS + GRID_GAP
    e.preventDefault()
    // The header under this grip starts a MOVE. Without stopping here, one
    // press would begin both gestures.
    e.stopPropagation()
    gesture.current = { kind: "resize", id, x: e.clientX, span: layoutRef.current.spanOf(id), col }
  }, [enabled])

  const live = dragging != null && dropAt != null
  const past = live && dropAt >= layout.ids.length
  return {
    gridRef, grab, startResize, dragging,
    dropBefore: live && !past ? (layout.ids[dropAt as number] ?? null) : null,
    dropAfter: past ? (layout.ids[layout.ids.length - 1] ?? null) : null,
  }
}
