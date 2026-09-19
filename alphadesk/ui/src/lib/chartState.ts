import { useEffect, useRef, useState } from "react"
import { useAuthMe } from "@/lib/queries"

/** Chart state that follows the account (2026-09-05).
 *
 * Two keys, the split TradingView makes: 'prefs' is HOW you read a chart
 * (interval, type, scale, indicators) and follows you across symbols;
 * 'drawings:SYM' is what you drew ON one chart and stays with that symbol.
 * Signed in, both live on the server; anonymous, the browser keeps them
 * under the same keys, so an open instance still remembers.
 *
 * Reads happen on key change; writes are debounced per gesture. The echo of
 * a load is never written back — a `hydrated` flag gates the first save.
 */

const LOCAL_PREFIX = "alphadesk.chart."

function readLocal<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(LOCAL_PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch { return null }
}

function writeLocal<T>(key: string, value: T) {
  try { localStorage.setItem(LOCAL_PREFIX + key, JSON.stringify(value)) } catch { /* private mode */ }
}

/** One persisted value. `initial` seeds the first paint (and is what an
 * empty store means); `validate` sanitizes whatever comes back so a stale
 * entry from an older build degrades to the default, never into a crash. */
export function useChartState<T>(
  key: string | null,
  initial: T,
  validate: (raw: unknown) => T,
): [T, (next: T | ((prev: T) => T)) => void, boolean] {
  const { data: me } = useAuthMe()
  const serverMode = !!me?.user
  const [value, setValue] = useState<T>(initial)
  const [hydrated, setHydrated] = useState(false)
  const timer = useRef<number | null>(null)
  const keyRef = useRef(key)
  /** Whether the account's copy was READ for this key. A read that failed
   * (a 5xx, a blip) used to come back as "empty", and the next edit then
   * replaced the account's whole set with one item. Until the read lands,
   * edits stay in the browser. */
  const serverRead = useRef(false)
  const pending = useRef<{ key: string; value: T } | null>(null)

  // Load on key change (or when sign-in resolves).
  useEffect(() => {
    keyRef.current = key
    setHydrated(false)
    if (!key) { setValue(initial); setHydrated(true); return }
    let alive = true
    const apply = (raw: unknown) => {
      if (!alive || keyRef.current !== key) return
      setValue(raw == null ? initial : validate(raw))
      setHydrated(true)
    }
    serverRead.current = false
    if (serverMode) {
      fetch(`/api/chart/state/${encodeURIComponent(key)}`)
        // 404 and 422 are answers (nothing saved; a key this server does
        // not keep); anything else is a failure to be retried once.
        .then(r => (r.ok ? r.json() : r.status === 404 || r.status === 422 ? { state: null } : Promise.reject(new Error(String(r.status)))))
        .then(d => { serverRead.current = true; apply(d.state ?? readLocal(key)) })
        .catch(() => new Promise(res => setTimeout(res, 3000))
          .then(() => fetch(`/api/chart/state/${encodeURIComponent(key)}`))
          .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
          .then(d => { serverRead.current = true; apply(d.state ?? readLocal(key)) })
          .catch(() => apply(readLocal(key))))
    } else {
      apply(readLocal(key))
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, serverMode])

  // Leaving the page flushes the write the debounce is holding.
  useEffect(() => {
    const flush = () => {
      const p = pending.current
      pending.current = null
      if (timer.current) { window.clearTimeout(timer.current); timer.current = null }
      if (!p || !serverMode || !serverRead.current) return
      void fetch(`/api/chart/state/${encodeURIComponent(p.key)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: p.value }), keepalive: true,
      }).catch(() => { /* the browser copy stands */ })
    }
    window.addEventListener("pagehide", flush)
    return () => { window.removeEventListener("pagehide", flush); flush() }
  }, [serverMode])

  const update = (next: T | ((prev: T) => T)) => {
    setValue(prev => {
      const resolved = typeof next === "function" ? (next as (p: T) => T)(prev) : next
      if (!hydrated || !key) return resolved
      writeLocal(key, resolved)
      if (serverMode && serverRead.current) {
        pending.current = { key, value: resolved }
        if (timer.current) window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => {
          pending.current = null
          void fetch(`/api/chart/state/${encodeURIComponent(key)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ state: resolved }),
          }).catch(() => { /* the browser copy stands */ })
        }, 600)
      }
      return resolved
    })
  }

  return [value, update, hydrated]
}
