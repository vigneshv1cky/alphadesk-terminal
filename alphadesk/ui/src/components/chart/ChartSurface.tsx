import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { ChartCanvas } from "@/components/chart/ChartCanvas"
import { ChartDrawings, DrawingToolbar, nextId } from "@/components/ChartDrawings"
import { IndicatorLegend, IndicatorSettings } from "@/components/chart/IndicatorPanel"
import type { ChartEngine } from "@/lib/chartEngine"
import { menuItemCls, menuPanelCls } from "@/components/terminal"
import { useNarrowViewport } from "@/lib/viewport"

type MenuAt = { clientX: number; clientY: number; price: number | null; time: string | null }

/** The right-click menu over the plot — theirs, trimmed to what this chart
 * can honestly do: the view, a line at the price under the pointer, the
 * scale, the price line, the drawings. Nothing here trades. */
function ContextMenu({ e, at, onClose, drawable }: { e: ChartEngine; at: MenuAt; onClose: () => void; drawable: boolean }) {
  useEffect(() => {
    const away = () => onClose()
    const esc = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose() }
    document.addEventListener("mousedown", away)
    document.addEventListener("keydown", esc)
    document.addEventListener("scroll", away, true)
    return () => {
      document.removeEventListener("mousedown", away)
      document.removeEventListener("keydown", esc)
      document.removeEventListener("scroll", away, true)
    }
  }, [onClose])
  const price = at.price
  const fmt = (n: number) => n.toFixed(n >= 1 ? 2 : 4)
  const item = (label: string, act: () => void, opts: { disabled?: boolean; on?: boolean; danger?: boolean } = {}) => (
    <button key={label} type="button" disabled={opts.disabled}
      onMouseDown={ev => ev.stopPropagation()}
      onClick={() => { act(); onClose() }}
      className={`${menuItemCls} ${
        opts.danger ? "hover:text-loss" : "text-foreground"}`}>
      <span className="w-3 shrink-0 text-muted-foreground">{opts.on ? "✓" : ""}</span>
      {label}
    </button>
  )
  const rule = <span className="-mx-1 my-1 block h-px bg-row-rule" />
  // Keep the menu on screen: flip left/up near the edges.
  const w = 232, h = 300
  const left = Math.min(at.clientX, window.innerWidth - w - 8)
  const top = Math.min(at.clientY, window.innerHeight - h - 8)
  return createPortal(
    <div data-slot="dialog" style={{ left, top, width: w }}
      className={`pop-in fixed z-[80] ${menuPanelCls}`}
      onMouseDown={ev => ev.stopPropagation()}>
      {item("Reset chart view", () => e.viewRef.current?.reset())}
      {rule}
      {/* The line items and the drawing controls only where drawing is
          offered, the /chart workspace. */}
      {drawable && item(price != null ? `Horizontal line at ${fmt(price)}` : "Horizontal line here", () => {
        if (price == null || !at.time) return
        e.history.commit([...e.drawings, { id: nextId(), kind: "hline", a: { time: at.time, price } }])
      }, { disabled: price == null || !at.time })}
      {drawable && item("Vertical line here", () => {
        if (!at.time || price == null) return
        e.history.commit([...e.drawings, { id: nextId(), kind: "vline", a: { time: at.time, price } }])
      }, { disabled: !at.time || price == null })}
      {item(price != null ? `Copy price ${fmt(price)}` : "Copy price", () => {
        if (price != null) void navigator.clipboard?.writeText(fmt(price))
      }, { disabled: price == null })}
      {rule}
      {item("Logarithmic scale", () => e.setScale(e.scale === "log" ? "linear" : "log"), { on: e.scale === "log" })}
      {item("Percent scale", () => e.setScale(e.scale === "percent" ? "linear" : "percent"), { on: e.scale === "percent" })}
      {item("Last price line", () => e.setPriceLine(!e.priceLine), { on: e.priceLine })}
      {drawable && (
        <>
          {rule}
          {item(e.drawVisible ? "Hide drawings" : "Show drawings", () => e.setDrawVisible(!e.drawVisible),
            { disabled: !e.drawings.length })}
          {item(`Remove all drawings${e.drawings.length ? ` (${e.drawings.length})` : ""}`, () => e.history.commit([]),
            { disabled: !e.drawings.length, danger: true })}
        </>
      )}
    </div>,
    document.body,
  )
}

/** The drawable chart: tool column, canvas, annotation overlay. One
 * component for both surfaces (the Markets tile and the /chart workspace),
 * so the canvas is wired to the engine in exactly one place. Children are
 * laid over the plot — the workspace's legend goes there. */
export function ChartSurface({ e, legendTop, toolsAlwaysOn = false, children }: {
  e: ChartEngine
  /** Where the overlay legend starts — below whatever the surface itself
   * draws at the top-left of the plot. */
  legendTop?: number
  /** The tool column stays up and cannot be closed — the workspace's way;
   * the tile keeps its toggle because 34px of a small tile is a lot. */
  toolsAlwaysOn?: boolean
  children?: React.ReactNode
}) {
  const { data } = e
  const [menu, setMenu] = useState<MenuAt | null>(null)
  // Drawing is the /chart workspace's alone, and not on a phone (2026-09-18):
  // the tool column took 34px of a 375px screen, and placing anchors by
  // finger on a small chart is not a real use.
  const narrow = useNarrowViewport()
  const drawable = toolsAlwaysOn && !narrow
  if (!data) return null
  return (
    // The tool column sits BESIDE the canvas, not over it: a strip floating
    // on the plot hid the bars under it, and the canvas measures its own
    // width so it simply gives the column its 34px.
    <div className="flex">
      {drawable && (
        <DrawingToolbar
          closable={!toolsAlwaysOn}
          tool={e.tool} onTool={e.setTool}
          magnet={e.magnet} onMagnet={e.setMagnet}
          visible={e.drawVisible} onVisible={e.setDrawVisible}
          count={e.drawings.length}
          allLocked={e.allLocked}
          onLockAll={() => e.history.commit(e.drawings.map(d => ({ ...d, locked: !e.allLocked })))}
          onClear={() => e.history.commit([])}
          onClose={() => { e.setDrawOpen(false); e.setTool("none") }}
          onUndo={e.history.undo} onRedo={e.history.redo}
          canUndo={e.history.canUndo} canRedo={e.history.canRedo}
        />
      )}
      <div className="relative min-w-0 flex-1" data-chart-surface
        // Replay's "pick a bar": a click while selecting takes the bar under
        // the crosshair. The canvas's own mousedown starts a pan, which a
        // click without movement leaves harmless.
        onClick={ev => {
          if (!e.replay.active || !e.replay.selecting || !e.projection) return
          const r = ev.currentTarget.getBoundingClientRect()
          const t = e.projection.coordinateToTime(ev.clientX - r.left)
          if (t) e.selectReplayAt(t)
        }}>
        {e.replay.active && e.replay.selecting && (
          <div className="pointer-events-none absolute inset-x-0 top-2 z-30 flex justify-center">
            <span data-slot="dialog" className="border-2 border-info bg-popover px-3 py-1 text-caption font-semibold text-info">
              Click a bar to start the replay from
            </span>
          </div>
        )}
        <ChartCanvas
          bars={e.bars}
          kind={e.type}
          scale={e.scale}
          height={e.canvasHeight}
          panes={e.stacked}
          overlays={e.overlaySeries}
          onProjection={e.setProjection}
          onHover={(b, at) => { e.setHovered(b); e.setHoverAt(at) }}
          // The SERIES identity, not the bars. A poll brings a new array
          // for the same series and must not reset the reader's view.
          seriesId={e.seriesId}
          onRemovePane={e.removeIndicator}
          onResizePane={e.setPaneHeight}
          onPaneSettings={e.setSettingsId}
          timeZone={e.timeZone}
          interval={data.interval}
          priceLine={e.priceLine}
          // The workspace draws its readout over the plot; the series keeps
          // out from under it. The tile's readout sits above the canvas.
          topInset={legendTop ?? 0}
          onNeedHistory={e.loadHistory}
          focusFrom={e.focusFrom}
          historyNote={e.historyNote}
          live={e.live}
          provisional={e.provisional}
          controlRef={e.viewRef}
          onContextMenu={setMenu}
          // Session shading only means something on intraday bars — a
          // daily bar IS a session, so marking its boundaries would draw a
          // divider between every pair of bars.
          intraday={!!data.interval && !["1d", "1wk", "1mo"].includes(data.interval)}
          {...e.theme}
        />
        {/* Drawing is the /chart workspace's alone (2026-09-18, the
            owner's call): a line drawn on a board tile was left there and
            forgotten. The tile draws none and offers no tools. */}
        {drawable && <ChartDrawings
          projection={e.projection}
          bars={e.bars}
          tool={e.tool}
          onToolDone={() => e.setTool("none")}
          onArm={k => { e.setDrawOpen(true); e.setTool(k) }}
          drawings={e.drawings}
          onChange={e.history.commit}
          onUndo={e.history.undo} onRedo={e.history.redo}
          // A wheel over this layer is the chart's, not the drawing's.
          onWheel={ev => e.viewRef.current?.wheel(ev)}
          magnet={e.magnet}
          visible={e.drawVisible}
          // Matches the canvas, not the price pane: this is the surface
          // drawings are placed on. Where a drawing LANDS is the
          // projection's business either way.
          height={e.canvasHeight}
        />}
        <IndicatorLegend e={e} top={legendTop} />
        {children}
        <IndicatorSettings e={e} />
        {menu && <ContextMenu e={e} at={menu} drawable={drawable} onClose={() => setMenu(null)} />}
      </div>
    </div>
  )
}
