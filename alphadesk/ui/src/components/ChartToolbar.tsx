import { useEffect, useMemo, useRef, useState } from "react"
import { usePopoverFocus } from "@/lib/focus"
import { Activity, PenLine, Search } from "lucide-react"
import { INDICATORS, type Indicator, type IndicatorDef, type IndicatorType } from "@/lib/indicators"
import type { ScaleMode } from "@/components/chart/ChartCanvas"
import { SERIES_KINDS, type SeriesKind } from "@/lib/series"
import type { ChartRange, IntervalSpec } from "@/lib/api"
import { menuHeadCls, menuItemCls, menuPanelCls } from "@/components/terminal"

/** The chart's controls: series type, interval, scale, indicators.
 *
 * Expanding is NOT here. It is a property of the tile rather than of the chart,
 * so it lives in the widget header alongside every other tile's — this toolbar
 * carried a second copy of it, which is one control too many for one action.
 *
 * Modelled on the toolbar their board carries (type · interval · Lin · Ind)
 * rather than invented.
 *
 * The interval readout is not a control. It reports which SERIES the range
 * selected — minute bars for 1D/5D, daily past that — because the reader
 * should be able to see that "3M" is not the same kind of data as "1D". The
 * server owns that mapping; offering it as a picker here would let the two
 * disagree.
 *
 * There is no "Metrics" menu. One existed — statements plotted in a pane under
 * price — and it was removed from the CHART on 2026-08-21. The server side is
 * deliberately still there: /api/fundamentals and ingest/prices.fundamentals_series
 * are untouched, so the data is a fetch away if the direction returns, and
 * `api.fundamentals` in lib/api.ts is still bound to it with no caller. Git
 * history has the menu, the pane and the wiring.
 */

const TYPES = SERIES_KINDS

/** The intervals a provider that predates the catalogue would serve — the
 * builtin table. The live menu comes from /api/chart/capabilities; this is
 * the fallback while it loads and the label lookup for a stale id. */
export const INTERVALS: IntervalSpec[] = [
  { id: "1m", label: "1 min", unit: "Min", n: 1, max_days: 30 }, { id: "2m", label: "2 mins", unit: "Min", n: 2, max_days: 30 },
  { id: "5m", label: "5 mins", unit: "Min", n: 5, max_days: 60 }, { id: "15m", label: "15 mins", unit: "Min", n: 15, max_days: 60 },
  { id: "30m", label: "30 mins", unit: "Min", n: 30, max_days: 60 }, { id: "1h", label: "1 hour", unit: "Hour", n: 1, max_days: 730 },
  { id: "4h", label: "4 hours", unit: "Hour", n: 4, max_days: 730 }, { id: "1d", label: "1 day", unit: "Day", n: 1, max_days: null },
  { id: "1wk", label: "1 week", unit: "Week", n: 1, max_days: null }, { id: "1mo", label: "1 month", unit: "Month", n: 1, max_days: null },
]
export const intervalLabel = (id: string, catalogue?: IntervalSpec[]) =>
  (catalogue ?? INTERVALS).find(i => i.id === id)?.label ?? INTERVALS.find(i => i.id === id)?.label ?? id

/** The menu's sections, in the order theirs uses. */
const UNIT_GROUPS: { unit: IntervalSpec["unit"][]; label: string }[] = [
  { unit: ["Sec"], label: "Seconds" },
  { unit: ["Min"], label: "Minutes" },
  { unit: ["Hour"], label: "Hours" },
  { unit: ["Day", "Week", "Month"], label: "Days" },
]

const SCALES: { id: ScaleMode; label: string }[] = [
  { id: "linear", label: "Linear" },
  { id: "log", label: "Logarithmic" },
  { id: "percent", label: "Percent" },
]

/** Their exact set. 1D/5D are intraday, the rest daily — the server decides
 * which, so this is only a label. */
export const RANGES: ChartRange[] = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"]
/** The label theirs uses for the whole series. The server's key stays MAX. */
export const rangeLabel = (r: ChartRange) => (r === "MAX" ? "All" : r)

// The toolbar's bordered chip. Selected is the shared soft grey fill, as
// everywhere else (2026-09-18): red is for headings and alerts.
const btn = "inline-flex h-[24px] items-center whitespace-nowrap border px-2 text-caption font-semibold tracking-ticker transition-colors"
/** The toolbar button, the way theirs is: borderless, 28px, an icon and
 * a short label, tinted when open or active. Exported for the page's own
 * buttons so the whole bar reads as one row. */
// 13.5px on a 14px root (2026-09-11, the reader's call — 12.5 read small):
// the toolbar's words sit a hair under body size, its icons a hair over.
export const BAR = "inline-flex h-[32px] shrink-0 items-center gap-1.5 rounded-sm px-2 text-body font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-35 disabled:hover:bg-transparent"
export const BAR_ON = "bg-foreground/10 !text-foreground"
export const BAR_ICON = "h-[17px] w-[17px]"
export const Divider = () => <span aria-hidden="true" className="mx-1 h-5 w-px shrink-0 bg-border" />

/** The interval the way theirs writes it: 1m, 5m, 1h, 1D, 1W, 1M. */
export function compactInterval(id: string): string {
  const m = /^(\d+)(s|m|h|d|wk|mo)$/.exec(id)
  if (!m) return id
  return m[1] + ({ s: "s", m: "m", h: "h", d: "D", wk: "W", mo: "M" } as Record<string, string>)[m[2]]
}

/** A 16px picture of each series kind — drawn here, not borrowed. */
export function SeriesGlyph({ kind }: { kind: SeriesKind }) {
  const st = { fill: "none", stroke: "currentColor", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const }
  const body: Record<SeriesKind, React.ReactNode> = {
    candles: <><path d="M5 2v3M5 11v3M11 2v2M11 12v2" {...st} /><rect x="3" y="5" width="4" height="6" fill="currentColor" /><rect x="9" y="4" width="4" height="8" {...st} /></>,
    hollow: <><path d="M5 2v3M5 11v3M11 2v2M11 12v2" {...st} /><rect x="3" y="5" width="4" height="6" {...st} /><rect x="9" y="4" width="4" height="8" {...st} /></>,
    heikin: <><path d="M5 3v2M5 11v2M11 2v3M11 11v3" {...st} /><rect x="3" y="5" width="4" height="6" rx="1" fill="currentColor" /><rect x="9" y="5" width="4" height="6" rx="1" {...st} /></>,
    bars: <><path d="M5 2v12M3 6h2M5 10h2M11 2v12M9 8h2M11 5h2" {...st} /></>,
    line: <path d="M2 12l3.5-4 3 2.5L14 3" {...st} />,
    step: <path d="M2 12h3V8h3V5h3V3h3" {...st} />,
    area: <><path d="M2 12l3.5-4 3 2.5L14 3" {...st} /><path d="M2 12l3.5-4 3 2.5L14 3v11H2z" fill="currentColor" opacity="0.25" /></>,
    baseline: <><path d="M2 8h12" {...st} strokeDasharray="2 2" /><path d="M2 11l3.5-4 3 2.5L14 4" {...st} /></>,
    hlc: <><path d="M2 10l3.5-4 3 2.5L14 3" {...st} /><path d="M2 12l3.5-4 3 2.5L14 5v-4L11.5 3l-3 2.5L5 9 2 8z" fill="currentColor" opacity="0.2" /></>,
    highlow: <><rect x="3" y="4" width="2.5" height="8" fill="currentColor" /><rect x="7" y="2" width="2.5" height="10" fill="currentColor" /><rect x="11" y="6" width="2.5" height="7" fill="currentColor" /></>,
    columns: <><rect x="2.5" y="8" width="2.5" height="6" fill="currentColor" /><rect x="6.5" y="4" width="2.5" height="10" fill="currentColor" /><rect x="10.5" y="6" width="2.5" height="8" fill="currentColor" /></>,
  }
  return <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">{body[kind]}</svg>
}
const on = "border-border bg-foreground/10 text-foreground"
const off = "border-border text-muted-foreground hover:bg-foreground/5 hover:text-foreground"

/** A menu that closes on outside click and on Escape. Hand-rolled for the same
 * reason the rest of the primitives are — one popover does not justify a
 * dependency, and this one has to sit inside a 440px tile without clipping. */
export function Menu({ label, active, wide, chevron = true, up = false, align = "left", variant = "chip", title, children }: {
  /** Which edge the panel hangs from. A menu in the toolbar's right-hand
   * cluster opens leftwards, or it runs off the panel and its last
   * control — the Save button — is clipped. */
  align?: "left" | "right"
  /** "chip" is the bordered 22px Modernist chip; "bar" is the borderless
   * 28px toolbar button theirs uses — an icon or a short label, no
   * chevron, a tint when open or active. */
  variant?: "chip" | "bar"
  title?: string
  label: React.ReactNode
  active?: boolean
  wide?: boolean
  /** A value picker shows what it will change; a panel like "Ind" does not,
   * which is how theirs distinguishes the two. */
  chevron?: boolean
  /** Open upward. Required for anything on the BOTTOM edge of a tile: the
   * widget clips to its own box, so a menu dropped downward from there is
   * rendered entirely outside the clip and is simply invisible — it opens,
   * it responds, and nothing appears. */
  up?: boolean
  children: (close: () => void) => React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  // Into the panel on open, the arrow keys between its controls, and back
  // to this button on close (2026-09-18): keyboard users could open the
  // menu and then not reach anything in it.
  usePopoverFocus(open, panel, trigger)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      const t = e.target as Node
      // The symbol suggest box portals its panel to the document; a pick in
      // that panel is not a click away from this menu.
      if ((t as Element).closest?.("[data-symbol-suggest]")) return
      if (ref.current && !ref.current.contains(t)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", away)
    document.addEventListener("keydown", esc)
    return () => {
      document.removeEventListener("mousedown", away)
      document.removeEventListener("keydown", esc)
    }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        title={title}
        onClick={() => setOpen(o => !o)}
        className={variant === "bar"
          ? `${BAR} ${active || open ? BAR_ON : ""}`
          : `${btn} ${active || open ? on : off}`}
      >
        {label}{chevron && variant === "chip" && <span className="text-label"> ▾</span>}
      </button>
      {open && (
        <div ref={panel} className={`pop-in absolute z-50 ${menuPanelCls} ${
          align === "right" ? "right-0" : "left-0"
        } ${up ? "bottom-full mb-1" : "top-full mt-1"} ${wide ? "w-[320px]" : "min-w-[168px]"}`}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

export function Item({ selected, onClick, children }: {
  selected?: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${menuItemCls} text-foreground ${selected ? "font-semibold" : ""}`}
    >
      <span className="w-3 shrink-0 text-muted-foreground">{selected ? "✓" : ""}</span>
      {children}
    </button>
  )
}

export function ChartToolbar({
  type, onType, scale, onScale,
  indicators, onAddIndicator, indicatorsReliable,
  interval, onInterval, pinned = false, servedInterval, servedLabel, available, barCount = 0, drawOpen, onDrawOpen,
  leading, trailing, drawToggle = true, intervals, refused = [], planNote,
}: {
  /** The active provider's interval catalogue. Absent, the builtin list. */
  intervals?: IntervalSpec[]
  /** Intervals the reader's plan has refused this hour — listed, greyed. */
  refused?: string[]
  /** The server's sentence when a plan refusal was served as a coarser bar. */
  planNote?: string | null
  /** The ✎ that opens the tool column; off where the column is always up. */
  drawToggle?: boolean
  /** Symbols overlaid on the price pane. */
  /** The workspace puts its symbol box before the controls and its
   * undo/fullscreen/snapshot cluster after them; the tile has neither. */
  leading?: React.ReactNode
  trailing?: React.ReactNode
  type: SeriesKind
  onType: (t: SeriesKind) => void
  scale: ScaleMode
  onScale: (v: ScaleMode) => void
  interval: string
  /** The reader's choice for this range; "" hands the range back to its
   * default, the finest bar it offers. */
  onInterval: (v: string) => void
  /** Whether the interval on screen is the reader's pin for this range. */
  pinned?: boolean
  /** What the server actually served — may be coarser than asked. */
  servedInterval?: string
  servedLabel?: string
  /** The interval ids this range may offer, from the server. Undefined before
   * the first response, when the full list is the honest thing to show. */
  available?: string[]
  /** The instances on the chart; the menu counts them per type. */
  indicators: Indicator[]
  /** Adds an instance with the type's default parameters. */
  onAddIndicator: (t: IndicatorType) => void
  drawOpen: boolean
  onDrawOpen: () => void
  indicatorsReliable: boolean
  /** Bars on this range, so an indicator that cannot warm up on them is not
   * offered as though it could. */
  barCount?: number
}) {
  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-row-rule px-2.5 py-1.5">
      {leading}
      {leading && <Divider />}
      {/* Theirs, control for control: the series as a picture, the
          interval as its short form, the indicators with an
          icon and a word. Borderless buttons, dividers between groups. */}
      <Menu variant="bar" title={`Chart type · ${TYPES.find(t => t.id === type)!.label}`}
            label={<SeriesGlyph kind={type} />}>
        {close => TYPES.map(t => (
          <Item key={t.id} selected={t.id === type} onClick={() => { onType(t.id); close() }}>
            <span className="flex items-center gap-2"><SeriesGlyph kind={t.id} />{t.label}</span>
          </Item>
        ))}
      </Menu>

      <Menu variant="bar" title={`Interval · ${intervalLabel(interval, intervals)}`}
            label={<span className="tnum">{compactInterval(interval)}</span>}
            active={!!planNote || (!!servedInterval && servedInterval !== interval)}>
        {close => (
          <>
            {/* Grouped by unit, the way theirs is. Only what this RANGE can
                serve from this PROVIDER — the server sends that list with
                the series; a provider with second bars shows a Seconds
                section, one without never does. */}
            {UNIT_GROUPS.map(g => {
              const rows = (intervals ?? INTERVALS)
                .filter(i => g.unit.includes(i.unit) && (!available || available.includes(i.id)))
              if (!rows.length) return null
              return (
                <div key={g.label}>
                  <div className={menuHeadCls}>{g.label}</div>
                  {rows.map(i => refused.includes(i.id) ? (
                    // Still listed — the provider has it — but greyed: the
                    // reader's plan said no within the hour.
                    <button key={i.id} type="button" disabled title="Not included in your plan"
                      className={`${menuItemCls} text-muted-foreground opacity-45 hover:bg-transparent`}>
                      <span className="w-3 shrink-0" />{i.label}<span className="ml-auto text-label uppercase tracking-caps">plan</span>
                    </button>
                  ) : (
                    <Item key={i.id} selected={i.id === interval} onClick={() => { onInterval(i.id); close() }}>
                      {i.label}
                    </Item>
                  ))}
                </div>
              )
            })}
            <div className="my-1 h-px bg-border" />
            <Item selected={!pinned} onClick={() => { onInterval(""); close() }}>
              Finest for this range
            </Item>
            {planNote ? (
              <p className="px-3 py-1 text-label leading-snug text-warn">{planNote}</p>
            ) : servedInterval && servedInterval !== interval && (
              // Say so rather than silently redrawing at a coarser interval —
              // a chart that quietly changes what a bar means is the same
              // failure as an indicator drawn on data too sparse for it.
              <p className="px-3 py-1 text-label leading-snug text-muted-foreground">
                This range cannot reach that interval; showing {servedLabel} instead.
              </p>
            )}
          </>
        )}
      </Menu>

      <Menu variant="bar" title={`Scale · ${SCALES.find(x => x.id === scale)!.label}`}
            label={<span>{scale === "linear" ? "Lin" : scale === "log" ? "Log" : "%"}</span>}
            active={scale !== "linear"}>
        {close => SCALES.map(x => (
          <Item key={x.id} selected={x.id === scale} onClick={() => { onScale(x.id); close() }}>
            {x.label}
          </Item>
        ))}
      </Menu>

      <Divider />

      <Menu variant="bar" title="Indicators" wide chevron={false} active={indicators.length > 0}
            label={<><Activity className={BAR_ICON} aria-hidden="true" /><span className="hidden sm:inline">Indicators</span></>}>
        {() => (
          <IndicatorMenu
            indicators={indicators} onAdd={onAddIndicator}
            indicatorsReliable={indicatorsReliable}
            barCount={barCount}
          />
        )}
      </Menu>


      <div className="flex-1" />

      {drawToggle && (
        <button
          type="button"
          onClick={onDrawOpen}
          aria-label="Drawing tools"
          title="Drawing tools"
          className={`${BAR} ${drawOpen ? BAR_ON : ""}`}
        >
          <PenLine className={BAR_ICON} aria-hidden="true" />
        </button>
      )}
      {trailing}
      {/* No expand button here. Expanding is a WIDGET action, not a chart one,
          and it now lives in the widget header where every other tile carries
          it — one control in one place beats the same control twice. */}
    </div>
  )
}

/** The range strip. Theirs runs along the BOTTOM of the chart, under the
 * time axis, which is where a reader reaches for it — the top toolbar is for
 * what the chart IS, the bottom for how much of it you are looking at. All
 * nine, in the row (2026-09-10: the three-plus-a-menu form was cut — the
 * menu hid the selection and cost a click for every other range). */
export function ChartRanges({ range, onRange }: {
  range: ChartRange
  onRange: (r: ChartRange) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-0.5 border-t border-row-rule px-2.5 py-1.5">
      {RANGES.map(r => (
        <button
          key={r}
          type="button"
          onClick={() => onRange(r)}
          aria-pressed={range === r}
          className={`${BAR} tnum !px-1.5 ${range === r ? BAR_ON : "text-muted-foreground"}`}
        >
          {rangeLabel(r)}
        </button>
      ))}
    </div>
  )
}

/** The indicator picker: a search box over a grouped list, the way theirs is.
 * With twenty entries a flat list is already hard to scan, and the groups are
 * how a reader thinks about them — averages, then bands, then oscillators.
 *
 * Picking ADDS an instance (with the type's defaults) rather than toggling
 * one: two moving averages of different lengths are two rows, each with its
 * own settings, and the count beside a name says how many are on the chart.
 * Removing is done where the indicator is — the legend row or the pane. */
function IndicatorMenu({ indicators, onAdd, indicatorsReliable, barCount }: {
  indicators: Indicator[]
  onAdd: (t: IndicatorType) => void
  indicatorsReliable: boolean
  barCount: number
}) {
  const [q, setQ] = useState("")
  const needle = q.trim().toLowerCase()
  const groups = useMemo(() => {
    const defaults = (d: IndicatorDef) => Object.fromEntries(d.params.map(p => [p.key, p.def]))
    // Only what this range has the bars to warm up. Offering MACD on a 24-bar
    // month would add a row and draw nothing.
    const hits = INDICATORS.filter(d =>
      (!needle || d.label.toLowerCase().includes(needle) || d.short.toLowerCase().includes(needle))
      && (d.place === "overlay" || barCount >= d.warmup(defaults(d))))
    const by = new Map<string, IndicatorDef[]>()
    for (const d of hits) by.set(d.group, [...(by.get(d.group) ?? []), d])
    return [...by.entries()]
  }, [needle, barCount])
  const count = (t: IndicatorType) => indicators.filter(i => i.type === t).length
  const paneHidden = !indicatorsReliable

  return (
    <>
      <label className="-mx-1 -mt-1 mb-1 flex items-center gap-2 border-b border-row-rule px-3 py-2">
        <Search className="h-[14px] w-[14px] shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          autoFocus
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search indicators…"
          aria-label="Search indicators"
          className="min-w-0 flex-1 bg-transparent text-body outline-none placeholder:text-muted-foreground"
        />
      </label>
      <div className="max-h-[300px] overflow-y-auto">
        {groups.length === 0 && (
          <p className="px-2 py-3 text-caption text-muted-foreground">No indicator matches “{q}”.</p>
        )}
        {groups.map(([group, items]) => (
          <div key={group}>
            <div className={menuHeadCls}>{group}</div>
            {items.map(d => {
              const n = count(d.type)
              const gated = d.place === "pane" && paneHidden
              return (
                <button key={d.type} type="button" disabled={gated}
                  onClick={() => onAdd(d.type)}
                  title={gated ? "Hidden for this symbol — the feed is too sparse to compute it honestly." : `Add ${d.label}`}
                  className={`${menuItemCls} text-foreground`}>
                  <span className="h-[2px] w-3 shrink-0" style={{ background: d.color }} />
                  <span className="min-w-0 flex-1 truncate">{d.label}</span>
                  <span className="shrink-0 text-label text-muted-foreground">
                    {d.params.map(p => p.def).join(" ")}
                  </span>
                  {n > 0 && (
                    <span className="min-w-[18px] shrink-0 rounded-full bg-foreground/10 px-1.5 text-center text-label font-semibold leading-[16px] text-foreground">
                      {n}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        ))}
        {paneHidden && (
          // The server measured this feed too sparse to support oscillators,
          // and it hides them rather than draw something that looks right.
          // That verdict covers the browser-computed ones too: they read the
          // same bars, so they inherit the same doubt.
          <p className="px-2 py-2 text-label leading-snug text-muted-foreground">
            Oscillators are hidden for this symbol — the feed is too sparse to compute them honestly.
          </p>
        )}
      </div>
    </>
  )
}

