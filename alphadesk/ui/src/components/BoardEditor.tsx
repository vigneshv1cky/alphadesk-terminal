import { AlignCenter, AlignLeft, AlignRight } from "lucide-react"
import type { TileAlign } from "@/lib/layoutEntries"
import { useState } from "react"
import { Btn } from "@/components/terminal"
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
  const { items, isCustom, move, setSpan, setAlign, applyIds, reset } = layout

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
      <ul className="px-2.5 py-2">
        {items.map(({ def: w, span, align }, i) => (
          <li key={w.id} className="row-rule flex min-h-[44px] flex-wrap items-center gap-x-2 gap-y-2 py-2.5">
            {/* The label takes the slack and the controls sit flush right —
                a fixed label column left the row's right half empty once
                Hide was removed. */}
            <span className="min-w-[120px] flex-1 truncate text-caption font-semibold">{w.label}</span>
            <Btn variant="ghost" size="lg" icon disabled={i === 0}
                 onClick={() => move(w.id, -1)} aria-label={`Move ${w.label} up`}>▲</Btn>
            <Btn variant="ghost" size="lg" icon disabled={i === items.length - 1}
                 onClick={() => move(w.id, 1)} aria-label={`Move ${w.label} down`}>▼</Btn>
            <span className="ml-2 flex items-center gap-1.5" role="group"
                  aria-label={`Width of ${w.label}`}>
              {WIDTHS.map(o => (
                <Btn key={o.label} variant="ghost" size="lg" active={span === o.span}
                     className="min-w-[40px]"
                     onClick={() => setSpan(w.id, o.span)}
                     title={o.span ? `${o.span} of 12 columns` : "the tile's own width"}>
                  {o.label}
                </Btn>
              ))}
            </span>
            {/* Where a tile narrower than its row sits (2026-09-18): left is
                the grid's own flow; a full-width tile has nowhere to move. */}
            <span className="ml-2 flex items-center gap-1.5" role="group"
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
