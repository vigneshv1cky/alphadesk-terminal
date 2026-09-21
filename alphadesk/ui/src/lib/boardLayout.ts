import { useCallback, useEffect, useMemo, useRef } from "react"
import { useLocation, useSearchParams } from "react-router-dom"
import { widgets } from "@/widgets/registry"
import { parseLayout, resolveLayout, serializeLayout, type LayoutEntry, type TileAlign } from "@/lib/layoutEntries"

/** The Markets board's composition — which tiles render, in what order.
 *
 * Same shape as the symbol strip (lib/boardSymbols): the URL is the source
 * of truth, so a shared link restores exactly the board it names, and a
 * storage mirror covers the one case the URL cannot — chrome navigation that
 * carries no query. `?tiles=` holds the visible tile ids in render order;
 * ABSENCE means the default board, every registered tile in registry order.
 * That default is deliberately not written anywhere: a fresh deployment, a
 * new widget backend, or a plugin registering a tile all show up without
 * anyone editing a saved layout.
 *
 * The editor composes, ORDERS and WIDTHS tiles. Width is an OVERRIDE of the
 * rendered span — exactly the mechanism the registry's note reserved: the
 * component keeps owning its default, the reader's choice wins where set,
 * and nothing declares a width twice. Heights stay uniform on purpose; the
 * board reads as composed because its bottom edge is straight.
 *
 * The board is never empty: the last visible tile cannot be hidden, the
 * same deal the symbol strip's lone chip makes. A panel the page gained
 * after a layout was saved shows in it (lib/layoutEntries), except on a
 * reader-built view. Unknown ids in the param —
 * a link from a deployment with a widget this one lacks — are ignored
 * rather than erroring, and if nothing in the param is known the default
 * board renders.
 */
/** The Markets board keeps its original key; every other page gets its own.
 * Layouts are PER PAGE — a page's ?tiles= names that page's panels. */
function storageKey(pageKey: string): string {
  return pageKey === "markets" ? "alphadesk.layout" : `alphadesk.layout.${pageKey}`
}

function readStored(pageKey: string): string | null {
  try {
    const raw = localStorage.getItem(storageKey(pageKey))
    if (!raw) return null
    // Legacy form: a JSON array of ids, from before widths existed.
    if (raw.startsWith("[")) {
      const parsed = JSON.parse(raw) as string[]
      return Array.isArray(parsed) ? parsed.filter(v => typeof v === "string").join(",") : null
    }
    return raw
  } catch {
    return null
  }
}

function writeStored(pageKey: string, serialized: string | null) {
  try {
    if (serialized === null) localStorage.removeItem(storageKey(pageKey))
    else localStorage.setItem(storageKey(pageKey), serialized)
  } catch { /* private mode */ }
}

/** THE BOARD FOLLOWS THE ACCOUNT, NOT THE BROWSER (2026-09-21).
 *
 * Arranging a board on a desktop and finding the default one on a phone is
 * the whole of the complaint this answers. The browser's copy still LEADS —
 * a reader mid-arrangement is never overruled by a row written from another
 * device — and the account's copy is the fallback for a browser that has
 * never seen this page. Same deal user_views has had since 2 September.
 *
 * Read ONCE per session rather than per page: a reader moving between tabs
 * would otherwise ask again on every navigation, for an answer that cannot
 * have changed. A refusal (signed out, offline) is an empty set, so an open
 * instance behaves exactly as it did.
 */
let accountLayouts: Promise<Record<string, string>> | null = null

function fetchAccountLayouts(): Promise<Record<string, string>> {
  if (!accountLayouts) {
    accountLayouts = import("@/lib/api")
      .then(({ api }) => api.getLayouts())
      .then(r => r.layouts ?? {})
      .catch(() => ({}))
  }
  return accountLayouts
}

/** Written back a moment after a board settles. Debounced per page and
 * skipped when unchanged: a width drag commits on every step, and each one
 * would otherwise be a request. */
const mirrorTimers = new Map<string, ReturnType<typeof setTimeout>>()
const mirrored = new Map<string, string>()

function mirrorLayout(pageKey: string, tiles: string) {
  if (mirrored.get(pageKey) === tiles) return
  const pending = mirrorTimers.get(pageKey)
  if (pending) clearTimeout(pending)
  mirrorTimers.set(pageKey, setTimeout(() => {
    mirrorTimers.delete(pageKey)
    void import("@/lib/api")
      .then(({ api }) => api.saveLayout(pageKey, tiles))
      .then(() => {
        mirrored.set(pageKey, tiles)
        // The session's cached answer is now stale in one entry; keep it
        // true rather than throwing the whole thing away.
        if (accountLayouts) accountLayouts = accountLayouts.then(all => ({ ...all, [pageKey]: tiles }))
      })
      .catch(() => { /* signed out or offline: retried on the next change */ })
  }, 1200))
}

/** One layout entry: a tile, and optionally the WIDTH the reader gave it.
 * `span: null` means "the component's own default" — the registry's note
 * holds: the editor overrides the rendered span, components keep owning
 * their defaults, and a tile never declares its width twice. The string
 * form, and how hidden and newly added panels are told apart, live in
 * lib/layoutEntries. */
export type { LayoutEntry }

/** The minimum a composable panel declares. The Markets board's WidgetDef
 * satisfies it; other pages pass {id, label, node} literals. */
export type PanelDef = {
  id: string
  label: string
  /** Library-only: offered in the widget library but NOT part of a page's
   * DEFAULT board — without this, every newly registered tile would flood
   * every board that never saved a layout. */
  optIn?: boolean
}

/** What a page's layout hook hands back — the editor renders against this
 * shape, whichever page it is composing. */
export type LayoutApi<T extends PanelDef> = {
  all: T[]
  items: { def: T; span: number | null; align: TileAlign | null }[]
  isCustom: boolean
  move: (id: string, dir: -1 | 1) => void
  setSpan: (id: string, span: number | null) => void
  /** Place a tile narrower than its row: left (null), centre or right. */
  setAlign: (id: string, align: TileAlign | null) => void
  /** Set the board's MEMBERSHIP in one move (the widget-library dialog):
   * kept tiles keep their order and width, newly picked ones append at
   * their default span. An empty pick is ignored — the board is never
   * empty. */
  applyIds: (ids: string[]) => void
  reset: () => void
}

/** The Markets board's layout — the registry is its panel list. */
export function useBoardLayout() {
  return usePageLayout("markets", widgets())
}

/** Any page's composition, keyed by page. Same contract everywhere: ?tiles=
 * on that page's own URL, a per-page storage mirror, absence = the page's
 * default, the last panel un-hidable. */
export function usePageLayout<T extends PanelDef>(
  pageKey: string, all: T[],
  /** False on a reader-built view: its tiles are a hand-picked set, so a
   * newly registered tile does not join it. */
  { addNew = true }: { addNew?: boolean } = {},
): LayoutApi<T> {
  const [params, setParams] = useSearchParams()
  const raw = params.get("tiles") || ""

  // The route pages are LAZY, so during a navigation the OLD page stays
  // mounted while the new chunk loads — and its restore effect would see the
  // NEW location's bare URL and write the old page's stored layout onto it
  // (a custom view's starter board once overwrote the Markets layout this
  // way). A page's layout hook may touch the URL only while the path it
  // mounted on is still the current one.
  const { pathname } = useLocation()
  const home = useRef(pathname)
  const athome = pathname === home.current

  /** The custom layout the URL names, filtered to tiles that exist here,
   * with any panel added since it was saved. Empty array = no custom layout
   * (default board). */
  const custom = useMemo(() => resolveLayout(raw, all, addNew), [raw, all, addNew])
  const keepHidden = useMemo(() => parseLayout(raw, all).hidden, [raw, all])
  const serial = useCallback(
    (entries: LayoutEntry[]) => serializeLayout(entries, all, addNew, keepHidden),
    [all, addNew, keepHidden],
  )

  const isCustom = custom.length > 0

  /** What the page renders, in order: the tile and the reader's width for
   * it (null = the component's own). */
  const items: { def: T; span: number | null; align: TileAlign | null }[] = useMemo(
    () => (isCustom
      ? custom.map(e => ({ def: all.find(w => w.id === e.id)!, span: e.span, align: e.align ?? null }))
      : all.filter(w => !w.optIn).map(w => ({ def: w, span: null, align: null }))),
    [isCustom, custom, all],
  )

  const commit = useCallback((entries: LayoutEntry[] | null) => {
    const p = new URLSearchParams(params)
    if (entries && entries.length) p.set("tiles", serial(entries))
    else p.delete("tiles")
    const tiles = entries && entries.length ? serial(entries) : ""
    writeStored(pageKey, tiles || null)
    mirrorLayout(pageKey, tiles)
    setParams(p, { replace: true })
  }, [params, setParams, pageKey, serial])

  /** Mirror and restore, like the strip: a URL that names a layout is written
   * to storage; a bare navigation gets the stored one back. No seeding —
   * absence IS the default board. */
  useEffect(() => {
    if (!athome) return
    if (raw) {
      writeStored(pageKey, custom.length ? serial(custom) : null)
      return
    }
    const stored = readStored(pageKey)
    if (!stored?.length) {
      // Nothing in this browser — but the ACCOUNT may hold this board from
      // another one. Checked at the moment the answer lands, not when it was
      // asked for: a reader who arranged something meanwhile, or navigated
      // away, must not have it overwritten by a reply to an older question.
      let dropped = false
      void fetchAccountLayouts().then(all => {
        const seed = all[pageKey]
        if (dropped || !seed || window.location.pathname !== home.current) return
        setParams(prev => {
          const p = new URLSearchParams(prev)
          if (p.get("tiles")) return prev
          p.set("tiles", seed)
          return p
        }, { replace: true })
        writeStored(pageKey, seed)
      })
      return () => { dropped = true }
    }
    // FUNCTIONAL update, not a snapshot: the strip's seed effect writes the
    // URL on the same mount, and two writers each building from their own
    // stale copy lose whichever landed first — this restore once erased the
    // strip's just-seeded ?symbols=. Building from `prev` composes instead.
    setParams(prev => {
      const p = new URLSearchParams(prev)
      p.set("tiles", stored)
      return p
    }, { replace: true })
    // Keyed on params so a restore swallowed by the strip's same-tick write
    // is retried against the now-current URL — see boardSymbols for the
    // full story. Terminates: with the key present, only the mirror runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  const entries: LayoutEntry[] = isCustom
    ? custom
    : all.filter(w => !w.optIn).map(w => ({ id: w.id, span: null }))

  const move = useCallback((id: string, dir: -1 | 1) => {
    const i = entries.findIndex(e => e.id === id)
    const j = i + dir
    if (i < 0 || j < 0 || j >= entries.length) return
    const next = [...entries]
    next[i] = next[j]
    next[j] = entries[i]
    commit(next)
  }, [entries, commit])

  /** Give a tile a width (3–12 grid columns), or null to hand it back to
   * the component's own default. */
  const setSpan = useCallback((id: string, span: number | null) => {
    commit(entries.map(e => e.id === id
      ? { ...e, span: span ? Math.max(3, Math.min(12, span)) : null }
      : e))
  }, [entries, commit])

  const setAlign = useCallback((id: string, align: TileAlign | null) => {
    commit(entries.map(e => (e.id === id ? { ...e, align } : e)))
  }, [entries, commit])

  const applyIds = useCallback((ids: string[]) => {
    const keep = entries.filter(e => ids.includes(e.id))
    const added = ids.filter(id => !entries.some(e => e.id === id))
      .map(id => ({ id, span: null }))
    const next = [...keep, ...added]
    if (next.length) commit(next)
  }, [entries, commit])

  const reset = useCallback(() => commit(null), [commit])

  return { all, items, isCustom, move, setSpan, setAlign, applyIds, reset }
}
