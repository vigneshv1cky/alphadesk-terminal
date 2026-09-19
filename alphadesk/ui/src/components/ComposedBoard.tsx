import { BoardEditor } from "@/components/BoardEditor"
import { TileSlot } from "@/components/terminal"
import { usePageLayout } from "@/lib/boardLayout"

/** A page's panels, composed by the reader — the Markets board's Customize
 * control, generalized to every tab.
 *
 * A page hands over its panels (id, label, the rendered node) and gets back
 * the whole apparatus: the Customize button, show/hide/reorder/width, the
 * layout in that page's own ?tiles= with a per-page storage mirror, absence
 * meaning the page's default. The page keeps building its panels with its
 * own state and props — composition only decides which render, in what
 * order, at what width.
 *
 * `before` is for the rare fixed element that must stay above the panels
 * and outside composition — the options page's scope-and-expiry form.
 */
export type ComposedPanel = {
  id: string
  label: string
  node: React.ReactNode
}

/** The heading each board carries, by its layout key. */
const PAGE_TITLES: Record<string, string> = {
  markets: "Markets", sectors: "Sectors", analysis: "Analysis", compare: "Compare", company: "Profile",
  earnings: "Earnings week", calendars: "Calendars", news: "News", portfolio: "Portfolio", options: "Options", ai: "AI",
}

export function ComposedBoard({ page, panels, before, title }: {
  page: string
  panels: ComposedPanel[]
  before?: React.ReactNode
  /** Overrides the heading PAGE_TITLES gives the layout key. */
  title?: string
}) {
  const layout = usePageLayout(page, panels)
  return (
    <>
      <div className="px-4 pt-2">
        <BoardEditor layout={layout} title={title ?? PAGE_TITLES[page]} />
      </div>
      <div className="collage !pt-0">
        {before}
        {layout.items.map(({ def, span, align }) => (
          <TileSlot key={def.id} span={span} align={align}>
            {def.node}
          </TileSlot>
        ))}
      </div>
    </>
  )
}
