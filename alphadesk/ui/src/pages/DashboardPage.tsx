import "@/widgets/builtin"          // registers the shipped tiles
import "@/widgets/chart"            // the price tile
import "@/widgets/market"           // quote + movers
import "@/widgets/external"
import "@/widgets/more"
import "@/widgets/desk"         // declarative tiles from widget backends
import { BoardEditor } from "@/components/BoardEditor"
import { TileSlot } from "@/components/terminal"
import { BoardDragContext, useBoardDrag } from "@/components/BoardDrag"
import { useBoardLayout } from "@/lib/boardLayout"

/** The collage — the tiles this READER composed, on one canvas.
 *
 * This page deliberately knows nothing about what it renders. Tiles come from
 * the widget registry, so adding one means writing a module, not editing this
 * file — and which of them render, in what order, is the reader's saved
 * layout (lib/boardLayout, edited by the Customize control). Default is
 * everything registered, in registry order.
 *
 * Each tile owns its own polling; shared query keys mean two tiles reading the
 * same endpoint still produce one request.
 */
export default function DashboardPage() {
  const layout = useBoardLayout()
  // Dragging a tile moves it; dragging the grip in its header sizes it.
  // Same layout, same URL — see components/BoardDrag.
  const drag = useBoardDrag({
    ids: layout.items.map(i => i.def.id),
    spanOf: id => layout.items.find(i => i.def.id === id)?.span ?? 12,
    moveTo: layout.moveTo,
    setSpan: layout.setSpan,
  })
  return (
    <>
      {/* Same 16px inset the collage gives its tiles; the collage's own top
          padding provides the gap below. */}
      <div className="px-4 pt-2">
        <BoardEditor layout={layout} title="Markets" />
      </div>
      <BoardDragContext.Provider value={drag}>
        <div ref={drag.gridRef} className="collage !pt-0">
          {layout.items.map(({ def, span, align }) => {
            const W = def.component
            return (
              // The reader's width, where they set one, over the component's
              // own — the override mechanism the registry note reserved.
              <TileSlot key={def.id} id={def.id} span={span} align={align}>
                <W />
              </TileSlot>
            )
          })}
        </div>
      </BoardDragContext.Provider>
    </>
  )
}
