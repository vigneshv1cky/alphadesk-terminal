import type { ChartRange } from "@/lib/api"
import type { ScaleMode } from "@/components/chart/ChartCanvas"
import { SERIES_KINDS, type SeriesKind } from "@/lib/series"
import { DEFAULT_TIME_ZONE, validTimeZone } from "@/lib/chartTime"
import {
  INDICATORS, LEGACY, indicatorDef, newIndicator, type Indicator, type IndicatorType, quantizeParam, cleanParams } from "@/lib/indicators"

/** The chart's view settings, persisted so the chart survives navigation.
 *
 * Range, interval, series type, scale and the chosen indicators are HOW you
 * read a chart, not WHAT it shows — the symbol scopes the board and lives in
 * the URL; these are reader preferences and live in the browser (and on the
 * account, once signed in — see lib/chartEngine). One store for both charts
 * (the Markets tile and the /chart workspace), so switching views keeps the
 * same reading.
 *
 * Everything read back is validated against the known ids — a stale entry
 * from an older build degrades to the default rather than into a chart asking
 * the server for a range it no longer knows. Prefs written before indicators
 * became instances (2026-09-05) carried `overlays` and `panes` id lists;
 * those migrate to instances with the parameters the id implied.
 */

const KEY = "alphadesk.chart"
/** Slot 0 is THE chart — the tile and the workspace's first cell share it.
 * Slots 1–3 are the workspace's other grid cells, each with its own prefs. */
export const localPrefsKey = (slot = 0) => (slot ? `${KEY}.slot${slot}` : KEY)
export const serverPrefsKey = (slot = 0) => (slot ? `prefs:${slot}` : "prefs")

export type ChartPrefs = {
  /** When this record was last changed (ms since the epoch). The account's
   * copy replaces the browser's only when it is NEWER; a change made in
   * the last 600ms before a reload would otherwise lose to the stale copy. */
  updatedAt?: number
  range: ChartRange
  /** The interval on screen (the server's choice when nothing is pinned). */
  interval: string
  /** Whether `interval` is the reader's demand for the CURRENT range —
   * derived from `intervalByRange`; kept in the record for older readers. */
  intervalPinned: boolean
  /** The reader's interval PER RANGE (2026-09-11): a bar chosen on 1M is
   * 1M's, and comes back with it; ranges without an entry open on the
   * finest bar they offer. */
  intervalByRange: Partial<Record<ChartRange, string>>
  type: SeriesKind
  scale: ScaleMode
  indicators: Indicator[]
  /** Pane heights the reader has dragged, by pane id ("volume" included). */
  paneHeights: Record<string, number>
  /** How the axis and readouts label instants. Sessions stay in exchange time. */
  timeZone: string
  /** The dashed rule at the last price. */
  priceLine: boolean
}

const RANGES: ChartRange[] = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"]
const KINDS: SeriesKind[] = SERIES_KINDS.map(k => k.id)
const SCALES: ScaleMode[] = ["linear", "log", "percent"]
// Any well-formed id: the provider's catalogue decides what is served, and
// a preference saved under a richer provider must survive a switch (the
// server substitutes the nearest bar the new one has, and says so).
const INTERVAL_ID = /^\d+(s|m|h|d|wk|mo)$/

const DEFAULTS: ChartPrefs = {
  range: "1D", interval: "1m", intervalPinned: false, intervalByRange: {},
  type: "line", scale: "linear", indicators: [], paneHeights: {},
  timeZone: DEFAULT_TIME_ZONE, priceLine: true,
}

function pick<T>(v: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(v as T) ? (v as T) : fallback
}

const TYPES = new Set<string>(INDICATORS.map(d => d.type))

/** One instance, cleaned: known type, every param a number inside its
 * bounds (else the default), colour a token or hex, weight 1–4. */
export function normalizeIndicator(raw: unknown): Indicator | null {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Partial<Indicator>
  if (typeof r.type !== "string" || !TYPES.has(r.type)) return null
  const def = indicatorDef(r.type as IndicatorType)
  const params: Record<string, number> = {}
  const src = (r.params && typeof r.params === "object" ? r.params : {}) as Record<string, unknown>
  for (const d of def.params) {
    const v = src[d.key]
    params[d.key] = typeof v === "number" && Number.isFinite(v) ? quantizeParam(d, v) : d.def
  }
  const out: Indicator = {
    id: typeof r.id === "string" && r.id ? r.id : newIndicator(def.type).id,
    type: def.type, params: cleanParams(def, params),
  }
  if (typeof r.color === "string" && (/^var\(--[\w-]+\)$/.test(r.color) || /^#[0-9a-f]{3,8}$/i.test(r.color))) out.color = r.color
  if (typeof r.width === "number" && r.width >= 1 && r.width <= 4) out.width = r.width
  if (r.hidden === true) out.hidden = true
  return out
}

function migrateLegacy(ids: unknown): Indicator[] {
  if (!Array.isArray(ids)) return []
  const out: Indicator[] = []
  for (const id of ids) {
    const l = typeof id === "string" ? LEGACY[id] : undefined
    if (l) out.push(newIndicator(l.type, l.params, l.color))
  }
  return out
}

/** The same gate for a copy that arrives from the account rather than the
 * browser: whatever the store held, only known ids come through. */
export function normalizeChartPrefs(raw: unknown): ChartPrefs {
  try {
    const p = (raw && typeof raw === "object" ? raw : {}) as Partial<ChartPrefs> & {
      overlays?: unknown; panes?: unknown
    }
    const indicators = Array.isArray(p.indicators)
      ? p.indicators.map(normalizeIndicator).filter((x): x is Indicator => !!x)
      : [...migrateLegacy(p.overlays), ...migrateLegacy(p.panes)]
    const paneHeights: Record<string, number> = {}
    if (p.paneHeights && typeof p.paneHeights === "object") {
      for (const [k, v] of Object.entries(p.paneHeights as Record<string, unknown>)) {
        if (typeof v === "number" && v >= 40 && v <= 1200) paneHeights[k] = Math.round(v)
      }
    }
    return {
      range: pick(p.range, RANGES, DEFAULTS.range),
      interval: typeof p.interval === "string" && INTERVAL_ID.test(p.interval) ? p.interval : DEFAULTS.interval,
      intervalPinned: p.intervalPinned === true,
      intervalByRange: (() => {
        const out: Partial<Record<ChartRange, string>> = {}
        const src = (p.intervalByRange && typeof p.intervalByRange === "object" ? p.intervalByRange : {}) as Record<string, unknown>
        for (const [k, v] of Object.entries(src)) {
          if ((RANGES as readonly string[]).includes(k) && typeof v === "string" && INTERVAL_ID.test(v)) out[k as ChartRange] = v
        }
        // A record from before per-range pins: its one pin was the pin for
        // the range it was saved on.
        const r = pick(p.range, RANGES, DEFAULTS.range)
        if (p.intervalPinned === true && out[r] == null && typeof p.interval === "string" && INTERVAL_ID.test(p.interval)) out[r] = p.interval
        return out
      })(),
      type: pick(p.type, KINDS, DEFAULTS.type),
      scale: pick(p.scale, SCALES, DEFAULTS.scale),
      indicators,
      paneHeights,
      timeZone: validTimeZone(p.timeZone) ? p.timeZone : DEFAULT_TIME_ZONE,
      priceLine: p.priceLine !== false,
      updatedAt: typeof p.updatedAt === "number" && Number.isFinite(p.updatedAt) ? p.updatedAt : undefined,
    }
  } catch {
    return DEFAULTS
  }
}

export function loadChartPrefs(slot = 0): ChartPrefs {
  try {
    const raw = localStorage.getItem(localPrefsKey(slot))
    if (!raw) return DEFAULTS
    return normalizeChartPrefs(JSON.parse(raw))
  } catch {
    return DEFAULTS
  }
}

/** Merge a change in. Written per gesture, read at mount — the two charts
 * never render at once, so no live subscription is needed. */
export function saveChartPrefs(patch: Partial<ChartPrefs>, slot = 0) {
  try {
    localStorage.setItem(localPrefsKey(slot), JSON.stringify({ ...loadChartPrefs(slot), ...patch }))
  } catch { /* private mode */ }
}

/** Wipe this slot's saved reading setup — the browser's copy and, when
 * signed in, the account's — and reload, so a preference that crashes the
 * chart cannot come back on the next paint. */
export async function resetChartPrefs(slot = 0): Promise<void> {
  try { localStorage.removeItem(localPrefsKey(slot)) } catch { /* private mode */ }
  try { await fetch(`/api/chart/state/${serverPrefsKey(slot)}`, { method: "DELETE" }) } catch { /* anonymous, or offline */ }
  window.location.reload()
}
