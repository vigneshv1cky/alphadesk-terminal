import { AlignCenter, AlignLeft, AlignRight } from "lucide-react"
import type { TileAlign, TileHeight } from "@/lib/layoutEntries"
import { useState } from "react"
import { Btn, TILE_HEIGHT_PX } from "@/components/terminal"
import { WidgetLibraryDialog } from "@/components/WidgetLibrary"
import type { LayoutApi, PanelDef } from "@/lib/boardLayout"

/** Compose the Markets board — show, hide, reorder and WIDTH its tiles.
 *
 * Closed, this is one ghost button on a slim right-aligned row; the board
 * pays no chrome for a feature most sessions never touch. Open, it is a
 * bordered strip listing every registered tile: the visible ones first in
 * render order with reorder arrows, the hidden ones dimmed after them. No
 * drag-and-drop — two arrows are keyboard-reachable, undoable and need no
 * dependency.
 *
 * The layout itself lives in ?tiles= (lib/boardLayout), so the URL with a
 * customized board IS the saved layout — copy it, share it, bookmark it.
 * The last visible tile has no Hide control: the board is never empty, the
 * same deal the symbol strip's lone chip makes.
 */
/** The width presets, in grid columns of 12. "Auto" hands the tile back to
 * its component's own span — the only place a tile's default is defined. */
const WIDTHS: { label: string; span: number | null }[] = [
  { label: "auto", span: null },
  { label: "⅓", span: 4 },
  { label: "½", span: 6 },
  { label: "⅔", span: 8 },
  { label: "full", span: 12 },
]

/** HOW TALL A TILE MAY GROW (2026-09-29). "Auto" is the tile's own default
 * and is what every board saved before this holds, so an unedited board does
 * not move. "Fill" is the viewport envelope the tall tiles already use.
 *
 * Steps, not pixels: a free number invites a board of 41 different heights,
 * and the point is a composed board. This reverses "heights stay uniform on
 * purpose" (lib/boardLayout) — taken by the owner, because a chart and a news
 * list side by side want different heights and a straight bottom edge was
 * buying tidiness at the cost of the arrangement actually wanted. */
/** The same field the news toolbar's pickers use, so a control that picks
 * one of a few named values looks the same wherever it appears. */
const pickerCls = "h-[28px] w-[92px] border border-border bg-panel px-1.5 text-caption text-foreground"

const HEIGHTS: { label: string; height: TileHeight | null; why: string }[] = [
  { label: "auto", height: null, why: "grows with its content, to the foot of the window" },
  // THE PIXELS COME FROM THE TABLE, NOT FROM A COPY OF IT (2026-09-29, the
  // owner spotting a stale tooltip). These said 260 / 402 / 620 while the
  // steps were 360 / 540 / 720 — the numbers moved three times in an hour and
  // a hand-written label cannot be expected to follow. Read from the same
  // constant the layout uses, so the two cannot disagree again.
  ...([1, 2, 3] as const).map((h, i) => ({
    label: ["S", "M", "L"][i],
    height: h as TileHeight,
    why: `${["short", "medium", "tall"][i]} — ${TILE_HEIGHT_PX[h]}px tall`,
  })),
]

/** A tile's place in its row when it is narrower than the row. */
const PLACES: { label: string; align: TileAlign | null; Icon: typeof AlignLeft }[] = [
  { label: "Left", align: null, Icon: AlignLeft },
  { label: "Centre", align: "center", Icon: AlignCenter },
  { label: "Right", align: "right", Icon: AlignRight },
]

export function BoardEditor({ layout, title, defaultOpen = false, open: openProp, onOpenChange, doneLabel = "Done" }: {
  layout: LayoutApi<PanelDef>
  /** The tab's name, as a heading at the top of the board — the reader's
   * bearing on a page whose tiles look alike from view to view
   * (2026-09-12). */
  title?: string
  /** The create-a-view flow lands here with the editor already open, so
   * picking tiles flows straight into ordering and widths. */
  defaultOpen?: boolean
  /** Controlled open — a page that owns a Widgets button passes these. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** The close button's word. The board tabs say Done (the URL already IS
   * the save); a custom view says Save, and its page flushes on close. */
  doneLabel?: string
}) {
  const [openState, setOpenState] = useState(defaultOpen)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const open = openProp ?? openState
  const setOpen = (v: boolean) => (onOpenChange ? onOpenChange(v) : setOpenState(v))
  const { items, isCustom, move, setSpan, setAlign, setHeight, applyIds, reset } = layout

  if (!open) {
    return (
      <div className="mb-2 flex items-center justify-between gap-3">
        {title ? <h1 className="text-emph font-extrabold tracking-tight">{title}</h1> : <span />}
        <Btn variant="ghost" onClick={() => setOpen(true)} aria-expanded={false}>
          Customize board{isCustom ? " · custom" : ""}
        </Btn>
      </div>
    )
  }

  return (
    // Capped width: full-board rows left a void between the label and the
    // right-aligned controls. Three quarters of the board, centred (the
    // owner's call, 2026-09-18; it was a 560px column against the left
    // edge); the full width below 768px, where a quarter is too much to give.
    // data-slot="widget" for the CENTRAL radius rule — components write no
    // rounded classes; the slot is what earns the soft corners and the clip.
    <div data-slot="widget" className="mx-auto mb-3 w-full border border-card-border bg-card shadow-card md:w-3/4">
      {/* Wrapping, not fixed-height: on a phone the title plus three buttons
          exceed the panel and would bleed past its border. */}
      <div className="flex min-h-[40px] flex-wrap items-center gap-2 border-b border-row-rule px-2.5 py-2.5">
        <span className="text-label font-medium uppercase tracking-caps">Board layout</span>
        <span className="min-w-0 flex-1" />
        {isCustom && <Btn variant="ghost" onClick={reset}>Reset to default</Btn>}
        <Btn onClick={() => setLibraryOpen(true)}>Widgets</Btn>
        <Btn onClick={() => setOpen(false)}>{doneLabel}</Btn>
      </div>
      {libraryOpen && (
        <WidgetLibraryDialog
          title="Board widgets"
          submitLabel="Save"
          initialIds={items.map(i => i.def.id)}
          options={layout.all}
          onClose={() => setLibraryOpen(false)}
          onSubmit={(_name, ids) => { applyIds(ids); setLibraryOpen(false) }}
        />
      )}
      {/* TARGETS, not styling (2026-09-21, the owner: "difficult to press").
          Ten controls a row across eleven rows, each 24px tall with 8px of
          padding — the arrows were barely wider than the glyph inside them.
          Every control here is now the 28px size the system already has for
          a field or a chip, the arrows and the place icons are square at it,
          and the width presets carry a floor so "⅓" is not a sliver beside
          "full". The look is untouched. */}
      {/* TEN BUTTONS A ROW WAS A WALL (2026-09-29, the owner: "looks a lot
          messy"). Adding the height group doubled the presets to ten
          near-identical chips with no cue where one group ended and the next
          began — fifteen controls a row across eleven rows. Width and height
          are one choice each, so they are ONE PICKER each, the same control
          the news toolbar uses. Place stays as icons: three glyphs read
          faster than a menu naming them, and they are a different kind of
          choice. Columns are headed, so nothing has to be guessed from
          position. */}
      {/* 32px, the height the system gives a TABLE ROW — this is one, and at
          23px it sat squashed against the bar above it. */}
      <div className="hidden min-h-[32px] items-center gap-2 border-b border-row-rule px-2.5 text-label uppercase tracking-caps text-muted-foreground md:flex">
        <span className="min-w-[120px] flex-1">Tile</span>
        <span className="w-[64px] text-center">Move</span>
        <span className="w-[92px]">Width</span>
        <span className="w-[92px]">Height</span>
        <span className="w-[96px] text-center">Place</span>
      </div>
      <ul className="px-2.5 py-2">
        {items.map(({ def: w, span, align, height }, i) => (
          <li key={w.id} className="row-rule flex min-h-[44px] flex-wrap items-center gap-x-2 gap-y-2 py-2.5">
            {/* The label takes the slack and the controls sit flush right —
                a fixed label column left the row's right half empty once
                Hide was removed. */}
            <span className="min-w-[120px] flex-1 truncate text-caption font-semibold">{w.label}</span>
            <span className="flex w-[64px] items-center justify-center gap-2">
              <Btn variant="ghost" size="lg" icon disabled={i === 0}
                   onClick={() => move(w.id, -1)} aria-label={`Move ${w.label} up`}>▲</Btn>
              <Btn variant="ghost" size="lg" icon disabled={i === items.length - 1}
                   onClick={() => move(w.id, 1)} aria-label={`Move ${w.label} down`}>▼</Btn>
            </span>
            <select value={span ?? ""} aria-label={`Width of ${w.label}`}
                    onChange={e => setSpan(w.id, e.target.value ? Number(e.target.value) : null)}
                    title="How many of the row's twelve columns this tile takes"
                    className={pickerCls}>
              {WIDTHS.map(o => (
                <option key={o.label} value={o.span ?? ""}
                        title={o.span ? `${o.span} of 12 columns` : "the tile's own width"}>{o.label}</option>
              ))}
            </select>
            {/* HOW TALL IT MAY GROW (2026-09-29). Beside the width, because
                the two are one question — how much room does this tile get —
                and a reader setting one usually wants the other. */}
            <select value={height ?? ""} aria-label={`Height of ${w.label}`}
                    onChange={e => setHeight(w.id, e.target.value ? Number(e.target.value) as TileHeight : null)}
                    title="How tall this tile may grow"
                    className={pickerCls}>
              {HEIGHTS.map(o => (
                <option key={o.label} value={o.height ?? ""} title={o.why}>{o.label}</option>
              ))}
            </select>
            {/* Where a tile narrower than its row sits (2026-09-18): left is
                the grid's own flow; a full-width tile has nowhere to move. */}
            <span className="flex w-[96px] items-center justify-center gap-1.5" role="group"
                  aria-label={`Place of ${w.label} in its row`}>
              {PLACES.map(o => (
                <Btn key={o.label} variant="ghost" size="lg" icon active={(align ?? null) === o.align}
                     disabled={span === 12}
                     onClick={() => setAlign(w.id, o.align)}
                     aria-label={`${o.label}: ${w.label}`} title={span === 12 ? "a full-width tile fills its row" : o.label}>
                  <o.Icon className="h-[13px] w-[13px]" aria-hidden="true" />
                </Btn>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
