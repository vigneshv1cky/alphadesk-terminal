import { useMemo, useState } from "react"
import { Eye, EyeOff, Settings2, X } from "lucide-react"
import { Btn, Dialog } from "@/components/terminal"
import { PALETTE } from "@/components/ChartDrawings"
import { indicatorDef, indicatorLabel, quantizeParam, type Indicator, type ParamDef } from "@/lib/indicators"
import type { ChartEngine } from "@/lib/chartEngine"

/** The overlay legend and the settings dialog (2026-09-05).
 *
 * Every indicator on the price pane gets a legend row the way theirs does:
 * name with its parameters, the value under the cursor in the line's own
 * colour, then eye / gear / remove. Pane indicators already carry a legend
 * inside their pane (ChartCanvas draws it), so this lists overlays only —
 * the gear there and the gear here open the same dialog.
 */

const swatches = [
  ...PALETTE,
  { id: "n800", css: "var(--n800)", label: "Dark grey" },
  { id: "n500", css: "var(--n500)", label: "Grey" },
  { id: "n300", css: "var(--n300)", label: "Light grey" },
]

export function IndicatorLegend({ e, top = 4 }: { e: ChartEngine; top?: number }) {
  const rows = e.indicators.filter(i => indicatorDef(i.type).place === "overlay")
  // One map per line so the value at the cursor is a constant-time read;
  // built once per series change, not per mouse move.
  const lookups = useMemo(
    () => e.overlaySeries.map(s => ({ id: s.id, color: s.color, m: new Map(s.points.map(p => [p.t, p.v])) })),
    [e.overlaySeries])
  const btn = "flex h-[14px] w-[14px] items-center justify-center text-muted-foreground hover:text-foreground"
  if (!rows.length) return null
  const at = (e.hovered ?? e.bars[e.bars.length - 1])?.t
  return (
    <div className="absolute left-1 z-20 flex flex-col gap-[1px]" style={{ top }}>
      {rows.map(ind => {
        const color = ind.color ?? indicatorDef(ind.type).color
        const lines = lookups.filter(l => l.id === ind.id)
        return (
          <div key={ind.id}
            className={`group flex items-center gap-1.5 rounded-sm px-1 text-label leading-[16px] ${ind.hidden ? "opacity-50" : ""}`}>
            <span className="h-[2px] w-3 shrink-0" style={{ background: color }} />
            <span className="tnum text-muted-foreground">{indicatorLabel(ind)}</span>
            {!ind.hidden && lines.map((l, i) => {
              const v = at == null ? undefined : l.m.get(at)
              return v == null ? null : (
                <span key={i} className="tnum" style={{ color: l.color }}>{v.toFixed(2)}</span>
              )
            })}
            <span className="ml-0.5 flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button type="button" className={btn} title={ind.hidden ? "Show" : "Hide"}
                aria-label={ind.hidden ? "Show indicator" : "Hide indicator"}
                onClick={() => e.updateIndicator(ind.id, { hidden: !ind.hidden })}>
                {ind.hidden ? <EyeOff className="h-[11px] w-[11px]" /> : <Eye className="h-[11px] w-[11px]" />}
              </button>
              <button type="button" className={btn} title="Settings" aria-label="Indicator settings"
                onClick={() => e.setSettingsId(ind.id)}>
                <Settings2 className="h-[11px] w-[11px]" />
              </button>
              <button type="button" className={`${btn} hover:!text-loss`} title="Remove" aria-label="Remove indicator"
                onClick={() => e.removeIndicator(ind.id)}>
                <X className="h-[11px] w-[11px]" />
              </button>
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** Inputs, then style — theirs has the same two tabs; ours fits on one card.
 * Changes apply as they are made, so the chart is the preview. */
export function IndicatorSettings({ e }: { e: ChartEngine }) {
  const ind = e.settingsId ? e.indicators.find(i => i.id === e.settingsId) : undefined
  if (!ind) return null
  const def = indicatorDef(ind.type)
  const color = ind.color ?? def.color
  const set = (patch: Partial<Indicator>) => e.updateIndicator(ind.id, patch)
  const setParam = (key: string, v: number) => set({ params: { ...ind.params, [key]: v } })
  const field = "h-[28px] w-[88px] border border-input bg-card px-2 text-body tnum text-foreground focus:border-accent focus:outline-none"
  return (
    <Dialog title={`${def.label} · ${indicatorLabel(ind)}`} onClose={() => e.setSettingsId(null)} maxWidth="max-w-[380px]">
      <div className="px-4 py-3">
        {def.params.length > 0 && (
          <>
            <div className="mb-1.5 text-label font-medium uppercase tracking-caps text-muted-foreground">Inputs</div>
            <div className="mb-3 flex flex-col gap-1.5">
              {def.params.map(p => (
                <label key={p.key} className="flex items-center justify-between gap-3 text-body">
                  <span>{p.label}</span>
                  <ParamField p={p} value={ind.params[p.key] ?? p.def} onCommit={v => setParam(p.key, v)} className={field} />
                </label>
              ))}
            </div>
          </>
        )}
        <div className="mb-1.5 text-label font-medium uppercase tracking-caps text-muted-foreground">Style</div>
        <div className="mb-2 flex items-center justify-between gap-3 text-body">
          <span>Colour</span>
          <span className="flex items-center gap-1">
            {swatches.map(s => (
              <button key={s.id} type="button" title={s.label} aria-label={s.label}
                onClick={() => set({ color: s.css })}
                className={`flex h-[20px] w-[20px] items-center justify-center rounded-sm ${color === s.css ? "bg-muted" : "hover:bg-muted"}`}>
                <span className="block h-[12px] w-[12px] rounded-full border border-border" style={{ background: s.css }} />
              </button>
            ))}
          </span>
        </div>
        <div className="mb-3 flex items-center justify-between gap-3 text-body">
          <span>Weight</span>
          <span className="flex items-center gap-1">
            {[1, 1.5, 2.5, 3.5].map(w => (
              <button key={w} type="button" title={`Width ${w}`} aria-label={`Width ${w}`}
                onClick={() => set({ width: w })}
                className={`flex h-[24px] w-[28px] items-center justify-center rounded-sm ${
                  (ind.width ?? (def.place === "overlay" ? 1 : 1.5)) === w ? "bg-muted" : "hover:bg-muted"}`}>
                <span className="block w-[14px] bg-foreground" style={{ height: w }} />
              </button>
            ))}
          </span>
        </div>
        <div className="flex items-center justify-end gap-1.5 border-t border-row-rule pt-3">
          <Btn onClick={() => {
            const params: Record<string, number> = {}
            for (const p of def.params) params[p.key] = p.def
            set({ params, color: undefined, width: undefined })
          }}>Defaults</Btn>
          <Btn variant="accent" onClick={() => e.setSettingsId(null)}>Done</Btn>
        </div>
      </div>
    </Dialog>
  )
}

/** A number field that lets the reader CLEAR it on the way to a new value.
 * Bound straight to the parameter, an emptied field read as 0, clamped to
 * the minimum, and typing 50 produced 15 then 150. The draft is the field's
 * own; the parameter takes the value on blur or Enter, snapped to its step
 * and bounds (a length is a whole number). */
function ParamField({ p, value, onCommit, className }: {
  p: ParamDef; value: number; onCommit: (v: number) => void; className: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const commit = () => {
    if (draft == null) return
    const v = Number(draft)
    if (draft.trim() !== "" && Number.isFinite(v)) onCommit(quantizeParam(p, v))
    setDraft(null)
  }
  return (
    <input type="number" value={draft ?? value}
      min={p.min} max={p.max} step={p.step ?? 1}
      onChange={ev => setDraft(ev.target.value)}
      onBlur={commit}
      onKeyDown={ev => { if (ev.key === "Enter") { ev.preventDefault(); commit() } }}
      className={className} />
  )
}
