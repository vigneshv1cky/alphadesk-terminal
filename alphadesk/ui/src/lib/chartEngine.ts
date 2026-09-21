import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ChartBar, ChartRange } from "@/lib/api"
import type { Projection, ScaleMode, SeriesKind } from "@/components/chart/ChartCanvas"
import { indicatorPane, volumePane, type Pane } from "@/components/chart/panes"
import { useDrawingHistory, type Drawing, type Tool } from "@/components/ChartDrawings"
import { loadChartPrefs, normalizeChartPrefs, saveChartPrefs, serverPrefsKey, type ChartPrefs } from "@/lib/chartPrefs"
import {
  buildOverlays, indicatorDef, newIndicator, type Indicator, type IndicatorDef, type IndicatorType,
} from "@/lib/indicators"
import { useQueryClient } from "@tanstack/react-query"
import { ApiError, api } from "@/lib/api"
import { focusIndex } from "@/lib/chartTime"
import { keys, useAuthMe, useChartSeries } from "@/lib/queries"
import { useLiveTrade } from "@/lib/live"
import { foldLiveTrade, provisionalPoints, tradeIsPastLastBar, type FormingBar } from "@/lib/provisional"
import { useNarrowViewport } from "@/lib/viewport"
import { useChartTheme } from "@/lib/theme"

/** One empty list, so a symbol with no drawings keeps a stable identity. */
const NO_DRAWINGS: Drawing[] = []

// Drawings used to be saved in the browser under this prefix. They are not
// any more; the copies left behind are cleared once per load.
try {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith("alphadesk.chart.drawings:")) localStorage.removeItem(k)
  }
} catch { /* storage blocked */ }

/** THE chart's state, as one hook (2026-09-05).
 *
 * Two surfaces render a chart — the Markets tile and the full-page workspace
 * at /chart — and they must be the same chart: same prefs, same drawings,
 * same series, same panes, same live edge. Everything that used to live in
 * the tile component lives here, and each surface is only a layout around
 * it. A fix to how bars refresh or how a pane is built lands once.
 *
 * Sizing is the one thing the surfaces disagree on, so it is the one input:
 * a tile says how tall the PRICE pane is and grows by the panes it adds; the
 * workspace says how tall the WHOLE canvas may be and the price pane takes
 * what the panes leave.
 */

/** How tall a pane needs to be depends on how much of itself it uses.
 *
 * A FITTED pane — MACD, CCI, ATR, OBV — is scaled to its own data, so it
 * fills whatever box it is given and 120px shows the shape fine. A pane with
 * a FIXED scale only ever occupies the slice its readings fall in, and the
 * rest is empty axis: measured on 1,558 bars of NVDA, the middle 90% of
 * RSI-9 sits between 25 and 72, which is 46% of the 0-100 range. That is why
 * the bounded ones get the taller box, and why the fixed range is not the
 * thing to change — auto-scaling RSI would put 45 at the top of the pane and
 * make a neutral reading look extreme. */
export const FITTED_PANE_H = 120
export const BOUNDED_PANE_H = 170
/** The default box for a pane, from its catalogue entry — here so a surface
 * can budget height BEFORE the panes are built: the workspace needs the sum
 * to know what the price pane gets. A reader's own drag overrides it. */
export const paneHeightFor = (def: IndicatorDef) => (def.bounded ? BOUNDED_PANE_H : FITTED_PANE_H)

export type ChartSize = { priceHeight: number } | { totalHeight: number }

export type ReplayState = {
  active: boolean
  /** Waiting for the reader to click the bar to start from. */
  selecting: boolean
  /** Index into the full series of the last bar shown. */
  at: number | null
  playing: boolean
  /** Bars per 0.7s. */
  speed: number
}


export function useChartEngine(symbol: string, size: ChartSize, opts: { slot?: number } = {}) {
  const slot = opts.slot ?? 0
  // The view settings survive navigation: seeded from the persisted prefs,
  // written back per gesture below. The SYMBOL deliberately does not live
  // here — the strip owns it (slot 0) or the workspace's layout (slots 1–3).
  const [prefs] = useState(() => loadChartPrefs(slot))
  const [range, setRange] = useState<ChartRange>(prefs.range)
  const [type, setType] = useState<SeriesKind>(prefs.type)
  const [scale, setScale] = useState<ScaleMode>(prefs.scale)
  const [timeZone, setTimeZone] = useState(prefs.timeZone)
  const [priceLine, setPriceLine] = useState(prefs.priceLine)
  /** The canvas registers its view controls here (reset), so a surface's
   * context menu can reach them without owning the view. */
  const viewRef = useRef<{ reset: () => void; wheel: (e: WheelEvent) => void } | null>(null)
  const [interval, setInterval] = useState(prefs.interval)
  /** Whether the interval was chosen BY HAND. Unpinned, the server picks the
   * one that suits the range and the toolbar adopts it.
   *
   * Carrying a hand-set interval across a range change was quietly expensive:
   * the 1D view defaults to 1-minute bars, so switching to 1Y asked for a year
   * of minute data. The server correctly refuses and serves hourly instead —
   * but a year of HOURLY bars is a 20-second upstream fetch that nothing
   * caches, and the answer is not even the daily series the range wants.
   * Asking for the range alone returns in half a second. */
  /** The reader's interval per range. A range with no entry opens on the
   * finest bar it offers (the server's default); a choice made on a range
   * is that range's and comes back with it. */
  const [intervalByRange, setIntervalByRange] = useState<Partial<Record<ChartRange, string>>>(prefs.intervalByRange)
  const wantedInterval = intervalByRange[range] ?? null
  const intervalPinned = wantedInterval != null
  /** Pin `iv` for the current range; "" (or null) releases the range back
   * to its default. */
  const pinInterval = (iv: string | null) => {
    setIntervalByRange(m => {
      const next = { ...m }
      if (iv) next[range] = iv
      else delete next[range]
      return next
    })
    if (iv) setInterval(iv)
  }
  const setIntervalPinned = (on: boolean) => { if (!on) pinInterval(null) }
  /** The indicators on this chart — instances with their own parameters
   * (lib/indicators). One dialog edits an instance; the tile and the
   * workspace share the list. */
  const [indicators, setIndicators] = useState<Indicator[]>(prefs.indicators)
  const [paneHeights, setPaneHeights] = useState<Record<string, number>>(prefs.paneHeights)
  /** Which instance the settings dialog is open for. Here rather than in a
   * surface so the pane's gear (drawn by the canvas) and the overlay legend's
   * gear open the same dialog. */
  const [settingsId, setSettingsId] = useState<string | null>(null)
  const addIndicator = (type: IndicatorType) => setIndicators(l => [...l, newIndicator(type)])
  const updateIndicator = (id: string, patch: Partial<Indicator>) =>
    setIndicators(l => l.map(i => (i.id === id ? { ...i, ...patch } : i)))
  const removeIndicator = (id: string) => {
    setIndicators(l => l.filter(i => i.id !== id))
    setPaneHeights(ph => { const { [id]: _drop, ...rest } = ph; return rest })
    setSettingsId(cur => (cur === id ? null : cur))
  }
  const setPaneHeight = (id: string, h: number) =>
    setPaneHeights(ph => (ph[id] === h ? ph : { ...ph, [id]: h }))

  // The reading setup follows the account: once sign-in resolves, the
  // server's copy (if any) replaces the browser seed, and every change is
  // written to both.
  const { data: me } = useAuthMe()
  /** Whether the account's copy has been READ this session. Saves to the
   * account wait for it: a save before the read landed replaced the
   * account's range and indicators with whatever the browser
   * held — a deploy blip on the read was enough. The read is retried. */
  const serverHydrated = useRef(false)
  const stamp = useRef<number>(prefs.updatedAt ?? 0)
  useEffect(() => {
    if (!me?.user || serverHydrated.current) return
    let alive = true
    const delays = [0, 2000, 6000, 15000]
    const attempt = (n: number) => {
      if (!alive) return
      window.setTimeout(() => {
        if (!alive) return
        fetch(`/api/chart/state/${serverPrefsKey(slot)}`)
          .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
          .then(d => {
            if (!alive) return
            serverHydrated.current = true
            if (!d.state) return
            const theirs = normalizeChartPrefs(d.state)
            // Newer wins. A change made here in the last 600ms before a
            // reload has a fresher stamp than the account's copy; applying
            // the account's copy anyway threw the change away.
            if ((theirs.updatedAt ?? 0) > stamp.current) { stamp.current = theirs.updatedAt ?? 0; applyPrefs(theirs) }
          })
          .catch(() => { if (n + 1 < delays.length) attempt(n + 1) })
      }, delays[n])
    }
    attempt(0)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.user])

  /** Put a whole prefs record in place — a saved layout being opened, the
   * account's copy arriving. Everything the prefs carry, in one go. */
  const applyPrefs = (p: ChartPrefs) => {
    setRange(p.range); setType(p.type); setScale(p.scale)
    setTimeZone(p.timeZone); setPriceLine(p.priceLine)
    setInterval(p.interval); setIntervalByRange(p.intervalByRange)
    setIndicators(p.indicators); setPaneHeights(p.paneHeights)
  }
  const replaceIndicators = (list: Indicator[]) => setIndicators(list)

  // One write per settings change. The adopted (server-chosen) interval is
  // saved too, but only alongside its pinned flag — an unpinned interval is
  // a report, and restoring it as a demand would re-create the expensive
  // range/interval mismatch the pin exists to prevent.
  const prefsTimer = useRef<number | null>(null)
  /** The write the debounce is holding, so leaving the page can flush it
   * with a keepalive request instead of cancelling it. */
  const pending = useRef<ChartPrefs | null>(null)
  const firstSave = useRef(true)
  const flush = useCallback((keepalive = false) => {
    const next = pending.current
    pending.current = null
    if (prefsTimer.current) { window.clearTimeout(prefsTimer.current); prefsTimer.current = null }
    if (!next || !serverHydrated.current) return
    void fetch(`/api/chart/state/${serverPrefsKey(slot)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: next }), keepalive,
    }).catch(() => { /* the browser copy stands */ })
  }, [slot])
  useEffect(() => {
    // The mount's own echo of what was loaded is not a change.
    if (firstSave.current) { firstSave.current = false; return }
    const updatedAt = Date.now()
    stamp.current = updatedAt
    const next: ChartPrefs = { range, type, scale, interval, intervalPinned, intervalByRange, indicators, paneHeights, timeZone, priceLine, updatedAt }
    saveChartPrefs(next, slot)
    if (!me?.user) return
    pending.current = next
    if (prefsTimer.current) window.clearTimeout(prefsTimer.current)
    prefsTimer.current = window.setTimeout(() => flush(), 600)
  }, [range, type, scale, interval, intervalPinned, intervalByRange, indicators, paneHeights, timeZone, priceLine, me?.user, slot, flush])
  useEffect(() => {
    const onHide = () => flush(true)
    window.addEventListener("pagehide", onHide)
    return () => { window.removeEventListener("pagehide", onHide); flush(true) }
  }, [flush])
  /** The prefs as they stand — what a saved layout records for this cell. */
  const snapshotPrefs = (): ChartPrefs =>
    ({ range, type, scale, interval, intervalPinned, intervalByRange, indicators, paneHeights, timeZone, priceLine })

  // Drawings live here, not inside the canvas: that component is torn down
  // and rebuilt on every range or series change, and annotations must outlive
  // both. They are kept PER SYMBOL FOR THIS VISIT ONLY (2026-09-18, the
  // owner's call): nothing is saved to the account or the browser, so a
  // line drawn and forgotten does not greet the reader next week. Leaving
  // the page or reloading clears them. They used to persist per symbol.
  const [bySymbol, setBySymbol] = useState<Record<string, Drawing[]>>({})
  const drawings = useMemo(() => (symbol ? bySymbol[symbol] ?? NO_DRAWINGS : NO_DRAWINGS), [bySymbol, symbol])
  const setDrawings = useCallback((next: Drawing[]) => {
    if (symbol) setBySymbol(m => ({ ...m, [symbol]: next }))
  }, [symbol])
  const [tool, setTool] = useState<Tool>("none")
  const [drawOpen, setDrawOpen] = useState(false)
  const [drawVisible, setDrawVisible] = useState(true)
  const [magnet, setMagnet] = useState(false)
  // Every edit the overlay makes lands here first, so Ctrl+Z walks back
  // through placements, drags and style changes alike.
  const history = useDrawingHistory(drawings, setDrawings)
  const allLocked = drawings.length > 0 && drawings.every(d => d.locked)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [hovered, setHovered] = useState<ChartBar | null>(null)
  const [hoverAt, setHoverAt] = useState<{ x: number; y: number } | null>(null)
  const theme = useChartTheme()

  /** Polled, shared and de-duplicated like every other endpoint on the board
   * (lib/queries). This replaced a hand-rolled fetch whose request-id guard,
   * keep-the-old-series-while-loading and loading flag were all reimplementing
   * what the query layer already does — and which, being one-shot, left the
   * chart frozen at whatever moment the page was opened. */
  const { data, isFetching, error } = useChartSeries(symbol, range, wantedInterval)
  const err = error ? String((error as Error).message ?? error) : null
  // A plan refusal changes the catalogue's refused list; the menu should
  // grey the bar before the reader tries it again.
  const qc = useQueryClient()
  useEffect(() => {
    if (data?.plan_note) void qc.invalidateQueries({ queryKey: keys.chartCapabilities })
  }, [data?.plan_note, qc])

  // Adopt whatever the server chose, so the toolbar reports the series
  // actually on screen. No refetch loop: `wantedInterval` stays null while
  // unpinned, so this changes no query key.
  useEffect(() => {
    if (wantedInterval == null && data?.interval) setInterval(data.interval)
  }, [wantedInterval, data?.interval])
  // A range that carries a pin shows it at once — the label followed the
  // last served interval otherwise, so 1M came back reading "1h" after a
  // visit to 3M while its bars were the pinned 15 minutes.
  useEffect(() => {
    if (wantedInterval) setInterval(wantedInterval)
  }, [wantedInterval])

  /** The live edge, pushed. The polled series owns the bars; a trade only
   * moves the one still forming, so the right edge and the price tag track the
   * market between refreshes without the history ever being invented here.
   *
   * The array LENGTH never changes, which is what keeps this from disturbing
   * the reader: the canvas resets its view on series identity and follows
   * growth, and a tick is neither. */
  const { tick, live: liveFeed } = useLiveTrade(symbol)
  const narrow = useNarrowViewport()

  /** HISTORY PAGES (2026-09-10). A range fetches its own span and the view
   * opens on exactly that — theirs does the same — but the reader can keep
   * panning left: near the oldest bar the canvas asks for more, and a page
   * of the same interval, one range-span deep, is prepended. The pages
   * belong to one series (symbol, range, served interval) and are dropped
   * with it; an empty page is the end of the history and is remembered so
   * the edge is not asked again. The poll keeps owning the live edge — the
   * pages sit in front of whatever it delivers. */
  // The SERVED identity, not the asked-for one: while a new range loads,
  // the query hands back the previous series as a placeholder, and the
  // canvas must not reset onto it — that made a 1D→5D switch land on the
  // last 2,626 bars of the new series, as if they had merely grown. The
  // id changes when the server's bars for the new range actually land.
  const seriesKey = `${symbol}:${data?.range ?? range}:${data?.interval ?? ""}:${data?.source ?? ""}`
  const [older, setOlder] = useState<{ key: string; bars: ChartBar[]; done: boolean; loading: boolean; note: string | null }>(
    { key: seriesKey, bars: [], done: false, loading: false, note: null })
  const pages = older.key === seriesKey ? older : { key: seriesKey, bars: [], done: false, loading: false, note: null }
  const firstT = pages.bars[0]?.t ?? data?.bars[0]?.t
  const loadHistory = useCallback((need?: number) => {
    if (!data?.interval || !firstT || pages.loading || pages.done) return
    const key = seriesKey
    setOlder({ key, bars: pages.bars, done: false, loading: true, note: null })
    api.chartRange(symbol, range, data.interval, firstT, data.source ?? undefined, need).then(
      page => {
        const older = (page?.bars ?? []).filter(b => b.t < firstT)
        // The end of the history: an empty page, or a page the server cut
        // at its floor and said so.
        const done = older.length === 0 || !!page?.history_end
        setOlder(h => (h.key !== key ? h : { key, bars: [...older, ...h.bars], done, loading: false, note: done ? (page?.history_note ?? h.note) : null }))
      },
      (err: unknown) => {
        // 404 is "nothing before this"; anything else (a 503 from a
        // rate-limited source, a network blip) leaves the edge open to be
        // asked again on the next pan.
        const end = err instanceof ApiError && err.status === 404
        // The 404's own sentence says how far this feed reaches at this
        // interval; the canvas shows it at the left edge.
        setOlder(h => (h.key !== key ? h : { ...h, done: end, loading: false, note: end ? err.message : h.note }))
      },
    )
  }, [data?.interval, data?.source, firstT, pages.loading, pages.done, pages.bars, seriesKey, symbol, range])

  /** The poll window slides: its oldest bar drops off the front on a later
   * poll while the pages were cut at the FIRST bar of an earlier one, so
   * the bars between them would exist in neither list — a one-bar hole at
   * the seam that grew by a bar a minute. A bar the poll no longer holds
   * moves into the pages instead; it is older than everything polled and
   * newer than everything paged, so it goes on the end. */
  const prevPolled = useRef<{ key: string; bars: ChartBar[] } | null>(null)
  useEffect(() => {
    const polled = data?.bars ?? []
    const prev = prevPolled.current
    prevPolled.current = { key: seriesKey, bars: polled }
    if (!prev || prev.key !== seriesKey || !polled.length) return
    const first = polled[0].t
    const dropped = prev.bars.filter(b => b.t < first)
    if (!dropped.length) return
    setOlder(h => {
      if (h.key !== seriesKey) return h
      const have = new Set(h.bars.map(b => b.t))
      const add = dropped.filter(b => !have.has(b.t))
      return add.length ? { ...h, bars: [...h.bars, ...add] } : h
    })
  }, [data?.bars, seriesKey])

  /** Where the range's view opens, on the polled series alone — at the
   * moment the canvas resets there are no pages yet, so the index holds. */
  const focusFrom = useMemo(
    () => pages.bars.length + focusIndex((data?.bars ?? []).map(b => b.t), range), [data?.bars, range, pages.bars.length])

  /** The series WITHOUT the live tick: pages plus the poll. Everything
   * derived by walking the whole series — indicators, panes, the
   * alignment — reads this, so a trade does not recompute an oscillator
   * over thousands of bars once a second; the last point of an SMA lags
   * the tick by at most one poll, which is invisible. The candles, the tag
   * and the readout read `bars`, which carries the tick. */
  const stableBars = useMemo(() => {
    const polled = data?.bars ?? []
    return pages.bars.length ? [...pages.bars, ...polled] : polled
  }, [data?.bars, pages.bars])
  /** The live trade folded into the last bar (lib/provisional): the close
   * follows the trade, and the high and low accumulate across trades of
   * THIS series only. */
  const forming = useRef<FormingBar | null>(null)
  const fullBars = useMemo(() => {
    const src = stableBars
    if (!src.length || !tick || tick.stale || tick.symbol !== symbol) return src
    const late = !!data?.delay_minutes && tradeIsPastLastBar(src[src.length - 1].t, tick.at, data.interval)
    const got = foldLiveTrade(src, seriesKey, tick, forming.current, late)
    forming.current = got.forming
    return got.bars
  }, [stableBars, tick, symbol, seriesKey, data?.delay_minutes, data?.interval])

  /** The provisional line past a delayed series' last bar: the server's
   * one-exchange closes plus the live trade. Empty when the series is
   * real-time, replaying, or the tick is stale. */
  const provisional = useMemo(() => {
    if (!data?.delay_minutes || !stableBars.length) return []
    const live = tick && !tick.stale && tick.symbol === symbol ? tick : null
    return provisionalPoints(stableBars[stableBars.length - 1].t, data.provisional, live, data.interval)
  }, [data?.delay_minutes, data?.provisional, data?.interval, stableBars, tick, symbol])

  /** REPLAY (2026-09-06). Pick a bar; the chart shows the series only up to
   * it, and every derived thing — panes, overlays, markers, the
   * price tag — is computed on those bars alone, because they all read
   * `bars`. Step or play forward; the future arrives one bar at a time.
   * The live edge is off while replaying: a tick is news from a time the
   * chart is pretending has not happened. Leaving the series (symbol, range,
   * interval) ends the replay, since the index would point at nothing. */
  const [replay, setReplay] = useState<ReplayState>({ active: false, selecting: false, at: null, playing: false, speed: 1 })
  const bars = useMemo(
    () => (replay.active && replay.at != null ? fullBars.slice(0, replay.at + 1) : fullBars),
    [fullBars, replay.active, replay.at])
  const calcBars = useMemo(
    () => (replay.active && replay.at != null ? stableBars.slice(0, replay.at + 1) : stableBars),
    [stableBars, replay.active, replay.at])
  const live = replay.active ? false : liveFeed
  // A history page prepended under a replay moved every index; the
  // position follows the bars, not the number.
  const pagesLen = useRef(pages.bars.length)
  useEffect(() => {
    const delta = pages.bars.length - pagesLen.current
    pagesLen.current = pages.bars.length
    if (delta > 0) setReplay(r => (r.at != null ? { ...r, at: r.at + delta } : r))
  }, [pages.bars.length])
  useEffect(() => {
    setReplay(r => (r.active ? { ...r, active: false, selecting: false, at: null, playing: false } : r))
  }, [symbol, range, data?.interval])
  useEffect(() => {
    if (!replay.active || !replay.playing || replay.at == null) return
    const id = window.setInterval(() => {
      setReplay(r => {
        if (r.at == null) return r
        const last = fullBars.length - 1
        return r.at >= last ? { ...r, at: last, playing: false } : { ...r, at: r.at + 1 }
      })
    }, Math.max(40, 700 / replay.speed))
    return () => window.clearInterval(id)
  }, [replay.active, replay.playing, replay.speed, replay.at == null, fullBars.length])  // eslint-disable-line react-hooks/exhaustive-deps
  const startReplay = () => setReplay(r => ({ ...r, active: true, selecting: true, at: null, playing: false }))
  const exitReplay = () => setReplay(r => ({ ...r, active: false, selecting: false, at: null, playing: false }))
  const selectReplayAt = (t: string) => {
    const i = fullBars.findIndex(b => b.t === t)
    if (i >= 0) setReplay(r => ({ ...r, selecting: false, at: i, playing: false }))
  }
  const stepReplay = (d: number) => setReplay(r => {
    if (r.at == null) return r
    return { ...r, playing: false, at: Math.max(0, Math.min(fullBars.length - 1, r.at + d)) }
  })
  const seekReplay = (where: "start" | "end") => setReplay(r =>
    ({ ...r, playing: false, at: where === "start" ? Math.min(20, Math.max(0, fullBars.length - 1)) : fullBars.length - 1 }))
  const toggleReplayPlay = () => setReplay(r => (r.at == null ? r : { ...r, playing: !r.playing }))
  const setReplaySpeed = (speed: number) => setReplay(r => ({ ...r, speed }))
  // Space plays and pauses; the arrows step. Only while replaying, and never
  // over a text field.
  useEffect(() => {
    if (!replay.active) return
    const onKey = (ev: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return
      if (ev.key === " ") { ev.preventDefault(); toggleReplayPlay() }
      else if (ev.key === "ArrowRight") { ev.preventDefault(); stepReplay(1) }
      else if (ev.key === "ArrowLeft") { ev.preventDefault(); stepReplay(-1) }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay.active, fullBars.length])

  /** Which indicator panes this series can carry. Built in the order the
   * menu lists them, not the order they were clicked, so the stack does not
   * reshuffle as you toggle. Each indicator judges its own warm-up against
   * the bars actually here, so a shorter range drops only what genuinely
   * cannot be computed. Every one of them is gated on `indicators_reliable`:
   * the browser-computed ones read the same bars the server measured, so they
   * inherit the same verdict rather than each forming its own — an oscillator
   * on a feed too sparse to support it draws identically to a real one, which
   * is exactly what makes it dangerous (the coverage gate). */
  const drawable = useMemo(() =>
    data?.indicators_reliable
      ? indicators.filter(i => {
          const def = indicatorDef(i.type)
          return def.place === "pane" && !i.hidden && calcBars.length >= def.warmup(i.params)
        })
      : [],
    [data?.indicators_reliable, indicators, calcBars.length])
  const heightOf = (i: Indicator) => paneHeights[i.id] ?? paneHeightFor(indicatorDef(i.type))
  const budgeted = drawable.reduce((n, i) => n + heightOf(i), 0)
  const priceHeight = "priceHeight" in size
    ? size.priceHeight
    : Math.max(160, size.totalHeight - budgeted)

  /** What the range strip does with a click. Picking a DIFFERENT range
   * changes it; picking the one already showing puts the view back where
   * that range starts (2026-09-21, the owner: after scrolling through the
   * chart, "I press the active 1D again, it should recalibrate for 1D").
   * Before this the click was a state write of the value already held, so
   * React did nothing and the button looked broken. */
  const pickRange = (r: ChartRange) => {
    if (r === range) viewRef.current?.reset()
    else setRange(r)
  }

  /** The panes' SERIES — volume always, the oscillators as the reader adds
   * them — computed off the stable bars. Heights are applied below, so a
   * divider drag does not recompute every oscillator per frame. */
  const paneSeries = useMemo(() => {
    if (!data) return []
    const out: (Pane | null)[] = [volumePane(calcBars, 1, theme.gain, theme.loss)]
    for (const ind of drawable) out.push(indicatorPane(ind, calcBars, 1, theme))
    return out.filter(Boolean) as Pane[]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, calcBars, drawable, theme])
  const stacked: Pane[] = useMemo(() => paneSeries.map(p => ({
    ...p,
    height: p.id === "volume"
      // A SHARE OF THE PRICE AREA, not a fixed height, so the band keeps its
      // proportion on a tall monitor and a short tile alike. 16% on a
      // desktop (2026-09-21, the owner's own resize, measured off it and set
      // as the default — it was 22%, which took a quarter of a 560px chart
      // for a band that is context for the price above it). On a phone a
      // smaller share still, of a chart that is already short (2026-09-11).
      ? (paneHeights.volume ?? Math.round(priceHeight * (narrow ? 0.14 : 0.16)))
      : (paneHeights[p.id] ?? paneHeightFor(indicatorDef((drawable.find(i => i.id === p.id) ?? drawable[0]).type))),
  })), [paneSeries, paneHeights, priceHeight, drawable])

  /** The overlay lines, tagged by instance so the legend finds its own. */
  const overlaySeries = useMemo(() => buildOverlays(calcBars, indicators), [calcBars, indicators])


  /** The canvas GROWS with the panes instead of the price pane paying for
   * them (in tile mode). Panes are subtracted from the canvas height inside
   * the renderer, so a fixed height meant each new oscillator ate the chart
   * it was meant to annotate. */
  const oscHeight = stacked
    .filter(p => p.id !== "volume")
    .reduce((n, p) => n + p.height, 0)
  const canvasHeight = priceHeight + oscHeight

  return {
    provisional: replay.active ? [] : provisional,
    symbol, slot, applyPrefs, snapshotPrefs, replaceIndicators,
    range, setRange, pickRange, type, setType, scale, setScale,
    loadHistory, historyLoading: pages.loading, historyDone: pages.done, historyNote: pages.note, focusFrom, seriesId: seriesKey,
    timeZone, setTimeZone, priceLine, setPriceLine, viewRef,
    interval, setInterval, intervalPinned, setIntervalPinned, pinInterval, intervalByRange,
    indicators, addIndicator, updateIndicator, removeIndicator,
    paneHeights, setPaneHeight, settingsId, setSettingsId, overlaySeries,
    drawings, history, tool, setTool, drawOpen, setDrawOpen,
    drawVisible, setDrawVisible, magnet, setMagnet, allLocked,
    projection, setProjection, hovered, setHovered, hoverAt, setHoverAt,
    theme, data, isFetching, err, bars, fullBars, live,
    replay, startReplay, exitReplay, selectReplayAt, stepReplay, seekReplay, toggleReplayPlay, setReplaySpeed,
    stacked, priceHeight, canvasHeight,
  }
}

export type ChartEngine = ReturnType<typeof useChartEngine>
