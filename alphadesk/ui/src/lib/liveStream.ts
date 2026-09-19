/** The tab's ONE live connection (2026-09-15).
 *
 * Every live surface — a chart's trades, the panels' row prices, the crypto
 * tape — used to open its own EventSource: one per charted symbol, one per
 * quotes panel, one for crypto. Over HTTP/1.1 (a local server) a browser
 * keeps six connections to an origin, the Markets board held five or six
 * streams, and a chart request could wait indefinitely for a free one. Now
 * the hooks register what they watch here and the tab holds one connection
 * to /api/stream carrying three channels.
 *
 * WHEN THE SET CHANGES the connection is reopened with the new lists: on
 * Cloud Run a side request to change subscriptions can reach another
 * instance than the stream, so the lists ride in the URL. Changes within
 * 60ms are batched; the new connection opens BEFORE the old one closes, and
 * the old one is closed when the new one says hello, so ticks do not gap.
 * The server holds a released subscription for a few seconds, so the reopen
 * finds it and its last price still there. The last value per symbol is
 * also kept here, so a surface that mounts later starts with a price.
 *
 * No onerror handling on purpose: EventSource reconnects by itself, and
 * treating a dropped connection as an error would flash a warning every time
 * a laptop lid closes.
 */

export type TradeTick = {
  symbol: string; price: number; size: number; at: string; age_s: number; stale: boolean
}
export type PriceTick = { symbol: string; price: number; at: string; age_s?: number; stale: boolean }

/** The server's TICK_STALE_AFTER_S: a print older than this is information
 * about the past, not the live edge. */
export const STALE_AFTER_S = 30

type Kept<T> = { tick: T; received: number }

/** A kept tick as it stands NOW: its age carried forward from when it
 * arrived, so a price remembered from minutes ago is handed to a late
 * watcher as the stale price it is. */
export function aged<T extends { age_s?: number; stale: boolean }>(k: Kept<T>, now: number): T {
  const age = (k.tick.age_s ?? 0) + (now - k.received) / 1000
  return { ...k.tick, age_s: age, stale: k.tick.stale || age > STALE_AFTER_S }
}

export type Watch = {
  trades?: string[]
  quotes?: string[]
  crypto?: string[]
  /** The reader's real-time news: told when a story has been stored. */
  news?: boolean
  onNews?: (seq: number) => void
  /** One print for a charted symbol. */
  onTrade?: (t: TradeTick) => void
  /** Whether the server could subscribe each charted symbol. */
  onTradeLive?: (symbol: string, live: boolean) => void
  /** Row prices that moved, for any watched row symbol. */
  onQuotes?: (ticks: PriceTick[]) => void
  onCrypto?: (ticks: PriceTick[]) => void
}

const watches = new Set<Watch>()
const lastTrade = new Map<string, Kept<TradeTick>>()
const tradeLive = new Map<string, boolean>()
const lastQuote = new Map<string, Kept<PriceTick>>()
const lastCoin = new Map<string, Kept<PriceTick>>()

let current: { url: string; es: EventSource } | null = null
let pending: { url: string; es: EventSource } | null = null
let timer: number | null = null

/** The connection URL for everything watched, or null for nothing. Sorted,
 * so the same set in a different mount order is the same connection. */
export function liveUrl(all: Iterable<Pick<Watch, "trades" | "quotes" | "crypto" | "news">>): string | null {
  const t = new Set<string>(), q = new Set<string>(), c = new Set<string>()
  let news = false
  for (const w of all) {
    w.trades?.forEach(s => s && t.add(s.toUpperCase()))
    w.quotes?.forEach(s => s && q.add(s.toUpperCase()))
    w.crypto?.forEach(s => s && c.add(s.toUpperCase()))
    news = news || !!w.news
  }
  if (!t.size && !q.size && !c.size && !news) return null
  const p = new URLSearchParams()
  if (t.size) p.set("trades", [...t].sort().join(","))
  if (q.size) p.set("quotes", [...q].sort().join(","))
  if (c.size) p.set("crypto", [...c].sort().join(","))
  if (news) p.set("news", "1")
  return `/api/stream?${p.toString()}`
}

function frame<T>(e: Event, fn: (data: T) => void) {
  try { fn(JSON.parse((e as MessageEvent).data) as T) } catch { /* a malformed frame is not fatal */ }
}

function open(url: string) {
  const es = new EventSource(url)
  const conn = { url, es }
  es.addEventListener("hello", e => frame<{ trades?: Record<string, boolean> }>(e, hello => {
    // This connection now carries everything: the one it replaces can go.
    if (pending === conn) {
      current?.es.close()
      current = conn
      pending = null
    }
    for (const [sym, live] of Object.entries(hello.trades ?? {})) {
      tradeLive.set(sym, live)
      watches.forEach(w => w.trades?.includes(sym) && w.onTradeLive?.(sym, live))
    }
  }))
  es.addEventListener("trade", e => frame<TradeTick>(e, t => {
    if (conn !== current || typeof t?.price !== "number") return
    lastTrade.set(t.symbol, { tick: t, received: Date.now() })
    watches.forEach(w => w.trades?.includes(t.symbol) && w.onTrade?.(t))
  }))
  es.addEventListener("quotes", e => frame<{ ticks?: PriceTick[] }>(e, d => {
    if (conn !== current || !d.ticks?.length) return
    d.ticks.forEach(t => lastQuote.set(t.symbol, { tick: t, received: Date.now() }))
    watches.forEach(w => w.onQuotes?.(d.ticks!))
  }))
  es.addEventListener("news", e => frame<{ seq?: number }>(e, d => {
    if (conn !== current) return
    watches.forEach(w => w.news && w.onNews?.(d.seq ?? 0))
  }))
  es.addEventListener("crypto", e => frame<{ ticks?: PriceTick[] }>(e, d => {
    if (conn !== current || !d.ticks?.length) return
    d.ticks.forEach(t => lastCoin.set(t.symbol, { tick: t, received: Date.now() }))
    watches.forEach(w => w.onCrypto?.(d.ticks!))
  }))
  return conn
}

function sync() {
  timer = null
  const url = liveUrl(watches)
  if (!url) {
    pending?.es.close(); pending = null
    current?.es.close(); current = null
    return
  }
  if (url === (pending ?? current)?.url) return
  pending?.es.close()
  pending = open(url)
  // The first connection has nothing to wait for.
  if (!current) { current = pending; pending = null }
}

function schedule() {
  if (timer == null) timer = window.setTimeout(sync, 60)
}

/** Watch symbols on the tab's connection; returns the unwatch. A late
 * watcher gets the last values already seen for its symbols at once. */
export function watch(w: Watch): () => void {
  watches.add(w)
  schedule()
  const now = Date.now()
  for (const sym of w.trades ?? []) {
    const t = lastTrade.get(sym)
    if (t) w.onTrade?.(aged(t, now))
    if (tradeLive.has(sym)) w.onTradeLive?.(sym, tradeLive.get(sym)!)
  }
  const kept = (m: Map<string, Kept<PriceTick>>, syms: string[] = []) =>
    syms.map(s => m.get(s)).filter((k): k is Kept<PriceTick> => !!k).map(k => aged(k, now))
  const q = kept(lastQuote, w.quotes)
  if (q.length) w.onQuotes?.(q)
  const c = kept(lastCoin, w.crypto)
  if (c.length) w.onCrypto?.(c)
  return () => {
    watches.delete(w)
    schedule()
  }
}
