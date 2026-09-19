/** The Sectors page's figures moved by live prices (2026-09-15).
 *
 * The server sends each fund's returns and the closes they run from
 * (`bases`); a live price moves every return, the relative returns against
 * SPY's live price, and the rotation standing with them. A tick that is
 * stale, or a row without a base, keeps the server's figure. Pure, so it is
 * tested without a page. */

export type Bases = { d1?: number | null; w1?: number | null; m1?: number | null; m3?: number | null; ytd?: number | null; y1?: number | null }

export type LiveRow = {
  symbol: string
  price: number | null
  change_pct: number | null
  w1: number | null; m1: number | null; m3: number | null; ytd: number | null; y1: number | null
  rel_m1?: number | null; rel_m3?: number | null
  rotation?: "leading" | "weakening" | "lagging" | "improving" | null
  bases?: Bases
}

export type Tick = { price: number; stale: boolean }

const ret = (price: number, base: number | null | undefined, fallback: number | null) =>
  base ? Math.round((price / base - 1) * 10000) / 100 : fallback

export function rotation(relM1: number | null | undefined, relM3: number | null | undefined): LiveRow["rotation"] {
  if (relM1 == null || relM3 == null) return null
  if (relM3 >= 0) return relM1 >= 0 ? "leading" : "weakening"
  return relM1 >= 0 ? "improving" : "lagging"
}

/** One row at its live price. */
export function liveRow<R extends LiveRow>(row: R, tick: Tick | undefined): R {
  if (!tick || tick.stale || !(tick.price > 0)) return row
  const p = tick.price
  const b = row.bases ?? {}
  return {
    ...row, price: p,
    change_pct: ret(p, b.d1, row.change_pct), w1: ret(p, b.w1, row.w1), m1: ret(p, b.m1, row.m1),
    m3: ret(p, b.m3, row.m3), ytd: ret(p, b.ytd, row.ytd), y1: ret(p, b.y1, row.y1),
  }
}

/** A group's rows at live prices, their relative returns against the live
 * benchmark, and the standing those give. */
export function liveGroup<R extends LiveRow>(rows: R[], bench: R, ticks: Record<string, Tick>): { rows: R[]; bench: R } {
  const b = liveRow(bench, ticks[bench.symbol])
  const rel = (v: number | null, bv: number | null) => (v != null && bv != null ? Math.round((v - bv) * 100) / 100 : null)
  return {
    bench: b,
    rows: rows.map(r => {
      const l = liveRow(r, ticks[r.symbol])
      const relM1 = rel(l.m1, b.m1), relM3 = rel(l.m3, b.m3)
      return { ...l, rel_m1: relM1, rel_m3: relM3, rotation: rotation(relM1, relM3) }
    }),
  }
}
