import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { on, type MomentumAtHigh, type SessionHigh, type UpDownVolume } from "@/lib/api"
import { compact } from "@/components/Treemap"
import { Empty, Widget } from "@/components/terminal"

/** HAS THE DAY'S HIGH BEEN PUT IN (2026-10-27, the owner's "daily peaks").
 * The session high read closely — new highs, VWAP, momentum at the high,
 * volume either side of it, and when this stock's high usually comes. Every
 * line is a measurement with its window; nothing here says the high is in. */

const dash = "—"
const n2 = (v: number | null | undefined) => (v == null ? dash : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const pct = (v: number | null | undefined) => (v == null ? dash : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`)
const ratio = (v: number | null | undefined) => (v == null ? dash : `${v.toFixed(2)}×`)

type Cell = [string, string, string?]   // label, value, tooltip

function Column({ title, cells, note }: { title: string; cells: Cell[]; note?: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">{title}</div>
      {note ? <div className="py-1 text-caption text-muted-foreground">{note}</div> : cells.map(([l, v, tip]) => (
        <div key={l} className="flex items-baseline justify-between gap-2 border-b border-row-rule py-1 text-body" title={tip}>
          <span className="truncate text-muted-foreground">{l}</span>
          <span className="shrink-0 font-medium tnum">{v}</span>
        </div>
      ))}
    </div>
  )
}

const volLine = (v: UpDownVolume | undefined): string =>
  !v || !v.bars ? dash : `${compact(v.up_volume)} up / ${compact(v.down_volume)} down`

const momentumLine = (m: MomentumAtHigh | null | undefined, digits: number): string => {
  if (!m) return dash
  const at = m.at_high.toFixed(digits)
  if (m.earlier_peak == null) return `${at} (high was the first bar)`
  return `${at} at the high · ${m.earlier_peak.toFixed(digits)} at ${m.earlier_peak_at}`
}

const peakedWords = (m: MomentumAtHigh | null | undefined): string =>
  m?.peaked_before_price == null ? dash : m.peaked_before_price ? "Yes, earlier and higher" : "No, highest at the price high"

export function SessionHighPanel({ symbol, span = 12 }: { symbol: string; span?: number }) {
  const q = useQuery({
    queryKey: ["move-state", symbol],
    queryFn: ({ signal }) => on(signal).moveState(symbol),
    enabled: !!symbol,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
    retry: false,
  })
  const m = q.data
  const h = m?.session_high
  return (
    <Widget span={span} symbol={symbol} title="Session high" subtitle={m?.session ? `${m.session} · New York time` : undefined}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the session's bars are unavailable right now</QueryFailure>
        : !h || !h.reliable ? <Empty>{h?.note ?? "no intraday bars for this session"}</Empty> : (
          <div className="p-3">
            <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
              <Column title="The high" cells={[
                ["High", n2(h.high), "The session's highest price"],
                ["Set at", h.at_session_high ? `${h.high_at} (latest bar)` : h.high_at ?? dash],
                ["Minutes since", h.minutes_since_high == null ? dash : String(h.minutes_since_high)],
                ["Below the high", pct(h.down_from_high_pct), "The last price against the session high"],
                ["Swing given back", m?.given_back_from_high_pct == null ? dash : `${m.given_back_from_high_pct}%`,
                  "How much of the session's low-to-high swing has been given back: 0 at the high, 100 at the low"],
              ]} />
              <Column title="New highs and VWAP" cells={[
                ["New highs, last 30 min", String(h.new_highs?.last_30min ?? dash), "Bars that set a new session high in the last 30 minutes"],
                ["New highs, last 60 min", String(h.new_highs?.last_60min ?? dash)],
                ["New highs, session", String(h.new_highs?.session ?? dash)],
                ["Session VWAP", n2(h.vwap?.session_vwap), "The session's volume-weighted average price"],
                ["Last vs VWAP", pct(h.vwap?.last_vs_vwap_pct)],
                ["Range in typical ranges", ratio(h.range?.session_range_in_typical_ranges),
                  `The session's low-to-high range (${pct(h.range?.session_range_pct)}) against the typical daily range of the last 20 sessions (${pct(h.range?.typical_daily_range_pct)})`],
              ]} />
              <Column title="Momentum at the high" note={h.momentum?.reliable ? undefined : h.momentum?.note} cells={[
                ["RSI-9", momentumLine(h.momentum?.rsi_9, 1), "Intraday RSI-9 at the bar of the session high, and its highest earlier reading this session"],
                ["RSI peaked first", peakedWords(h.momentum?.rsi_9), `An earlier reading more than ${h.momentum?.rsi_margin_points ?? 5} points higher than at the price high`],
                ["MACD histogram", momentumLine(h.momentum?.macd_hist, 3)],
                ["MACD peaked first", peakedWords(h.momentum?.macd_hist)],
              ]} />
              <Column title="Volume either side" cells={[
                ["Since the high", volLine(h.volume?.since_high), "Volume on bars closing above the previous bar against bars closing below it, since the high"],
                ["Up to down, since", ratio(h.volume?.since_high.up_to_down_volume)],
                ["30 min into the high", volLine(h.volume?.last_30min_into_high)],
                ["Up to down, into", ratio(h.volume?.last_30min_into_high.up_to_down_volume)],
              ]} />
            </div>
            <UsualTime h={h} />
          </div>
        )}
    </Widget>
  )
}

function UsualTime({ h }: { h: SessionHigh }) {
  const u = h.usual_high_time
  if (!u) return null
  return (
    <div className="mt-3 border-t border-row-rule pt-2 text-caption leading-[1.5] text-muted-foreground">
      <span className="font-semibold text-foreground">When this stock's high usually comes. </span>
      {!u.reliable ? u.note : (
        <>
          Over {u.window}, the regular-session high was set at a median of {u.median_high_at};{" "}
          {u.set_later_than_now} of {u.sessions} set it later than {u.compared_with}. Past sessions are not a forecast.
        </>
      )}
    </div>
  )
}
