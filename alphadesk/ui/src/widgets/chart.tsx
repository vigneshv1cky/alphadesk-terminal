import * as React from "react"
import { useLayoutEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { OhlcvStrip } from "@/components/chart/OhlcvStrip"
import { ChartSurface } from "@/components/chart/ChartSurface"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { resetChartPrefs } from "@/lib/chartPrefs"
import { ChartRanges, ChartToolbar } from "@/components/ChartToolbar"
import { Empty, HEADER_BAND, HeightOverride, useScreenBand, Widget } from "@/components/terminal"
import { TILE_PX, stepFor } from "@/lib/tileHeight"
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

/** A CHART IS NEVER DRAWN SMALL (2026-09-29, the owner: "never set charts
 * small", "never set charts small as auto").
 *
 * It spends ~135px of any tile on toolbar, price readout and range row before
 * a candle exists, so a share of a short window — or of the room left to a
 * tile low on a long board — can leave a plot of a few dozen pixels, which is
 * a sparkline pretending to be a chart. The floor applies to a chosen STEP
 * and to `auto` alike: a chart that cannot have its minimum takes the
 * minimum anyway and the board scrolls, which is the honest failure.
 *
 * 260px is about what the standard tile always gave it. */
const MIN_PLOT = 260

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

/** THE PLOT IS SIZED BEFORE THE FIRST PAINT, AND NOT RE-SIZED AGAINST AN
 * EMPTY TILE (2026-09-29, the owner, of a screen recording: "look at chart
 * changing sizes").
 *
 * Two faults, and they compounded into the jump the recording shows — the
 * chart arriving as tall as the window and shrinking by a third a second
 * later, on every tab change.
 *
 * THE FIRST IS THAT THE CORRECTION RAN WHILE THERE WAS NO CHART. The plot's
 * height is corrected by how far the tile's body misses the room, which is
 * the right rule once a chart is in it and a nonsense one before: a body
 * holding the word "loading" misses the room by almost all of it, so the
 * correction handed the canvas the entire overshoot and the tile arrived at
 * full window height. The toolbar, the price readout and the range row then
 * mounted underneath — about 135px that had already been given away — and the
 * next correction took it back. Nothing was wrong with the arithmetic; it was
 * being asked a question about a tile whose contents did not exist yet. It
 * now waits for the chart, and a tile mid-load simply keeps the height it
 * already had.
 *
 * THE SECOND IS THAT IT STARTED FROM THE WRONG NUMBER. The plot opened at the
 * standard tile's worth whatever the window, so even a correction that ran at
 * exactly the right moment had a visible distance to travel. It is seeded
 * from the same arithmetic every other tile was seeded with earlier today —
 * one window, less what sits above a board and the board's own reserve — so
 * the first paint is already about right and the correction is a few pixels
 * rather than a few hundred.
 *
 * The seed is a constant's worth of chrome and a constant cannot be right at
 * every width, which is why the measured correction stays. The point of the
 * seed is only that the reader never watches it converge. */
function useCanvasHeight(ref: React.RefObject<HTMLDivElement | null>, ready: boolean): number {
  // THE TILE'S HEIGHT IS A NUMBER, AND THE CANVAS IS WHAT IS LEFT OF IT
  // (2026-09-29, the owner's call to drop measured sizes entirely).
  //
  // What stood here measured the distance from this tile's body to the foot
  // of the window and took a share of it. That is why the chart kept resizing:
  // the distance depends on where the tile sits, so the chart under the
  // Earnings calendar got a different answer from the chart at the top of
  // Markets, and it could not be known until the page had laid out. The tile
  // height now comes from the screen band — a constant, known before anything
  // renders and identical on every load of the same screen.
  //
  // ONE THING IS STILL MEASURED, and it is not the tile: how much of the tile
  // is NOT plot. The toolbar and the range row WRAP at narrow widths, so the
  // chrome is 114px at full width and about 135 at half, and no constant is
  // right at both. It is corrected from the DOM once there is a chart to
  // measure against — and because the target no longer depends on the page,
  // the correction moves the canvas within a known tile instead of
  // renegotiating the tile itself.
  const step = React.useContext(HeightOverride)
  const band = useScreenBand()
  // The whole tile the reader asked for, less its header, less what the plot
  // has to share the body with.
  const tile = TILE_PX[band][stepFor(step, 2)]
  const target = Math.max(MIN_PLOT, tile - HEADER_BAND - CHART_CHROME)

  const [h, setH] = useState(target)
  const now = useRef(h)
  now.current = h
  // A NEW SIZE IS NOT SOMETHING TO CREEP TOWARDS. Changing the step in the
  // board editor, or moving the window across a band, asks for a different
  // tile — the reader should get it at once rather than watching a correction
  // walk there, and a correction from the old size would be measuring the
  // wrong thing anyway.
  const lastTarget = useRef(target)
  if (lastTarget.current !== target) {
    lastTarget.current = target
    now.current = target
    setH(target)
  }

  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current
      if (!el) return
      const body = el.parentElement
      if (!body) return
      // NOT AGAINST A TILE WITH NO CHART IN IT. The body's miss against the
      // tile is the plot's error only once the bands around the plot exist;
      // before that the body holds the word "loading" and misses by nearly
      // the whole tile, which is what once handed the canvas the entire
      // overshoot and drew a chart the height of the window.
      if (!ready) return
      // MEASURED ON THE SECTION, NOT REBUILT FROM THE BODY (2026-09-29, the
      // owner: "the chart tile seems a bit taller than news even though both
      // are xl"). Adding a header constant to the body's height leaves out
      // the card's 1px border top and bottom, so the chart settled 2px over
      // its size while every other tile sat 2px under — 4px apart at the
      // same named size. The outside height is the thing being matched, so
      // it is the thing to measure.
      const section = el.closest("[data-slot=widget]")
      if (!section) return
      const delta = Math.round(section.getBoundingClientRect().height) - tile
      if (Math.abs(delta) > 2) setH(Math.max(MIN_PLOT, now.current - delta))
    }
    // WATCHED, because one pass is not enough: the canvas changes, the bands
    // around it reflow, and the new error is only visible on the layout after
    // that. It stops on its own once the error is under 2px.
    measure()
    const body = ref.current?.parentElement
    const ro = body ? new ResizeObserver(measure) : null
    if (body && ro) ro.observe(body)
    return () => { ro?.disconnect() }
  }, [ref, tile, ready])
  return h
}


/** THE chart tile — one implementation for every board surface. The Markets
 * board registers it; Analysis and Portfolio render it directly.
 *
 * The symbol comes from ?symbol= (the strip) unless a page passes its own —
 * Portfolio scopes it to the picked row. */
// HALF THE ROW BY DEFAULT, beside the news tile on the Markets board
// (2026-09-29). Analysis, Portfolio, Earnings and the theme page all pass
// their own span, so this default is the registry's render alone.
export function MarketChart({ span = 6, symbol: symbolProp }: {
  span?: number
  symbol?: string
} = {}) {
  const [params] = useSearchParams()
  const symbol = (symbolProp ?? params.get("symbol") ?? "").toUpperCase()
  // The chart tile draws at its board height (2026-09-25): the popup that
  // gave it 620px is gone, so there is no second size to hold. A chart that
  // wants more room is widened in the board editor, which persists.
  const bodyRef = useRef<HTMLDivElement>(null)
  // The engine is asked for a height before it has anything to draw, so the
  // hook is told whether a chart is on screen yet — see its note.
  const [drawn, setDrawn] = useState(false)
  const priceHeight = useCanvasHeight(bodyRef, drawn)
  const e = useChartEngine(symbol, { priceHeight })
  const { data: caps } = useChartCapabilities()
  const { data, bars, err, isFetching, live, hovered, hoverAt } = e
  // Once a chart has been drawn it stays drawn: a refetch must not put the
  // tile back into the state where its height is up for renegotiation.
  const hasChart = !!data && bars.length > 0
  useLayoutEffect(() => { if (hasChart) setDrawn(true) }, [hasChart])

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
      <ChartRanges range={e.range} onRange={e.pickRange} loading={e.switching} />
    </Widget>
  )
}

// NO DEFAULT HEIGHT: "auto" already fills the room to the foot of the window,
// which on a common screen is within a few pixels of L, and unlike L it grows
// with the window instead of being pinned (2026-09-29, the owner: "auto
// should be L right?"). A registry default would also have shown as a
// reader's own choice in the board editor, which it is not.
registerWidget({ id: "market-chart", label: "Chart", order: 12, minStep: 2, component: MarketChart })
