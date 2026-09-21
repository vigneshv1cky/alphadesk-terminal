import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import type { ChartBar } from "@/lib/api"
import {
  clampView, indexToX, padRangeInset, priceDecimals, priceTicks, priceTicksLog, priceToY,
  RIGHT_GAP, scaledRange, visibleExtent, xToIndex, yToPrice, zoomAt, type Scale,
} from "@/lib/chartScales"
import { columnBucket, columnHeight, paneAxisLabel, paneExtent, sessionLayout, steadyColumnMax, volumeColumns, type Pane, type PaneSeries } from "@/components/chart/panes"
import { heikinAshi, type SeriesKind } from "@/lib/series"
import { barCloseCountdown, countdownLabel, thinTicks, timeAxisTicks, timeParts } from "@/lib/chartTime"
import { provisionalSlots } from "@/lib/provisional"

export type { SeriesKind }

/** The chart renderer.
 *
 * Ours rather than a library's, and SVG rather than canvas, which is the same
 * choice AlphaSpace made. The reason to own it is control: every axis label,
 * every tick, the exact crosshair behaviour and the pane layout answer to this
 * file instead of to another project's options object.
 *
 * PERFORMANCE — the thing that makes hand-rolled SVG charts fall over is one
 * element per bar. At 6,937 daily bars that is 14,000 nodes and every pan
 * re-lays-out the document. So candles are drawn as FOUR paths (up bodies, up
 * wicks, down bodies, down wicks) built as strings, and volume as two. Node
 * count is then constant no matter how much history is loaded.
 *
 * PROJECTION — `timeToCoordinate` and `priceToCoordinate` are exposed with the
 * same shape the drawing layer already consumed from the previous library, so
 * the ten drawing tools work against this renderer untouched.
 */

export type ScaleMode = "linear" | "log" | "percent"

export type Projection = {
  timeToCoordinate: (t: string) => number | null
  priceToCoordinate: (p: number) => number | null
  coordinateToTime: (x: number) => string | null
  coordinateToPrice: (y: number) => number | null
}

const AXIS_W = 62      // right price gutter
/** How much history the cushion fetches ahead of the reader: a pan's worth,
 * not a screenful. A screenful was 1,500 bars and 170KB per chart. */
const CUSHION_BARS = 600
const AXIS_H = 22      // bottom time gutter
// Breathing room between the newest bar and the price axis. Reserved in the
// SCALE rather than added as a one-off margin on the initial view, so it
// survives every zoom and pan instead of closing up the first time you touch
// the chart. The grid, the axis labels and the price tag still run the full
// width — the gap is for the series, which otherwise ends flush against the
// numbers describing it.
const AXIS_GAP = 12

export function ChartCanvas({
  bars, kind, scale: scaleMode, height, panes = [],
  gain, loss, accent, grid, text, tagBg, tagFg, tagBorder, bg = "#f3f2f2",
  onProjection, onHover, overlays = [], seriesId, intraday = false, onRemovePane,
  onResizePane, onPaneSettings,
  timeZone = "America/New_York", interval, priceLine = true, live = false, controlRef, onContextMenu,
  compares = [], topInset = 0,
  ink,
  onNeedHistory, focusFrom = 0, historyNote, provisional = [],
}: {
  /** One exchange's closes after the last bar of a DELAYED series, drawn as
   * a dashed provisional line spaced by time. Never bars. lib/provisional. */
  provisional?: { t: string; c: number }[]
  /** Why there is nothing before the oldest bar — the feed's reach at this
   * interval — drawn at the left edge once the reader is there. */
  historyNote?: string | null
  /** The bar index a fresh series opens on — the range's own span, with
   * the server's buffer before it left as history to pan into. */
  focusFrom?: number
  /** Called when the view nears the oldest bar — the reader is panning
   * into history the series does not hold yet. The owner fetches a page
   * and prepends it; the view is shifted by the prepended count so nothing
   * moves under the pointer. */
  onNeedHistory?: (need?: number) => void
  /** Full-strength ink, for the heavier calendar labels on the time axis. */
  ink?: string
  /** Session tints behind the plot: pre-market, after-hours, overnight. */
  sessionPre?: string
  sessionAfter?: string
  sessionNight?: string
  sessionWeekend?: string
  /** Pixels at the top of the price pane the series keeps out of — the
   * height of a legend drawn over the plot, so the line never runs under
   * the readout. Nothing else moves: the axis and the grid still use the
   * whole pane. */
  topInset?: number
  /** Other symbols on this pane, aligned to these bars, drawn percent-rebased
   * to the first visible bar. Only meaningful on the percent scale. */
  compares?: { symbol: string; color: string; points: { t: string; v: number }[] }[]
  /** How the axis and the hover stamp label instants. */
  timeZone?: string
  /** The bar interval served, for the countdown to the forming bar's close. */
  interval?: string
  /** The dashed rule at the last price (the tag always draws). */
  priceLine?: boolean
  /** Whether the last bar is still forming — only then does a countdown mean
   * anything. */
  live?: boolean
  /** Filled with the view controls, so a menu outside can reset the view. */
  controlRef?: React.MutableRefObject<{ reset: () => void; wheel: (e: WheelEvent) => void } | null>
  /** Right-click on the plot: where, and what price and time sit there. */
  onContextMenu?: (at: { clientX: number; clientY: number; price: number | null; time: string | null }) => void
  /** Drag a pane's top edge. Down shrinks the pane, up grows it; the caller
   * owns the height and hands it back through `panes`. */
  onResizePane?: (id: string, height: number) => void
  /** The gear on a pane's header. */
  onPaneSettings?: (id: string) => void
  bars: ChartBar[]
  kind: SeriesKind
  scale: ScaleMode
  height: number
  /** Bands stacked under the price, each with its own y scale but sharing the
   * x scale — volume, RSI, MACD, fundamentals. */
  panes?: Pane[]
  gain: string
  loss: string
  accent: string
  grid: string
  text: string
  /** Crosshair chip colours — a muted surface, not the muted text colour. */
  tagBg: string
  tagFg: string
  tagBorder: string
  /** The ground — what a filled tag paints its label in. */
  bg?: string
  /** Handed out on every layout change so annotations can project against it. */
  onProjection?: (p: Projection | null) => void
  onHover?: (bar: ChartBar | null, at: { x: number; y: number } | null) => void
  /** Extra lines drawn over the price pane, already in price space. */
  overlays?: { color: string; points: { t: string; v: number }[]; width?: number }[]
  /** Identity of the SERIES — symbol, range and interval. What resets the
   * view. Distinct from `bars`, which now arrives afresh on every poll. */
  seriesId?: string
  /** Whether these bars are INTRADAY. Only then do session boundaries mean
   * anything: on daily bars every bar is already one session. */
  intraday?: boolean
  /** Remove a pane from its own header. Omitted, no control is drawn. */
  onRemovePane?: (id: string) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  // The live wheel handler, so the drawing layer over the plot can hand
  // its own wheel events back to the chart (see the wheel effect below).
  const wheelRef = useRef<((e: WheelEvent) => void) | null>(null)
  const [box, setBox] = useState({ w: 0, h: height })
  // Opens on the range's focus from the first paint: the effect below
  // resets only when the series CHANGES, and at mount it has not.
  const [view, setView] = useState<{ from: number; to: number } | null>(
    () => (bars.length ? { from: Math.min(focusFrom, Math.max(0, bars.length - 2)), to: bars.length } : null))
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ x: number; from: number; to: number } | null>(null)
  // State, not just the ref: the grab cursor is rendered, and a ref mutation
  // does not re-render, so reading drag.current in the style never changed it.
  const [panning, setPanning] = useState(false)
  /** Manual price-scale zoom, 1 = fit the visible bars. Dragging the price
   * gutter changes it; double-clicking there puts it back to fitting. */
  const [yZoom, setYZoom] = useState(1)
  /** The price range the reader set BY HAND, in the axis' own units, or null
   * while the scale fits the bars on screen. Held absolutely rather than as a
   * factor over the fit, so panning through history does not move it. */
  const [held, setHeld] = useState<{ min: number; max: number } | null>(null)
  const yDrag = useRef<{ y: number; range: { min: number; max: number } } | null>(null)
  // A held range is in the units of the axis it was set on: dollars on the
  // linear and log scales, per cent on the rebased one. Changing which axis
  // is drawn hands the scale back to the fit rather than keeping numbers
  // that no longer mean anything.
  useEffect(() => { setHeld(null) }, [scaleMode])
  /** Rendered, so the ns-resize cursor holds for the WHOLE gesture instead of
   * reverting to the crosshair the moment the pointer leaves the gutter. */
  const [yResizing, setYResizing] = useState(false)
  /** The time gutter's mirror of the price-scale stretch: dragging it
   * stretches the bar spacing, anchored at the RIGHT edge of the view — the
   * newest visible bar stays put while history compresses or expands, which
   * is where the eye is during the gesture. Double-click fits the series. */
  const xDrag = useRef<{ x: number; from: number; to: number } | null>(null)
  const [xResizing, setXResizing] = useState(false)
  /** A pane divider being dragged: which pane, where it started, how tall
   * it was. Down shrinks the pane below the divider. */
  const paneDrag = useRef<{ id: string; y: number; h: number } | null>(null)
  // One update per frame. A price-scale change invalidates every path string
  // and re-fires the projection effect (a setState in the parent), so running
  // that per mousemove event does several times the work a frame can show.
  const yFrame = useRef<number | null>(null)
  const yNext = useRef<{ min: number; max: number } | null>(null)
  useEffect(() => () => { if (yFrame.current != null) cancelAnimationFrame(yFrame.current) }, [])
  const clipId = useId()
  /** The provisional line's slots past the last bar, and how many the view
   * keeps room for at the live edge. */
  const provSlots = useMemo(
    () => provisionalSlots(bars[bars.length - 1]?.t, provisional, interval),
    [provisional, bars.length, bars[bars.length - 1]?.t, interval])  // eslint-disable-line react-hooks/exhaustive-deps
  const extra = provSlots.length ? provSlots[provSlots.length - 1].k : 0
  const edgeLen = bars.length + extra

  useEffect(() => {
    if (!host.current) return
    // Measure from the delivered entry, never back through the ref: delivery
    // is async, and the removal of the element itself queues one final
    // callback that can land after unmount has already cleared the ref.
    // (The host carries no border or padding, so contentRect is the same
    // box getBoundingClientRect measured.)
    const ro = new ResizeObserver(entries => {
      const r = entries[0]?.contentRect
      if (r) setBox({ w: r.width, h: r.height })
    })
    ro.observe(host.current)
    return () => ro.disconnect()
  }, [])

  /** What a new poll must NOT do is move the chart under the reader.
   *
   * Resetting on `bars` was right when the series was fetched once: a new
   * array meant a new series. Now that it refreshes every 30 seconds, a new
   * array usually means the same series with one more bar on it, and resetting
   * there would throw away the reader's zoom twice a minute.
   *
   * So the reset keys on the SERIES identity. Within one series, growth is
   * followed only if the view was already sitting at the live edge — pan the
   * window along so the newest bar stays visible. A reader who has scrolled
   * back to look at yesterday is left exactly where they are.
   */
  /** Whether the reader has moved the view since the series opened. History
   * is asked for only then: a range whose focus starts at bar 0 (a daily
   * range, 5D with exactly five sessions) would otherwise page at rest, and
   * a page is a fetch. */
  const userMoved = useRef(false)
  /** Where a fresh series opens: the range's own span, ending a little short
   * of the price axis. Without that gap the newest candle is pressed against
   * the axis and the live price tag sits on top of it (2026-09-16). */
  const focusView = () => {
    if (!bars.length) return null
    const from = Math.min(focusFrom, Math.max(0, bars.length - 2))
    return { from, to: edgeLen + Math.max(1, (edgeLen - from) * RIGHT_GAP) }
  }
  const prevSeries = useRef({ id: seriesId, len: bars.length, lastT: bars[bars.length - 1]?.t })
  useEffect(() => {
    const was = prevSeries.current
    prevSeries.current = { id: seriesId, len: bars.length, lastT: bars[bars.length - 1]?.t }
    if (was.id !== seriesId) {
      setView(focusView())
      userMoved.current = false
      // A hand-set price scale belongs to the series it was set on; carrying
      // it onto a different symbol or range would silently misframe the new one.
      setYZoom(1)
      setHeld(null)
      return
    }
    // Within one series the array can change three ways at once: a history
    // page PREPENDED at the left, the poll window's oldest bar DROPPED off
    // the front, and a new bar APPENDED at the right. All three are read
    // off where the old last bar now sits — its index moved by exactly the
    // net change at the left — so the view is shifted by that amount and
    // the chart stays put under the reader; then, and only if the view was
    // sitting at the live edge, it follows the appended bars.
    if (!was.lastT) return
    let idxLast = -1
    for (let i = bars.length - 1; i >= 0; i--) if (bars[i].t === was.lastT) { idxLast = i; break }
    if (idxLast < 0) return                       // not the same series' bars; leave the view
    const shift = idxLast - (was.len - 1)
    const appended = bars.length - 1 - idxLast
    if (!shift && !appended) return
    setView(v => {
      if (!v) return v
      const atEdge = v.to >= was.len - 0.5
      const f = v.from + shift, t = v.to + shift
      return atEdge && appended ? { from: f + appended, to: t + appended } : { from: f, to: t }
    })
  }, [seriesId, bars])  // eslint-disable-line react-hooks/exhaustive-deps

  /** The provisional line growing (or shrinking as real bars replace it)
   * moves the live edge; a view sitting at that edge follows it. */
  const prevExtra = useRef(extra)
  useEffect(() => {
    const was = prevExtra.current
    prevExtra.current = extra
    if (was === extra) return
    setView(v => (v && v.to >= bars.length + was - 0.5 ? { from: v.from + (extra - was), to: v.to + (extra - was) } : v))
  }, [extra])  // eslint-disable-line react-hooks/exhaustive-deps

  /** Ask for history when the view nears the oldest bar AFTER the reader has
   * moved it. The callback is read through a ref so a pan does not re-run
   * this on every frame's closure; the owner throttles by its own loading
   * flag. */
  const needHistory = useRef(onNeedHistory)
  needHistory.current = onNeedHistory
  // Keyed on `from` itself, not only on the near-left flag: a range whose
  // view OPENS near the oldest bar (5D with few sessions, a daily range)
  // had the flag true from the start, so the reader's pans changed nothing
  // and no page was ever asked for. The owner's loading/done flags make the
  // repeated calls free.
  // Zoomed out, the view reaches PAST the oldest bar: everything left of
  // index zero is blank. Asking for a page one range-span deep filled a
  // sliver of it and the reader watched the line creep in, so the ask
  // carries the whole gap plus a screen of margin (2026-09-16).
  const viewFrom = view?.from ?? 0
  const viewTo = view?.to ?? 0
  const nearLeft = bars.length > 0 && viewFrom < 40
  useEffect(() => {
    if (!nearLeft || !userMoved.current) return
    const width = Math.max(1, viewTo - viewFrom)
    needHistory.current?.(Math.ceil(Math.max(0, -viewFrom) + width))
  }, [nearLeft, bars.length, viewFrom, viewTo])

  /** THE CUSHION (2026-09-16, made cheap the same day). One screenful of
   * older bars is fetched ahead of the reader, so the first pan draws from
   * bars already in hand instead of waiting on a round trip.
   *
   * It is a WHOLE EXTRA REQUEST per chart, and the first version paid for it
   * at the worst moment: 400ms after the series landed, 1,500 bars, on every
   * tile at once, while the page was still fetching everything else it
   * needed — measured at 0.6s and 170KB for one chart, and a board has
   * several. So it now waits for the browser to be idle, asks for a pan's
   * worth rather than a screenful, and does not run at all in a tab nobody
   * is looking at. Once per series; the near-left ask above owns the case
   * where the reader is already pulling history in. */
  const cushioned = useRef("")
  useEffect(() => {
    if (!bars.length || !view || cushioned.current === seriesId) return
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return
    cushioned.current = seriesId ?? ""
    const want = Math.ceil(Math.min(Math.max(1, view.to - view.from), CUSHION_BARS))
    const ric = (window as unknown as {
      requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number
      cancelIdleCallback?: (h: number) => void
    })
    if (ric.requestIdleCallback) {
      const h = ric.requestIdleCallback(() => needHistory.current?.(want), { timeout: 6_000 })
      return () => ric.cancelIdleCallback?.(h)
    }
    const id = window.setTimeout(() => needHistory.current?.(want), 2_500)
    return () => window.clearTimeout(id)
  }, [seriesId, bars.length, view])

  const panesH = panes.reduce((n, p) => n + p.height, 0)
  const priceH = Math.max(40, box.h - AXIS_H - panesH)
  const plotW = Math.max(10, box.w - AXIS_W)
  // Where the SERIES lives. `plotW` stays the full drawing width, so anything
  // that belongs to the axis rather than to the data keeps reaching it.
  const seriesW = Math.max(10, plotW - AXIS_GAP)
  const from = view?.from ?? 0
  const to = view?.to ?? Math.max(1, bars.length)

  /** What the SERIES is drawn from. Heikin Ashi redraws the bars; every
   * other kind draws the real ones. The hover readout, the price tag and the
   * projection all keep the real bars — the smoothing is for the eye. */
  const drawBars = useMemo(() => (kind === "heikin" ? heikinAshi(bars) : bars), [bars, kind])

  const { min, max } = useMemo(() => {
    const ext = { ...visibleExtent(drawBars, from, to) }
    // The provisional line is on screen past the last bar: fit it too, or a
    // move since the delayed bars would run off the pane.
    if (to > bars.length && provSlots.length) {
      for (const p of provSlots) { ext.min = Math.min(ext.min, p.c); ext.max = Math.max(ext.max, p.c) }
    }
    const fitted = (() => {
      if (scaleMode !== "percent") return padRangeInset(ext.min, ext.max, topInset, priceH)
      // Percent rebases to the first visible bar, so two names of very
      // different price can be compared on one axis.
      const base = bars[Math.max(0, Math.floor(from))]?.c
      if (!base) return padRangeInset(ext.min, ext.max, topInset, priceH)
      return padRangeInset((ext.min / base - 1) * 100, (ext.max / base - 1) * 100, topInset, priceH)
    })()
    // A PRICE SCALE SET BY HAND STAYS SET (2026-09-16). Dragging the gutter
    // used to scale whatever the visible bars fitted to, so the range moved
    // again the moment the reader panned — theirs holds the exact range
    // until it is handed back, and that is what makes it usable for reading
    // one level across a long stretch of history. Double-click the gutter to
    // return to fitting the bars on screen.
    if (held) return held
    if (yZoom === 1) return fitted
    // Expand or contract about the MIDDLE of the fitted range, so the series
    // stays put while the scale opens up around it rather than sliding. On
    // the log scale the middle is the LOG middle: the linear centre of 10 to
    // 1,000 is 505, which sits near the top of a log pane, and stretching
    // about it ran the series off the bottom (and compressing produced a
    // negative floor).
    if (scaleMode === "log" && fitted.min > 0) {
      const lo = Math.log(fitted.min), hi = Math.log(fitted.max)
      const c = (lo + hi) / 2, h = (hi - lo) / 2 / yZoom
      return { min: Math.exp(c - h), max: Math.exp(c + h) }
    }
    const centre = (fitted.min + fitted.max) / 2
    const half = (fitted.max - fitted.min) / 2 / yZoom
    return { min: centre - half, max: centre + half }
  }, [bars, drawBars, from, to, scaleMode, yZoom, held, topInset, priceH, provSlots])

  // Memoized on its six numbers, and that memo is load-bearing rather than an
  // optimization. `s` feeds the projection effect's dep array, and the effect
  // calls onProjection() — which is a setState in the parent. A fresh object
  // literal here made those deps differ on every render, so the effect re-ran
  // after every commit and set state again: an infinite render loop that React
  // ends by refusing to commit. The first paint had already landed, so the
  // board looked correct and then silently stopped responding to anything —
  // no symbol change, no chip, no toolbar. Keep every field primitive.
  const s: Scale = useMemo(
    () => ({ from, to, width: seriesW, height: priceH, min, max }),
    [from, to, seriesW, priceH, min, max],
  )
  const log = scaleMode === "log"
  const base = bars[Math.max(0, Math.floor(from))]?.c ?? 1
  const toDisplay = useCallback(
    (p: number) => (scaleMode === "percent" ? (p / base - 1) * 100 : p), [scaleMode, base])
  const fromDisplay = useCallback(
    (v: number) => (scaleMode === "percent" ? base * (1 + v / 100) : v), [scaleMode, base])

  const yOf = useCallback((price: number) => priceToY(s, toDisplay(price), log), [s, toDisplay, log])

  /** The bars' TIMESTAMPS as one key. A live trade rewrites the last bar's
   * OHLC and hands over a new array, and every memo keyed on the array
   * identity — the calendar parts, the session layout, the index map — was
   * re-running its full pass over thousands of bars once a second for a
   * change to one bar's close. None of them read a price; they are keyed on
   * the timestamps, which a tick never changes. */
  const timesKey = `${bars.length}|${bars[0]?.t ?? ""}|${bars[bars.length - 1]?.t ?? ""}`

  // Index lookups for projection. Built once per series rather than scanned.
  const indexByTime = useMemo(() => {
    const m = new Map<string, number>()
    bars.forEach((b, i) => m.set(b.t, i))
    return m
  }, [timesKey])  // eslint-disable-line react-hooks/exhaustive-deps

  /** Overlay and compare paths, built ONCE per view change and culled to the
   * bars on screen. They were string-built inline in render, so every
   * mousemove (a crosshair setState) and every countdown second re-walked
   * every point of every line: 28,000 lookups and toFixed calls per move
   * on a 7,000-bar series with four overlays. A point off the view starts a
   * new subpath when the line comes back, so the path is exact where it is
   * visible and empty where it is not. */
  const visLo = Math.floor(from) - 1, visHi = Math.ceil(to) + 1
  const overlayPaths = useMemo(() => overlays.map(o => {
    let d = "", pen = false
    for (const p of o.points) {
      const idx = indexByTime.get(p.t)
      if (idx == null || idx < visLo || idx > visHi) { pen = false; continue }
      d += `${pen ? "L" : "M"}${indexToX(s, idx + 0.5).toFixed(1)},${yOf(p.v).toFixed(1)}`
      pen = true
    }
    return { d, color: o.color, width: o.width ?? 1 }
  }), [overlays, s, yOf, visLo, visHi, indexByTime])
  const comparePaths = useMemo(() => {
    if (scaleMode !== "percent") return []
    return compares.flatMap(cs => {
      const byT = new Map(cs.points.map(p => [p.t, p.v]))
      let base: number | undefined
      for (let i = Math.max(0, Math.floor(from)); i < bars.length; i++) {
        const v = byT.get(bars[i].t)
        if (v != null) { base = v; break }
      }
      if (!base) return []
      let d = "", pen = false
      for (const p of cs.points) {
        const idx = indexByTime.get(p.t)
        if (idx == null || idx < visLo || idx > visHi) { pen = false; continue }
        d += `${pen ? "L" : "M"}${indexToX(s, idx + 0.5).toFixed(1)},${priceToY(s, (p.v / base - 1) * 100, log).toFixed(1)}`
        pen = true
      }
      return [{ symbol: cs.symbol, d, color: cs.color }]
    })
  }, [compares, scaleMode, s, log, from, visLo, visHi, bars, indexByTime])


  useEffect(() => {
    if (!onProjection) return
    if (!bars.length || !plotW) { onProjection(null); return }
    onProjection({
      timeToCoordinate: t => {
        const i = indexByTime.get(t)
        return i == null ? null : indexToX(s, i + 0.5)
      },
      priceToCoordinate: p => yOf(p),
      coordinateToTime: x => {
        const i = Math.round(xToIndex(s, x) - 0.5)
        return bars[Math.max(0, Math.min(bars.length - 1, i))]?.t ?? null
      },
      coordinateToPrice: y => fromDisplay(yToPrice(s, y, log)),
    })
  }, [onProjection, bars, indexByTime, s, yOf, fromDisplay, log, plotW])

  // ── interaction ─────────────────────────────────────────────────────────

  /** Wheel is bound here rather than as an `onWheel` prop because React
   * registers wheel on the root container as PASSIVE, which makes
   * `preventDefault()` silently do nothing — the chart would zoom while the
   * page scrolled underneath it at the same time. A non-passive listener on
   * the host element is the only way to own the gesture.
   *
   * Every wheel over the plot belongs to the chart, theirs' way (2026-09-10;
   * the plain vertical wheel was left to the page until then, so the
   * board's tile did not trap the scroll — the reader chose the chart's
   * behaviour over the page's on every surface):
   *
   *   vertical wheel → zoom about the pointer.
   *   ctrl/cmd+wheel → NOT the chart's (2026-09-10, the reader's call): it
   *     is left to the browser untouched. A trackpad pinch reports as a
   *     ctrl+wheel and so goes with it.
   *   sideways (trackpad swipe / shift+wheel) → pan. A swipe sends deltaX with
   *     deltaY at ~0; reading only deltaY meant every sideways swipe zoomed IN
   *     instead. The page does not scroll horizontally, so this costs nothing.
   *
   * preventDefault fires on all of them, which is why the listener must be
   * non-passive: React registers wheel on its root as passive, where
   * preventDefault silently does nothing at all.
   *
   * It must also stay ATTACHED for the whole gesture, which is why the deps
   * below hold nothing that panning changes. With `from`/`to` in there, every
   * wheel event tore the listener down and React re-attached it after the next
   * paint; a trackpad swipe fires ~100 events a second, so events kept landing
   * in the gap unprevented — and on macOS an unprevented horizontal wheel is
   * the back-navigation gesture. Swiping left to pan would leave the page.
   * The window is therefore read inside the state updater rather than closed
   * over here. */
  useEffect(() => {
    const el = host.current
    if (!el) return
    const total = edgeLen
    const onWheel: (e: WheelEvent) => void = (e: WheelEvent) => {
      if (!total) return
      if (e.ctrlKey || e.metaKey) return        // the browser's, not ours
      const sideways = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)
      const zooming = !sideways
      e.preventDefault()
      const x = e.clientX - el.getBoundingClientRect().left
      // Whichever axis actually carries the movement. Reading deltaY whenever
      // shift was held looked right and panned by exactly zero: the BROWSER
      // already rewrites a shift+wheel into deltaX, so the axis being read was
      // the one guaranteed to be 0. Platforms that do not rewrite it leave the
      // movement on deltaY, so both have to be tolerated.
      const delta = Math.abs(e.deltaX) >= Math.abs(e.deltaY) ? e.deltaX : e.deltaY
      // Zoom in proportion to the wheel's travel, not per event: a trackpad
      // flick is dozens of 1–10px events and a fixed 15% each slammed the
      // view to its floor or ceiling in one gesture. A notched mouse wheel
      // (100px a click) zooms about 28% a click; a 4px trackpad event, 1%.
      // deltaMode 1 is lines, 2 is pages.
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1
      const factor = Math.exp(Math.max(-0.5, Math.min(0.5, (e.deltaY * unit) / 400)))
      userMoved.current = true
      setView(prev => {
        const cur = prev ?? { from: 0, to: total }
        if (sideways && !zooming) {
          const shift = (delta / seriesW) * (cur.to - cur.from)
          return clampView(cur.from + shift, cur.to + shift, total)
        }
        // Only from/to/width are consulted by xToIndex and zoomAt — the price
        // axis plays no part in a horizontal gesture, so it is not rebuilt.
        const sc: Scale = { from: cur.from, to: cur.to, width: seriesW, height: 0, min: 0, max: 0 }
        return zoomAt(sc, xToIndex(sc, x), factor, total)
      })
    }
    // Also handed out on the control ref: the drawing layer covers the plot
    // while a tool is armed, and a wheel landing on it bubbles to the shared
    // parent, never to this sibling — so scrolling stopped zooming the
    // moment a tool was picked (2026-09-20). A wheel is not a drawing
    // gesture; the layer forwards it here.
    wheelRef.current = onWheel
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => { el.removeEventListener("wheel", onWheel); wheelRef.current = null }
  }, [bars.length, seriesW, edgeLen])

  /** The plot pan runs on POINTER events with capture, like the gutters: on
   * mouse events a drag died the moment the pointer crossed the tile's edge,
   * which in a narrow tile is almost at once. Only the primary button pans;
   * a gutter or divider that took the pointer first has set its own ref. */
  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || yDrag.current || xDrag.current || paneDrag.current) return
    try { (e.currentTarget as Element).setPointerCapture(e.pointerId) } catch { /* no live pointer (synthetic) */ }
    drag.current = { x: e.clientX, from, to }
    userMoved.current = true
    setPanning(true)
  }
  const onKey = (e: React.KeyboardEvent) => {
    const total = edgeLen
    if (!total) return
    const cur = view ?? { from: 0, to: total }
    const span = cur.to - cur.from
    const pan = (frac: number) => clampView(cur.from + span * frac, cur.to + span * frac, total)
    const zoom = (factor: number) => {
      const sc: Scale = { from: cur.from, to: cur.to, width: seriesW, height: 0, min: 0, max: 0 }
      return zoomAt(sc, (cur.from + cur.to) / 2, factor, total)
    }
    const next =
      e.key === "ArrowLeft" ? pan(e.shiftKey ? -0.5 : -0.1)
      : e.key === "ArrowRight" ? pan(e.shiftKey ? 0.5 : 0.1)
      : e.key === "+" || e.key === "=" ? zoom(1 / 1.25)
      : e.key === "-" || e.key === "_" ? zoom(1.25)
      : e.key === "Home" ? clampView(0, span, total)
      : e.key === "End" ? clampView(total - span, total, total)
      : null
    if (!next) return
    e.preventDefault()
    userMoved.current = true
    setView(next)
  }
  const onMove = (e: React.PointerEvent) => {
    if (!host.current) return
    const r = host.current.getBoundingClientRect()
    const x = e.clientX - r.left
    const y = e.clientY - r.top
    // A gutter owns its gesture via pointer capture; the host's job is to
    // not draw a crosshair through the middle of it.
    if (yDrag.current || xDrag.current) return
    if (drag.current) {
      const span = drag.current.to - drag.current.from
      const shift = ((drag.current.x - e.clientX) / seriesW) * span
      // Clamped like every other view change — an unclamped drag could push
      // the series off the edge and leave a blank chart with no way back.
      setView(clampView(drag.current.from + shift, drag.current.to + shift, edgeLen))
      return
    }
    if (x > plotW || y > priceH) { setCursor(null); onHover?.(null, null); return }
    setCursor({ x, y })
    const i = Math.round(xToIndex(s, x) - 0.5)
    onHover?.(bars[Math.max(0, Math.min(bars.length - 1, i))] ?? null, { x, y })
  }
  const stop = (e?: React.PointerEvent) => {
    if (e && drag.current) {
      try { (e.currentTarget as Element).releasePointerCapture(e.pointerId) } catch { /* not captured */ }
    }
    drag.current = null
    setPanning(false)
  }
  // Deliberately NOT cleared here or in leave(): the price gutter is a couple
  // of hundred pixels tall and a stretch runs past the tile edge almost at
  // once. Ending the resize on mouseleave made every drag of any size die
  // halfway, which is most of why this felt broken rather than merely fast.
  // Pointer capture keeps delivering to the gutter, and pointerup ends it.
  // A captured pan keeps running past the edge; only the crosshair leaves.
  const leave = () => { if (!drag.current) stop(); setCursor(null); onHover?.(null, null) }

  // ── geometry, built as path strings ─────────────────────────────────────
  const barW = Math.max(1, (seriesW / Math.max(1, to - from)) * 0.7)
  const half = barW / 2

  const paths = useMemo(() => {
    const upBody: string[] = [], downBody: string[] = []
    const upWick: string[] = [], downWick: string[] = []
    // Hollow candles: colour by close against the PREVIOUS close, fill by
    // close against open — four buckets, so a rising bar that closed under
    // its open reads as "up, but filled".
    const hollowUp: string[] = [], hollowDown: string[] = []
    const solidUp: string[] = [], solidDown: string[] = []
    const line: string[] = []
    const step: string[] = []
    const highs: string[] = [], lowsRev: string[] = []
    const colsUp: string[] = [], colsDown: string[] = []
    const lo = Math.max(0, Math.floor(from) - 1)
    const hi = Math.min(drawBars.length - 1, Math.ceil(to) + 1)
    let prevY: number | null = null
    let firstX: number | null = null, lastX: number | null = null

    for (let i = lo; i <= hi; i++) {
      const b = drawBars[i]
      if (!b) continue
      const x = indexToX(s, i + 0.5)
      if (x < -barW || x > seriesW + barW) continue
      const up = b.c >= b.o
      const rising = i > 0 ? b.c >= drawBars[i - 1].c : up
      const yO = yOf(b.o), yC = yOf(b.c), yH = yOf(b.h), yL = yOf(b.l)
      const X = x.toFixed(1)
      if (firstX == null) firstX = x
      lastX = x
      if (kind === "candles" || kind === "heikin" || kind === "bars" || kind === "hollow") {
        const wick = `M${X},${yH.toFixed(1)}L${X},${yL.toFixed(1)}`
        ;((kind === "hollow" ? rising : up) ? upWick : downWick).push(wick)
        if (kind === "bars") {
          // OHLC bars: ticks left for open, right for close.
          ;(up ? upBody : downBody).push(
            `M${(x - half).toFixed(1)},${yO.toFixed(1)}h${half.toFixed(1)}` +
            `M${X},${yC.toFixed(1)}h${half.toFixed(1)}`)
        } else {
          const top = Math.min(yO, yC)
          const h = Math.max(1, Math.abs(yC - yO))
          const body = `M${(x - half).toFixed(1)},${top.toFixed(1)}h${barW.toFixed(1)}v${h.toFixed(1)}h${(-barW).toFixed(1)}Z`
          if (kind === "hollow") {
            ;(up ? (rising ? hollowUp : hollowDown) : (rising ? solidUp : solidDown)).push(body)
          } else {
            ;(up ? upBody : downBody).push(body)
          }
        }
      } else if (kind === "highlow") {
        const h = Math.max(1, yL - yH)
        ;(up ? upBody : downBody).push(
          `M${(x - half).toFixed(1)},${yH.toFixed(1)}h${barW.toFixed(1)}v${h.toFixed(1)}h${(-barW).toFixed(1)}Z`)
      } else if (kind === "columns") {
        const h = Math.max(1, priceH - yC)
        ;(up ? colsUp : colsDown).push(
          `M${(x - half).toFixed(1)},${yC.toFixed(1)}h${barW.toFixed(1)}v${h.toFixed(1)}h${(-barW).toFixed(1)}Z`)
      } else {
        const Y = yC.toFixed(1)
        line.push(`${line.length ? "L" : "M"}${X},${Y}`)
        // A step holds the previous close until this bar, then jumps.
        step.push(step.length ? `L${X},${prevY!.toFixed(1)}L${X},${Y}` : `M${X},${Y}`)
        prevY = yC
        if (kind === "hlc") {
          highs.push(`${highs.length ? "L" : "M"}${X},${yH.toFixed(1)}`)
          lowsRev.unshift(`L${X},${yL.toFixed(1)}`)
        }
      }
    }
    const lineD = line.join("")
    const x0 = (firstX ?? 0).toFixed(1), x1 = (lastX ?? 0).toFixed(1)
    // The baseline sits at the middle of the visible scale — theirs defaults
    // to 50% — so the fill above reads as "over the middle of what you can
    // see" and below as under it.
    const baseY = priceH / 2
    return {
      upBody: upBody.join(""), downBody: downBody.join(""),
      upWick: upWick.join(""), downWick: downWick.join(""),
      hollowUp: hollowUp.join(""), hollowDown: hollowDown.join(""),
      solidUp: solidUp.join(""), solidDown: solidDown.join(""),
      colsUp: colsUp.join(""), colsDown: colsDown.join(""),
      line: lineD,
      step: step.join(""),
      // Closed at the LAST bar, not the plot's right edge: to the edge, the
      // fill ran on past the live price as a wedge to the bottom corner
      // (2026-09-19, the owner: "area looks odd").
      area: lineD ? `${lineD}L${x1},${priceH}L${x0},${priceH}Z` : "",
      baseArea: lineD ? `${lineD}L${x1},${baseY.toFixed(1)}L${x0},${baseY.toFixed(1)}Z` : "",
      baseY,
      hlc: highs.length ? `${highs.join("")}${lowsRev.join("")}Z` : "",
    }
  }, [drawBars, s, kind, yOf, barW, half, seriesW, priceH, from, to])

  /** Each pane's own geometry: offset, scale and batched paths. */
  const paneLayout = useMemo(() => {
    let offset = priceH
    return panes.map(pane => {
      const top = offset
      offset += pane.height
      const byTimeIdx = indexByTime
      // Bucketed BEFORE the extent is taken: a summed column is taller than any
      // bar inside it, so an extent measured on the raw points would let the
      // columns run straight out of the pane.
      const grouped = new Map<PaneSeries, ReturnType<typeof volumeColumns>>()
      for (const ser of pane.series) {
        if (ser.kind !== "histogram" || !ser.aggregate) continue
        const entries: { i: number; v: number; up: boolean }[] = []
        for (const p of ser.points) {
          const i = byTimeIdx.get(p.t)
          if (i == null || i < from - 1 || i > to + 1) continue
          entries.push({ i, v: p.v, up: bars[i].c >= bars[i].o })
        }
        grouped.set(ser, volumeColumns(entries, s, seriesW, 7))
      }
      // Only when EVERY series was grouped — a pane mixing a summed histogram
      // with a plain line would need both to agree on one axis, and they don't.
      const allGrouped = grouped.size > 0 && grouped.size === pane.series.length
      const onScreen = (t: string) => {
        const i = byTimeIdx.get(t)
        return i != null && i >= from - 1 && i <= to + 1
      }
      // A STEADY pane measures the whole series, not the bars on screen: a
      // quantity's column height is the reading, and a scale that re-fits as
      // the view moves makes a quiet bar look busy the moment the busy ones
      // scroll off (2026-09-21). The same bucket width the visible columns
      // are drawn with is used for the ceiling, so the two agree.
      const steadyCeiling = () => {
        let max = 0
        for (const ser of pane.series) {
          const per = ser.kind === "histogram" && ser.aggregate
            ? columnBucket(Math.max(1, to - from + 1), s, seriesW, 7)
            : 1
          max = Math.max(max, steadyColumnMax(ser.points, t => byTimeIdx.get(t), per))
        }
        return { min: 0, max: Math.max(1, max) }
      }
      const ext = pane.steady
        ? steadyCeiling()
        : allGrouped
          ? { min: 0, max: Math.max(1, ...[...grouped.values()].flat().map(c => c.v)) }
          : paneExtent(pane, onScreen)
      const inner = Math.max(10, pane.height - 6)
      const yIn = (v: number) => {
        const r = ext.max - ext.min
        return top + 3 + (r <= 0 ? inner / 2 : inner - ((v - ext.min) / r) * inner)
      }
      const zeroY = yIn(Math.min(Math.max(0, ext.min), ext.max))
      const byTime = byTimeIdx
      const drawn = pane.series.map(ser => {
        if (ser.kind === "histogram" && grouped.has(ser)) {
          const up: string[] = [], down: string[] = []
          for (const c of grouped.get(ser)!) {
            if (c.x < -c.w || c.x > seriesW + c.w) continue
            const h = columnHeight(c.v, zeroY, yIn(c.v))
            if (!h) continue
            const half2 = c.w / 2
            ;(c.up ? up : down).push(
              `M${(c.x - half2).toFixed(1)},${(zeroY - h).toFixed(1)}h${c.w.toFixed(1)}v${h.toFixed(1)}h${(-c.w).toFixed(1)}Z`)
          }
          return { kind: "histogram" as const, up: up.join(""), down: down.join(""),
                   color: ser.color, downColor: ser.downColor ?? ser.color }
        }
        if (ser.kind === "histogram") {
          const up: string[] = [], down: string[] = []
          const upWeak: string[] = [], downWeak: string[] = []
          let prev: number | null = null
          for (const p of ser.points) {
            const i = byTime.get(p.t)
            // Tracked before the visibility cut, so the first column on
            // screen still knows what it followed.
            const before = prev
            prev = p.v
            if (i == null) continue
            const x = indexToX(s, i + 0.5)
            if (x < -barW || x > seriesW + barW) continue
            const y = yIn(p.v)
            const h = columnHeight(p.v, zeroY, y)
            if (!h) continue
            // Grown AWAY from zero, so a column held up to the floor does not
            // reach across the zero line into the other half of the pane.
            const topY = y <= zeroY ? zeroY - h : zeroY
            // `signs` decides what "up" means: the value's own sign for MACD
            // and fundamentals, the bar's direction for volume.
            const isUp = ser.signs ? p.v >= 0 : (bars[i].c >= bars[i].o)
            // Shaded: a column shorter than the one before it is fading.
            const weak = !!ser.shade && before != null && Math.abs(p.v) < Math.abs(before)
            ;(isUp ? (weak ? upWeak : up) : (weak ? downWeak : down)).push(
              `M${(x - half).toFixed(1)},${topY.toFixed(1)}h${barW.toFixed(1)}v${h.toFixed(1)}h${(-barW).toFixed(1)}Z`)
          }
          return { kind: "histogram" as const, up: up.join(""), down: down.join(""),
                   upWeak: upWeak.join(""), downWeak: downWeak.join(""), shade: !!ser.shade,
                   color: ser.color, downColor: ser.downColor ?? ser.color }
        }
        const d = ser.points.map((p, n) => {
          const i = byTime.get(p.t)
          if (i == null) return ""
          return `${n === 0 ? "M" : "L"}${indexToX(s, i + 0.5).toFixed(1)},${yIn(p.v).toFixed(1)}`
        }).filter(Boolean).join("")
        // Closed under its own first and last points, like the price area.
        const xs = [...d.matchAll(/[ML](-?[\d.]+),/g)].map(m => m[1])
        const areaD = ser.kind === "area" && d && xs.length
          ? `${d}L${xs[xs.length - 1]},${top + pane.height}L${xs[0]},${top + pane.height}Z` : ""
        return { kind: ser.kind, d, areaD, color: ser.color, width: (ser as { width?: number }).width ?? 1.5 }
      })
      // One map per series so the legend can read a value at the cursor in
      // constant time. Built here because this memo already walks every point;
      // doing it at render would repeat that work on every mouse move.
      const lookups = pane.series.map(ser => new Map(ser.points.map(p => [p.t, p.v])))
      const colors = pane.series.map(ser => ser.color)
      const levels = (pane.levels ?? []).map(v => ({ v, y: yIn(v) }))
      const axis = [ext.min, (ext.min + ext.max) / 2, ext.max]
        .map(v => ({ v, y: yIn(v) }))
      const band = pane.band
        ? { y: Math.min(yIn(pane.band.from), yIn(pane.band.to)),
            h: Math.abs(yIn(pane.band.to) - yIn(pane.band.from)), color: pane.band.color }
        : null
      return { pane, top, drawn, levels, axis, lookups, colors, band }
    })
  }, [panes, priceH, bars, s, barW, half, seriesW, from, to, indexByTime])

  /** Axis rows covered by a price tag.
   *
   * The last-price tag and the crosshair tag are opaque chips pinned to the
   * gutter at whatever price they mark, so whenever that price sits near a
   * round number the chip lands on top of the tick label and the two render
   * over each other. The tick is the one that gives way: it is a fixed
   * gridline a reader can infer from its neighbours, while the tag carries the
   * number actually being asked about.
   *
   * 12px is the tag's half-height (8) plus half a line of 11px text, so a
   * label is dropped exactly when it would collide rather than whenever it is
   * merely close. */
  const TAG_HALF = 12
  const tagRows: number[] = []
  const ticks = log ? priceTicksLog(min, max) : priceTicks(min, max)
  const decimals = priceDecimals(ticks.length > 1
    ? Math.min(...ticks.slice(1).map((v, i) => Math.abs(v - ticks[i]))) : 1)
  const last = bars[bars.length - 1]
  const provLast = provSlots.length ? provSlots[provSlots.length - 1] : null
  // The tag quotes the newest price on screen — the provisional one when the
  // series is delayed — and is drawn faded then, like the line it ends.
  const tagPrice = provLast ? provLast.c : last?.c
  // The last-price tag is PINNED to the pane's edge when the price is off
  // it (theirs does the same), so the row it covers is the pinned one.
  const lastY = last && tagPrice != null ? yOf(tagPrice) : 0
  const lastOnPane = last != null && lastY >= 0 && lastY <= priceH
  const tagY = Math.min(priceH - 8, Math.max(8, lastY))
  if (last) tagRows.push(tagY)
  if (cursor) tagRows.push(cursor.y)
  const tagHides = (y: number) => tagRows.some(t => Math.abs(y - t) < TAG_HALF)
  const hoveredIdx = cursor
    ? Math.max(0, Math.min(bars.length - 1, Math.round(xToIndex(s, cursor.x) - 0.5)))
    : -1
  const hovered = cursor ? bars[hoveredIdx] : null

  /** Time labels, thinned to whatever fits without collision. */
  /** Session shading and day breaks. Memoized on the bars because it walks
   * every one of them through a timezone conversion — cheap once, wasteful on
   * each of the thirty-odd renders a minute the live feed now causes. */
  const sessions = useMemo(
    () => (intraday ? sessionLayout(bars) : { bands: [], dividers: [] }),
    [timesKey, intraday],  // eslint-disable-line react-hooks/exhaustive-deps
  )

  /** Time labels at calendar BOUNDARIES — hours within a day, the day number
   * at a day change, the month, the year — placed by lib/chartTime's
   * ladder against a budget of one label per ~70px. The parts are built
   * once per series; the per-pan pass is integer comparisons. */
  const parts = useMemo(() => timeParts(bars.map(b => b.t), timeZone), [timesKey, timeZone])  // eslint-disable-line react-hooks/exhaustive-deps
  const timeTicks = useMemo(() => {
    const lo = Math.max(0, Math.ceil(from))
    const hi = Math.min(bars.length - 1, Math.ceil(to))
    const budget = Math.max(2, Math.floor(seriesW / 70))
    return thinTicks(timeAxisTicks(parts, lo, hi, budget).map(t => ({
      x: indexToX(s, t.i + 0.5), label: t.label, major: t.major, level: t.level,
    })), 48)
  }, [parts, from, to, seriesW, s, bars.length])

  /** Seconds to the forming bar's close, ticking once a second while the
   * feed is live. Null hides the tag: a countdown on a closed market would
   * be counting to nothing. */
  const [countdown, setCountdown] = useState<number | null>(null)
  useEffect(() => {
    if (!live || !last) { setCountdown(null); return }
    const tick = () => setCountdown(barCloseCountdown(last.t, interval))
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [live, last?.t, interval])  // eslint-disable-line react-hooks/exhaustive-deps

  // The view controls, for whoever holds the ref.
  useEffect(() => {
    if (!controlRef) return
    controlRef.current = {
      reset: () => { setView(focusView()); setYZoom(1); setHeld(null); userMoved.current = false },
      wheel: (e: WheelEvent) => wheelRef.current?.(e),
    }
    return () => { controlRef.current = null }
  }, [controlRef, bars.length, focusFrom])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={host}
      // The focus ring is for a reader who TABBED here. A click also focuses
      // the chart (so the arrows pan it), and the browser then counts the
      // next key press as keyboard use and drew the red box round the whole
      // chart (2026-09-18). A pointer marks the chart until it loses focus.
      className="relative w-full select-none outline-none [&:not([data-pointer])]:focus-visible:ring-1 [&:not([data-pointer])]:focus-visible:ring-accent/60"
      onPointerDownCapture={e => { e.currentTarget.dataset.pointer = "" }}
      onBlur={e => { delete e.currentTarget.dataset.pointer }}
      style={{ height, cursor: yResizing ? "ns-resize" : xResizing ? "ew-resize" : panning ? "grabbing" : "crosshair", touchAction: "none" }}
      // The chart as one image to assistive tech, with the keyboard as a
      // second pointer: arrows pan (shift for half a screen), + and − zoom
      // about the centre, Home and End go to the oldest and newest bar.
      role="img"
      tabIndex={0}
      aria-label={`${(seriesId ?? "chart").replace(/:/g, ", ")}${last ? `; last ${last.c.toFixed(decimals)}` : ""}. Arrow keys pan, plus and minus zoom.`}
      onKeyDown={onKey}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      onPointerLeave={leave}
      onContextMenu={e => {
        if (!onContextMenu || !host.current) return
        e.preventDefault()
        const r = host.current.getBoundingClientRect()
        const x = e.clientX - r.left, y = e.clientY - r.top
        const inPlot = x <= plotW && y <= priceH
        const i = Math.round(xToIndex(s, x) - 0.5)
        onContextMenu({
          clientX: e.clientX, clientY: e.clientY,
          price: inPlot ? fromDisplay(yToPrice(s, y, log)) : null,
          time: x <= plotW ? bars[Math.max(0, Math.min(bars.length - 1, i))]?.t ?? null : null,
        })
      }}
    >
      <svg width="100%" height={height} className="block">
        <defs>
          {/* Everything that draws data is clipped to the plot. Without it a
              panned series runs straight under the price gutter and collides
              with the axis labels and the price tag — the bars are still drawn
              past the edge on purpose (a partially visible candle at the edge
              is correct), they just must not be VISIBLE there. */}
          <clipPath id={clipId}>
            <rect x={0} y={0} width={plotW} height={priceH + panesH} />
          </clipPath>
          {/* Out-of-session hatching: fine diagonal lines in the ink colour. */}
          <pattern id={`${clipId}-hatch`} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1={0} y1={0} x2={0} y2={6} stroke={ink ?? text} strokeOpacity={0.12} strokeWidth={1} />
          </pattern>
        </defs>

        {/* horizontal grid + price axis */}
        {ticks.map(v => {
          const y = priceToY(s, v, log)
          return (
            <g key={v}>
              {/* The gridline stays either way — it is behind the plot, not
                  under the chip, and losing it would leave a visible hole in
                  the grid every time the price passed a round number. */}
              <line x1={0} y1={y} x2={plotW} y2={y} stroke={grid} strokeWidth={1} />
              {!tagHides(y) && y >= 5 && (
              <text x={plotW + 6} y={y + 3.5} fill={text} fontSize={11} className="tnum">
                {scaleMode === "percent" ? `${v.toFixed(1)}%` : v.toFixed(decimals)}
              </text>
              )}
            </g>
          )
        })}

        {/* vertical grid + time axis */}
        {/* A TICK below the axis, not a rule through the plot. The horizontal
            grid is what a price is read against; the vertical one was crossing
            every candle and every indicator line without any reading being
            taken against it, which is most of what made this canvas busier
            than theirs. The tick still says where the label points. */}
        {timeTicks.map((t, i) => (
          <g key={i}>
            <line x1={t.x} y1={priceH + panesH} x2={t.x} y2={priceH + panesH + 4}
                  stroke={grid} strokeWidth={1} />
            {/* A label centred within 20px of the plot's left edge would be
                cut to its tail ("p 2"); the tick still marks the instant. */}
            {t.x >= 20 && (
              <text x={t.x} y={priceH + panesH + 16} fill={t.major ? (ink ?? text) : text} fontSize={11}
                fontWeight={t.major ? 600 : 400} textAnchor="middle" className="tnum">
                {t.label}
              </text>
            )}
          </g>
        ))}

        <g clipPath={`url(#${clipId})`}>
        {/* Extended hours, and the breaks between trading days.
            Drawn FIRST so they sit behind the data: this is context for
            reading the series, not a thing to read on its own. The x scale is
            bar index, so a night between a 16:00 close and the next 09:30 open
            is one bar wide and otherwise invisible — the divider is what keeps
            an overnight gap from reading as a minute's move. */}
        {/* Monochrome, the Vercel/Next.js way (2026-09-19, the owner: the
            coloured bands "look amateur", then "make it look like nextjs
            ish"): out-of-session time is fine grey diagonal hatching over
            the PRICE area only, and a weekend sits on a slightly darker grey
            ground under the same hatch. Pastel tints, edge hairlines and
            names along the top were each tried and taken out the same day.
            Which session a band is shows in its hover title. */}
        {sessions.bands.map((b, i) => {
          const x0 = indexToX(s, b.from)
          const x1 = indexToX(s, b.to)
          if (x1 < 0 || x0 > seriesW) return null
          const name = b.kind === "pre" ? "Pre-market" : b.kind === "after" ? "After hours"
            : b.kind === "weekend" ? "Weekend" : "Overnight"
          const left = Math.max(0, x0), right = Math.min(seriesW, x1)
          const w = Math.max(1, right - left)
          return (
            <g key={`b${i}`}>
              {b.kind === "weekend" && <rect x={left} y={0} width={w} height={priceH} fill={ink ?? text} opacity={0.035} />}
              <rect x={left} y={0} width={w} height={priceH} fill={`url(#${clipId}-hatch)`}>
                <title>{name}</title>
              </rect>
            </g>
          )
        })}
        {sessions.dividers.map((idx, i) => {
          const x = indexToX(s, idx)
          if (x < 0 || x > seriesW) return null
          return (
            <line key={`d${i}`} x1={x} y1={0} x2={x} y2={priceH + panesH}
              stroke={text} strokeWidth={1} strokeDasharray="2 4" opacity={0.35} />
          )
        })}

        {/* the end of the feed's history, named where the reader meets it */}
        {historyNote && from < 8 && (
          <text x={8} y={topInset + 16} fill={text} fontSize={11} className="tnum">{historyNote}</text>
        )}

        {/* the series */}
        {kind === "area" && <path d={paths.area} fill={accent} fillOpacity={0.14} />}
        {kind === "hlc" && <path d={paths.hlc} fill={accent} fillOpacity={0.14} />}
        {(kind === "line" || kind === "area" || kind === "hlc") && (
          <path d={paths.line} fill="none" stroke={accent} strokeWidth={1.5}
            strokeLinejoin="round" strokeLinecap="round" />
        )}
        {kind === "step" && (
          <path d={paths.step} fill="none" stroke={accent} strokeWidth={1.5} strokeLinejoin="miter" />
        )}
        {kind === "baseline" && (
          // The same line drawn twice, each half clipped to its side of the
          // baseline: gain above, loss below, with a fill to the line.
          <>
            <clipPath id={`${clipId}-above`}><rect x={0} y={0} width={plotW} height={paths.baseY} /></clipPath>
            <clipPath id={`${clipId}-below`}><rect x={0} y={paths.baseY} width={plotW} height={Math.max(0, priceH - paths.baseY)} /></clipPath>
            <g clipPath={`url(#${clipId}-above)`}>
              <path d={paths.baseArea} fill={gain} fillOpacity={0.14} />
              <path d={paths.line} fill="none" stroke={gain} strokeWidth={1.5} strokeLinejoin="round" />
            </g>
            <g clipPath={`url(#${clipId}-below)`}>
              <path d={paths.baseArea} fill={loss} fillOpacity={0.14} />
              <path d={paths.line} fill="none" stroke={loss} strokeWidth={1.5} strokeLinejoin="round" />
            </g>
            <line x1={0} y1={paths.baseY} x2={plotW} y2={paths.baseY} stroke={text} strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
          </>
        )}
        {kind === "columns" && (
          <>
            <path d={paths.colsUp} fill={gain} fillOpacity={0.55} />
            <path d={paths.colsDown} fill={loss} fillOpacity={0.55} />
          </>
        )}
        {kind === "highlow" && (
          <>
            <path d={paths.upBody} fill={gain} fillOpacity={0.7} />
            <path d={paths.downBody} fill={loss} fillOpacity={0.7} />
          </>
        )}
        {kind === "hollow" && (
          <>
            <path d={paths.upWick} stroke={gain} strokeWidth={1} fill="none" />
            <path d={paths.downWick} stroke={loss} strokeWidth={1} fill="none" />
            <path d={paths.hollowUp} stroke={gain} strokeWidth={1} fill={bg} />
            <path d={paths.hollowDown} stroke={loss} strokeWidth={1} fill={bg} />
            <path d={paths.solidUp} fill={gain} />
            <path d={paths.solidDown} fill={loss} />
          </>
        )}
        {(kind === "candles" || kind === "heikin" || kind === "bars") && (
          <>
            <path d={paths.upWick} stroke={gain} strokeWidth={1} fill="none" />
            <path d={paths.downWick} stroke={loss} strokeWidth={1} fill="none" />
            {kind !== "bars" ? (
              <>
                <path d={paths.upBody} fill={gain} />
                <path d={paths.downBody} fill={loss} />
              </>
            ) : (
              <>
                <path d={paths.upBody} stroke={gain} strokeWidth={1.2} fill="none" />
                <path d={paths.downBody} stroke={loss} strokeWidth={1.2} fill="none" />
              </>
            )}
          </>
        )}

        {/* indicator overlays, in price space */}
        {overlayPaths.map((o, i) => (
          <path key={i} d={o.d} fill="none" stroke={o.color} strokeWidth={o.width} />
        ))}

        {/* compared symbols, each rebased to ITS OWN first visible close so
            every line starts at 0% together — the point of the comparison */}
        {comparePaths.map(c => (
          <path key={c.symbol} d={c.d} fill="none" stroke={c.color} strokeWidth={1.5} strokeLinejoin="round" />
        ))}

        {/* the stacked panes */}
        {paneLayout.map(({ pane, top, drawn, levels, axis, lookups, colors, band }) => (
          <g key={pane.id}>
            <line x1={0} y1={top} x2={plotW} y2={top} stroke={grid} strokeWidth={1} />
            {band && <rect x={0} y={band.y} width={plotW} height={band.h} fill={band.color} fillOpacity={0.07} />}
            {/* The divider. A 7px grab band on the pane's top rule: drag it
                and the pane's height follows, the price pane above giving or
                taking the difference. Pointer capture, like the gutters —
                a resize of any real size leaves the band at once. */}
            {onResizePane && (
              <rect x={0} y={top - 3} width={plotW} height={7} fill="transparent"
                style={{ cursor: "ns-resize", touchAction: "none" }}
                pointerEvents="all"
                onMouseDown={e => e.stopPropagation()}
                onPointerDown={e => {
                  e.stopPropagation()
                  ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
                  paneDrag.current = { id: pane.id, y: e.clientY, h: pane.height }
                }}
                onPointerMove={e => {
                  const g = paneDrag.current
                  if (!g || g.id !== pane.id) return
                  e.stopPropagation()
                  const dy = e.clientY - g.y
                  // The price pane keeps at least 80px and the time axis
                  // stays on the canvas: a pane may grow only into what the
                  // canvas has left once the other panes and the axis are
                  // paid for.
                  const room = box.h - AXIS_H - (panesH - pane.height) - 80
                  onResizePane(pane.id, Math.round(Math.min(800, Math.max(40, Math.min(room, g.h - dy)))))
                }}
                onPointerUp={e => {
                  e.stopPropagation()
                  ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
                  paneDrag.current = null
                }}
              />
            )}
            {levels.map(l => (
              <line key={l.v} x1={0} y1={l.y} x2={plotW} y2={l.y}
                stroke={text} strokeOpacity={0.35} strokeWidth={1} strokeDasharray="3 3" />
            ))}
            {axis.map((a, i) => (
              tagHides(a.y) ? null : (
                <text key={i} x={plotW + 6} y={a.y + 3.5} fill={text} fontSize={10} className="tnum">
                  {paneAxisLabel(a.v, pane.compact)}
                </text>
              )
            ))}
            {drawn.map((d, i) =>
              d.kind === "histogram" ? (
                <g key={i}>
                  {/* Lighter than a candle body: the volume band is context
                      for the price above it, not a second thing to read. A
                      shaded histogram draws its growing columns solid and its
                      fading ones faint. */}
                  <path d={d.up} fill={d.color} fillOpacity={"shade" in d && d.shade ? 0.85 : 0.42} />
                  <path d={d.down} fill={d.downColor} fillOpacity={"shade" in d && d.shade ? 0.85 : 0.42} />
                  {"upWeak" in d && d.upWeak && <path d={d.upWeak} fill={d.color} fillOpacity={0.3} />}
                  {"downWeak" in d && d.downWeak && <path d={d.downWeak} fill={d.downColor} fillOpacity={0.3} />}
                </g>
              ) : (
                <g key={i}>
                  {d.kind === "area" && d.areaD && <path d={d.areaD} fill={d.color} fillOpacity={0.16} />}
                  <path d={d.d} fill="none" stroke={d.color} strokeWidth={d.width} />
                </g>
              ))}
            {/* The legend, with the VALUES at the cursor.
                A pane labelled only "RSI 9" makes the reader estimate a number
                off a 90px axis; the price strip above already answers that for
                price, and an indicator deserves the same. Falls back to the
                latest bar when nothing is hovered, so it reads as a current
                value rather than going blank. */}
            {pane.label && (() => {
              const at = bars[hoveredIdx >= 0 ? hoveredIdx : bars.length - 1]?.t
              return (
                <text x={4} y={top + 12} fontSize={10} className="tnum">
                  <tspan fill={text}>{pane.label}</tspan>
                  {lookups.map((m, i) => {
                    const v = at == null ? undefined : m.get(at)
                    if (v == null || !Number.isFinite(v)) return null
                    return (
                      <tspan key={i} dx={6} fill={colors[i]}>
                        {paneAxisLabel(v, pane.compact)}
                      </tspan>
                    )
                  })}
                </text>
              )
            })()}
            {/* Drop the pane from where it is, rather than reopening the menu
                to find the row you just ticked. */}
            {onPaneSettings && pane.id !== "volume" && (
              <g
                style={{ cursor: "pointer" }}
                role="button" tabIndex={0} aria-label={`Settings for ${pane.label ?? pane.id}`}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onPaneSettings(pane.id) } }}
                onPointerDown={e => e.stopPropagation()}
                onMouseDown={e => e.stopPropagation()}
                onClick={e => { e.stopPropagation(); onPaneSettings(pane.id) }}
                pointerEvents="all"
              >
                <rect x={seriesW - 32} y={top + 3} width={13} height={13} fill="transparent" />
                <text x={seriesW - 26} y={top + 13} fill={text} fontSize={10} textAnchor="middle">⚙</text>
                <title>Settings for {pane.label ?? pane.id}</title>
              </g>
            )}
            {onRemovePane && pane.id !== "volume" && (
              <g
                style={{ cursor: "pointer" }}
                role="button" tabIndex={0} aria-label={`Remove ${pane.label ?? pane.id}`}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onRemovePane(pane.id) } }}
                // Kept off the host, whose pointerdown starts a horizontal
                // pan. Harmless on a click that does not move, but it would
                // arm a drag on the way to dismissing a pane.
                onPointerDown={e => e.stopPropagation()}
                onMouseDown={e => e.stopPropagation()}
                onClick={e => { e.stopPropagation(); onRemovePane(pane.id) }}
                pointerEvents="all"
              >
                <rect x={seriesW - 16} y={top + 3} width={13} height={13} fill="transparent" />
                <text x={seriesW - 10} y={top + 13} fill={text} fontSize={10} textAnchor="middle">×</text>
                <title>Remove {pane.label ?? pane.id}</title>
              </g>
            )}
          </g>
        ))}

        </g>

        {/* last price, tagged on the axis. The dashed line and the filled tag
            take the TREND colour — where the last print sits against the first
            visible bar — not the accent: a red tag on a rising day would say
            "down" in the one place colour is a claim. */}
        {last && (() => {
          const price = tagPrice ?? last.c
          const trend = price >= (bars[Math.max(0, Math.floor(from))]?.c ?? price) ? gain : loss
          return (
          <g>
            {provSlots.length > 0 && (() => {
              const pts = [{ i: bars.length - 1, c: last.c }, ...provSlots.map(p => ({ i: bars.length - 1 + p.k, c: p.c }))]
              const d = pts.map((p, n) => `${n ? "L" : "M"}${indexToX(s, p.i + 0.5).toFixed(1)},${yOf(p.c).toFixed(1)}`).join("")
              const end = pts[pts.length - 1]
              const ex = indexToX(s, end.i + 0.5), ey = yOf(end.c)
              return (
                <g pointerEvents="none" clipPath={`url(#${clipId})`}>
                  <path d={d} fill="none" stroke={text} strokeWidth={1.5} strokeDasharray="4 3" strokeOpacity={0.9} />
                  <circle cx={ex} cy={ey} r={2.5} fill={text} />
                  <text x={ex - 4} y={ey - 7} fill={text} fontSize={10} textAnchor="end" opacity={0.85}>provisional</text>
                </g>
              )
            })()}
            {priceLine && lastOnPane && (
              <line x1={0} y1={lastY} x2={plotW} y2={lastY}
                stroke={trend} strokeWidth={1} strokeDasharray="3 3" />
            )}
            <rect x={plotW + 2} y={tagY - 8} width={AXIS_W - 4} height={16} fill={trend} fillOpacity={provLast ? 0.6 : 1} />
            <text x={plotW + 6} y={tagY + 3.5} fill={bg} fontSize={11} className="tnum">
              {lastOnPane ? "" : lastY < 0 ? "▲ " : "▼ "}
              {(scaleMode === "percent" ? toDisplay(price) : price).toFixed(decimals)}
            </text>
            {/* The countdown to this bar's close, under the price the way
                theirs sits — the one number that says how much of the
                forming bar is still to come. */}
            {countdown != null && lastOnPane && (
              <>
                <rect x={plotW + 2} y={tagY + 8} width={AXIS_W - 4} height={14} fill={trend} fillOpacity={0.75} />
                <text x={plotW + AXIS_W / 2} y={tagY + 18.5} fill={bg} fontSize={10}
                  textAnchor="middle" className="tnum">{countdownLabel(countdown)}</text>
              </>
            )}
          </g>
          )
        })()}

        {/* crosshair */}
        {cursor && (
          <g pointerEvents="none">
            <line x1={cursor.x} y1={0} x2={cursor.x} y2={priceH + panesH}
              stroke={text} strokeWidth={1} strokeDasharray="3 3" />
            <line x1={0} y1={cursor.y} x2={plotW} y2={cursor.y}
              stroke={text} strokeWidth={1} strokeDasharray="3 3" />
            {/* The bar being read, marked ON the series.
                The vertical rule says which COLUMN the cursor is in, which is
                not the same as which point the OHLCV strip is quoting — at a
                few bars to the pixel they can differ by several bars, and the
                rule alone leaves the reader to guess where on the line the
                numbers came from. Only on the line kinds: a candle already
                shows its own close, and a dot on top of one would just cover
                the thing it was pointing at. */}
            {hovered && (kind === "line" || kind === "area") && (() => {
              const mx = indexToX(s, hoveredIdx + 0.5)
              const my = yOf(hovered.c)
              return (
                <g>
                  {/* A soft halo behind the marker. The dot has to read against
                      a line of its OWN colour, so size alone does not separate
                      the two — the halo gives it an edge without needing a
                      heavier ring that would start hiding the series under it. */}
                  <circle cx={mx} cy={my} r={9} fill={accent} opacity={0.18} />
                  <circle cx={mx} cy={my} r={5} fill={accent}
                    stroke={tagBg} strokeWidth={2.5} />
                </g>
              )
            })()}
            <rect x={plotW + 2} y={cursor.y - 8} width={AXIS_W - 4} height={16}
              fill={tagBg} stroke={tagBorder} strokeWidth={1} />
            <text x={plotW + 6} y={cursor.y + 3.5} fill={tagFg} fontSize={11} className="tnum">
              {yToPrice(s, cursor.y, log).toFixed(decimals)}
            </text>
            {hovered && (
              <>
                <rect x={cursor.x - 42} y={priceH + panesH + 3} width={84} height={16}
                  fill={tagBg} stroke={tagBorder} strokeWidth={1} />
                <text x={cursor.x} y={priceH + panesH + 14.5} fill={tagFg} fontSize={11}
                  textAnchor="middle" className="tnum">
                  {new Date(hovered.t).toLocaleString("en-US", {
                    timeZone, month: "short", day: "numeric",
                    hour: "numeric", minute: "2-digit",
                  })}
                </text>
              </>
            )}
          </g>
        )}

        {/* The price gutter, grabbable. Rendered LAST so it is on top of the
            axis labels: a transparent rect still takes the pointer, and if the
            labels sat above it a drag begun exactly on "44.00" would fall
            through to the pan handler instead. */}
        <rect
          x={plotW} y={0} width={AXIS_W} height={priceH}
          fill="transparent"
          style={{ cursor: "ns-resize", touchAction: "none" }}
          onPointerDown={e => {
            // Capture, so the rest of the gesture keeps arriving here even once
            // the pointer is off the gutter, off the tile, or over the AI rail.
            // Without it a stretch of any real size ended the moment the cursor
            // crossed the chart's edge.
            e.stopPropagation()
            ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
            // From wherever the scale is NOW: the fit if it has been
            // fitting, the held range if the reader already set one.
            yDrag.current = { y: e.clientY, range: { min, max } }
            setYResizing(true)
          }}
          onPointerMove={e => {
            if (!yDrag.current) return
            e.stopPropagation()
            // Exponential: the same drag distance is the same proportional
            // change at every zoom level, and the factor can never reach zero
            // and invert the axis. Down compresses, matching theirs.
            const dy = e.clientY - yDrag.current.y
            const factor = Math.min(8, Math.max(0.125, Math.exp(-dy / 160)))
            yNext.current = scaledRange(yDrag.current.range, factor, scaleMode === "log")
            if (yFrame.current == null) {
              yFrame.current = requestAnimationFrame(() => {
                yFrame.current = null
                if (yNext.current != null) { setHeld(yNext.current); setYZoom(1) }
              })
            }
          }}
          onPointerUp={e => {
            e.stopPropagation()
            ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
            yDrag.current = null
            setYResizing(false)
          }}
          onPointerCancel={() => { yDrag.current = null; setYResizing(false) }}
          onDoubleClick={e => { e.stopPropagation(); setYZoom(1); setHeld(null) }}
        >
          <title>Drag to set the price scale — it stays where you put it · double-click to fit the bars again</title>
        </rect>

        {/* The time gutter, grabbable — the x-axis twin of the price gutter
            above. Dragging right stretches the bars (fewer visible), left
            compresses them, exponentially so equal drags are equal
            proportional changes at every zoom. Anchored at the view's right
            edge rather than the cursor: mid-gesture the newest visible bar is
            the reference the eye holds. Same pointer capture as the price
            gutter, and for the same reason — a 22px-tall strip is left almost
            immediately. */}
        <rect
          x={0} y={priceH + panesH} width={plotW} height={AXIS_H}
          fill="transparent"
          style={{ cursor: "ew-resize", touchAction: "none" }}
          onPointerDown={e => {
            e.stopPropagation()
            ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
            xDrag.current = { x: e.clientX, from, to }
            setXResizing(true)
          }}
          onPointerMove={e => {
            const d = xDrag.current
            if (!d) return
            e.stopPropagation()
            const dx = e.clientX - d.x
            const span = d.to - d.from
            // Same span floor and ceiling the wheel zoom applies (zoomAt), so
            // the two gestures can never reach states the other cannot leave.
            const next = Math.max(5, Math.min(bars.length * 3, span * Math.exp(-dx / 200)))
            setView(clampView(d.to - next, d.to, edgeLen))
          }}
          onPointerUp={e => {
            e.stopPropagation()
            ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
            xDrag.current = null
            setXResizing(false)
          }}
          onPointerCancel={() => { xDrag.current = null; setXResizing(false) }}
          onDoubleClick={e => {
            e.stopPropagation()
            if (bars.length) setView({ from: 0, to: edgeLen })
          }}
        >
          <title>Drag to stretch the time scale · double-click to fit</title>
        </rect>
      </svg>
    </div>
  )
}
