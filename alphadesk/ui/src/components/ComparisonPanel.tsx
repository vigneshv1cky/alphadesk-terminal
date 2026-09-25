import React from "react"
import { Sparkline, Empty, Widget } from "@/components/terminal"
import { useChartSeries, useEarningsContext, useQuote } from "@/lib/queries"

/** The strip, side by side — one cell per chip, the active one first. The
 * board's strip is the input: comparison is what a second (or seventh) chip
 * is FOR, so the panel reads the lineup from there rather than carrying its
 * own picker.
 *
 * Four across, then a NEW BLOCK: four is the width where the metric numbers
 * stay readable, so a fifth chip starts a second panel rather than squeezing
 * the first. Each row of four is its own bordered block with the collage's
 * gap between them — the same separation the page's rows have — and only the
 * first carries the header; a continuation block is all cells. Nothing is
 * capped: every chip on the strip gets a cell. The sparkline is the day,
 * stroked in the direction colour with no fill. Metric rows: Last, market
 * cap, P/E, volume, revenue growth (quarter over quarter, from the reported
 * statements — a fact, not a forecast).
 */
const COLS = 4

const compact = (n: number | null | undefined): string => {
  if (n == null) return "—"
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (a >= 1e3) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return n.toFixed(2)
}

function MetricRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="row-rule flex items-baseline justify-between gap-2 py-1.5">
      <span className="shrink-0 text-caption text-muted-foreground">{label}</span>
      <span className="num truncate text-body font-semibold">{value}</span>
    </div>
  )
}

function Side({ symbol }: { symbol: string }) {
  const { data: q } = useQuote(symbol)
  const { data: ctx } = useEarningsContext(symbol)
  // A SPARKLINE, NOT A CHART (2026-09-16). This drew a 220-pixel line from
  // the day's full one-minute series — about 2,600 bars and 75–117KB per
  // card, twelve points to every pixel — once for every stock on the board.
  // Five-minute bars draw the same line from a fifth of the points.
  const { data: series } = useChartSeries(symbol, "1D", "5m")
  const closes = (series?.bars ?? []).map(b => b.c)
  const up = (q?.change_pct ?? 0) >= 0
  return (
    <div className="min-w-0 flex-1 px-3 py-2.5">
      <div className="flex items-baseline gap-2">
        <span className="text-figure font-extrabold tracking-tight">{symbol}</span>
        <span className={`num ml-auto shrink-0 text-body font-semibold ${up ? "text-gain" : "text-loss"}`}>
          {q?.change_pct == null ? "—" : `${up ? "+" : ""}${q.change_pct.toFixed(2)}%`}
        </span>
      </div>
      {q?.name && (
        <div className="hidden truncate text-label text-muted-foreground md:block">{q.name}</div>
      )}
      <div className={`my-2 ${up ? "text-gain" : "text-loss"}`}>
        {closes.length > 1
          ? <Sparkline points={closes} width={220} height={40} className="w-full" />
          : <div className="h-[40px]" />}
      </div>
      <MetricRow label="Last" value={q?.price != null ? q.price.toFixed(2) : "—"} />
      <MetricRow label="Mkt cap" value={compact(q?.market_cap)} />
      <MetricRow label="P/E" value={q?.pe_trailing != null ? q.pe_trailing.toFixed(1) : "—"} />
      <MetricRow label="Volume" value={q?.volume != null ? q.volume.toLocaleString() : "—"} />
      <MetricRow
        label="Rev QoQ"
        value={ctx?.revenue_qoq_pct != null
          ? `${ctx.revenue_qoq_pct >= 0 ? "+" : ""}${ctx.revenue_qoq_pct.toFixed(1)}%`
          : "—"}
      />
    </div>
  )
}

export function ComparisonPanel({ symbols, title = "Comparison" }: { symbols: string[]; title?: string }) {
  if (symbols.length < 2) {
    return (
      <Widget span={12} title={title}>
        <Empty>Add more chips to the board to compare {symbols[0] ?? "the active symbol"} against them.</Empty>
      </Widget>
    )
  }
  const rows: string[][] = []
  for (let i = 0; i < symbols.length; i += COLS) rows.push(symbols.slice(i, i + COLS))
  const subtitle = symbols.length === 2
    ? `${symbols[0]} against ${symbols[1]} — the strip's chips`
    : `all ${symbols.length} chips on the strip`
  return (
    <>
      {rows.map((row, r) => (
        // A Widget with no title renders no header — a continuation block is
        // just the bordered cells, and the collage supplies the gap.
        <Widget
          key={row.join()}
          span={12}
          title={r === 0 ? title : undefined}
          subtitle={r === 0 ? subtitle : undefined}
         
        >
          <div className="grid grid-cols-2 lg:grid-cols-4">
            {row.map((symbol, i) => (
              // A full row's last cell is closed by the panel border; a
              // partial row's last cell borders empty grid space and has to
              // close its own right edge.
              <div
                key={symbol}
                className={`min-w-0 ${i > 0 ? "border-l border-row-rule" : ""} ${
                  i === row.length - 1 && row.length < COLS ? "border-r border-row-rule" : ""
                }`}
              >
                <Side symbol={symbol} />
              </div>
            ))}
          </div>
        </Widget>
      ))}
    </>
  )
}
