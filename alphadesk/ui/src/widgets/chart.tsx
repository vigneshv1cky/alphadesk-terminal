import * as React from "react"
import { useLayoutEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { OhlcvStrip } from "@/components/chart/OhlcvStrip"
import { ChartSurface } from "@/components/chart/ChartSurface"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { resetChartPrefs } from "@/lib/chartPrefs"
import { ChartRanges, ChartToolbar } from "@/components/ChartToolbar"
import { Empty, HeightOverride, TILE_HEIGHT_PX, Widget } from "@/components/terminal"
import { useChartEngine } from "@/lib/chartEngine"
import { useChartCapabilities } from "@/lib/queries"
import { registerWidget } from "@/widgets/registry"
import { TILE_BODY_HEIGHT } from "@/widgets/tile"

/** The chart tile on the Markets board.
 *
 * Scoped by ?symbol= like every other tile, so one chip re-points the chart,
 * the quote panel and the AI rail together.
 *
 * Expanding takes the tile to the full width of the board. It is NOT what
 * makes room for indicators: panes used to require it, which meant ticking RSI
 * on a closed tile did nothing, and auto-opening the tile to compensate turned
 * one menu click into the chart taking over the board — then hid the panes
 * again the moment it was closed. A pane is simply drawn, and the tile grows
 * by exactly the height the panes need. Adding one costs a taller tile, which
 * is the honest price and is reversible by removing it; it does not cost the
 * rest of the board.
 *
 * The chart itself — state, series, panes, drawings — is lib/chartEngine and
 * chart/ChartSurface, shared with the /chart workspace. This file is the
 * TILE around it.
 */

/** What the canvas shares its tile with, MEASURED off the running page, not
 * derived: the toolbar and the range strip render at 40 each (28px bar
 * buttons, 6px air each side, the 1px rule), the OHLCV readout with its top padding at 25,
 * and the tile's 2px borders eat 4 from the body box. One extra pixel of
 * headroom so sub-pixel rounding never produces a one-pixel scrollbar.
 *
 * The canvas takes whatever is left, rather than a number picked
 * independently of the tile it has to fit inside — when these disagree with
 * reality the slack pools under the range strip (too big) or a scrollbar
 * appears on the chart (too small). Re-measure after touching any band. */
const CHART_CHROME = 42 + 42 + 25 + 4 + 1
const COLLAPSED = TILE_BODY_HEIGHT - CHART_CHROME

/** THE CANVAS FILLS WHAT IS ACTUALLY BELOW IT (2026-09-29, the owner: "like
 * increasing the height of the chart here", then "reduce the height just a
 * bit, or make it non scrollable when nothings below").
 *
 * A tile's body may grow to `max(402px, 100vh - 190px)` and most do, because
 * their content is a list. The chart never did: its canvas is a number handed
 * to the engine rather than content that reflows, so a half-and-half board had
 * one tall panel and one short one.
 *
 * THE FIRST FIX USED THAT SAME 190px CONSTANT AND STILL SCROLLED, because the
 * constant is a guess about what sits above and says nothing about what sits
 * BELOW: the board reserves 120px under its last row (80 on a phone), so a
 * tile that ends exactly at the viewport's foot pushes that reserve past it.
 * A guess cannot be right on the Markets board, a custom view with its own
 * heading and the News page at once.
 *
 * So it is MEASURED. The canvas takes the distance from the top of this tile's
 * body to the foot of the window, less the chart's own chrome and whatever the
 * board reserves beneath it. A tile below the fold measures negative and
 * falls back to the old fixed height, which is also what a window too short
 * for it gets.
 *
 * `scroll` stays undefined: a chart must still show WHOLE, toolbar and range
 * row included, and a cap put the toolbar behind an inner scrollbar (below).
 */

function useCanvasHeight(ref: React.RefObject<HTMLDivElement | null>): number {
  // THE READER'S STEP WINS OVER THE MEASUREMENT (2026-09-29). The board
  // editor offers a height for every tile, and a chart that ignored it would
  // show the step as active while rendering something else — a control
  // displaying a setting it does not obey, which is the fault this codebase
  // keeps finding. The tile still takes no body CAP: a cap put its toolbar
  // behind an inner scrollbar, so the step sizes the CANVAS instead, which is
  // what makes the tile as tall as the step asked for.
  //
  // "fill" and no step both measure, because filling the room available IS
  // the chart's own default.
  // ONE HEIGHT STANDARD (2026-09-29, the owner: "lets have one height
  // standard", after seeing a chart ladder and a tile ladder side by side).
  // A chart had its own numbers for a real reason — it spends 114px of any
  // body on toolbar, readout and range row before a candle is drawn, so the
  // same step buys it less — but two ladders meant S was not S, and a step
  // that means different things on different tiles is worse than a step that
  // is honestly small. The cost is stated rather than hidden: at S a chart
  // has 146px of plot, which is a sparkline. M is the smallest step worth
  // giving a chart.
  const step = React.useContext(HeightOverride)
  const fixed = step ? TILE_HEIGHT_PX[step] : null
  const [h, setH] = useState(COLLAPSED)
  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current
      if (!el) return
      const board = el.closest(".collage")
      const reserved = board
        ? parseFloat(getComputedStyle(board).paddingBottom) || 0
        : 0
      const room = window.innerHeight - el.getBoundingClientRect().top - CHART_CHROME - reserved
      setH(Math.max(COLLAPSED, Math.round(room)))
    }
    measure()
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [ref])
  return typeof fixed === "number" ? Math.max(80, fixed - CHART_CHROME) : h
}

/** THE chart tile — one implementation for every board surface. The Markets
 * board registers it; Analysis and Portfolio render it directly.
 *
 * The symbol comes from ?symbol= (the strip) unless a page passes its own —
 * Portfolio scopes it to the picked row. */
export function MarketChart({ span = 12, symbol: symbolProp }: {
  span?: number
  symbol?: string
} = {}) {
  const [params] = useSearchParams()
  const symbol = (symbolProp ?? params.get("symbol") ?? "").toUpperCase()
  // The chart tile draws at its board height (2026-09-25): the popup that
  // gave it 620px is gone, so there is no second size to hold. A chart that
  // wants more room is widened in the board editor, which persists.
  const bodyRef = useRef<HTMLDivElement>(null)
  const priceHeight = useCanvasHeight(bodyRef)
  const e = useChartEngine(symbol, { priceHeight })
  const { data: caps } = useChartCapabilities()
  const { data, bars, err, isFetching, live, hovered, hoverAt } = e

  if (!symbol) {
    return (
      <Widget span={span} title="Chart" scroll={TILE_BODY_HEIGHT}>
        <Empty>Pick a symbol to scope this board — use the chip in the header, or a movers row.</Empty>
      </Widget>
    )
  }

  return (
    <Widget
      span={span}
      symbol={symbol}
      title="Chart"
      subtitle={data ? `${data.bar_count} bars · ${data.sessions} sessions${live ? " · live" : ""}${isFetching ? " · updating…" : ""}` : undefined}
      // No height cap: a chart must show WHOLE — toolbar, readout, canvas
      // and range row. On a phone the readout wraps and the total passes
      // 402px; a cap there put the toolbar behind an internal scrollbar.
      // The canvas already draws at the standard tile height, so on desktop
      // the tile lands where it always did.
      scroll={undefined}
      ownHeight
    >
      {/* The measuring point: the top of the body, below the tile header. */}
      <div ref={bodyRef} />
      <ChartToolbar
        type={e.type} onType={e.setType}
        scale={e.scale} onScale={e.setScale}
        interval={e.interval}
        intervals={caps?.intervals}
        refused={caps?.refused}
        planNote={data?.plan_note}
        onInterval={iv => e.pinInterval(iv)}
        pinned={e.intervalPinned}
        servedInterval={data?.interval}
        servedLabel={data?.interval_label}
        available={data?.intervals}
        indicators={e.indicators} onAddIndicator={e.addIndicator}
        drawOpen={false} onDrawOpen={() => {}}
        // Drawing is the /chart workspace's alone (2026-09-18, the owner's
        // call): a line drawn on a tile was left on the board and forgotten.
        drawToggle={false}
        indicatorsReliable={data?.indicators_reliable ?? false}
        barCount={bars.length}
      />
      {err && <Empty>{err}</Empty>}
      {/* THE TILE KEEPS ITS HEIGHT WHILE THE SERIES LOADS (2026-09-16). A
          bare line of text collapsed the chart to one row, so every tile
          below it jumped up the page and back down a second later — plainly
          visible on a reload. The placeholder now stands as tall as the
          canvas it is about to be replaced by. */}
      {!err && !data && (
        <div className="flex items-center justify-center" style={{ height: priceHeight }}>
          <Empty>loading…</Empty>
        </div>
      )}
      {!err && data && (
        <div className="relative px-3 pt-1">
          <OhlcvStrip bar={hovered ?? bars[bars.length - 1] ?? null}
                      live={hovered == null} symbol={data.symbol}
                      first={bars[0] ?? null} at={hoverAt} timeZone={e.timeZone} delayMinutes={data.delay_minutes} />
          <ErrorBoundary label="The chart" onReset={() => resetChartPrefs(e.slot)}>
            <ChartSurface e={e} />
          </ErrorBoundary>
        </div>
      )}
      {/* A range change releases the interval back to the server's choice —
          the two are one decision, and pinning minute bars onto a year is not
          a thing to preserve. */}
      <ChartRanges range={e.range} onRange={e.pickRange} />
    </Widget>
  )
}

registerWidget({ id: "market-chart", label: "Chart", order: 12, component: MarketChart })
