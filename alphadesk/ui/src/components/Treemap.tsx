import { useLayoutEffect, useMemo, useRef, useState } from "react"

/** The market treemap and its measure catalog — extracted from the theme
 * page so the board can register a heatmap tile over the strip's symbols.
 * Area encodes the chosen measure (squarified), color saturates with the
 * day's move; see the Treemap docstring below for the floor that keeps the
 * smallest name readable.
 */

export const compact = (n: number | null | undefined): string => {
  if (n == null) return "—"
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

export /** The measures the heatmap offers. "Today's move" is first and the
 * default (2026-09-19, the owner's pick: size by today's gain, "biggest
 * movers biggest"): the tile's area is the size of the move either way, its
 * colour the direction. */
const HEAT = [
  { id: "move", label: "Today's move", fmt: (n: number | null | undefined) => n == null ? "—" : `${n.toFixed(2)}%` },
  { id: "market_cap", label: "Market cap", fmt: compact },
  { id: "volume", label: "Volume", fmt: compact },
  { id: "avg_volume", label: "Avg vol", fmt: compact },
  { id: "pe_trailing", label: "P/E", fmt: (n: number | null | undefined) => n == null ? "—" : n.toFixed(1) },
] as const

export type Heat = (typeof HEAT)[number]["id"]

/** What to ask /api/quotes to fill for a measure: the quote vendor carries
 * only the day's volume, so the other three are filled on request — only
 * the one on screen, since P/E costs a key-statistics call per company
 * (2026-09-19). */
export const HEAT_FILL: Record<Heat, string | undefined> = {
  move: undefined, market_cap: "cap", volume: undefined, avg_volume: "avgvol", pe_trailing: "pe",
}

/** Said when no symbol on the map has the measure, rather than drawing
 * equal tiles that read as equal values. */
export const HEAT_NONE: Record<Heat, string> = {
  move: "No move for these symbols yet today.",
  market_cap: "No market cap for these symbols — a coin needs a CoinGecko key, and a fund has none.",
  volume: "No volume for these symbols yet today.",
  avg_volume: "No average volume for these symbols — no daily bars from your data keys.",
  pe_trailing: "No P/E for these symbols — coins and funds have no earnings.",
}

/** A symbol's value for a measure: a quote field, or for "move" the size
 * of today's change either way. */
export function heatValue(q: Record<string, unknown> | null | undefined, metric: string): number | null {
  const v = metric === "move" ? q?.change_pct : q?.[metric]
  if (typeof v !== "number") return null
  return metric === "move" ? Math.abs(v) : v
}

/** True when at least one symbol carries the measure. */
export function heatHasData(symbols: string[], priced: Record<string, unknown> | undefined, metric: Heat): boolean {
  return symbols.some(s => {
    const v = heatValue(priced?.[s] as Record<string, unknown> | null | undefined, metric)
    return v != null && v > 0
  })
}


/** A real heatmap this time (feedback, 2026-09-02 — "heatmaps are not
 * heatmaps"): a squarified TREEMAP where each tile's AREA is the chosen
 * measure and its COLOR saturates with today's move. The old equal-tile grid
 * feared one giant name drowning the rest; the floor below answers that —
 * no tile may fall under 2.5% of the canvas, so the smallest name stays
 * readable and clickable while the area story stays honest above it. */

type TmRect = { x: number; y: number; w: number; h: number }

function squarify(items: { key: string; value: number }[], W: number, H: number): Record<string, TmRect> {
  const total = items.reduce((s, i) => s + i.value, 0)
  if (!total || W <= 0 || H <= 0) return {}
  const scaled = [...items]
    .map(i => ({ key: i.key, area: (i.value / total) * W * H }))
    .sort((a, b) => b.area - a.area)
  const rects: Record<string, TmRect> = {}
  let x = 0, y = 0, w = W, h = H
  let row: typeof scaled = []

  const worst = (r: typeof scaled, length: number) => {
    const s = r.reduce((t, c) => t + c.area, 0)
    return Math.max(
      (length * length * r[0].area) / (s * s),
      (s * s) / (length * length * r[r.length - 1].area),
    )
  }
  const layoutRow = (r: typeof scaled) => {
    const s = r.reduce((t, c) => t + c.area, 0)
    if (w >= h) {
      const rw = s / h
      let ry = y
      for (const c of r) { const rh = c.area / rw; rects[c.key] = { x, y: ry, w: rw, h: rh }; ry += rh }
      x += rw; w -= rw
    } else {
      const rh = s / w
      let rx = x
      for (const c of r) { const cw = c.area / rh; rects[c.key] = { x: rx, y, w: cw, h: rh }; rx += cw }
      y += rh; h -= rh
    }
  }
  for (const item of scaled) {
    const length = Math.min(w, h)
    if (row.length && worst([...row, item], length) > worst(row, length)) {
      layoutRow(row)
      row = [item]
    } else {
      row.push(item)
    }
  }
  if (row.length) layoutRow(row)
  return rects
}

/** Anything with today's move: a quote, or a sector fund's row. */
type Priced = { change_pct?: number | null }

export function Treemap({ symbols, priced, metric, picked, onPick, fmt, labels }: {
  symbols: string[]
  priced: Record<string, Priced | null> | undefined
  /** A HEAT measure, or any numeric field of `priced` when `fmt` is given. */
  metric: Heat | string
  picked: string
  onPick: (s: string) => void
  /** How the size measure reads on a tile; defaults to the HEAT entry's. */
  fmt?: (n: number | null | undefined) => string
  /** A name per symbol, shown under it where the tile has room (sectors). */
  labels?: Record<string, string>
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const HEIGHT = 340
  const format = fmt ?? HEAT.find(h => h.id === metric)?.fmt ?? compact
  const rects = useMemo(() => {
    const raw = symbols.map(s => {
      const v = heatValue(priced?.[s] as Record<string, unknown> | null | undefined, metric)
      return { key: s, value: v != null && v > 0 ? v : 0 }
    })
    const max = Math.max(...raw.map(r => r.value), 0)
    // Every name renders: a missing or dwarfed value gets the floor, so the
    // area encoding is honest above it and nothing becomes unclickable.
    const total = raw.reduce((s, r) => s + (r.value || 0), 0) || 1
    const floor = total * 0.025
    const items = raw.map(r => ({ key: r.key, value: max ? Math.max(r.value, floor) : 1 }))
    return squarify(items, width, HEIGHT)
  }, [symbols, priced, metric, width])

  return (
    <div ref={ref} className="relative" style={{ height: HEIGHT }}>
      {symbols.map(s => {
        const r = rects[s]
        if (!r) return null
        const q = priced?.[s] as Record<string, unknown> | null | undefined
        const chg = (q?.change_pct as number | null | undefined) ?? null
        const size = heatValue(q, metric)
        const up = (chg ?? 0) >= 0
        // Saturation ramps with the move: flat days read muted, a ±3% day
        // reads loud, anything past that clamps so one crash can't wash out
        // the rest of the scale.
        const mix = chg == null ? 6 : 10 + Math.min(Math.abs(chg) / 3, 1) * 55
        const roomy = r.w >= 76 && r.h >= 56
        const cramped = r.w < 46 || r.h < 30
        return (
          <button
            key={s}
            onClick={() => onPick(s)}
            title={`${s}${labels?.[s] ? ` · ${labels[s]}` : ""} · ${chg == null ? "—" : `${up ? "+" : ""}${chg.toFixed(2)}%`}${metric === "move" ? "" : ` · ${format(size)}`}`}
            className={`absolute flex flex-col items-start justify-center overflow-hidden rounded-xs px-1.5 text-left transition-colors ${
              s === picked ? "ring-2 ring-accent" : "hover:ring-1 hover:ring-foreground/40"}`}
            style={{
              left: r.x + 1, top: r.y + 1, width: Math.max(r.w - 2, 0), height: Math.max(r.h - 2, 0),
              backgroundColor: `color-mix(in srgb, var(--${up ? "gain" : "loss"}) ${mix}%, var(--surface))`,
            }}
          >
            {!cramped && <span className="num max-w-full truncate text-body font-extrabold">{s}</span>}
            {!cramped && (
              <span className="tnum max-w-full truncate text-caption">
                {chg == null ? "—" : `${up ? "+" : ""}${chg.toFixed(2)}%`}
              </span>
            )}
            {roomy && labels?.[s] && (
              <span className="max-w-full truncate text-label text-muted-foreground">{labels[s]}</span>
            )}
            {/* The move is already the line above; it is not said twice. */}
            {roomy && metric !== "move" && (
              <span className="tnum max-w-full truncate text-label text-muted-foreground">
                {format(size)}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

