import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  Camera, History, Layers, Lock, LockOpen, Maximize2, Minimize2, Newspaper, Pause, Play, Redo2,
  SkipBack, SkipForward, Star, StepBack, StepForward, Trash2, Undo2, X,
} from "lucide-react"
import { ChartSurface } from "@/components/chart/ChartSurface"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { resetChartPrefs } from "@/lib/chartPrefs"
import { OhlcvStrip } from "@/components/chart/OhlcvStrip"
import { BAR, BAR_ICON, ChartToolbar, Divider, Item, Menu, RANGES, intervalLabel, rangeLabel } from "@/components/ChartToolbar"
import { TIME_ZONES, offsetLabel } from "@/lib/chartTime"
import { useChartState } from "@/lib/chartState"
import {
  DEFAULT_LAYOUT, GRIDS, cellCount, makeSavedLayout, makeTemplate,
  validateLayout, validateLayouts, validateTemplates, type GridId, type Layout, type SavedLayout, type Template,
} from "@/lib/chartLayouts"
import { TOOL_GROUPS, type Drawing } from "@/components/ChartDrawings"
import { SymbolSuggest } from "@/components/SymbolSuggest"
import { SymbolNews } from "@/components/SymbolNews"
import { Empty, btnCls, menuHeadCls, menuItemCls } from "@/components/terminal"
import { indicatorLabel } from "@/lib/indicators"
import { useChartEngine, type ChartEngine } from "@/lib/chartEngine"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { useChartCapabilities, useQuote, useQuotes } from "@/lib/queries"

/** The chart WORKSPACE — the whole page is the chart (2026-09-05).
 *
 * The tile on the Markets board is the chart in a box; this is the chart as
 * the room. Same engine, same drawings, same prefs (lib/chartEngine), laid
 * out the way a full-screen charting terminal is: controls across the top,
 * the tool column down the left, a legend over the plot, the range strip and
 * the clock along the bottom, and a rail on the right for the watchlist,
 * the drawings on this chart, and the symbol's news.
 *
 * What is deliberately NOT here, from the reference it copies: buy/sell
 * buttons (this terminal does not trade), a currency switch (it would need
 * FX rates the platform does not carry), and alerts (no notification path
 * yet). Nothing renders as a control that does nothing.
 */

type RailPanel = "watchlist" | "objects" | "news"
const RAIL_KEY = "alphadesk.chart.rail"

/** The clock, ticking, in the chart's display zone — and the menu that
 * changes the zone for the axis, the readouts and this clock together. */
function Clock({ timeZone, onTimeZone }: { timeZone: string; onTimeZone: (tz: string) => void }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const fmt = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone,
  })
  const zone = TIME_ZONES.find(z => z.id === timeZone)?.label ?? timeZone
  return (
    <span className="flex items-center gap-1.5">
      <span className="tnum whitespace-nowrap text-caption text-muted-foreground" title={zone}>
        {fmt.format(now)}
      </span>
      <Menu label={offsetLabel(timeZone, now)} up>
        {close => TIME_ZONES.map(z => (
          <Item key={z.id} selected={z.id === timeZone} onClick={() => { onTimeZone(z.id); close() }}>
            <span className="flex-1">{z.label}</span>
            <span className="tnum text-label text-muted-foreground">{offsetLabel(z.id, now)}</span>
          </Item>
        ))}
      </Menu>
    </span>
  )
}

/** Their legend, over the plot: who this is, at what interval, on which
 * exchange, the live price and the change on the day. */
function Legend({ e }: { e: ChartEngine }) {
  const { data: q } = useQuote(e.symbol)
  const { data, bars, hovered, hoverAt, live } = e
  const last = bars[bars.length - 1]
  const price = last?.c ?? q?.price
  // Replaying, "previous close" is the bar before the one shown — today's
  // previous close belongs to a day the replay has not reached.
  const prev = e.replay.active ? bars[bars.length - 2]?.c ?? null : q?.previous_close ?? null
  const chg = price != null && prev != null ? price - prev : q?.change ?? null
  const pct = price != null && prev ? ((price - prev) / prev) * 100 : q?.change_pct ?? null
  const up = (chg ?? 0) >= 0
  const { data: caps } = useChartCapabilities()
  const iv = data?.interval_label ?? intervalLabel(data?.interval ?? e.interval, caps?.intervals)
  return (
    <div className="pointer-events-none absolute left-2 top-1.5 z-20 max-w-[70%]">
      <div className="flex flex-wrap items-baseline gap-x-2 text-body">
        <span className="font-extrabold text-foreground">{q?.name ?? e.symbol}</span>
        <span className="text-muted-foreground">· {iv}{q?.exchange ? ` · ${q.exchange}` : ""}</span>
        {/* A soft pill with a pulsing dot (2026-09-18: the bordered caps
            box read as awkward). The pulse stops under reduced motion,
            like every animation here. */}
        {live && (
          <span className="inline-flex h-[20px] items-center gap-1.5 self-center rounded-full bg-gain/15 px-2 text-label font-semibold text-gain">
            <span aria-hidden="true" className="h-[6px] w-[6px] animate-pulse rounded-full bg-gain" />
            Live
          </span>
        )}
      </div>
      {price != null && (
        <div className="flex items-baseline gap-2">
          <span className="tnum text-figure font-extrabold text-foreground">{price.toFixed(2)}</span>
          {chg != null && (
            <span className={`tnum text-body font-semibold ${up ? "text-gain" : "text-loss"}`}>
              {up ? "+" : ""}{chg.toFixed(2)}{pct != null ? ` (${up ? "+" : ""}${pct.toFixed(2)}%)` : ""}
            </span>
          )}
        </div>
      )}
      {data && (
        <OhlcvStrip bar={hovered ?? last ?? null} live={hovered == null}
                    symbol={data.symbol} first={bars[0] ?? null} at={hoverAt} timeZone={e.timeZone} delayMinutes={data.delay_minutes} />
      )}
    </div>
  )
}

/** Save the chart as a PNG — the SVGs composited over the ground colour, with
 * every token reference resolved, since an <img> loading serialized SVG knows
 * nothing about the page's CSS variables. */
async function snapshot(host: HTMLElement, name: string) {
  const svgs = [...host.querySelectorAll("svg")].filter(s => s.getBoundingClientRect().width > 100)
  if (!svgs.length) return
  const root = getComputedStyle(document.documentElement)
  const resolve = (src: string) =>
    src.replace(/var\((--[\w-]+)\)/g, (_, v) => root.getPropertyValue(v).trim() || "#888")
  const base = host.getBoundingClientRect()
  const scale = window.devicePixelRatio || 1
  const canvas = document.createElement("canvas")
  canvas.width = base.width * scale
  canvas.height = base.height * scale
  const ctx = canvas.getContext("2d")
  if (!ctx) return
  ctx.scale(scale, scale)
  ctx.fillStyle = root.getPropertyValue("--background").trim() || "#fff"
  ctx.fillRect(0, 0, base.width, base.height)
  for (const svg of svgs) {
    const r = svg.getBoundingClientRect()
    const clone = svg.cloneNode(true) as SVGSVGElement
    clone.setAttribute("width", String(r.width))
    clone.setAttribute("height", String(r.height))
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
    clone.querySelectorAll(".tnum").forEach(t => t.setAttribute("font-family", "ui-monospace, monospace"))
    const xml = resolve(new XMLSerializer().serializeToString(clone))
    const img = new Image()
    await new Promise<void>((ok, fail) => {
      img.onload = () => ok()
      img.onerror = () => fail(new Error("svg"))
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`
    }).catch(() => undefined)
    if (img.complete && img.naturalWidth) ctx.drawImage(img, r.left - base.left, r.top - base.top, r.width, r.height)
  }
  const a = document.createElement("a")
  a.download = `${name}.png`
  a.href = canvas.toDataURL("image/png")
  a.click()
}

const railBtn = (on: boolean) =>
  `flex h-[32px] w-[32px] items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground ${
    on ? "bg-foreground/10 !text-foreground" : ""}`

/* The side panels' rows are rounded highlights inset from the panel's edge,
 * not full-width stripes (2026-09-19, the owner: "boxy, sharp, not nextjs
 * ish") — the same row the menus use. */
const panelRow = (on = false) =>
  `group flex items-center gap-2 rounded-md px-2 py-1.5 text-body ${
    on ? "bg-foreground/[0.08]" : "hover:bg-foreground/[0.05]"}`

/** The board, in the chart's rail (2026-09-16): the same symbols the strip
 * carries, so the workspace and every other page follow one list. Adding
 * happens on the strip, which is on screen here too. */
function BoardRail({ current, onPick }: { current: string; onPick: (s: string) => void }) {
  const { symbols, remove } = useBoardSymbols()
  const quotes = useQuotes(symbols)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {symbols.length === 0 && <Empty>nothing on the board yet — add a symbol on the strip</Empty>}
        {symbols.map(s => {
          const q = quotes.data?.quotes?.[s]
          const pct = q?.change_pct ?? null
          const up = (pct ?? 0) >= 0
          return (
            <div key={s}
              className={`${panelRow(s === current)} cursor-pointer`}
              onClick={() => onPick(s)}>
              <span className="shrink-0 whitespace-nowrap font-bold tracking-ticker">{s}</span>
              <span className="tnum min-w-0 flex-1 text-right">{q ? q.price.toFixed(2) : "…"}</span>
              <span className={`tnum w-[58px] shrink-0 text-right ${pct == null ? "text-muted-foreground" : up ? "text-gain" : "text-loss"}`}>
                {pct == null ? "—" : `${up ? "+" : ""}${pct.toFixed(2)}%`}
              </span>
              <button type="button" aria-label={`Take ${s} off the board`}
                onClick={ev => { ev.stopPropagation(); remove(s) }}
                className="w-4 shrink-0 text-muted-foreground opacity-0 hover:text-loss group-hover:opacity-100">×</button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** The object tree: every drawing on this chart, with lock and delete. */
function Objects({ e }: { e: ChartEngine }) {
  const label = (d: Drawing) =>
    TOOL_GROUPS.flatMap(g => g.tools).find(t => t.id === d.kind)?.label ?? d.kind
  const patch = (id: string, p: Partial<Drawing>) =>
    e.history.commit(e.drawings.map(d => (d.id === id ? { ...d, ...p } : d)))
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
      {e.drawings.length === 0 && <Empty>no drawings on {e.symbol} yet</Empty>}
      {e.drawings.map(d => (
        <div key={d.id} className={panelRow()}>
          <span className="h-[10px] w-[10px] shrink-0 rounded-full border border-border"
                style={{ background: d.style?.color ?? "var(--accent)" }} />
          <span className="min-w-0 flex-1 truncate">
            {d.kind === "text" && d.text ? `“${d.text}”` : label(d)}
          </span>
          <span className="tnum shrink-0 text-label text-muted-foreground">{d.a.price.toFixed(2)}</span>
          <button type="button" aria-label={d.locked ? "Unlock" : "Lock"} onClick={() => patch(d.id, { locked: !d.locked })}
            className={`shrink-0 ${d.locked ? "text-accent" : "text-muted-foreground hover:text-foreground"}`}>
            {d.locked ? <Lock className="h-[12px] w-[12px]" /> : <LockOpen className="h-[12px] w-[12px]" />}
          </button>
          <button type="button" aria-label="Delete drawing" disabled={!!d.locked}
            onClick={() => e.history.commit(e.drawings.filter(x => x.id !== d.id))}
            className="shrink-0 text-muted-foreground hover:text-loss disabled:opacity-35">
            <Trash2 className="h-[12px] w-[12px]" />
          </button>
        </div>
      ))}
    </div>
  )
}

/** The replay transport, above the range bar while a replay is on: to the
 * start, a bar back, play/pause, a bar forward, to the end, the speed, and
 * where the tape is. Space and the arrows do the same from the keyboard. */
function ReplayBar({ e }: { e: ChartEngine }) {
  const { replay, fullBars, bars, timeZone } = e
  const n = fullBars.length
  const at = replay.at
  const stamp = at != null && bars[at]
    ? new Date(bars[at].t).toLocaleString("en-US", { timeZone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : null
  const b = "inline-flex h-[24px] w-[24px] items-center justify-center border border-border text-muted-foreground hover:bg-foreground/5 hover:text-foreground disabled:opacity-35 disabled:hover:bg-transparent"
  const idle = at == null
  return (
    <div className="flex items-center gap-1 border-t border-row-rule bg-info-tint px-2.5 py-1.5">
      <span className="mr-1 text-label font-medium uppercase tracking-caps text-info">Replay</span>
      <button type="button" className={b} title="To the start" aria-label="Replay to start" disabled={idle} onClick={() => e.seekReplay("start")}><SkipBack className="h-[12px] w-[12px]" /></button>
      <button type="button" className={b} title="Back one bar (←)" aria-label="Replay back one bar" disabled={idle || at === 0} onClick={() => e.stepReplay(-1)}><StepBack className="h-[12px] w-[12px]" /></button>
      <button type="button" className={`${b} ${replay.playing ? "bg-info text-background hover:bg-info hover:text-background" : ""}`}
        title={replay.playing ? "Pause (space)" : "Play (space)"} aria-label={replay.playing ? "Pause replay" : "Play replay"}
        disabled={idle || at === n - 1} onClick={e.toggleReplayPlay}>
        {replay.playing ? <Pause className="h-[12px] w-[12px]" /> : <Play className="h-[12px] w-[12px]" />}
      </button>
      <button type="button" className={b} title="Forward one bar (→)" aria-label="Replay forward one bar" disabled={idle || at === n - 1} onClick={() => e.stepReplay(1)}><StepForward className="h-[12px] w-[12px]" /></button>
      <button type="button" className={b} title="To the end" aria-label="Replay to end" disabled={idle} onClick={() => e.seekReplay("end")}><SkipForward className="h-[12px] w-[12px]" /></button>
      <Menu label={`${replay.speed}×`} up>
        {close => [0.5, 1, 2, 5, 10].map(sp => (
          <Item key={sp} selected={sp === replay.speed} onClick={() => { e.setReplaySpeed(sp); close() }}>{sp}× speed</Item>
        ))}
      </Menu>
      <span className="tnum ml-2 text-caption text-muted-foreground">
        {idle ? "Click a bar on the chart to start" : `bar ${at + 1} of ${n} · ${stamp}`}
      </span>
      <div className="flex-1" />
      <button type="button" onClick={e.exitReplay} aria-label="Exit replay"
        className={btnCls({}, "uppercase tracking-caps")}>
        <X className="h-[11px] w-[11px]" /> Exit
      </button>
    </div>
  )
}

/** A grid glyph: the cells of a layout, drawn as boxes. */
function GridGlyph({ id }: { id: GridId }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.3 }
  const box: Record<GridId, React.ReactNode> = {
    "1": <rect x="2" y="3" width="12" height="10" {...p} />,
    "2h": <><rect x="2" y="3" width="5.5" height="10" {...p} /><rect x="8.5" y="3" width="5.5" height="10" {...p} /></>,
    "2v": <><rect x="2" y="3" width="12" height="4.5" {...p} /><rect x="2" y="8.5" width="12" height="4.5" {...p} /></>,
    "3": <><rect x="2" y="3" width="5.5" height="10" {...p} /><rect x="8.5" y="3" width="5.5" height="4.5" {...p} /><rect x="8.5" y="8.5" width="5.5" height="4.5" {...p} /></>,
    "4": <><rect x="2" y="3" width="5.5" height="4.5" {...p} /><rect x="8.5" y="3" width="5.5" height="4.5" {...p} /><rect x="2" y="8.5" width="5.5" height="4.5" {...p} /><rect x="8.5" y="8.5" width="5.5" height="4.5" {...p} /></>,
  }
  return <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{box[id]}</svg>
}

/** A name box that saves on Enter — for a layout or a template. */
function NameEntry({ placeholder, onSave }: { placeholder: string; onSave: (name: string) => void }) {
  const [name, setName] = useState("")
  return (
    <div className="flex items-center gap-1 px-2 py-1.5">
      <input value={name} onChange={ev => setName(ev.target.value)} placeholder={placeholder}
        onKeyDown={ev => { if (ev.key === "Enter" && name.trim()) { ev.preventDefault(); onSave(name); setName("") } }}
        aria-label={placeholder}
        className="h-[28px] min-w-0 flex-1 border border-input bg-card px-2 text-body text-foreground outline-none focus:border-accent" />
      <button type="button" disabled={!name.trim()} onClick={() => { onSave(name); setName("") }}
        className={btnCls({ variant: "accent", size: "lg" }, "font-extrabold")}>Save</button>
    </div>
  )
}

/** One cell of the grid: measures its own height for its engine, draws the
 * legend over the plot, and marks itself when it is the cell the toolbar
 * acts on. The indicator legend starts 92px down: the name line, the price
 * line, the OHLCV row and its stamp line stack to about 86px at narrow widths. */
function Cell({ e, active, onActivate, onHeight }: {
  e: ChartEngine
  active: boolean
  onActivate: () => void
  onHeight: (h: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(entries => {
      const h = entries[0]?.contentRect.height
      if (h) onHeight(Math.max(160, Math.floor(h)))
    })
    ro.observe(ref.current)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const { data, err, symbol } = e
  return (
    // flex-1: the cell FILLS its grid slot. Without it the cell was as tall
    // as its content, its content was as tall as the canvas, and the canvas
    // was as tall as the cell said — a loop that settled at the 160px floor
    // with the rest of the slot empty.
    <div ref={ref} onMouseDown={onActivate}
      className={`relative min-h-0 min-w-0 flex-1 overflow-hidden ${active ? "ring-1 ring-inset ring-accent/60" : ""}`}>
      {!symbol && <Empty>Pick a symbol — the box in the toolbar, or a chip on the strip.</Empty>}
      {symbol && err && <Empty>{err}</Empty>}
      {symbol && !err && !data && <Empty>loading…</Empty>}
      {symbol && !err && data && (
        <ErrorBoundary label="This chart" onReset={() => resetChartPrefs(e.slot)}>
          <ChartSurface e={e} legendTop={92} toolsAlwaysOn>
            <Legend e={e} />
          </ChartSurface>
        </ErrorBoundary>
      )}
    </div>
  )
}

export default function ChartPage() {
  const [params] = useSearchParams()
  const symbol = (params.get("symbol") ?? "").toUpperCase()
  const { add } = useBoardSymbols()
  const { data: caps } = useChartCapabilities()
  const root = useRef<HTMLDivElement>(null)
  const [full, setFull] = useState(false)
  const [rail, setRail] = useState<RailPanel | null>(() => {
    try { return (localStorage.getItem(RAIL_KEY) as RailPanel | "none" | null) === "none" ? null
      : (localStorage.getItem(RAIL_KEY) as RailPanel | null) ?? "watchlist" } catch { return "watchlist" }
  })
  const [draft, setDraft] = useState("")

  // The grid and what is in it. The live layout follows the account like
  // the prefs; saved layouts and templates are the named copies.
  const [layout, setLayout] = useChartState<Layout>("layout", DEFAULT_LAYOUT, validateLayout)
  const [saved, setSaved] = useChartState<SavedLayout[]>("layouts", [], validateLayouts)
  const [templates, setTemplates] = useChartState<Template[]>("templates", [], validateTemplates)
  const cells = cellCount(layout.grid)
  const [active, setActive] = useState(0)
  const [heights, setHeights] = useState<number[]>([520, 520, 520, 520])
  const setHeight = (i: number, h: number) =>
    setHeights(hs => (hs[i] === h ? hs : hs.map((x, k) => (k === i ? h : x))))

  // Four engines, always — hooks cannot come and go with the grid. A cell
  // the grid does not show gets an empty symbol, which disables its queries
  // and its live subscription; it costs a few state slots and nothing else.
  const symbolFor = (i: number) => (i < cells ? (i === 0 ? symbol : layout.symbols[i - 1] ?? symbol) : "")
  const e0 = useChartEngine(symbolFor(0), { totalHeight: heights[0] }, { slot: 0 })
  const e1 = useChartEngine(symbolFor(1), { totalHeight: heights[1] }, { slot: 1 })
  const e2 = useChartEngine(symbolFor(2), { totalHeight: heights[2] }, { slot: 2 })
  const e3 = useChartEngine(symbolFor(3), { totalHeight: heights[3] }, { slot: 3 })
  const engines = [e0, e1, e2, e3]
  const e = engines[Math.min(active, cells - 1)]
  const { data, bars } = e

  useEffect(() => { if (active >= cells) setActive(0) }, [cells, active])
  useEffect(() => {
    const onChange = () => setFull(!!document.fullscreenElement)
    document.addEventListener("fullscreenchange", onChange)
    return () => document.removeEventListener("fullscreenchange", onChange)
  }, [])
  const setRailPersist = (p: RailPanel | null) => {
    setRail(p)
    try { localStorage.setItem(RAIL_KEY, p ?? "none") } catch { /* private mode */ }
  }

  /** Re-point the ACTIVE cell. Cell 0 is the board's symbol, so it goes
   * through the strip; the others are the layout's own. */
  const pickSymbol = (s: string) => {
    if (e.slot === 0) add(s)
    else setLayout(l => ({ ...l, symbols: l.symbols.map((x, k) => (k === e.slot - 1 ? s.toUpperCase() : x)) }))
  }

  const saveLayout = (name: string) => {
    const snap = makeSavedLayout(name, layout.grid,
      engines.map((x, i) => (i < cells ? x.symbol : "")),
      engines.map(x => x.snapshotPrefs()))
    setSaved(l => [snap, ...l.filter(x => x.name !== snap.name)].slice(0, 20))
    setLayout(l => ({ ...l, openId: snap.id }))
  }
  const openSaved = (l: SavedLayout) => {
    setLayout({ grid: l.grid, symbols: [1, 2, 3].map(i => l.symbols[i] || null), openId: l.id })
    if (l.symbols[0]) add(l.symbols[0])
    engines.forEach((x, i) => x.applyPrefs(l.prefs[i]))
    setActive(0)
  }
  const openLayout = layout.openId ?? null
  const currentName = saved.find(x => x.id === openLayout)?.name

  const gridCls: Record<GridId, string> = {
    "1": "grid-cols-1 grid-rows-1",
    "2h": "grid-cols-2 grid-rows-1",
    "2v": "grid-cols-1 grid-rows-2",
    "3": "grid-cols-2 grid-rows-2",
    "4": "grid-cols-2 grid-rows-2",
  }

  return (
    <div ref={root} data-slot="widget"
      className="flex h-full min-h-0 flex-col border border-card-border bg-card shadow-card">
      <ChartToolbar
        leading={
          <div className="mr-1 flex items-center">
            <SymbolSuggest value={draft} onChange={setDraft}
              onPick={pickSymbol} placeholder={e.symbol || "Symbol"} width="w-[120px]" />
          </div>
        }
        type={e.type} onType={e.setType}
        scale={e.scale} onScale={e.setScale}
        interval={e.interval}
        intervals={caps?.intervals}
        refused={caps?.refused}
        planNote={data?.plan_note}
        onInterval={iv => e.pinInterval(iv)}
        pinned={e.intervalPinned}
        servedInterval={data?.interval}
        servedLabel={data?.interval_label}
        available={data?.intervals}
        indicators={e.indicators} onAddIndicator={e.addIndicator}
        drawOpen={e.drawOpen} onDrawOpen={() => e.setDrawOpen(!e.drawOpen)}
        drawToggle={false}
        indicatorsReliable={data?.indicators_reliable ?? false}
        barCount={bars.length}
        trailing={
          // Wraps rather than scrolls on a phone: its Templates and Layout
          // menus drop down, and a scrolling row would clip them.
          <div className="flex flex-wrap items-center gap-0.5">
            {/* Indicator templates: the setup you keep applying. */}
            <Menu variant="bar" label="Templates" chevron={false} active={templates.length > 0} align="right">
              {close => (
                <div className="min-w-[240px]">
                  <div className={menuHeadCls}>
                    Indicator templates
                  </div>
                  {templates.length === 0 && (
                    <p className="px-2 py-1 text-caption text-muted-foreground">None saved yet.</p>
                  )}
                  {templates.map(t => (
                    <div key={t.id} className="group flex items-center gap-2 rounded-sm px-2 py-1 text-caption hover:bg-foreground/[0.06]">
                      <button type="button" className="min-w-0 flex-1 text-left" title={t.indicators.map(indicatorLabel).join(", ") || "empty"}
                        onClick={() => { e.replaceIndicators(t.indicators); close() }}>
                        <span className="block truncate">{t.name}</span>
                        <span className="block truncate text-label text-muted-foreground">
                          {t.indicators.map(indicatorLabel).join(" · ") || "no indicators"}
                        </span>
                      </button>
                      <button type="button" aria-label={`Delete template ${t.name}`} onClick={() => setTemplates(l => l.filter(x => x.id !== t.id))}
                        className="text-muted-foreground opacity-0 hover:text-loss group-hover:opacity-100">×</button>
                    </div>
                  ))}
                  <span className="-mx-1 my-1 block h-px bg-row-rule" />
                  <NameEntry placeholder="Save current indicators as…"
                    onSave={name => setTemplates(l => [makeTemplate(name, e.indicators), ...l.filter(x => x.name !== name.trim())].slice(0, 30))} />
                </div>
              )}
            </Menu>
            {/* Layouts: the grid, and the named ones. */}
            <Menu variant="bar" label={<><GridGlyph id={layout.grid} />{currentName ?? "Layout"}</>} active={cells > 1 || !!currentName} align="right">
              {close => (
                <div className="min-w-[260px]">
                  <div className="flex items-center gap-1 px-1 py-1">
                    {GRIDS.map(g => (
                      <button key={g.id} type="button" title={g.label} aria-label={g.label} aria-pressed={layout.grid === g.id}
                        onClick={() => setLayout(l => ({ ...l, grid: g.id, openId: null }))}
                        className={`flex h-[28px] w-[28px] items-center justify-center rounded-sm ${
                          layout.grid === g.id ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
                        <GridGlyph id={g.id} />
                      </button>
                    ))}
                  </div>
                  <span className="-mx-1 my-1 block h-px bg-row-rule" />
                  <div className={menuHeadCls}>
                    Saved layouts
                  </div>
                  {saved.length === 0 && (
                    <p className="px-2 py-1 text-caption text-muted-foreground">None saved yet.</p>
                  )}
                  {saved.map(l => (
                    <div key={l.id} className={`group flex items-center gap-2 rounded-sm px-2 py-1 text-caption hover:bg-foreground/[0.06] ${
                      l.id === openLayout ? "bg-foreground/[0.08] font-semibold" : ""}`}>
                      <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { openSaved(l); close() }}>
                        <span className="block truncate">{l.name}</span>
                        <span className="block truncate text-label text-muted-foreground">
                          {l.symbols.filter(Boolean).join(" · ")}
                        </span>
                      </button>
                      <button type="button" aria-label={`Delete layout ${l.name}`}
                        onClick={() => { setSaved(x => x.filter(y => y.id !== l.id)); if (openLayout === l.id) setLayout(cur => ({ ...cur, openId: null })) }}
                        className="text-muted-foreground opacity-0 hover:text-loss group-hover:opacity-100">×</button>
                    </div>
                  ))}
                  <span className="-mx-1 my-1 block h-px bg-row-rule" />
                  {currentName && (
                    <button type="button" onClick={() => { saveLayout(currentName); close() }}
                      className={menuItemCls}>
                      Save “{currentName}”
                    </button>
                  )}
                  <NameEntry placeholder="Save layout as…" onSave={name => { saveLayout(name); close() }} />
                </div>
              )}
            </Menu>
            <Divider />
            <button type="button" title={e.replay.active ? "Exit replay" : "Bar replay"} aria-label="Bar replay"
              aria-pressed={e.replay.active} onClick={() => (e.replay.active ? e.exitReplay() : e.startReplay())}
              className={`${BAR} ${e.replay.active ? "bg-info/15 !text-info" : ""}`}>
              <History className={BAR_ICON} />
            </button>
            <button type="button" title="Undo (⌘Z)" aria-label="Undo" disabled={!e.history.canUndo}
              onClick={e.history.undo} className={BAR}><Undo2 className={BAR_ICON} /></button>
            <button type="button" title="Redo (⇧⌘Z)" aria-label="Redo" disabled={!e.history.canRedo}
              onClick={e.history.redo} className={BAR}><Redo2 className={BAR_ICON} /></button>
            <button type="button" title="Save chart as image" aria-label="Save chart as image"
              onClick={() => { const h = root.current?.querySelectorAll<HTMLElement>("[data-chart-surface]")[Math.min(active, cells - 1)]; if (h) void snapshot(h, `${e.symbol}-${e.interval}`) }}
              className={BAR}><Camera className={BAR_ICON} /></button>
            <button type="button" title={full ? "Exit fullscreen" : "Fullscreen"} aria-label="Toggle fullscreen"
              onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void root.current?.requestFullscreen() }}
              className={BAR}>
              {full ? <Minimize2 className={BAR_ICON} /> : <Maximize2 className={BAR_ICON} />}
            </button>
          </div>
        }
      />

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className={`grid min-h-0 flex-1 gap-px bg-border ${gridCls[layout.grid]}`}>
            {engines.slice(0, cells).map((x, i) => (
              <div key={i} className={`flex min-h-0 min-w-0 flex-col bg-panel ${layout.grid === "3" && i === 0 ? "row-span-2" : ""}`}>
                <Cell e={x} active={cells > 1 && i === Math.min(active, cells - 1)}
                  onActivate={() => setActive(i)} onHeight={h => setHeight(i, h)} />
              </div>
            ))}
          </div>
          {e.replay.active && <ReplayBar e={e} />}
          <div className="flex flex-wrap items-center gap-1 border-t border-row-rule px-2.5 py-1.5">
            {RANGES.map(r => (
              <button key={r} type="button" onClick={() => e.setRange(r)}
                className={btnCls({ variant: "ghost", active: e.range === r })}>
                {rangeLabel(r)}
              </button>
            ))}
            <div className="flex-1" />
            <Clock timeZone={e.timeZone} onTimeZone={e.setTimeZone} />
          </div>
        </div>

        {/* The right rail: a column of icons, and the panel the active one
            opens. Hidden on phones, where the chart needs every pixel. */}
        {rail && (
          <div className="hidden w-[280px] shrink-0 flex-col border-l border-row-rule lg:flex">
            <div className="flex h-[40px] items-center justify-between border-b border-row-rule pl-3.5 pr-1.5">
              <span className="text-caption font-semibold text-foreground">
                {rail === "watchlist" ? "Board" : rail === "objects" ? "Objects" : "News"}
                <span className="ml-1.5 font-normal text-muted-foreground">
                  {rail === "watchlist" ? "" : rail === "objects" ? String(e.drawings.length) : e.symbol}
                </span>
              </span>
              <button type="button" aria-label="Close panel" onClick={() => setRailPersist(null)}
                className="flex h-[28px] w-[28px] items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground">
                <X className="h-[14px] w-[14px]" /></button>
            </div>
            {rail === "watchlist" && <BoardRail current={e.symbol} onPick={pickSymbol} />}
            {rail === "objects" && <Objects e={e} />}
            {rail === "news" && e.symbol && (
              <div className="min-h-0 flex-1 overflow-y-auto">
                <SymbolNews symbol={e.symbol} framed={false} />
              </div>
            )}
          </div>
        )}
        <div className="hidden w-[36px] shrink-0 flex-col items-center border-l border-row-rule py-1 lg:flex">
          <button type="button" title="Board" aria-label="Board" aria-pressed={rail === "watchlist"}
            onClick={() => setRailPersist(rail === "watchlist" ? null : "watchlist")} className={railBtn(rail === "watchlist")}>
            <Star className="h-[15px] w-[15px]" />
          </button>
          <button type="button" title="Objects on this chart" aria-label="Objects" aria-pressed={rail === "objects"}
            onClick={() => setRailPersist(rail === "objects" ? null : "objects")} className={railBtn(rail === "objects")}>
            <Layers className="h-[15px] w-[15px]" />
          </button>
          <button type="button" title="Symbol news" aria-label="News" aria-pressed={rail === "news"}
            onClick={() => setRailPersist(rail === "news" ? null : "news")} className={railBtn(rail === "news")}>
            <Newspaper className="h-[15px] w-[15px]" />
          </button>
        </div>
      </div>
    </div>
  )
}
