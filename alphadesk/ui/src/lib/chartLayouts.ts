import { normalizeChartPrefs, normalizeIndicator, type ChartPrefs } from "@/lib/chartPrefs"
import type { Indicator } from "@/lib/indicators"

/** Layouts and templates for the chart workspace (2026-09-05).
 *
 * A LAYOUT is the grid and what is in each cell: which symbol, and that
 * cell's whole prefs record (interval, type, indicators…). The
 * live layout is one record; saved layouts are named snapshots of it that
 * can be put back. A TEMPLATE is just an indicator list with a name — the
 * setup you keep applying to whatever you open. All three live in the same
 * chart-state store as drawings and prefs, so they follow the account.
 *
 * Four cells at most. Slot 0 is THE chart (shared with the Markets tile);
 * slots 1–3 exist only in the workspace.
 */

export type GridId = "1" | "2h" | "2v" | "3" | "4"

export const GRIDS: { id: GridId; label: string; cells: number }[] = [
  { id: "1", label: "Single", cells: 1 },
  { id: "2h", label: "Two, side by side", cells: 2 },
  { id: "2v", label: "Two, stacked", cells: 2 },
  { id: "3", label: "One tall, two stacked", cells: 3 },
  { id: "4", label: "Four", cells: 4 },
]
export const cellCount = (g: GridId) => GRIDS.find(x => x.id === g)?.cells ?? 1

/** The live layout: the grid, and the symbols of cells 1–3 (cell 0 is the
 * board's symbol). Null means "same as cell 0". */
export type Layout = {
  grid: GridId
  symbols: (string | null)[]
  /** The saved layout this one was opened from, so its name stays on the
   * button across a reload; cleared by any change to the grid. */
  openId?: string | null
}
export const DEFAULT_LAYOUT: Layout = { grid: "1", symbols: [null, null, null], openId: null }

const SYM = /^[A-Z0-9.\-]{1,12}$/
const cleanSymbol = (v: unknown): string | null =>
  typeof v === "string" && SYM.test(v.toUpperCase()) ? v.toUpperCase() : null

export function validateLayout(raw: unknown): Layout {
  if (!raw || typeof raw !== "object") return DEFAULT_LAYOUT
  const r = raw as Partial<Layout>
  const grid = GRIDS.some(g => g.id === r.grid) ? (r.grid as GridId) : "1"
  const symbols = [0, 1, 2].map(i => cleanSymbol(Array.isArray(r.symbols) ? r.symbols[i] : null))
  return { grid, symbols, openId: typeof r.openId === "string" ? r.openId : null }
}

export type SavedLayout = {
  id: string
  name: string
  grid: GridId
  /** All four cells' symbols, cell 0 included. */
  symbols: string[]
  prefs: ChartPrefs[]
  savedAt: string
}

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

export function validateLayouts(raw: unknown): SavedLayout[] {
  if (!Array.isArray(raw)) return []
  const out: SavedLayout[] = []
  for (const x of raw.slice(0, 20)) {
    if (!x || typeof x !== "object") continue
    const r = x as Partial<SavedLayout>
    if (typeof r.name !== "string" || !r.name.trim()) continue
    const grid = GRIDS.some(g => g.id === r.grid) ? (r.grid as GridId) : "1"
    const symbols = [0, 1, 2, 3].map(i => cleanSymbol(Array.isArray(r.symbols) ? r.symbols[i] : null) ?? "")
    const prefs = [0, 1, 2, 3].map(i => normalizeChartPrefs(Array.isArray(r.prefs) ? r.prefs[i] : null))
    out.push({
      id: typeof r.id === "string" && r.id ? r.id : newId(),
      name: r.name.trim().slice(0, 60),
      grid, symbols, prefs,
      savedAt: typeof r.savedAt === "string" ? r.savedAt : new Date().toISOString(),
    })
  }
  return out
}

export function makeSavedLayout(name: string, grid: GridId, symbols: string[], prefs: ChartPrefs[]): SavedLayout {
  return { id: newId(), name: name.trim().slice(0, 60), grid, symbols, prefs, savedAt: new Date().toISOString() }
}

export type Template = { id: string; name: string; indicators: Indicator[] }

export function validateTemplates(raw: unknown): Template[] {
  if (!Array.isArray(raw)) return []
  const out: Template[] = []
  for (const x of raw.slice(0, 30)) {
    if (!x || typeof x !== "object") continue
    const r = x as Partial<Template>
    if (typeof r.name !== "string" || !r.name.trim()) continue
    const indicators = Array.isArray(r.indicators)
      ? r.indicators.map(normalizeIndicator).filter((i): i is Indicator => !!i)
      : []
    out.push({ id: typeof r.id === "string" && r.id ? r.id : newId(), name: r.name.trim().slice(0, 60), indicators })
  }
  return out
}

export function makeTemplate(name: string, indicators: Indicator[]): Template {
  return { id: newId(), name: name.trim().slice(0, 60), indicators }
}
