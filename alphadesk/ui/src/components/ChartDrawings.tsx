import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Lock, LockOpen, Trash2 } from "lucide-react"
import type { Projection } from "@/components/chart/ChartCanvas"
import type { ChartBar } from "@/lib/api"
import { measureLines } from "@/lib/measure"
import { btnCls, menuHeadCls, menuItemCls, menuPanelCls } from "@/components/terminal"
import { cn } from "@/lib/utils"

/** Hand-drawn annotations over the price pane — as OBJECTS.
 *
 * Shapes are stored in DATA coordinates — a (time, price) pair per anchor —
 * and re-projected to pixels on every pan, zoom and resize. Storing pixels
 * would be far simpler and completely wrong: the drawing would slide off the
 * bar it was drawn against the moment the chart moved, which is the one thing
 * an annotation must never do.
 *
 * Block 1 of the advanced chart (2026-09-05). A drawing used to be placed and
 * then only ever cleared; now it is a thing you can pick up: click selects,
 * drag moves, the anchor handles reshape, Delete removes, and a floating
 * strip sets colour, weight and dash. Every edit goes through one `onChange`,
 * which is where the caller's undo history and persistence both hang.
 *
 * ANCHORS SURVIVE AN INTERVAL CHANGE. A line drawn on minute bars has anchor
 * times that are not bar times on the daily chart, and the renderer's
 * projection answers null for those. So an anchor that misses is placed at
 * the nearest bar by timestamp — which is where the eye would put it — instead
 * of vanishing until the reader switches back.
 *
 * Rendered as an SVG overlay: hit-testing, hover states and crisp text come
 * from the browser, and the projection work is identical either way.
 */

export type Kind =
  | "trend" | "ray" | "extended" | "hline" | "hray" | "vline" | "channel"
  | "rect" | "ellipse" | "arrow"
  | "fib"
  | "text"
  | "measure" | "pricerange" | "daterange"
export type Tool = "none" | Kind

export type Dash = "solid" | "dashed" | "dotted"
export type Style = { color?: string; width?: number; dash?: Dash; fill?: boolean }
type Anchor = { time: string; price: number }
export type Drawing = {
  id: string
  kind: Kind
  a: Anchor
  b?: Anchor
  /** The third point of a parallel channel — where the second rail sits. */
  c?: Anchor
  text?: string
  style?: Style
  locked?: boolean
}

/** How many clicks a tool takes. */
const ANCHORS: Record<Kind, 1 | 2 | 3> = {
  hline: 1, hray: 1, vline: 1, text: 1,
  trend: 2, ray: 2, extended: 2, rect: 2, ellipse: 2, arrow: 2, fib: 2,
  measure: 2, pricerange: 2, daterange: 2,
  channel: 3,
}
const KINDS = Object.keys(ANCHORS) as Kind[]

/** The tool column's groups, in TradingView's order: the button shows the
 * group's last-used tool, the fly-out lists the rest. Shortcuts are theirs
 * too — a hand that knows Alt+T should not have to relearn it here. */
export const TOOL_GROUPS: { id: string; label: string; tools: { id: Kind; label: string; key?: string }[] }[] = [
  { id: "lines", label: "Lines", tools: [
    { id: "trend", label: "Trend line", key: "Alt+T" },
    { id: "ray", label: "Ray" },
    { id: "extended", label: "Extended line" },
    { id: "hline", label: "Horizontal line", key: "Alt+H" },
    { id: "hray", label: "Horizontal ray", key: "Alt+J" },
    { id: "vline", label: "Vertical line", key: "Alt+V" },
    { id: "channel", label: "Parallel channel" },
  ] },
  { id: "shapes", label: "Shapes", tools: [
    { id: "rect", label: "Rectangle" },
    { id: "ellipse", label: "Ellipse" },
    { id: "arrow", label: "Arrow" },
  ] },
  { id: "fib", label: "Fibonacci", tools: [
    { id: "fib", label: "Fib retracement", key: "Alt+F" },
  ] },
  { id: "text", label: "Text", tools: [
    { id: "text", label: "Text" },
  ] },
  { id: "measure", label: "Measure", tools: [
    { id: "measure", label: "Measure" },
    { id: "pricerange", label: "Price range" },
    { id: "daterange", label: "Date range" },
  ] },
]
const SHORTCUTS: Record<string, Kind> = { KeyT: "trend", KeyH: "hline", KeyJ: "hray", KeyV: "vline", KeyF: "fib" }
/** The physical key, whichever way the event names it: `code` is what a Mac
 * reports for Alt+T (whose `key` is a dead-key character), and `key` is what
 * a synthetic event carries when `code` is empty. */
const keyCode = (e: KeyboardEvent) =>
  e.code || (e.key.length === 1 ? `Key${e.key.toUpperCase()}` : e.key)

/** Stored as token references, so a drawing keeps its meaning across the
 * light and dark themes rather than a hex value that was picked for one. */
export const PALETTE: { id: string; css: string; label: string }[] = [
  { id: "accent", css: "var(--accent)", label: "Accent" },
  { id: "gain", css: "var(--gain)", label: "Gain" },
  { id: "loss", css: "var(--loss)", label: "Loss" },
  { id: "info", css: "var(--info)", label: "Info" },
  { id: "warn", css: "var(--warn)", label: "Amber" },
  { id: "ink", css: "var(--foreground)", label: "Ink" },
  { id: "muted", css: "var(--muted-foreground)", label: "Muted" },
]
const DEFAULT_COLOR = PALETTE[0].css
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618]
const DASHES: Record<Dash, string | undefined> = { solid: undefined, dashed: "6 4", dotted: "2 3" }

/** What a stored list must look like to be drawn. Anything else — an older
 * build's shape, a hand-edited row — is dropped, never rendered as a guess. */
export function validateDrawings(raw: unknown): Drawing[] {
  if (!Array.isArray(raw)) return []
  const anchor = (a: unknown): a is Anchor =>
    !!a && typeof a === "object" && typeof (a as Anchor).time === "string"
    && typeof (a as Anchor).price === "number" && Number.isFinite((a as Anchor).price)
  const colors = new Set(PALETTE.map(p => p.css))
  const out: Drawing[] = []
  for (const d of raw) {
    if (!d || typeof d !== "object") continue
    const { id, kind, a, b, c, text, style, locked } = d as Drawing
    if (typeof id !== "string" || !KINDS.includes(kind) || !anchor(a)) continue
    const need = ANCHORS[kind]
    if (need >= 2 && !anchor(b)) continue
    if (need >= 3 && !anchor(c)) continue
    const clean: Drawing = { id, kind, a: { time: a.time, price: a.price } }
    if (need >= 2 && b) clean.b = { time: b.time, price: b.price }
    if (need >= 3 && c) clean.c = { time: c.time, price: c.price }
    if (typeof text === "string") clean.text = text.slice(0, 200)
    if (style && typeof style === "object") {
      const s: Style = {}
      if (typeof style.color === "string" && (colors.has(style.color) || /^#[0-9a-f]{3,8}$/i.test(style.color))) s.color = style.color
      if (typeof style.width === "number" && style.width >= 1 && style.width <= 4) s.width = style.width
      if (style.dash === "solid" || style.dash === "dashed" || style.dash === "dotted") s.dash = style.dash
      if (typeof style.fill === "boolean") s.fill = style.fill
      if (Object.keys(s).length) clean.style = s
    }
    if (locked === true) clean.locked = true
    out.push(clean)
  }
  return out
}

// Time-salted, not a counter: drawings persist now, and a counter that
// restarts at 1 on reload would hand a new line the id of a saved one.
let seq = 0
export const nextId = () => `d${Date.now().toString(36)}${(seq++).toString(36)}`

/** Undo/redo over the drawing list, for the caller that owns it.
 *
 * Every edit the overlay makes arrives through `commit`, which is what puts
 * the previous list on the stack. A list that arrives from anywhere else — a
 * symbol change loading another chart's drawings — is a new document and
 * empties the history rather than letting Ctrl+Z walk into another symbol's
 * lines. */
export function useDrawingHistory(
  drawings: Drawing[],
  setDrawings: (next: Drawing[]) => void,
) {
  const past = useRef<Drawing[][]>([])
  const future = useRef<Drawing[][]>([])
  const ours = useRef<Drawing[] | null>(null)
  const current = useRef(drawings)
  current.current = drawings
  const [, bump] = useState(0)

  useEffect(() => {
    if (ours.current !== drawings) { past.current = []; future.current = []; bump(n => n + 1) }
  }, [drawings])

  const apply = useCallback((next: Drawing[]) => {
    ours.current = next
    setDrawings(next)
    bump(n => n + 1)
  }, [setDrawings])

  const commit = useCallback((next: Drawing[]) => {
    past.current.push(current.current)
    if (past.current.length > 100) past.current.shift()
    future.current = []
    apply(next)
  }, [apply])
  const undo = useCallback(() => {
    const prev = past.current.pop()
    if (!prev) return
    future.current.push(current.current)
    apply(prev)
  }, [apply])
  const redo = useCallback(() => {
    const next = future.current.pop()
    if (!next) return
    past.current.push(current.current)
    apply(next)
  }, [apply])

  return { commit, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0 }
}

const AXIS_W = 62
const AXIS_H = 22

type Px = { x: number; y: number }
type Drag = {
  id: string
  part: "move" | "a" | "b" | "c"
  start: Px
  orig: Drawing
  moved: boolean
}

export function ChartDrawings({
  projection, bars, tool, onToolDone, drawings, onChange, visible, height,
  magnet, onUndo, onRedo, onArm,
}: {
  /** Supplied by the renderer. Null before the first layout. */
  projection: Projection | null
  bars: ChartBar[]
  tool: Tool
  /** Fired after a shape completes, so the toolbar drops back to the crosshair
   * — matching how every charting tool behaves. */
  onToolDone: () => void
  drawings: Drawing[]
  /** One call per finished edit — a placement, a completed drag, a style
   * change — never per mouse move. */
  onChange: (next: Drawing[]) => void
  visible: boolean
  height: number
  /** Snap placements and drags to the nearest open/high/low/close. */
  magnet: boolean
  onUndo?: () => void
  onRedo?: () => void
  /** A keyboard shortcut picked a tool (Alt+T and friends). */
  onArm?: (k: Kind) => void
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const [pending, setPending] = useState<Anchor[]>([])
  /** THE MEASUREMENT IS A GLANCE, NOT A DRAWING (2026-09-16). Theirs shows
   * the span and its numbers until the next click and then it is gone, which
   * is what the tool is for: reading one move and moving on. Ours kept it as
   * an object to select, move and delete, so the chart filled with boxes
   * nobody meant to keep. It lives here instead of in `drawings`, so it is
   * never persisted, never selectable, and never in the undo history. */
  const [scratch, setScratch] = useState<Drawing | null>(null)
  const [cursor, setCursor] = useState<Px | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  /** The drawing under the pointer mid-drag, rendered in place of the stored
   * one so the list — and its history and its persistence — changes once. */
  const [live, setLive] = useState<Drawing | null>(null)
  const drag = useRef<Drag | null>(null)
  /** A text label being typed, before (or while re-editing) it is a drawing. */
  const [editing, setEditing] = useState<{ id: string | null; at: Anchor; px: Px; value: string } | null>(null)
  // Bumped whenever the chart moves, to force a re-projection.
  const [, setTick] = useState(0)
  useEffect(() => { setTick(t => t + 1) }, [projection])

  const width = wrap.current?.clientWidth ?? 0
  const plotW = Math.max(0, width - AXIS_W)
  const plotH = Math.max(0, height - AXIS_H)

  // ── time lookup: exact bar, else the nearest by timestamp ──────────────
  const stamps = useMemo(() => bars.map(b => Date.parse(b.t)), [bars])
  const byTime = useMemo(() => new Map(bars.map((b, i) => [b.t, i] as const)), [bars])
  const idxOf = useCallback((t: string): number | null => {
    const hit = byTime.get(t)
    if (hit != null) return hit
    if (!stamps.length) return null
    const ts = Date.parse(t)
    let lo = 0, hi = stamps.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (stamps[mid] < ts) lo = mid + 1; else hi = mid
    }
    if (lo > 0 && Math.abs(stamps[lo - 1] - ts) <= Math.abs(stamps[lo] - ts)) return lo - 1
    return lo
  }, [byTime, stamps])
  /** One bar's typical duration, for placing a time the loaded bars do not
   * reach: the median of the gaps, so a weekend does not stretch it. */
  const barMs = useMemo(() => {
    const gaps: number[] = []
    for (let i = 1; i < Math.min(stamps.length, 60); i++) gaps.push(stamps[i] - stamps[i - 1])
    gaps.sort((a, b) => a - b)
    return gaps.length ? gaps[gaps.length >> 1] : 0
  }, [stamps])
  const xOf = useCallback((t: string): number | null => {
    if (!projection) return null
    const direct = projection.timeToCoordinate(t)
    if (direct != null) return direct
    // A time BEFORE the first loaded bar or AFTER the last is extrapolated
    // at the bars' own spacing, off the edge of the plot. It used to be
    // pinned to the nearest bar, so a line drawn over 2021–2024 and viewed
    // on one month had both ends on the first bar and stood up as a
    // vertical rule down the plot's left edge (2026-09-18).
    const ts = Date.parse(t)
    const n = stamps.length
    if (n >= 2 && barMs > 0 && (ts < stamps[0] || ts > stamps[n - 1])) {
      const edge = ts < stamps[0] ? 0 : n - 1
      const x0 = projection.timeToCoordinate(bars[edge].t)
      const x1 = projection.timeToCoordinate(bars[edge === 0 ? 1 : n - 2].t)
      if (x0 != null && x1 != null) {
        const spacing = Math.abs(x0 - x1)
        return x0 + ((ts - stamps[edge]) / barMs) * spacing
      }
    }
    const i = idxOf(t)
    return i == null ? null : projection.timeToCoordinate(bars[i].t)
  }, [projection, idxOf, bars, stamps, barMs])

  /** data -> pixels. Null before layout or when the price cannot be placed. */
  const project = useCallback((a: Anchor): Px | null => {
    if (!projection) return null
    const x = xOf(a.time)
    const y = projection.priceToCoordinate(a.price)
    return x == null || y == null ? null : { x, y }
  }, [projection, xOf])

  /** The pixels a drawing covers, for placing its style strip beside it. A
   * horizontal line spans the plot's width from its anchor (a ray) or all
   * of it; a vertical line its height. Null when it cannot be placed. */
  const boxOf = (d: Drawing): Box | null => {
    const pts = [d.a, d.b, d.c].filter((p): p is Anchor => !!p).map(project).filter((p): p is Px => !!p)
    if (!pts.length) return null
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
    if (d.kind === "hline") { x0 = 0; x1 = plotW }
    if (d.kind === "hray") x1 = plotW
    if (d.kind === "vline") { y0 = 0; y1 = plotH }
    return { x0, x1, y0, y1 }
  }

  /** pixels -> data, snapped to the bar's nearest OHLC when the magnet is on
   * and one is within reach. Null outside the plotted area. */
  const unproject = useCallback((x: number, y: number): Anchor | null => {
    if (!projection) return null
    const time = projection.coordinateToTime(x)
    const price = projection.coordinateToPrice(y)
    if (time == null || price == null) return null
    if (!magnet) return { time, price }
    const i = byTime.get(time)
    const bar = i == null ? null : bars[i]
    if (!bar) return { time, price }
    let best = price, bestD = 14
    for (const v of [bar.o, bar.h, bar.l, bar.c]) {
      const py = projection.priceToCoordinate(v)
      if (py == null) continue
      const d = Math.abs(py - y)
      if (d < bestD) { bestD = d; best = v }
    }
    return { time, price: best }
  }, [projection, magnet, byTime, bars])

  const toLocal = (e: { clientX: number; clientY: number }): Px => {
    const r = wrap.current?.getBoundingClientRect()
    return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 }
  }

  // ── placement ───────────────────────────────────────────────────────────
  const commit = (d: Drawing) => { onChange([...drawings, d]); setSelected(d.id); onToolDone() }

  const onClick = (e: React.MouseEvent) => {
    if (tool === "none" || editing) return
    const px = toLocal(e)
    const at = unproject(px.x, px.y)
    if (!at) return
    if (tool === "text") { setEditing({ id: null, at, px, value: "" }); return }
    const need = ANCHORS[tool]
    const next = [...pending, at]
    if (next.length < need) { setPending(next); return }
    const d: Drawing = { id: nextId(), kind: tool, a: next[0] }
    if (need >= 2) d.b = next[1]
    if (need >= 3) d.c = next[2]
    if (tool === "measure") { setScratch(d); onToolDone() } else commit(d)
    setPending([])
  }

  const onMove = (e: React.MouseEvent) => {
    if (tool === "none" || !pending.length) { setCursor(null); return }
    setCursor(toLocal(e))
  }

  // Gone on the next click anywhere — the overlay is click-through while no
  // tool is armed, so the window is what hears it — and on Escape. Attached
  // only while a measurement is on screen, and after the click that made it,
  // which is why that click does not clear it immediately.
  useEffect(() => {
    if (!scratch) return
    const clear = () => setScratch(null)
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setScratch(null) }
    // Both kinds: a pen or touch reports only pointerdown, and some input
    // stacks deliver only the mouse events.
    window.addEventListener("pointerdown", clear, true)
    window.addEventListener("mousedown", clear, true)
    window.addEventListener("keydown", onEsc)
    return () => {
      window.removeEventListener("pointerdown", clear, true)
      window.removeEventListener("mousedown", clear, true)
      window.removeEventListener("keydown", onEsc)
    }
  }, [scratch])
  // Arming any tool, including the measure again, starts from a clean pane.
  useEffect(() => { if (tool !== "none") setScratch(null) }, [tool])

  // ── selection & dragging ────────────────────────────────────────────────
  const beginDrag = (e: React.MouseEvent, d: Drawing, part: Drag["part"]) => {
    if (tool !== "none") return
    e.preventDefault()
    e.stopPropagation()
    setSelected(d.id)
    if (d.locked) return
    drag.current = { id: d.id, part, start: toLocal(e), orig: d, moved: false }

    const move = (ev: MouseEvent) => {
      const g = drag.current
      if (!g) return
      const now = toLocal(ev)
      const dx = now.x - g.start.x, dy = now.y - g.start.y
      if (!g.moved && Math.hypot(dx, dy) < 2) return
      g.moved = true
      const shift = (a: Anchor | undefined): Anchor | undefined => {
        if (!a) return a
        const p = project(a)
        if (!p) return a
        return unproject(p.x + dx, p.y + dy) ?? a
      }
      const next: Drawing = { ...g.orig }
      if (g.part === "move") {
        next.a = shift(g.orig.a) ?? g.orig.a
        next.b = shift(g.orig.b)
        next.c = shift(g.orig.c)
      } else {
        const moved = unproject(now.x, now.y)
        if (moved) next[g.part] = moved
      }
      setLive(next)
    }
    const up = () => {
      window.removeEventListener("mousemove", move)
      window.removeEventListener("mouseup", up)
      const g = drag.current
      drag.current = null
      setLive(current => {
        if (g?.moved && current) onChange(drawings.map(x => (x.id === current.id ? current : x)))
        return null
      })
    }
    window.addEventListener("mousemove", move)
    window.addEventListener("mouseup", up)
  }

  // A click anywhere that is not a drawing or the property strip deselects.
  useEffect(() => {
    if (!selected) return
    const away = (e: MouseEvent) => {
      const t = e.target as Element | null
      if (t?.closest?.("[data-drawing]") || t?.closest?.("[data-drawing-ui]")) return
      setSelected(null)
    }
    document.addEventListener("mousedown", away)
    return () => document.removeEventListener("mousedown", away)
  }, [selected])

  const patch = (id: string, p: Partial<Drawing>) =>
    onChange(drawings.map(d => (d.id === id ? { ...d, ...p } : d)))
  const remove = (id: string) => { onChange(drawings.filter(d => d.id !== id)); setSelected(null) }

  // ── keyboard ────────────────────────────────────────────────────────────
  const armRef = useRef<(k: Kind) => void>(() => {})
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null
      const typing = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)
      if (e.key === "Escape") {
        if (editing) { setEditing(null); return }
        if (pending.length) { setPending([]); return }
        if (selected) { setSelected(null); return }
        if (tool !== "none") onToolDone()
        return
      }
      if (typing) return
      if ((e.key === "Delete" || e.key === "Backspace") && selected) {
        const d = drawings.find(x => x.id === selected)
        if (d && !d.locked) { e.preventDefault(); remove(selected) }
        return
      }
      const code = keyCode(e)
      if ((e.metaKey || e.ctrlKey) && code === "KeyZ") {
        e.preventDefault()
        if (e.shiftKey) onRedo?.(); else onUndo?.()
        return
      }
      if ((e.metaKey || e.ctrlKey) && code === "KeyY") { e.preventDefault(); onRedo?.(); return }
      if (e.altKey && SHORTCUTS[code]) { e.preventDefault(); armRef.current(SHORTCUTS[code]) }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, pending, selected, tool, drawings, onToolDone, onUndo, onRedo])

  // ── rendering ───────────────────────────────────────────────────────────
  const list = drawings.map(d => (live?.id === d.id ? live : d))

  /** Elapsed time between two anchors. Anchors carry an ISO timestamp, so
   * this is real elapsed time rather than a bar count — which is the honest
   * number when the series has gaps in it. */
  const spanLabel = (a: Anchor, b: Anchor) => {
    const secs = Math.abs(Date.parse(b.time) - Date.parse(a.time)) / 1000
    if (secs >= 86400) return `${(secs / 86400).toFixed(1)}d`
    if (secs >= 3600) return `${(secs / 3600).toFixed(1)}h`
    return `${Math.round(secs / 60)}m`
  }
  const barsBetween = (a: Anchor, b: Anchor) => {
    const i = idxOf(a.time), j = idxOf(b.time)
    return i == null || j == null ? null : Math.abs(j - i)
  }
  /** What traded across the measurement — the bars from one anchor to the
   * other, inclusive. Null when either anchor is off the loaded series, so
   * the label drops the line rather than printing a misleading zero. */
  const volumeBetween = (a: Anchor, b: Anchor) => {
    const i = idxOf(a.time), j = idxOf(b.time)
    if (i == null || j == null) return null
    let total = 0
    for (let k = Math.min(i, j); k <= Math.max(i, j); k++) total += bars[k]?.v ?? 0
    return total
  }
  const fmt = (n: number) => n.toFixed(n >= 100 ? 2 : n >= 1 ? 2 : 4)

  const shape = (d: Drawing, ghost = false) => {
    if (!projection) return null
    const st = d.style ?? {}
    const color = st.color ?? DEFAULT_COLOR
    const sw = st.width ?? 1.5
    const dash = DASHES[st.dash ?? "solid"]
    const isSel = !ghost && selected === d.id
    const op = ghost ? 0.6 : 1
    const a = project(d.a)
    const b = d.b ? project(d.b) : null
    const c = d.c ? project(d.c) : null
    if (!a) return null

    // The invisible, fat twin of a line that takes the mouse.
    const hitLine = (x1: number, y1: number, x2: number, y2: number) =>
      ghost ? null : (
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={12}
          style={{ pointerEvents: "stroke", cursor: d.locked ? "default" : "move" }}
          data-drawing={d.id} onMouseDown={e => beginDrag(e, d, "move")} />
      )
    const handle = (p: Px, part: Drag["part"]) =>
      !isSel || d.locked ? null : (
        <circle cx={p.x} cy={p.y} r={4.5} fill="var(--background)" stroke={color} strokeWidth={1.5}
          style={{ pointerEvents: "all", cursor: "grab" }}
          data-drawing={d.id} onMouseDown={e => beginDrag(e, d, part)} />
      )
    const lockGlyph = (p: Px) =>
      isSel && d.locked ? (
        <text x={p.x + 8} y={p.y - 8} fontSize={11} fill={color}>🔒</text>
      ) : null
    /** A price tag in the axis gutter — the level a horizontal line marks,
     * said where the axis says prices. */
    const priceTag = (y: number, price: number) => (
      <g>
        <rect x={plotW + 2} y={y - 8} width={AXIS_W - 4} height={16} fill={color} rx={2} />
        <text x={plotW + AXIS_W / 2} y={y + 3.5} textAnchor="middle" fill="var(--background)"
          fontSize={10} fontWeight={700} className="tnum">{fmt(price)}</text>
      </g>
    )
    const sel = isSel ? { filter: "drop-shadow(0 0 2px rgba(0,0,0,0.35))" } : undefined

    // ── one-anchor kinds ──
    if (d.kind === "hline" || d.kind === "hray") {
      const x0 = d.kind === "hline" ? 0 : Math.max(0, a.x)
      if (d.kind === "hray" && a.x > plotW) return null
      return (
        <g key={d.id} opacity={op} style={sel}>
          <line x1={x0} y1={a.y} x2={plotW} y2={a.y} stroke={color} strokeWidth={sw} strokeDasharray={dash} />
          {d.kind === "hray" && <circle cx={a.x} cy={a.y} r={2.5} fill={color} />}
          {hitLine(x0, a.y, plotW, a.y)}
          {priceTag(a.y, d.a.price)}
          {handle({ x: d.kind === "hline" ? Math.min(Math.max(a.x, 20), plotW - 20) : a.x, y: a.y }, "a")}
          {lockGlyph(a)}
        </g>
      )
    }
    if (d.kind === "vline") {
      return (
        <g key={d.id} opacity={op} style={sel}>
          <line x1={a.x} y1={0} x2={a.x} y2={plotH} stroke={color} strokeWidth={sw} strokeDasharray={dash} />
          {hitLine(a.x, 0, a.x, plotH)}
          {handle({ x: a.x, y: Math.min(Math.max(a.y, 20), plotH - 20) }, "a")}
          {lockGlyph(a)}
        </g>
      )
    }
    if (d.kind === "text") {
      const label = d.text ?? ""
      const w = Math.max(24, label.length * 7 + 10)
      return (
        <g key={d.id} opacity={op} style={sel}>
          <text x={a.x} y={a.y} fontSize={12} fontWeight={600} fill={color}
            paintOrder="stroke" stroke="var(--background)" strokeWidth={3}>{label}</text>
          {!ghost && (
            <rect x={a.x - 4} y={a.y - 13} width={w} height={18} fill="transparent"
              style={{ pointerEvents: "all", cursor: d.locked ? "default" : "move" }}
              data-drawing={d.id} onMouseDown={e => beginDrag(e, d, "move")}
              onDoubleClick={() => { if (!d.locked) setEditing({ id: d.id, at: d.a, px: a, value: label }) }} />
          )}
          {isSel && <rect x={a.x - 4} y={a.y - 13} width={w} height={18} fill="none" stroke={color} strokeDasharray="2 2" />}
          {lockGlyph(a)}
        </g>
      )
    }

    // ── two-anchor kinds: the second point is the cursor while drawing ──
    const bAt = b ?? (ghost && cursor ? cursor : null)
    if (!bAt) return null
    const bA = d.b ?? (ghost && cursor ? unproject(cursor.x, cursor.y) : null)

    if (d.kind === "trend" || d.kind === "ray" || d.kind === "extended" || d.kind === "arrow") {
      const dx = bAt.x - a.x, dy = bAt.y - a.y
      const at = (x: number) => a.y + (dx === 0 ? 0 : (x - a.x) * dy / dx)
      let p1: Px = a, p2: Px = bAt
      if (d.kind === "ray") {
        if (dx === 0) p2 = { x: a.x, y: dy >= 0 ? plotH : 0 }
        else p2 = dx > 0 ? { x: plotW, y: at(plotW) } : { x: 0, y: at(0) }
      } else if (d.kind === "extended") {
        if (dx === 0) { p1 = { x: a.x, y: 0 }; p2 = { x: a.x, y: plotH } }
        else { p1 = { x: 0, y: at(0) }; p2 = { x: plotW, y: at(plotW) } }
      }
      const ang = Math.atan2(dy, dx)
      const head = d.kind === "arrow" ? [
        bAt,
        { x: bAt.x - 11 * Math.cos(ang - 0.42), y: bAt.y - 11 * Math.sin(ang - 0.42) },
        { x: bAt.x - 11 * Math.cos(ang + 0.42), y: bAt.y - 11 * Math.sin(ang + 0.42) },
      ] : null
      return (
        <g key={d.id} opacity={op} style={sel}>
          <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={color} strokeWidth={sw} strokeDasharray={dash} />
          {d.kind === "ray" && <circle cx={a.x} cy={a.y} r={2.5} fill={color} />}
          {head && <polygon points={head.map(p => `${p.x},${p.y}`).join(" ")} fill={color} />}
          {hitLine(p1.x, p1.y, p2.x, p2.y)}
          {handle(a, "a")}{handle(bAt, "b")}
          {lockGlyph(a)}
        </g>
      )
    }

    if (d.kind === "channel") {
      const cAt = c ?? (ghost && cursor && d.b ? cursor : null)
      const dx = bAt.x - a.x, dy = bAt.y - a.y
      const at = (x: number) => a.y + (dx === 0 ? 0 : (x - a.x) * dy / dx)
      const off = cAt ? cAt.y - at(cAt.x) : 0
      const poly = `${a.x},${a.y} ${bAt.x},${bAt.y} ${bAt.x},${bAt.y + off} ${a.x},${a.y + off}`
      return (
        <g key={d.id} opacity={op} style={sel}>
          {cAt && st.fill !== false && <polygon points={poly} fill={color} fillOpacity={0.08} />}
          <line x1={a.x} y1={a.y} x2={bAt.x} y2={bAt.y} stroke={color} strokeWidth={sw} strokeDasharray={dash} />
          {cAt && <line x1={a.x} y1={a.y + off} x2={bAt.x} y2={bAt.y + off} stroke={color} strokeWidth={sw} strokeDasharray={dash} />}
          {cAt && <line x1={a.x} y1={a.y + off / 2} x2={bAt.x} y2={bAt.y + off / 2} stroke={color} strokeWidth={1} strokeDasharray="2 3" opacity={0.6} />}
          {hitLine(a.x, a.y, bAt.x, bAt.y)}
          {cAt && hitLine(a.x, a.y + off, bAt.x, bAt.y + off)}
          {handle(a, "a")}{handle(bAt, "b")}{cAt && c && handle(c, "c")}
          {lockGlyph(a)}
        </g>
      )
    }

    const box = {
      x: Math.min(a.x, bAt.x), y: Math.min(a.y, bAt.y),
      w: Math.abs(bAt.x - a.x), h: Math.abs(bAt.y - a.y),
    }

    if (d.kind === "rect" || d.kind === "ellipse") {
      const hit = ghost ? null : (
        d.kind === "rect"
          ? <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="none" stroke="transparent" strokeWidth={12}
              style={{ pointerEvents: "stroke", cursor: d.locked ? "default" : "move" }}
              data-drawing={d.id} onMouseDown={e => beginDrag(e, d, "move")} />
          : <ellipse cx={box.x + box.w / 2} cy={box.y + box.h / 2} rx={box.w / 2} ry={box.h / 2} fill="none" stroke="transparent" strokeWidth={12}
              style={{ pointerEvents: "stroke", cursor: d.locked ? "default" : "move" }}
              data-drawing={d.id} onMouseDown={e => beginDrag(e, d, "move")} />
      )
      return (
        <g key={d.id} opacity={op} style={sel}>
          {d.kind === "rect"
            ? <rect x={box.x} y={box.y} width={box.w} height={box.h} fill={color} fillOpacity={st.fill === false ? 0 : 0.1}
                stroke={color} strokeWidth={sw} strokeDasharray={dash} />
            : <ellipse cx={box.x + box.w / 2} cy={box.y + box.h / 2} rx={box.w / 2} ry={box.h / 2}
                fill={color} fillOpacity={st.fill === false ? 0 : 0.1} stroke={color} strokeWidth={sw} strokeDasharray={dash} />}
          {hit}
          {handle(a, "a")}{handle(bAt, "b")}
          {lockGlyph(a)}
        </g>
      )
    }

    if (d.kind === "fib") {
      const x0 = box.x, x1 = box.x + box.w
      const bPrice = bA?.price ?? d.a.price
      const rows = FIB_LEVELS.map(L => {
        const price = bPrice + (d.a.price - bPrice) * L
        const y = projection.priceToCoordinate(price)
        return y == null ? null : { L, price, y }
      }).filter((r): r is { L: number; price: number; y: number } => !!r)
      const labelLeft = x0 > 110
      return (
        <g key={d.id} opacity={op} style={sel}>
          {st.fill !== false && rows.slice(0, -1).map((r, i) => (
            <rect key={r.L} x={x0} y={Math.min(r.y, rows[i + 1].y)} width={box.w}
              height={Math.abs(rows[i + 1].y - r.y)} fill={color} fillOpacity={0.05 + (i % 2) * 0.03} />
          ))}
          <line x1={a.x} y1={a.y} x2={bAt.x} y2={bAt.y} stroke={color} strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
          {rows.map(r => (
            <g key={r.L}>
              <line x1={x0} y1={r.y} x2={x1} y2={r.y} stroke={color} strokeWidth={r.L === 0 || r.L === 1 ? sw : 1} strokeDasharray={dash} />
              <text x={labelLeft ? x0 - 6 : x1 + 6} y={r.y + 3.5} textAnchor={labelLeft ? "end" : "start"}
                fontSize={10} fill={color} className="tnum"
                paintOrder="stroke" stroke="var(--background)" strokeWidth={3}>
                {r.L.toFixed(3)} ({fmt(r.price)})
              </text>
              {hitLine(x0, r.y, x1, r.y)}
            </g>
          ))}
          {handle(a, "a")}{handle(bAt, "b")}
          {lockGlyph(a)}
        </g>
      )
    }

    // ── the measures ──
    const from = d.a.price
    const to = bA?.price ?? from
    const delta = to - from
    const pct = from === 0 ? 0 : (delta / Math.abs(from)) * 100
    const up = delta >= 0
    const tone = up ? "var(--gain)" : "var(--loss)"
    const n = bA ? barsBetween(d.a, bA) : null
    const span = bA ? spanLabel(d.a, bA) : ""
    const priceText = `${up ? "+" : ""}${fmt(delta)} (${up ? "+" : ""}${pct.toFixed(2)}%)`
    const timeText = `${n != null ? `${n} bars · ` : ""}${span}`
    const hitBox = ghost ? null : (
      <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="transparent"
        style={{ pointerEvents: "all", cursor: d.locked ? "default" : "move" }}
        data-drawing={d.id} onMouseDown={e => beginDrag(e, d, "move")} />
    )
    if (d.kind === "measure") {
      // THEIRS, AS THE OWNER ASKED (2026-09-16). The shaded span, an arrow
      // showing which way and how far price went, and a filled label
      // carrying the three things a measurement is read for: the move in
      // money, per cent and ticks; the bars and the clock time; the volume
      // that traded while it happened.
      const lines = bA
        ? measureLines({
            from: d.a.price, to: bA.price, bars: n,
            seconds: (Date.parse(bA.time) - Date.parse(d.a.time)) / 1000,
            volume: volumeBetween(d.a, bA),
          })
        : [priceText]
      const cx = box.x + box.w / 2
      const wide = Math.max(...lines.map(t => t.length)) * 6.1 + 18
      const tall = lines.length * 14 + 10
      // Below the span when there is room beneath it, above it otherwise —
      // the label must never be the thing that leaves the pane.
      const below = box.y + box.h + 10 + tall <= plotH
      const ly = below ? box.y + box.h + 10 : Math.max(2, box.y - 10 - tall)
      return (
        <g key={d.id} opacity={op} style={sel}>
          <rect x={box.x} y={box.y} width={box.w} height={box.h} fill={tone} fillOpacity={0.12}
            stroke={tone} strokeWidth={1} strokeDasharray={dash} />
          {/* Which way it went: down the middle from the first price to the
              second, and along to where it ended. */}
          <line x1={cx} y1={a.y} x2={cx} y2={bAt.y} stroke={tone} strokeWidth={1.5} />
          <path d={`M${cx - 4} ${bAt.y - (up ? -6 : 6)} L${cx} ${bAt.y} L${cx + 4} ${bAt.y - (up ? -6 : 6)}`}
            fill="none" stroke={tone} strokeWidth={1.5} />
          <line x1={box.x} y1={bAt.y} x2={box.x + box.w} y2={bAt.y} stroke={tone} strokeWidth={1.5} />
          <path d={`M${box.x + box.w - 6} ${bAt.y - 4} L${box.x + box.w} ${bAt.y} L${box.x + box.w - 6} ${bAt.y + 4}`}
            fill="none" stroke={tone} strokeWidth={1.5} />
          <g>
            <rect x={cx - wide / 2} y={ly} width={wide} height={tall} rx={4} fill={tone} />
            {lines.map((t, i) => (
              <text key={i} x={cx} y={ly + 16 + i * 14} textAnchor="middle" fill="var(--background)"
                fontSize={11} fontWeight={600} className="tnum">{t}</text>
            ))}
          </g>
          {hitBox}
          {handle(a, "a")}{handle(bAt, "b")}
          {lockGlyph(a)}
        </g>
      )
    }
    if (d.kind === "pricerange") {
      const cx = box.x + box.w / 2
      return (
        <g key={d.id} opacity={op} style={sel}>
          <rect x={box.x} y={box.y} width={box.w} height={box.h} fill={tone} fillOpacity={0.08} />
          <line x1={box.x} y1={a.y} x2={box.x + box.w} y2={a.y} stroke={tone} strokeWidth={1} />
          <line x1={box.x} y1={bAt.y} x2={box.x + box.w} y2={bAt.y} stroke={tone} strokeWidth={1} />
          <line x1={cx} y1={a.y} x2={cx} y2={bAt.y} stroke={tone} strokeWidth={1} strokeDasharray="3 3" />
          <text x={cx} y={box.y + box.h / 2 + 4} textAnchor="middle" fill={tone} fontSize={11} className="tnum"
            paintOrder="stroke" stroke="var(--background)" strokeWidth={3}>{priceText}</text>
          {hitBox}
          {handle(a, "a")}{handle(bAt, "b")}
          {lockGlyph(a)}
        </g>
      )
    }
    // daterange
    return (
      <g key={d.id} opacity={op} style={sel}>
        <rect x={box.x} y={0} width={box.w} height={plotH} fill={color} fillOpacity={0.05} />
        <line x1={box.x} y1={0} x2={box.x} y2={plotH} stroke={color} strokeWidth={1} strokeDasharray="3 3" />
        <line x1={box.x + box.w} y1={0} x2={box.x + box.w} y2={plotH} stroke={color} strokeWidth={1} strokeDasharray="3 3" />
        <line x1={box.x} y1={a.y} x2={box.x + box.w} y2={a.y} stroke={color} strokeWidth={1} />
        <text x={box.x + box.w / 2} y={a.y - 6} textAnchor="middle" fill={color} fontSize={11} className="tnum"
          paintOrder="stroke" stroke="var(--background)" strokeWidth={3}>{timeText}</text>
        {hitBox}
        {handle(a, "a")}{handle(bAt, "b")}
        {lockGlyph(a)}
      </g>
    )
  }

  const ghost = (() => {
    if (tool === "none" || !pending.length || !cursor) return null
    const g: Drawing = { id: "ghost", kind: tool, a: pending[0] }
    if (pending[1]) g.b = pending[1]
    return shape(g, true)
  })()

  const sel = selected ? drawings.find(d => d.id === selected) ?? null : null
  armRef.current = k => onArm?.(k)

  return (
    <div
      ref={wrap}
      onClick={onClick}
      onMouseMove={onMove}
      className="absolute inset-0"
      style={{
        height,
        // Above the chart's own canvases, which carry their own stacking and
        // would otherwise swallow the click that places a drawing.
        zIndex: 10,
        // Only intercept the mouse while a tool is armed — otherwise the chart
        // keeps its own crosshair, pan and zoom, and only the drawings
        // themselves (each opts back in) take the pointer.
        pointerEvents: tool === "none" ? "none" : "auto",
        cursor: tool === "none" ? "default" : "crosshair",
      }}
    >
      {visible && (
        <svg width="100%" height={height} className="pointer-events-none absolute inset-0">
          {list.map(d => shape(d))}
          {scratch && shape(scratch)}
          {ghost}
        </svg>
      )}

      {/* Inline text entry, at the point clicked. Enter keeps it, Escape does
          not; an empty label is not a drawing. */}
      {editing && (
        <input
          autoFocus
          data-drawing-ui
          value={editing.value}
          onChange={e => setEditing({ ...editing, value: e.target.value })}
          onKeyDown={e => {
            if (e.key === "Enter") {
              const text = editing.value.trim()
              if (editing.id) { if (text) patch(editing.id, { text }); else remove(editing.id) }
              else if (text) commit({ id: nextId(), kind: "text", a: editing.at, text })
              else onToolDone()
              setEditing(null)
            }
            if (e.key === "Escape") { setEditing(null); if (!editing.id) onToolDone() }
            e.stopPropagation()
          }}
          onBlur={() => { if (!editing.value.trim() && !editing.id) { setEditing(null); onToolDone() } }}
          placeholder="Type, then Enter"
          className="absolute z-20 h-[24px] w-[160px] border border-accent bg-popover px-2 text-caption font-semibold text-foreground outline-none"
          style={{ left: editing.px.x - 4, top: editing.px.y - 18, pointerEvents: "auto" }}
        />
      )}

      {/* The property strip for the selected drawing. */}
      {sel && !editing && (
        <DrawingProps
          d={sel}
          box={boxOf(sel)}
          plotW={plotW}
          plotH={plotH}
          onPatch={p => patch(sel.id, p)}
          onRemove={() => remove(sel.id)}
          onEditText={sel.kind === "text" ? () => {
            const p = project(sel.a)
            if (p) setEditing({ id: sel.id, at: sel.a, px: p, value: sel.text ?? "" })
          } : undefined}
        />
      )}
    </div>
  )
}

type Box = { x0: number; x1: number; y0: number; y1: number }

/** Room kept between the strip and the drawing, and the plot's edges. */
const STRIP_GAP = 10

/** Colour, weight, dash, lock, delete — the strip that appears over a
 * selected drawing. Their floating toolbar, in this terminal's skin.
 *
 * It sits at the FOOT of the plot, centred, just above the date axis and
 * the range buttons (2026-09-18). Pinned to the plot's top-left it covered
 * the legend, the price and the day's open/high/low/close; over the drawing
 * it covered the price action. */
function DrawingProps({ d, box, plotW, plotH, onPatch, onRemove, onEditText }: {
  d: Drawing
  box: Box | null
  plotW: number
  plotH: number
  onPatch: (p: Partial<Drawing>) => void
  onRemove: () => void
  onEditText?: () => void
}) {
  const st = d.style ?? {}
  const color = st.color ?? DEFAULT_COLOR
  const setStyle = (p: Partial<Style>) => onPatch({ style: { ...st, ...p } })
  const fillable = ["rect", "ellipse", "channel", "fib"].includes(d.kind)
  const icon = (active: boolean) => btnCls({ variant: "ghost", icon: true, active })
  const word = (active: boolean) => btnCls({ variant: "ghost", active })

  // The strip's own size, measured once it is on screen, so the placement
  // can centre it and keep it inside the plot.
  const self = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = self.current
    if (el && (el.offsetWidth !== size.w || el.offsetHeight !== size.h)) {
      setSize({ w: el.offsetWidth, h: el.offsetHeight })
    }
  })
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)))
  // Docked at the foot of the plot, centred, just over the date axis and
  // the range row beneath the chart (the owner's call, 2026-09-18). Only
  // when the drawing itself reaches down there does the strip move up to
  // sit just above it, so it never covers what is being edited.
  const left = clamp(plotW / 2 - size.w / 2, STRIP_GAP, plotW - size.w - STRIP_GAP)
  let top = Math.max(STRIP_GAP, plotH - size.h - STRIP_GAP)
  if (box && box.y1 >= top - STRIP_GAP && box.x1 >= left && box.x0 <= left + size.w) {
    top = clamp(box.y0 - size.h - STRIP_GAP, STRIP_GAP, top)
  }

  return (
    <div ref={self} data-drawing-ui data-slot="dialog"
      className="absolute z-30 flex flex-wrap items-center gap-0.5 rounded-md border border-card-border bg-card p-1 shadow-card"
      // Never wider than the plot: in a narrow pane the full strip is wider
      // than the chart and lost its lock and delete off the edge, so it
      // wraps to a second row instead.
      style={{
        left, top, maxWidth: Math.max(160, plotW - 2 * STRIP_GAP), pointerEvents: "auto",
        visibility: size.w ? "visible" : "hidden",
      }}
      onMouseDown={e => e.stopPropagation()}>
      {PALETTE.map(p => (
        <button key={p.id} type="button" title={p.label} aria-label={p.label} aria-pressed={color === p.css}
          onClick={() => setStyle({ color: p.css })}
          disabled={!!d.locked}
          className={icon(color === p.css)}>
          <span className="block h-[12px] w-[12px] rounded-full border border-border" style={{ background: p.css }} />
        </button>
      ))}
      <span className="mx-1 h-4 w-px bg-border" />
      {[1, 2, 3].map(w => {
        const px = w === 1 ? 1.5 : w === 2 ? 2.5 : 3.5
        return (
          <button key={w} type="button" title={`Width ${w}`} aria-label={`Width ${w}`}
            aria-pressed={(st.width ?? 1.5) === px}
            onClick={() => setStyle({ width: px })} disabled={!!d.locked}
            className={icon((st.width ?? 1.5) === px)}>
            <span className="block w-[14px] bg-current" style={{ height: w }} />
          </button>
        )
      })}
      <span className="mx-1 h-4 w-px bg-border" />
      {(["solid", "dashed", "dotted"] as Dash[]).map(k => (
        <button key={k} type="button" title={k} aria-label={`${k} line`} aria-pressed={(st.dash ?? "solid") === k}
          onClick={() => setStyle({ dash: k })} disabled={!!d.locked}
          className={icon((st.dash ?? "solid") === k)}>
          <svg width="16" height="6"><line x1="0" y1="3" x2="16" y2="3" stroke="currentColor" strokeWidth="1.5" strokeDasharray={DASHES[k]} /></svg>
        </button>
      ))}
      {fillable && (
        <>
          <span className="mx-1 h-4 w-px bg-border" />
          <button type="button" title="Fill" aria-label="Toggle fill" aria-pressed={st.fill !== false}
            disabled={!!d.locked}
            onClick={() => setStyle({ fill: st.fill === false })}
            className={word(st.fill !== false)}>Fill</button>
        </>
      )}
      {onEditText && (
        <>
          <span className="mx-1 h-4 w-px bg-border" />
          <button type="button" title="Edit text" aria-label="Edit text" disabled={!!d.locked}
            onClick={onEditText} className={word(false)}>Edit</button>
        </>
      )}
      <span className="mx-1 h-4 w-px bg-border" />
      <button type="button" title={d.locked ? "Unlock" : "Lock"} aria-label={d.locked ? "Unlock drawing" : "Lock drawing"}
        aria-pressed={!!d.locked}
        onClick={() => onPatch({ locked: !d.locked })} className={icon(!!d.locked)}>
        {d.locked ? <Lock className="h-[14px] w-[14px]" /> : <LockOpen className="h-[14px] w-[14px]" />}
      </button>
      <button type="button" title="Delete" aria-label="Delete drawing" disabled={!!d.locked}
        onClick={onRemove} className={cn(icon(false), "hover:text-loss")}>
        <Trash2 className="h-[14px] w-[14px]" />
      </button>
    </div>
  )
}

/** The small monochrome glyphs of the tool column. Ours, not theirs — the
 * behaviour is the thing being matched, the icon set is trade dress. */
function Glyph({ kind }: { kind: Kind | "cursor" | "magnet" | "eye" | "eyeoff" | "lock" | "trash" | "undo" | "redo" }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const }
  const body: Record<string, React.ReactNode> = {
    cursor: <><circle cx="8" cy="8" r="4.5" {...p} /><path d="M8 1v3M8 12v3M1 8h3M12 8h3" {...p} /></>,
    trend: <><path d="M3 12L13 4" {...p} /><circle cx="3" cy="12" r="1.5" fill="currentColor" /><circle cx="13" cy="4" r="1.5" fill="currentColor" /></>,
    ray: <><path d="M3 12L14 3" {...p} /><circle cx="3" cy="12" r="1.5" fill="currentColor" /></>,
    extended: <path d="M1 14L15 2" {...p} />,
    hline: <><path d="M1.5 8h13" {...p} /><circle cx="8" cy="8" r="1.5" fill="currentColor" /></>,
    hray: <><path d="M4 8h10.5" {...p} /><circle cx="4" cy="8" r="1.5" fill="currentColor" /></>,
    vline: <><path d="M8 1.5v13" {...p} /><circle cx="8" cy="8" r="1.5" fill="currentColor" /></>,
    channel: <><path d="M2 11L12 3M4 14L14 6" {...p} /></>,
    rect: <rect x="2.5" y="3.5" width="11" height="9" {...p} />,
    ellipse: <ellipse cx="8" cy="8" rx="6" ry="4.5" {...p} />,
    arrow: <><path d="M3 13L13 3M13 3H7M13 3V9" {...p} /></>,
    fib: <><path d="M2 3.5h12M2 7h8M2 10h10M2 13h6" {...p} /></>,
    text: <text x="8" y="12.5" textAnchor="middle" fontSize="12" fontWeight="700" fill="currentColor">T</text>,
    measure: <><rect x="2.5" y="4.5" width="11" height="7" {...p} /><path d="M5.5 4.5v2M8 4.5v3M10.5 4.5v2" {...p} /></>,
    pricerange: <><path d="M8 2v12M5 5l3-3 3 3M5 11l3 3 3-3" {...p} /></>,
    daterange: <><path d="M2 8h12M5 5L2 8l3 3M11 5l3 3-3 3" {...p} /></>,
    magnet: <><path d="M4 2v6a4 4 0 0 0 8 0V2" {...p} /><path d="M4 2h3M9 2h3M4 6h3M9 6h3" {...p} /></>,
    eye: <><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" {...p} /><circle cx="8" cy="8" r="2" {...p} /></>,
    eyeoff: <><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" {...p} /><path d="M2 14L14 2" {...p} /></>,
    lock: <><rect x="3.5" y="7" width="9" height="7" {...p} /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" {...p} /></>,
    trash: <><path d="M3 4.5h10M6 4.5V3h4v1.5M4.5 4.5l.7 9h5.6l.7-9" {...p} /></>,
    undo: <><path d="M6 4L2.5 7.5 6 11" {...p} /><path d="M2.5 7.5H10a3.5 3.5 0 0 1 0 7H8" {...p} /></>,
    redo: <><path d="M10 4l3.5 3.5L10 11" {...p} /><path d="M13.5 7.5H6a3.5 3.5 0 0 0 0 7h2" {...p} /></>,
  }
  return <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{body[kind]}</svg>
}

/** The tool column, down the left of the chart the way theirs is. Each
 * group button arms the group's last-used tool; its small caret opens the
 * fly-out with the rest. Below the groups: magnet, show/hide, lock all,
 * clear, undo/redo. */
/** The label that appears beside a column button on hover — what the tool
 * is, and its shortcut. A real tooltip rather than the browser's `title`,
 * which takes a second to show and looks like nothing else on the page.
 * It is a CHILD of the button, so a greyed-out button fades only its icon:
 * fading the button faded this label to 35% too, and "Lock all drawings"
 * was unreadable on hover (2026-09-18). */
function Tip({ label, keys }: { label: string; keys?: string }) {
  return (
    <span aria-hidden="true"
      className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md border border-card-border bg-card px-2 py-1 text-label font-semibold text-foreground opacity-0 shadow-card transition-opacity group-hover:opacity-100">
      {label}{keys && <span className="ml-1.5 text-label text-muted-foreground">{keys}</span>}
    </span>
  )
}

export function DrawingToolbar({
  tool, onTool, magnet, onMagnet, visible, onVisible, count, allLocked, onLockAll,
  onClear, onClose, onUndo, onRedo, canUndo, canRedo, closable = true,
}: {
  /** Whether the column can be closed. The workspace keeps it always on. */
  closable?: boolean
  tool: Tool
  onTool: (t: Tool) => void
  magnet: boolean
  onMagnet: (m: boolean) => void
  visible: boolean
  onVisible: (v: boolean) => void
  count: number
  allLocked: boolean
  onLockAll: () => void
  onClear: () => void
  onClose: () => void
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
}) {
  const [open, setOpen] = useState<string | null>(null)
  const [last, setLast] = useState<Record<string, Kind>>({})
  const box = useRef<HTMLDivElement>(null)

  // A tool armed from the keyboard is "last used" too — the group button
  // shows whatever is drawing, however it was picked.
  useEffect(() => {
    if (tool === "none") return
    const g = TOOL_GROUPS.find(g => g.tools.some(t => t.id === tool))
    if (g && last[g.id] !== tool) setLast(l => ({ ...l, [g.id]: tool }))
  }, [tool, last])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(null) }
    document.addEventListener("mousedown", away)
    return () => document.removeEventListener("mousedown", away)
  }, [open])

  const arm = (k: Kind) => {
    const g = TOOL_GROUPS.find(g => g.tools.some(t => t.id === k))
    if (g) setLast(l => ({ ...l, [g.id]: k }))
    onTool(tool === k ? "none" : k)
    setOpen(null)
  }

  const cell = (on: boolean, extra = "") =>
    `group relative flex h-[28px] w-[30px] items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:hover:bg-transparent disabled:[&>svg]:opacity-35 ${
      on ? "bg-foreground/10 !text-foreground" : ""} ${extra}`

  return (
    <div ref={box} data-drawing-ui
      className="relative flex w-[34px] shrink-0 flex-col items-center gap-px border-r border-row-rule bg-panel py-1">
      <button type="button" aria-label="Crosshair" aria-pressed={tool === "none"}
        onClick={() => onTool("none")} className={cell(tool === "none")}>
        <Glyph kind="cursor" /><Tip label="Crosshair" keys="Esc" />
      </button>
      <span className="my-1 h-px w-5 bg-border" />
      {TOOL_GROUPS.map(g => {
        const current = last[g.id] ?? g.tools[0].id
        const on = g.tools.some(t => t.id === tool)
        return (
          <div key={g.id} className="relative">
            <button type="button"
              aria-label={g.label} aria-pressed={on}
              onClick={() => arm(current)} className={cell(on)}>
              <Glyph kind={current} />
              {open !== g.id && (
                <Tip label={g.tools.find(t => t.id === current)?.label ?? g.label}
                  keys={g.tools.find(t => t.id === current)?.key} />
              )}
              {g.tools.length > 1 && (
                <span role="button" aria-label={`More ${g.label.toLowerCase()} tools`}
                  onClick={e => { e.stopPropagation(); setOpen(o => (o === g.id ? null : g.id)) }}
                  className="absolute bottom-0 right-0 h-[9px] w-[9px] text-[7px] leading-[9px] text-muted-foreground hover:text-foreground">◢</span>
              )}
            </button>
            {open === g.id && (
              <div data-slot="dialog"
                className={`pop-in absolute left-full top-0 z-40 ml-1 w-[220px] ${menuPanelCls}`}>
                <div className={menuHeadCls}>{g.label}</div>
                {g.tools.map(t => (
                  <button key={t.id} type="button" onClick={() => arm(t.id)}
                    className={`${menuItemCls} gap-2.5 text-foreground ${
                      tool === t.id ? "bg-foreground/[0.08] font-semibold" : ""}`}>
                    <Glyph kind={t.id} />
                    <span className="flex-1">{t.label}</span>
                    {t.key && <span className="text-label text-muted-foreground">{t.key}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })}
      <span className="my-1 h-px w-5 bg-border" />
      <button type="button" aria-label="Magnet"
        aria-pressed={magnet} onClick={() => onMagnet(!magnet)} className={cell(magnet)}>
        <Glyph kind="magnet" /><Tip label={magnet ? "Magnet on — snaps to open, high, low, close" : "Magnet — snap to open, high, low, close"} />
      </button>
      <button type="button"
        aria-label={visible ? "Hide drawings" : "Show drawings"}
        onClick={() => onVisible(!visible)} className={cell(!visible)}>
        <Glyph kind={visible ? "eye" : "eyeoff"} /><Tip label={visible ? "Hide drawings" : "Show drawings"} />
      </button>
      <button type="button" aria-label="Lock all drawings"
        aria-pressed={allLocked} onClick={onLockAll} disabled={!count} className={cell(allLocked)}>
        <Glyph kind="lock" /><Tip label={allLocked ? "Unlock all drawings" : "Lock all drawings"} />
      </button>
      <button type="button"
        aria-label="Remove all drawings" onClick={onClear} disabled={!count} className={cell(false, "hover:!text-loss")}>
        <Glyph kind="trash" /><Tip label={count ? `Remove all ${count} drawing${count === 1 ? "" : "s"}` : "Nothing to remove"} />
      </button>
      <span className="my-1 h-px w-5 bg-border" />
      <button type="button" aria-label="Undo" onClick={onUndo} disabled={!canUndo} className={cell(false)}>
        <Glyph kind="undo" /><Tip label="Undo" keys="⌘Z" />
      </button>
      <button type="button" aria-label="Redo" onClick={onRedo} disabled={!canRedo} className={cell(false)}>
        <Glyph kind="redo" /><Tip label="Redo" keys="⇧⌘Z" />
      </button>
      <div className="flex-1" />
      {closable && (
        <button type="button" aria-label="Close drawing tools"
          onClick={onClose} className={cell(false)}>✕<Tip label="Close drawing tools" /></button>
      )}
    </div>
  )
}
