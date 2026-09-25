import { useSearchParams } from "react-router-dom"
import type { ExternalWidgetDef } from "@/lib/api"
import { useExternalWidgetData, useExternalWidgets } from "@/lib/queries"
import { Empty, Table, TD, TH, THead, Widget } from "@/components/terminal"
import { TILE_BODY_HEIGHT } from "@/widgets/tile"
import { registerWidget } from "@/widgets/registry"

/** Declarative external tiles — the fourth plugin seam, rendered.
 *
 * A widget backend (ALPHADESK_WIDGET_BACKENDS) contributes DATA and a SHAPE;
 * this module renders both with the house primitives. Nothing a backend
 * serves is executed or interpreted as markup — the server already coerced
 * every value to a capped plain scalar (alphadesk/extwidgets.py), and React
 * renders them as text. A deployment with no backends configured renders
 * nothing at all here.
 *
 * Tiles that declare the `symbol` param follow the board's marked chip like
 * every native tile does; the rest are board-independent.
 */

function num(v: string | number | null): string {
  if (v == null) return "—"
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    })
  }
  return v
}

function ExternalTile({ def }: { def: ExternalWidgetDef }) {
  const [params] = useSearchParams()
  const symbol = def.params.includes("symbol")
    ? (params.get("symbol") ?? "").toUpperCase()
    : ""
  const { data, error, isLoading } = useExternalWidgetData(def.uid, symbol, def.refresh_s)

  return (
    <Widget
      span={def.span}
      title={def.title}
      symbol={symbol || undefined}
      subtitle={def.subtitle || "external widget"}
      scroll={TILE_BODY_HEIGHT}
     
    >
      {isLoading && <Empty>loading…</Empty>}
      {error != null && (
        // The backend failing degrades this one tile, with the reason —
        // never the board.
        <Empty>{String((error as Error).message ?? error)}</Empty>
      )}
      {data?.type === "table" && (
        (data.rows?.length ?? 0) === 0
          ? <Empty>nothing to show</Empty>
          : (
            <Table>
              <THead>
                {def.columns.map(c => (
                  <TH key={c.key} align={c.align}>{c.label}</TH>
                ))}
              </THead>
              <tbody>
                {data.rows!.map((row, i) => (
                  <tr key={i} className="hover:bg-foreground/5">
                    {def.columns.map(c => (
                      <TD key={c.key} align={c.align} mono={c.align === "right"}>
                        {num(row[c.key] ?? null)}
                      </TD>
                    ))}
                  </tr>
                ))}
              </tbody>
            </Table>
          )
      )}
      {data?.type === "metrics" && (
        (data.metrics?.length ?? 0) === 0
          ? <Empty>nothing to show</Empty>
          : (
            <div className="px-3 py-1">
              {data.metrics!.map(m => (
                <div key={m.label}
                     className="row-rule flex items-baseline justify-between gap-2 py-1.5">
                  <span className="shrink-0 text-caption text-muted-foreground">{m.label}</span>
                  <span className="num truncate text-body font-semibold">{num(m.value)}</span>
                </div>
              ))}
            </div>
          )
      )}
    </Widget>
  )
}

function ExternalWidgets() {
  const { data } = useExternalWidgets()
  const defs = data?.widgets ?? []
  if (!defs.length) return null
  return (
    <>
      {defs.map(def => <ExternalTile key={def.uid} def={def} />)}
    </>
  )
}

registerWidget({ id: "external", label: "External tiles", order: 900, component: ExternalWidgets })
