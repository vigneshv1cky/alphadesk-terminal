import type { ComponentType } from "react"

/** The dashboard widget registry.
 *
 * The collage used to be hardcoded JSX inside DashboardPage, which meant
 * adding a tile required editing the page — fine for one operator, hostile to
 * a contributor. Now a widget is a self-contained module that registers
 * itself, and the page just renders whatever is registered, in order.
 *
 * A widget owns its own data fetching (see lib/queries — shared query keys
 * mean two widgets asking for the same endpoint still make one request).
 */
export type WidgetDef = {
  /** Stable id — used for ordering and for saved layouts (lib/boardLayout). */
  id: string
  /** What the layout editor calls this tile. */
  label: string
  /** Lower sorts first. Leave gaps so a plugin can slot between built-ins.
   * This is the DEFAULT order — a reader's saved layout overrides it. */
  order: number
  /** Library-only tile: offered in the widget library, absent from default
   * boards (see lib/boardLayout's PanelDef). */
  optIn?: boolean
  /** Grid width is NOT declared here: the component renders its own
   * `<Widget span={n}>`, so duplicating it in the registry would be a second
   * source of truth that drifts. The layout editor composes and orders tiles;
   * it deliberately does not resize them. */
  component: ComponentType
}

const registry = new Map<string, WidgetDef>()

export function registerWidget(def: WidgetDef): void {
  // Last registration wins, so a fork or plugin can replace a built-in tile
  // by re-registering its id rather than patching the page.
  registry.set(def.id, def)
}

export function widgets(): WidgetDef[] {
  return [...registry.values()].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
}

export function unregisterWidget(id: string): boolean {
  return registry.delete(id)
}
