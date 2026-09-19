import { useState } from "react"
import { HEAT, HEAT_FILL, HEAT_NONE, Treemap, heatHasData, type Heat } from "@/components/Treemap"
import { Empty, Widget, btnCls } from "@/components/terminal"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { useQuotes } from "@/lib/queries"
import { registerWidget } from "@/widgets/registry"

/** The second wave of board tiles (feedback, 2026-09-02: "we can add more
 * widgets") — built from components other pages already proved out, scoped
 * the way every tile is: to the symbol strip.
 */

/** The theme page's treemap, drawn over YOUR strip: area by the chosen
 * measure, color by today's move, a click marks the symbol. */
function HeatmapTile() {
  const { symbols, active, activate } = useBoardSymbols()
  const [metric, setMetric] = useState<Heat>("move")
  const quotes = useQuotes(symbols, HEAT_FILL[metric])
  const priced = quotes.data?.quotes as Record<string, unknown> | undefined
  return (
    <Widget
      span={6}
      title="Heatmap"
      subtitle={`your strip · sized by ${HEAT.find(h => h.id === metric)!.label.toLowerCase()}`}
      toolbar={
        <>
          {HEAT.map(h => (
            <button
              key={h.id}
              onClick={() => setMetric(h.id)}
              aria-pressed={h.id === metric}
              className={btnCls({ variant: "ghost", active: h.id === metric })}
            >
              {h.label}
            </button>
          ))}
        </>
      }
    >
      {symbols.length < 2 ? (
        <Empty>add a few symbols to the strip to draw a map</Empty>
      ) : (
        <div className="p-2">
          {quotes.data && !heatHasData(symbols, priced, metric) && (
            <p className="px-1 pb-2 text-caption text-muted-foreground">{HEAT_NONE[metric]}</p>
          )}
          <Treemap symbols={symbols} priced={quotes.data?.quotes} metric={metric}
                   picked={active} onPick={activate} />
        </div>
      )}
    </Widget>
  )
}

registerWidget({ id: "heatmap", label: "Heatmap", order: 19, component: HeatmapTile, optIn: true })
