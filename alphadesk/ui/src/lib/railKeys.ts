/** Keyboard movement through the navigation rail (2026-11-23, the reader:
 * "cant navigate views section with keyboard").
 *
 * Measured before this: Tab and Enter reached every row, but the rail is a
 * column of thirty-odd stops — the twelve pages, My views, Baskets and their
 * headers — and the arrow keys did nothing, so walking down to a saved view
 * meant Tab, Tab, Tab past every page above it. Space did nothing on a row
 * either, because a link opens on Enter only.
 *
 * Tab still reaches every row and control: the arrows are an addition, not a
 * roving tab index, so nothing a Tab user relied on moved. They step through
 * every stop in the rail in the order it is drawn — section headers and their
 * + buttons included — wrapping at the ends, like the menus (lib/focus.ts).
 */

/** Where focus goes for `key`, given the focused stop's `index` among
 * `count` stops; -1 when the key is not a rail key (or there is nowhere to
 * go). An `index` of -1 means focus is in the rail but on none of the stops. */
export function railStep(key: string, index: number, count: number): number {
  if (count <= 0) return -1
  switch (key) {
    case "ArrowDown": return index < 0 ? 0 : (index + 1) % count
    case "ArrowUp": return index < 0 ? count - 1 : (index - 1 + count) % count
    case "Home": return 0
    case "End": return count - 1
    default: return -1
  }
}

/** Space opens a row the way Enter does. A button already treats Space as a
 * press, so only a link needs it done for it. */
export function opensOnSpace(key: string, tag: string): boolean {
  return key === " " && tag === "A"
}
