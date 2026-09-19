import { useCallback, useSyncExternalStore } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api, type ServerView } from "@/lib/api"
import { useAuthMe } from "@/lib/queries"

/** My Views — reader-created boards.
 *
 * SIGNED IN, the server is the durable copy (per-user rows: name + the same
 * `id:span,id` layout string ?tiles= carries), so a view follows the account
 * across devices. The browser's layout store (lib/boardLayout) stays the
 * WORKING copy that drives the live board; the view page seeds it from the
 * server on open and saves changes back, debounced.
 *
 * On an OPEN instance (auth off) there is no user, so the list falls back
 * to this browser's storage — the original per-browser behavior, unchanged
 * for self-hosters.
 */

export type CustomView = { id: string; name: string; layout?: string }

const STARTER = "market-chart:8,equity-overview:4"
const KEY = "alphadesk.views"
/** The composition store's key shape for a view — must match lib/boardLayout. */
export const viewLayoutKey = (id: string) => `alphadesk.layout.view:${id}`

const newId = () => Math.random().toString(36).slice(2, 10)

/* ── the local fallback store (open instances) ────────────────────────── */

function readLocal(): CustomView[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as CustomView[]
    return Array.isArray(parsed)
      ? parsed.filter(v => v && typeof v.id === "string" && typeof v.name === "string")
      : []
  } catch {
    return []
  }
}

let localViews: CustomView[] = readLocal()
const listeners = new Set<() => void>()

function commitLocal(next: CustomView[]) {
  localViews = next
  try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* private mode */ }
  listeners.forEach(fn => fn())
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/* ── the one hook every consumer uses ─────────────────────────────────── */

export type MyViewsApi = {
  ready: boolean
  serverBacked: boolean
  views: CustomView[]
  create: (name?: string, layout?: string) => Promise<string>
  rename: (id: string, name: string) => void
  clone: (id: string) => Promise<string | null>
  remove: (id: string) => void
  /** The durable layout for one view (server mode) — the page seeds the
   * browser's working copy from this on open. Null in local mode: there the
   * working copy IS the record. */
  layoutOf: (id: string) => string | null
  /** Persist the current composition (server mode; a no-op locally, where
   * lib/boardLayout already stored it). */
  saveLayout: (id: string, layout: string) => void
}

const VIEWS_QK = ["user-views"] as const

export function useMyViews(): MyViewsApi {
  const { data: me, isPending: authPending } = useAuthMe()
  const serverBacked = !!me?.user
  const qc = useQueryClient()
  const local = useSyncExternalStore(subscribe, () => localViews, () => localViews)
  const server = useQuery({
    queryKey: VIEWS_QK,
    queryFn: api.views,
    enabled: serverBacked,
    staleTime: 30_000,
  })

  const rows: ServerView[] = server.data?.views ?? []
  const views: CustomView[] = serverBacked
    ? rows.map(v => ({ id: v.view_id, name: v.name, layout: v.layout }))
    : local

  const setRows = useCallback((fn: (rows: ServerView[]) => ServerView[]) => {
    qc.setQueryData(VIEWS_QK, (old: { views: ServerView[] } | undefined) =>
      ({ views: fn(old?.views ?? []) }))
  }, [qc])

  const create = useCallback(async (name = "New view", layout: string = STARTER) => {
    const id = newId()
    const clean = name.trim().slice(0, 60) || "New view"
    try { localStorage.setItem(viewLayoutKey(id), layout) } catch { /* private mode */ }
    if (serverBacked) {
      await api.setView(id, { name: clean, layout })
      setRows(r => [...r, { view_id: id, name: clean, layout, position: r.length }])
    } else {
      commitLocal([...localViews, { id, name: clean }])
    }
    return id
  }, [serverBacked, setRows])

  const rename = useCallback((id: string, name: string) => {
    const clean = name.trim().slice(0, 60)
    if (!clean) return
    if (serverBacked) {
      const row = rows.find(v => v.view_id === id)
      void api.setView(id, { name: clean, layout: row?.layout ?? "" })
      setRows(r => r.map(v => (v.view_id === id ? { ...v, name: clean } : v)))
    } else {
      commitLocal(localViews.map(v => (v.id === id ? { ...v, name: clean } : v)))
    }
  }, [serverBacked, rows, setRows])

  const clone = useCallback(async (id: string) => {
    const next = newId()
    if (serverBacked) {
      const row = rows.find(v => v.view_id === id)
      if (!row) return null
      try { localStorage.setItem(viewLayoutKey(next), row.layout) } catch { /* private mode */ }
      await api.setView(next, { name: `${row.name} copy`, layout: row.layout })
      setRows(r => [...r, { view_id: next, name: `${row.name} copy`, layout: row.layout, position: r.length }])
      return next
    }
    const src = localViews.find(v => v.id === id)
    if (!src) return null
    try {
      const layout = localStorage.getItem(viewLayoutKey(id))
      if (layout) localStorage.setItem(viewLayoutKey(next), layout)
    } catch { /* private mode */ }
    commitLocal([...localViews, { id: next, name: `${src.name} copy` }])
    return next
  }, [serverBacked, rows, setRows])

  const remove = useCallback((id: string) => {
    try { localStorage.removeItem(viewLayoutKey(id)) } catch { /* private mode */ }
    if (serverBacked) {
      void api.deleteView(id)
      setRows(r => r.filter(v => v.view_id !== id))
    } else {
      commitLocal(localViews.filter(v => v.id !== id))
    }
  }, [serverBacked, setRows])

  const layoutOf = useCallback((id: string) => {
    if (!serverBacked) return null
    return rows.find(v => v.view_id === id)?.layout ?? null
  }, [serverBacked, rows])

  const saveLayout = useCallback((id: string, layout: string) => {
    if (!serverBacked) return
    const row = rows.find(v => v.view_id === id)
    if (!row || row.layout === layout) return
    void api.setView(id, { name: row.name, layout })
    setRows(r => r.map(v => (v.view_id === id ? { ...v, layout } : v)))
  }, [serverBacked, rows, setRows])

  return {
    // NOT ready while the who-am-I request is still in flight: at that
    // moment serverBacked reads false and a view page that trusted it
    // seeded nothing — the board then mounted with no layout anywhere and
    // "absence = default" rendered EVERY widget (the reported bug).
    ready: !authPending && (serverBacked ? !server.isPending : true),
    serverBacked,
    views,
    create,
    rename,
    clone,
    remove,
    layoutOf,
    saveLayout,
  }
}
