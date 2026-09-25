import * as React from "react"
import { createPortal } from "react-dom"
import { cn } from "@/lib/utils"
import { useModalFocus, usePopoverFocus } from "@/lib/focus"

/** The terminal primitives — hand-rolled, dependency-free replacements for
 * the shadcn/ui set that used to live in components/ui/.
 *
 * Sized to match AlphaSpace after measuring it: 14px cell type and ~33px rows,
 * not the 11px/24px this used to run. Measuring was the point — the assumption
 * had been that they were denser than us, and the reverse was true, so "more
 * terminal-like" was costing legibility for nothing.
 *
 * Still no shadows: separation comes from the four surface steps in index.css,
 * which is where their board actually gets its depth. Nothing animates,
 * because motion in a data grid is noise unless it encodes a change in the
 * data.
 *
 * Primitives carry `data-slot`, the same hook they use — it names the part in
 * the DOM, which makes both theme overrides and tests target intent rather
 * than a class string that will drift. */

/* ── Sparkline: a row-scale trend, not a chart ──────────────────────────── */

/** A bare trend line sized for a table cell.
 *
 * Inline SVG rather than a charting library: at 64x18 there is no axis, no
 * scale and no interaction to justify one, and this renders dozens of times
 * per movers table. Stroke is `currentColor`, so the caller tints it with a
 * gain/loss text class and it stays correct in both themes for free.
 *
 * Renders nothing at all below two points. A single point would draw a flat
 * line, which reads as "this did not move" rather than the truth, "we do not
 * have the data" — the same distinction the chart's indicator gate makes. */
export function Sparkline({
  points, className, width = 64, height = 18, baseline = false, dot = false,
}: {
  points: number[]
  className?: string
  width?: number
  height?: number
  /** A dashed rule at the FIRST value — the level the day is measured from,
   * which is what turns a squiggle into a gain or a loss at a glance. */
  baseline?: boolean
  /** Mark where the series ends, so the latest point is findable rather than
   * being wherever the line happens to stop. */
  dot?: boolean
}) {
  if (!points || points.length < 2) {
    return <span className="inline-block" style={{ width, height }} aria-hidden="true" />
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min
  // Inset by the stroke width so the extremes are not clipped at the edges.
  const pad = 1
  const h = height - pad * 2
  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width
      // A flat series has no span to scale against. Centre it rather than
      // letting the divide-by-zero guard pin it to the floor — a line along
      // the bottom edge reads as a collapse, which is the opposite of what
      // "unchanged" means.
      const y = span === 0 ? height / 2 : pad + h - ((p - min) / span) * h
      return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const yAt = (v: number) => (span === 0 ? height / 2 : pad + h - ((v - min) / span) * h)
  const last = points[points.length - 1]
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      role="img"
      aria-label="recent trend"
    >
      {baseline && (
        <line x1={0} y1={yAt(points[0])} x2={width} y2={yAt(points[0])}
          stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" opacity={0.35}
          vectorEffect="non-scaling-stroke" />
      )}
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {dot && <circle cx={width} cy={yAt(last)} r={1.8} fill="currentColor" />}
    </svg>
  )
}

/* ── Flash: a value that just moved ─────────────────────────────────────── */

/** Must stay in step with the .flash-gain / .flash-loss rules in index.css.
 * Holding the class longer than the animation runs leaves a dead window where
 * a fresh tick cannot re-trigger it. */
const FLASH_MS = 420


/** Tint a number for a moment when it changes, green up and red down.
 *
 * The one animation in the terminal, and it earns it: the house rule is that
 * motion in a data grid is noise UNLESS it encodes a change in the data, and
 * this encodes nothing else. It became worth having when prices started
 * streaming — a figure can move while the eye is on another panel, and without
 * this the only evidence is that it now reads differently than you remember.
 *
 * Remounted per change, so the animation restarts even when two ticks land
 * back to back. That is not cosmetic: without it, a second tick in the SAME
 * direction sets `dir` to the value it already holds, React bails on identical
 * state, the class never changes and the CSS animation never re-fires. On a
 * streaming price, consecutive ticks the same way are the common case, so the
 * flash was silently skipping most of them.
 *
 * The remount key is a counter rather than the value itself, because a price
 * that ticks away and back — A to B to A — would otherwise reuse the first
 * key and swallow the second change for the same reason.
 */
export function Flash({ value, className, children }: {
  value: number | null | undefined
  className?: string
  children: React.ReactNode
}) {
  const prev = React.useRef(value)
  const [dir, setDir] = React.useState<"up" | "down" | null>(null)
  const [seq, setSeq] = React.useState(0)
  React.useEffect(() => {
    const was = prev.current
    prev.current = value
    if (typeof was !== "number" || typeof value !== "number" || was === value) return
    setDir(value > was ? "up" : "down")
    setSeq(n => n + 1)
    const t = setTimeout(() => setDir(null), FLASH_MS)
    return () => clearTimeout(t)
  }, [value])
  return (
    <span
      key={seq}
      className={cn("flash-host",
                    dir === "up" && "flash-gain", dir === "down" && "flash-loss", className)}
    >
      {children}
    </span>
  )
}

/* ── Widget: the tiled panel every surface is built from ────────────────── */

/** The widget header, which the section's minimum has to account for. */
const HEADER_H = 38
// Must match the widget-toolbar band below — this is the height the tile's
// minimum reserves for it.
const TOOLBAR_H = 40

/** The reader's width for a tile, provided by the board's layout around a
 * tile component (lib/boardLayout). Null everywhere else, so a Widget off
 * the composed board renders exactly the span its component declared. */
export const SpanOverride = React.createContext<number | null>(null)
/** Where the reader placed a tile narrower than its row (2026-09-18). */
export const AlignOverride = React.createContext<"center" | "right" | null>(null)

/** A board slot: the reader's width and place for the tile inside it. */
export function TileSlot({ span, align, children }: {
  span: number | null; align?: "center" | "right" | null; children: React.ReactNode
}) {
  return (
    <SpanOverride.Provider value={span}>
      <AlignOverride.Provider value={align ?? null}>{children}</AlignOverride.Provider>
    </SpanOverride.Provider>
  )
}

/** How tall a capped tile body may grow: the viewport less the app header,
 * the symbol strip, the page heading and the tile's own header. */
export const BODY_VIEWPORT_CAP = "calc(100vh - 190px)"

export function Widget({
  title, symbol, subtitle, actions, toolbar, toolbarWraps, span = 12, className, bodyClassName,
  scroll, minBody, fitViewport = true, children,
}: {
  title?: React.ReactNode
  /** Rendered in accent blue before the title, the way AlphaSpace prefixes a
   * widget with the symbol it is scoped to ("NVDA EQUITY OVERVIEW"). */
  symbol?: string
  subtitle?: React.ReactNode
  actions?: React.ReactNode
  /** A strip pinned between the header and the scrolling body — tab switchers,
   * filters, anything that selects WHAT the body shows.
   *
   * It cannot live in the header: at a span-4 tile the header is 278px, and
   * three tab pills beside the title overflowed it by 63px while crushing the
   * subtitle to zero width. It cannot live in the body either, because the
   * body scrolls and the control naming the current view would scroll away
   * with the rows it labels. So it gets its own row, outside the scroller. */
  toolbar?: React.ReactNode
  /** Columns to span on the 12-col `.collage` grid. Ignored off-grid. */
  span?: number
  className?: string
  bodyClassName?: string
  /** Body height. A NUMBER is a cap: the body sizes to its content and
   * scrolls only once content exceeds it, so a short tile shrinks
   * (2026-09-02). A STRING is exact — viewport-fit bodies like the earnings
   * calendar reserve their height up front. */
  scroll?: number | string
  /** A toolbar holding a DROP-DOWN wraps instead of scrolling: a scrolling
   * row is a clipping box and the menu opens inside it, invisible. */
  toolbarWraps?: boolean
  /** Reserve this many pixels of BODY height without capping it, so a tile
   * that grows into its rows does not shove the board down when they land.
   * A cap would bring back the inner scroller the board deliberately has
   * not got. */
  minBody?: number
  /** With a numeric `scroll`: let the body grow to what the viewport shows
   * before it scrolls (the default). False keeps the number as the cap — for
   * a long list the reader scans rather than reads whole, like the week's
   * 500 ex-dividends, which otherwise filled the screen (2026-09-14). */
  fitViewport?: boolean
  /** Expansion state, when the OWNER needs it. A widget whose body changes
   * shape on expand has to know — the chart grows its price pane and only
   * offers RSI/MACD once there is height to read them — and it must be the
   * same state its own toolbar button drives, or the two controls disagree
   * about whether the tile is open. Omit both and the tile expands on its own. */
  /** Opt out for a tile the header control makes no sense on. */
  children?: React.ReactNode
}) {
  // NO POPUP (2026-09-25, the owner: "remove expansion from all grids").
  // Every tile carried a ⤢ that reopened its content in a centred dialog.
  // It competed for the header with the tile's own controls — the news tile
  // had five of those beside it — and a board is already the reader's own
  // arrangement: a tile that wants more room is widened in the editor,
  // which persists, where a popup lasted until the next click. Show all
  // below remains, because that answers a different question (a record
  // taller than its cap) and leaves the tile where it is.

  // NO "SHOW ALL" EITHER (2026-09-25, the owner, on being shown what it was
  // for: "1" — remove it). It lifted a capped tile's height so a long
  // record ran in the page instead of scrolling inside the tile, and it
  // carried the SAME flaw as the popup removed beside it: local state, so
  // it did not survive a reload or leaving the page. It was a per-visit
  // gesture standing in for a board setting that does not exist — the
  // editor sizes a tile by width and place, never height — and nothing was
  // unreachable without it, because the body scrolls. Its measurement went
  // with it: every capped tile ran a ResizeObserver AND a subtree
  // MutationObserver purely to decide whether to offer the button, which on
  // a news tile is a re-measure on every headline that arrives.
  //
  // If tile HEIGHT is wanted again, it belongs in the board editor beside
  // width and place, where it would persist — not as a header control.

  const overrideSpan = React.useContext(SpanOverride)
  const align = React.useContext(AlignOverride)
  const cols = overrideSpan ?? span
  const bodyHeight = scroll
  return (
    <section
      data-slot="widget"
      // Inline gridColumn, not a Tailwind class: `col-span-${n}` is built at
      // runtime and would be purged from the stylesheet.
      // The tile's floor lives HERE, not on the body.
      //
      // A minimum on the body is a floor its content simply exceeds, so every
      // tile grew to fit everything it had — Market News rendered all sixty
      // headlines at 4,026px and nothing scrolled at all. On the section it
      // reserves the tile's normal height while leaving the body free to be a
      // fixed box that scrolls inside it, and grid stretch still lets a tall
      // neighbour hand this one extra room to fill.
      // A STRING height needs the floor just as much as a number does, and for
      // a while it did not get one. The body is `flex-1`, which is
      // `flex-basis: 0%`, and on the main axis flex-basis beats an explicit
      // height — so a tile asking for `calc(100vh - 150px)` collapsed to its
      // header. The Earnings calendar rendered 172 rows into a body 0px tall.
      // Numbers were fine only because they already reserved the space here.
      // Only a STRING height still reserves the tile's space up front — the
      // flex-basis trap in the comment above is real and the earnings
      // calendar fell into it. A numeric height is a cap on the body instead,
      // so it reserves nothing here.
      style={{
        // Centre or right: an explicit start column, so the tile sits there
        // in its row; left is the grid's own flow. A full-width tile has no
        // room to move, and the phone layout's one column overrides it.
        gridColumn: align && cols < 12
          ? `${align === "center" ? Math.floor((12 - cols) / 2) + 1 : 13 - cols} / span ${cols}`
          : `span ${cols} / span ${cols}`,
        // A FLOOR THAT DOES NOT CAP (2026-09-25, #72). A string height
        // reserves the tile's space here and always did. A tile that GROWS
        // INTO ITS ROWS reserved nothing, so it was born at header height
        // and shoved everything below it down as its rows landed: measured
        // on Markets, cumulative layout shift was 1.274 against a 0.1
        // "good" threshold, and 0.907 of that was the tiles themselves.
        // With six movers tiles answering at different moments the board
        // rearranged itself under the reader for several seconds — the same
        // complaint as the chart scroll deleted in #279, that something
        // moves out from under you.
        //
        // `minBody` reserves the height WITHOUT capping the body, which is
        // what keeps "no inner scroller, the board scrolls" intact: the
        // tile is simply born the size it is about to be.
        ...(typeof bodyHeight === "string"
          ? { minHeight: `calc(${bodyHeight} + ${HEADER_H + (toolbar ? TOOLBAR_H : 0)}px)` }
          : minBody
            ? { minHeight: `${minBody + HEADER_H + (toolbar ? TOOLBAR_H : 0)}px` }
            : {}),
      }}
      className={cn(
        "flex min-w-0 flex-col overflow-hidden border border-card-border bg-card shadow-card",
        className,
      )}
    >
      {(title || actions) && (
        <header data-slot="widget-header" className="flex h-[40px] shrink-0 items-center gap-2 border-b border-card-rule bg-card px-3">
          {symbol && (
            <span className="shrink-0 text-body font-bold tracking-ticker text-accent">{symbol}</span>
          )}
          {title && (
            // flex: none, because the panel's NAME is the one thing in this
            // row that has to survive. Two truncating flex items shrink in
            // proportion to their content, so the LONGER one wins the space:
            // Stock Movers' 78-character subtitle took 417px and left the
            // title 92px, rendering it "STOCK …". The name is how you find the
            // panel; the subtitle is a footnote about it.
            // On phones the name may truncate after all: with the subtitle
            // gone its only competitor is the tile's own controls, and a
            // clipped button is worse than a clipped word.
            <h2 className="shrink-0 whitespace-nowrap text-body font-bold uppercase tracking-caps text-foreground max-sm:min-w-0 max-sm:shrink max-sm:truncate">
              {title}
            </h2>
          )}
          {subtitle && (
            // The truncating half — flex: 1, min-width: 0. This is required,
            // not cosmetic: a long subtitle out-competed the panel's own name
            // for width once already. Carries the full text on hover.
            // Hidden on phones outright: a footnote truncated to five letters
            // says nothing and crowds the title's controls.
            <span
              title={typeof subtitle === "string" ? subtitle : undefined}
              className="hidden min-w-0 flex-1 truncate text-caption text-muted-foreground sm:inline"
            >
              {subtitle}
            </span>
          )}
          {subtitle && <div className="min-w-0 flex-1 sm:hidden" />}
          {!subtitle && <div className="min-w-0 flex-1" />}
          {actions}
        </header>
      )}
      {toolbar && (
        // 40px around 26px tabs: 7px of air each side, so the tab row sits
        // off the header's rule instead of touching it — a band tall enough
        // to read as a control strip rather than a line of chips.
        // Scrolls sideways when its controls are wider than the tile — on a
        // phone the movers tabs cut "Losers" off at the edge (2026-09-18).
        <div data-slot="widget-toolbar"
             className={cn(
               "flex shrink-0 items-center gap-1.5 border-b border-card-rule bg-card px-3",
               // A SCROLLING ROW CLIPS ITS MENU (the convention, and #77 is
               // it being broken): `overflow-x-auto` makes a clipping box,
               // so a drop-down opened from inside one is rendered outside
               // the clip and simply never appears. A toolbar that holds a
               // menu WRAPS instead, and grows rather than scrolling.
               toolbarWraps
                 ? "min-h-[40px] flex-wrap py-1"
                 : "scrollbar-none h-[40px] overflow-x-auto",
             )}>
          {toolbar}
        </div>
      )}
      <div
        // A MINIMUM plus flex, not a fixed height.
        //
        // Grid rows stretch every tile to the tallest one in the row, so the
        // moment a chart grew for its indicator panes the quote panel beside
        // it was stretched with it while its body stayed pinned at 402px —
        // three hundred pixels of empty panel below the last row of data. The
        // body now takes whatever the row gives it and scrolls inside that, so
        // the neighbour's height buys extra rows instead of blank space.
        // A numeric height is a MAX: the body is in-flow, sizes to its
        // content, and scrolls only past the cap — that is what lets a short
        // tile end where its content does instead of holding a blank band.
        // A numeric cap is the LOWER bound of the real cap (2026-09-13:
        // "reduce scrolling inside grids as much as possible"). The body
        // may grow to what the viewport can show before it scrolls, so a
        // twenty-row movers list, a dividend record or a holdings table
        // reads whole on a normal screen and only a list longer than the
        // screen scrolls inside its tile. The page scrolls instead — one
        // scrollbar rather than one per tile.
        style={typeof bodyHeight === "string" ? { height: bodyHeight }
             : typeof bodyHeight === "number"
               ? { maxHeight: fitViewport ? `max(${bodyHeight}px, ${BODY_VIEWPORT_CAP})` : `${bodyHeight}px` }
             : undefined}
        className={cn(
          "min-h-0 min-w-0",
          typeof bodyHeight === "string" && "relative flex-1",
          typeof bodyHeight === "number" && "overflow-y-auto",
          bodyClassName,
        )}
      >
        {typeof bodyHeight === "string" ? (
          // Absolutely positioned, which is the only thing that actually stops
          // the content sizing the tile.
          //
          // A grid row is auto-sized to its items' MAX-CONTENT, and that walks
          // into a flex container's children whatever their flex-basis — so
          // `flex-1` alone did not stop sixty headlines demanding 4,026px, it
          // just stopped them scrolling on the way. Taken out of flow, the
          // content contributes no height at all: the section rests on its own
          // minimum, and a taller neighbour still stretches it and gets filled
          // rather than leaving a gap.
          <div className="absolute inset-0 overflow-y-auto">{children}</div>
        ) : children}
      </div>
    </section>
  )
}

/** The overlay both modals share: the fixed layer, the backdrop that closes,
 * and — the point of pulling it out (2026-09-18) — real modality. Both used
 * to declare aria-modal to a screen reader while letting Tab walk into the
 * page behind. Mounting only while open is what lets the focus hook run on
 * every open: written inline in the widget, a hook ran once at page load. */
function ModalShell({ label, onDismiss, initial = "field", children }: {
  label: string
  onDismiss: () => void
  /** Where focus starts: the first form field (a key to type), or simply
   * the first control (a popped-out board, where the close button is it). */
  initial?: "field" | "first"
  children: React.ReactNode
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  useModalFocus(ref, initial)
  return createPortal(
    <div ref={ref} className="modal-shell fixed inset-0 z-[70] flex items-center justify-center p-5"
         role="dialog" aria-modal="true" aria-label={label}>
      <div className="absolute inset-0 bg-black/60" onClick={onDismiss} aria-hidden="true" />
      {children}
    </div>,
    document.body,
  )
}

/** A small modal dialog for a form or a confirmation — the Widget popup's
 * manners (backdrop and Escape close, 2px border, the 38px header strip) at
 * form size instead of board size. Content renders through a portal so no
 * ancestor's overflow or transform can clip it. */
export function Dialog({ title, onClose, maxWidth = "max-w-[420px]", children }: {
  title: string
  onClose: () => void
  /** A Tailwind max-w class; forms fit 420, pickers breathe at more. */
  maxWidth?: string
  children: React.ReactNode
}) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
  return (
    <ModalShell label={title} onDismiss={onClose}>
      <section data-slot="dialog" className={`relative w-full ${maxWidth} border border-card-border bg-card shadow-card`}>
        <header className="flex h-[40px] shrink-0 items-center gap-2 border-b border-card-rule bg-card px-3">
          <h2 className="min-w-0 flex-1 truncate text-body font-bold uppercase tracking-caps text-foreground">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={`Close the ${title} dialog`}
            title="Close (Esc)"
            className={btnCls({ icon: true })}
          >
            ✕
          </button>
        </header>
        {children}
      </section>
    </ModalShell>
  )
}

/** An overflow menu — the ⋯ that holds a surface's secondary actions so
 * the header keeps one visible button. Closes on pick, outside click, or
 * Escape. Items marked danger read in the loss color. */
export function OverflowMenu({ label = "More actions", items }: {
  label?: string
  items: { label: string; danger?: boolean; onPick: () => void }[]
}) {
  const [open, setOpen] = React.useState(false)
  const ref = React.useRef<HTMLDivElement>(null)
  const panel = React.useRef<HTMLDivElement>(null)
  const trigger = React.useRef<HTMLButtonElement>(null)
  usePopoverFocus(open, panel, trigger)
  React.useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onDown)
    window.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      window.removeEventListener("keydown", onKey)
    }
  }, [open])
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        className={btnCls({ icon: true })}
      >
        <span aria-hidden="true" className="text-body leading-none tracking-caps">⋯</span>
      </button>
      {open && (
        <div role="menu" ref={panel}
             className={cn("pop-in absolute right-0 top-[26px] z-[60] min-w-[148px]", menuPanelCls)}>
          {items.map(it => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); it.onPick() }}
              className={cn(menuItemCls, it.danger ? "text-loss" : "text-foreground")}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Controls ───────────────────────────────────────────────────────────── */

/** Every button's look, as a class string (2026-09-18). One function so a
 * plain <button> and <Btn> can never drift apart — before this there were
 * five hand-rolled bordered buttons, six accent buttons and four "selected"
 * treatments. Use it on a raw <button> when changing the tag is awkward.
 *
 * - size: sm 20px (Account row actions, caps), md 24px, lg 28px.
 * - icon: square — width equals height.
 * - variant: default (bordered, muted label), strong (bordered, full-strength
 *   label — the way forward on a row), ghost (no border: segmented pickers,
 *   toolbars), accent (red fill: a form's submit), danger (bordered, red on
 *   hover).
 * - active: the SELECTED option — a soft grey fill, never red (the owner's
 *   call, 2026-09-18): red stays for headings and alerts. */
export type BtnStyle = {
  variant?: "default" | "strong" | "ghost" | "accent" | "danger"
  size?: "sm" | "md" | "lg"
  icon?: boolean
  active?: boolean
}

export function btnCls({ variant = "default", size = "md", icon, active }: BtnStyle = {}, className?: string) {
  return cn(
    "inline-flex shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-xs font-semibold leading-none transition-colors disabled:pointer-events-none disabled:opacity-45",
    size === "sm" && "h-[20px] px-1.5 text-label uppercase tracking-caps",
    size === "md" && "h-[24px] px-2 text-caption tracking-ticker",
    size === "lg" && "h-[28px] px-2.5 text-caption tracking-ticker",
    icon && "px-0",
    icon && size === "sm" && "w-[20px]",
    icon && size === "md" && "w-[24px]",
    icon && size === "lg" && "w-[28px]",
    (variant === "default" || variant === "danger") && "border border-border text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
    variant === "strong" && "border border-border text-foreground hover:bg-foreground/5",
    variant === "danger" && "hover:border-loss hover:bg-transparent hover:text-loss",
    variant === "ghost" && "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
    variant === "accent" && "bg-accent text-accent-foreground hover:bg-accent-600",
    active && "bg-foreground/10 text-foreground hover:bg-foreground/10 hover:text-foreground",
    className,
  )
}

export function Btn({
  variant, size, icon, active, className, ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & BtnStyle) {
  return (
    <button
      data-slot="button"
      type="button"
      aria-pressed={active}
      {...props}
      className={btnCls({ variant, size, icon, active }, className)}
    />
  )
}

/** A row in a dropdown menu: the chart's menus, the right-click menu, a
 * tile's overflow menu. */
/** A drop-down's rows and frame, the Next.js way (2026-09-19, the owner:
 * menus "dont look nextjs ish"): the panel is inset by 4px and each row is a
 * rounded highlight inside it, not a full-width stripe; the hover is a faint
 * ink wash. A picked row is marked with a tick, never red. */
export const menuItemCls =
  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-caption hover:bg-foreground/[0.06] disabled:opacity-40 disabled:hover:bg-transparent"
export const menuPanelCls = "rounded-md border border-card-border bg-card p-1 shadow-card"
/** A heading inside a menu: small grey text, not a filled band. */
export const menuHeadCls = "px-2 pb-1 pt-2 text-label font-medium text-muted-foreground"

/* No width here on purpose. Without tailwind-merge a caller's `w-24` does NOT
 * reliably beat a base `w-full` — both classes ship and CSS order decides, so
 * a base width silently wins and every field eats its own row. Callers state
 * their own width (`w-24`, `flex-1`, `w-full`). */
export const fieldCls =
  "h-[32px] border border-input bg-card px-2 text-body text-foreground placeholder:text-muted-foreground/70 focus:border-accent focus:outline-none"



export function Shimmer({ className }: { className?: string }) {
  return <div className={cn("animate-pulse bg-muted", className)} />
}

/** Native <details> instead of a JS collapsible — no dependency, keyboard and
 * find-in-page work for free. */

/* ── Dense table ────────────────────────────────────────────────────────── */

/** THE one table. 11px uppercase heads on a tinted band, every rule a light
 * hairline (2026-09-18: the 2px head rule and 40%-ink row rules read as
 * stripes on a white card), hover at 4% ink, numbers right and text left, a missing value is an
 * em dash and never a zero, long names truncate and never wrap. Every list on
 * every screen renders through this. `border-separate` rather than collapse so
 * the head's rule survives `position: sticky` — collapsed borders detach
 * from a stuck cell and scroll away with the rows. */
export function Table({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <table data-slot="table" className={cn("w-full table-fixed border-separate border-spacing-0 text-body", className)}>{children}</table>
  )
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    // sticky so a scrolling widget body keeps its column labels
    <thead className="sticky top-0 z-10 bg-panel">
      <tr>{children}</tr>
    </thead>
  )
}

/** A column heading. `title` is the column's description: it shows in the
 * app's own tooltip (HeaderTips), not the browser's, which waits about a
 * second and cannot be styled. */
export function TH({
  align = "left", className, title, width, children,
}: { align?: "left" | "right" | "center"; className?: string; title?: string
  /** A computed column width (e.g. "18.5%"), for a table whose shares vary. */
  width?: string; children?: React.ReactNode }) {
  return (
    <th
      style={width ? { width } : undefined}
      data-tip={title}
      aria-description={title}
      className={cn(
        "whitespace-nowrap border-b border-row-rule bg-panel px-2 py-2 text-label font-medium uppercase tracking-caps text-muted-foreground",
        align === "left" && "text-left",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  )
}

/** The description tooltip for anything carrying `data-tip` — every column
 * heading (2026-09-15). Mounted once at the app root: one delegated
 * listener rather than a handler per heading, so the plain `<th>` tables
 * (the option chain, the earnings calendar) take part by adding the
 * attribute.
 *
 * It opens after 250ms of rest, where the browser's own title tooltip waits
 * about a second, and renders through a portal at a fixed position, so a
 * panel's overflow cannot clip it. Placed under the heading and kept inside
 * the viewport; above it when there is no room below. Scrolling, a press or
 * leaving the heading closes it. A touch has no hover, so touches are
 * ignored rather than opening a tooltip that nothing would close. */
export function HeaderTips() {
  const [tip, setTip] = React.useState<{ text: string; rect: DOMRect } | null>(null)
  const box = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    let timer: number | undefined
    let on: Element | null = null
    const hide = () => { window.clearTimeout(timer); on = null; setTip(null) }
    const over = (e: PointerEvent) => {
      if (e.pointerType === "touch") return
      const el = (e.target as Element | null)?.closest?.("[data-tip]") ?? null
      if (el === on) return
      hide()
      const text = el?.getAttribute("data-tip")
      if (!el || !text) return
      on = el
      timer = window.setTimeout(() => setTip({ text, rect: el.getBoundingClientRect() }), 250)
    }
    const out = (e: PointerEvent) => { if (!e.relatedTarget) hide() }
    document.addEventListener("pointerover", over)
    document.addEventListener("pointerout", out)
    document.addEventListener("pointerdown", hide, true)
    window.addEventListener("scroll", hide, true)
    window.addEventListener("blur", hide)
    return () => {
      hide()
      document.removeEventListener("pointerover", over)
      document.removeEventListener("pointerout", out)
      document.removeEventListener("pointerdown", hide, true)
      window.removeEventListener("scroll", hide, true)
      window.removeEventListener("blur", hide)
    }
  }, [])
  React.useLayoutEffect(() => {
    const el = box.current
    if (!tip || !el) return
    const gap = 6, edge = 8
    const { width, height } = el.getBoundingClientRect()
    const centre = tip.rect.left + tip.rect.width / 2
    const left = Math.min(Math.max(centre - width / 2, edge), window.innerWidth - width - edge)
    const below = tip.rect.bottom + gap
    const top = below + height > window.innerHeight - edge ? tip.rect.top - gap - height : below
    el.style.left = `${left}px`
    el.style.top = `${top}px`
    el.style.visibility = "visible"
  }, [tip])
  if (!tip) return null
  return createPortal(
    <div ref={box} role="tooltip"
         style={{ left: 0, top: 0, visibility: "hidden" }}
         className="pop-in pointer-events-none fixed z-[90] max-w-[300px] rounded-sm border border-border bg-panel px-2.5 py-1.5 text-left text-caption font-normal normal-case leading-[1.45] tracking-normal text-foreground shadow-[0_8px_24px_rgba(0,0,0,0.45)]">
      {tip.text}
    </div>,
    document.body,
  )
}

export function TR({
  className, onClick, onRest, children,
}: {
  className?: string; onClick?: () => void
  /** Called once the pointer has rested on the row for 150ms — the moment
   * to start fetching what the click will open. A pointer sweeping down a
   * list fires nothing. */
  onRest?: () => void
  children: React.ReactNode
}) {
  const timer = React.useRef<number | null>(null)
  const stop = () => { if (timer.current) { window.clearTimeout(timer.current); timer.current = null } }
  React.useEffect(() => stop, [])
  return (
    <tr
      onClick={onClick}
      onPointerEnter={onRest ? () => { stop(); timer.current = window.setTimeout(onRest, 150) } : undefined}
      onPointerLeave={onRest ? stop : undefined}
      className={cn(
        "hover:bg-foreground/5",
        onClick && "cursor-pointer",
        className,
      )}
    >
      {children}
    </tr>
  )
}

export function TD({
  align = "left", mono, className, colSpan, title, children,
}: {
  align?: "left" | "right" | "center"
  /** Tabular figures — use for every numeric column so digits align. */
  mono?: boolean
  className?: string
  colSpan?: number
  /** The full value when the cell may truncate it. */
  title?: string
  children?: React.ReactNode
}) {
  return (
    <td
      colSpan={colSpan}
      title={title}
      className={cn(
        // overflow-hidden + ellipsis, not just nowrap: with table-fixed the
        // narrow-span rule is that a long name truncates inside its column
        // rather than forcing a horizontal scroll.
        "h-[32px] overflow-hidden text-ellipsis whitespace-nowrap border-b border-row-rule px-2 py-1.5",
        align === "left" && "text-left",
        align === "right" && "text-right",
        align === "center" && "text-center",
        mono && "num",
        className,
      )}
    >
      {children}
    </td>
  )
}

/** Filler for an empty/loading/error widget body. Flush left, never centered
 * — Modernist sets everything against the left edge, empty states included. */
export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 py-4 text-left text-body text-muted-foreground">{children}</div>
  )
}

/** Label/value pair — the stat readout used across the dashboard tiles. */
export function Stat({
  label, value, tone, sub, wrap = false,
}: {
  label: string
  value: React.ReactNode
  tone?: "gain" | "loss"
  sub?: React.ReactNode
  /** Let the value and sub-line wrap. The default truncates, which is right
   * for a figure and wrong for a phrase — "Commodity Contracts Brokers &
   * Dealers" cut to "Commodity Contracts Bro…" says less than nothing. */
  wrap?: boolean
}) {
  return (
    <div className="min-w-0 border-r border-row-rule px-2 py-1.5 last:border-r-0">
      <div className="truncate text-label font-medium uppercase tracking-caps text-muted-foreground">{label}</div>
      <div
        className={cn(
          "num text-emph font-extrabold leading-tight",
          wrap ? "break-words" : "truncate",
          tone === "gain" && "text-gain",
          tone === "loss" && "text-loss",
        )}
      >
        {value}
      </div>
      {sub && <div className={cn("text-label text-muted-foreground", wrap ? "leading-snug" : "truncate")}>{sub}</div>}
    </div>
  )
}
