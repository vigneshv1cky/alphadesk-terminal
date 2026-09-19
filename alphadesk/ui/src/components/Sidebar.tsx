import { useEffect, useState } from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { Activity, Building2, CalendarDays, CalendarRange, ChartCandlestick, ChevronDown, ChevronLeft, Layers3, LayoutGrid, LineChart, Newspaper, Plus,
  ShieldCheck, LayoutDashboard, Star, UserRound,
} from "lucide-react"
import { useAuthMe, useRail, useThemes } from "@/lib/queries"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { boardStories, useNewsSeen } from "@/lib/newsSeen"
import { useNarrowViewport } from "@/lib/viewport"
import { useMyViews } from "@/lib/customViews"
import { WidgetLibraryDialog } from "@/components/WidgetLibrary"
import { BasketDialog } from "@/components/BasketDialog"
import { searchBaskets } from "@/lib/basketSearch"
import { btnCls } from "@/components/terminal"

/** The nav rail — 208px, single-line 30px rows: icon, label, and a
 * right-aligned count where there is one. The counts are the same shared
 * queries the pages themselves poll, so the rail never fires a request a page
 * wouldn't. No hint text under rows — that pattern doubled the rail's height
 * for nothing. Collapses to 44px, icons only: no counts, no baskets, no
 * footer band.
 *
 * Active row: solid accent with white text (the ink-chrome theme,
 * 2026-09-18) — the page you are on, which is not a picker's selection.
 */

const VIEWS = [
  // The owner's order (2026-09-16): the names being held, then the chart of
  // one, then the market around them.
  { to: "/portfolio", label: "Portfolio", Icon: Star },
  { to: "/chart", label: "Chart", Icon: ChartCandlestick },
  { to: "/markets", label: "Markets", Icon: Activity },
  { to: "/sectors", label: "Sectors", Icon: LayoutGrid },
  { to: "/analysis", label: "Analysis", Icon: LineChart },
  { to: "/profile", label: "Profile", Icon: Building2 },
  { to: "/news", label: "News", Icon: Newspaper },
  { to: "/earnings", label: "Earnings", Icon: CalendarDays },
  { to: "/calendars", label: "Calendars", Icon: CalendarRange },
  { to: "/options", label: "Options", Icon: Layers3 },
] as const

const COLLAPSE_KEY = "alphadesk.rail.collapsed"

function readCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSE_KEY) === "1" } catch { return false }
}

/** On PHONES the rail is forced to its 44px icon form — a 208px column on a
 * 375px screen leaves the board 120px, and expanding opens the drawer
 * instead. From 640px up the rail is an ordinary expandable column: a
 * mid-size window can afford it, and a full-screen drawer there reads as a
 * takeover (feedback 2026-09-03). */
// useNarrowViewport lives in lib/viewport.ts now — the chart reads it too.

/** A rail section's fold state, remembered per section (open by default). */
function useSectionFold(id: string): [boolean, () => void] {
  const key = `alphadesk.rail.fold.${id}`
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(key) !== "0" } catch { return true }
  })
  const toggle = () => setOpen(v => {
    try { localStorage.setItem(key, v ? "0" : "1") } catch { /* private mode */ }
    return !v
  })
  return [open, toggle]
}

/** A section header that folds its rows — the chevron turns, the rows come
 * and go, and the choice sticks per section. */
function SectionHeader({ label, open, onToggle, className, children }: {
  label: string
  open: boolean
  onToggle: () => void
  className?: string
  children?: React.ReactNode
}) {
  return (
    <div className={`flex shrink-0 items-center justify-between ${className ?? ""}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-label font-medium uppercase tracking-caps text-muted-foreground hover:text-foreground"
      >
        <ChevronDown
          className={`h-[10px] w-[10px] shrink-0 transition-transform ${open ? "" : "-rotate-90"}`}
          aria-hidden="true"
        />
        {label}
      </button>
      {children}
    </div>
  )
}

/** Stories about the board's stocks published since the News page was last
 * open (lib/newsSeen) — 0 while it is open, since it keeps the mark moving. */
function useBoardNewsCount(): number {
  const { symbols } = useBoardSymbols()
  const rail = useRail(symbols)
  const seen = useNewsSeen()
  const { pathname } = useLocation()
  // The rail's stories carry identity only — id, tickers, time — which is
  // all the mark comparison needs; the headlines stay on the News page.
  if (pathname.startsWith("/news") || !rail.data) return 0
  return boardStories(rail.data.stories, symbols, seen).fresh.size
}

/** Dispatched by the header's menu button on a phone to open the drawer. */
export const OPEN_MENU_EVENT = "alphadesk:open-menu"

export function Sidebar() {
  const [collapsedChoice, setCollapsed] = useState(readCollapsed)
  const narrow = useNarrowViewport()
  const collapsed = collapsedChoice || narrow
  // On a narrow viewport the FULL rail opens as a drawer over the board —
  // there is no 208px column to give, but there is a whole screen to borrow
  // for a moment. Navigating anywhere puts it away.
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => { setDrawerOpen(false) }, [pathname])
  // On a phone there is no strip at all (2026-09-18): its 56px was a sixth
  // of a 375px screen. The header's menu button opens the drawer instead.
  useEffect(() => {
    const open = () => setDrawerOpen(true)
    window.addEventListener(OPEN_MENU_EVENT, open)
    return () => window.removeEventListener(OPEN_MENU_EVENT, open)
  }, [])
  const [viewsOpen, toggleViews] = useSectionFold("views")
  const [basketsOpen, toggleBaskets] = useSectionFold("baskets")
  const [mineOpen, toggleMine] = useSectionFold("my-views")
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [basketOpen, setBasketOpen] = useState(false)
  const [basketQuery, setBasketQuery] = useState("")
  const mine = useMyViews()
  const myViews = mine.views
  const navigate = useNavigate()
  const createFromLibrary = (name: string, ids: string[]) => {
    setLibraryOpen(false)
    void mine.create(name, ids.join(",")).then(id =>
      navigate(`/views/${id}`, { state: { compose: true } }))
  }
  const boardNews = useBoardNewsCount()
  const { data: themesData } = useThemes()
  const { data: me } = useAuthMe()
  const themes = themesData?.themes ?? []
  const shownBaskets = searchBaskets(themes, basketQuery)

  const toggle = () => {
    setCollapsed(v => {
      try { localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1") } catch { /* private mode */ }
      return !v
    })
  }

  // A selected row is a rounded pill inset from the rail's edges (the
  // reader's call, 2026-09-11): no bar at the left, no square corners.
  // Solid red with light ink since the ink chrome (2026-09-18): the rail's
  // current page is the one place besides the header's rule that carries
  // the brand colour at full strength. Its count follows the row's ink.
  const rowCls = (isActive: boolean, h: string) =>
    `mx-1.5 flex ${h} items-center gap-2 rounded-md px-1.5 text-body ${
      isActive
        ? "bg-accent font-extrabold text-white [&_*]:!text-white"
        : "font-semibold text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
    }`

  if (narrow && !drawerOpen) return null
  if (collapsed && !(narrow && drawerOpen)) {
    return (
      <nav aria-label="Views" className="flex w-[44px] shrink-0 flex-col overflow-hidden rounded-lg border border-card-border bg-card shadow-card">
        <div className="flex h-[32px] items-center justify-center border-b border-row-rule">
          <button
            type="button"
            onClick={() => (narrow ? setDrawerOpen(true) : toggle())}
            aria-label="Expand the navigation rail"
            className={btnCls({ size: "sm", icon: true })}
          >
            <ChevronLeft className="h-[11px] w-[11px] rotate-180" aria-hidden="true" />
          </button>
        </div>
        {VIEWS.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              `mx-1 flex h-[40px] items-center justify-center rounded-md ${
                isActive
                  ? "bg-accent text-white"
                  : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
              }`
            }
          >
            <span className="relative">
              <Icon className="h-[15px] w-[15px]" aria-hidden="true" />
              {to === "/news" && boardNews > 0 && (
                <span className="absolute -right-[5px] -top-[4px] h-[7px] w-[7px] rounded-full bg-accent" aria-label={`${boardNews} new stories about your board`} />
              )}
            </span>
          </NavLink>
        ))}
        <div className="flex-1" />
        {me?.user && (
          <NavLink
            to="/account"
            title="Account"
            className={({ isActive }) =>
              `flex h-[40px] items-center justify-center ${
                isActive ? "text-accent" : "text-muted-foreground hover:text-foreground"
              }`
            }
          >
            <UserRound className="h-[15px] w-[15px]" aria-hidden="true" />
          </NavLink>
        )}
        {me?.user?.owner && (
          <NavLink
            to="/admin"
            title="Admin"
            className={({ isActive }) =>
              `flex h-[40px] items-center justify-center ${
                isActive ? "text-accent" : "text-muted-foreground hover:text-foreground"
              }`
            }
          >
            <ShieldCheck className="h-[15px] w-[15px]" aria-hidden="true" />
          </NavLink>
        )}
      </nav>
    )
  }

  const rail = (
    <nav aria-label="Views" className={`flex w-[208px] shrink-0 flex-col overflow-hidden rounded-lg border border-card-border bg-card shadow-card ${narrow ? "h-full" : ""}`}>
      <SectionHeader label="Views" open={viewsOpen} onToggle={toggleViews}
                     className="h-[32px] py-0 pl-3 pr-2">
        <button
          type="button"
          onClick={() => (narrow ? setDrawerOpen(false) : toggle())}
          aria-label="Collapse the navigation rail"
          className={btnCls({ size: "sm", icon: true })}
        >
          <ChevronLeft className="h-[11px] w-[11px]" aria-hidden="true" />
        </button>
      </SectionHeader>

      {/* Everything between the header and the account footer scrolls
          (2026-09-16): baskets and saved views grow without limit, and on a
          short window they used to push the footer out of the rail. */}
      <div className="scrollbar-none min-h-0 flex-1 overflow-y-auto overscroll-contain">
      {/* No counts beside the views or the baskets (2026-09-18, the owner's
          call): the rail names places. The one number left is "N new" on
          News, an alert rather than a count. */}
      {viewsOpen && VIEWS.map(({ to, label, Icon }) => (
        <NavLink key={to} to={to} className={({ isActive }) => rowCls(isActive, "h-[32px]")}>
          {({ isActive }) => (
            <>
              <Icon className={`h-[15px] w-[15px] shrink-0 ${isActive ? "text-accent" : "text-muted-foreground"}`} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{label}</span>
              {to === "/news" && boardNews > 0 ? (
                <span className="num shrink-0 rounded-sm bg-accent px-1 text-label font-extrabold text-accent-foreground"
                      title={`${boardNews} new ${boardNews === 1 ? "story" : "stories"} about stocks on your board since you last opened News`}>
                  {boardNews} new
                </span>
              ) : null}
            </>
          )}
        </NavLink>
      ))}

      <SectionHeader label="My views" open={mineOpen} onToggle={toggleMine}
                     className="mt-1.5 h-[28px] pl-3 pr-2">
        <button
          type="button"
          onClick={() => setLibraryOpen(true)}
          aria-label="Create a view"
          title="Create a view"
          className={btnCls({ size: "sm", icon: true })}
        >
          <Plus className="h-[11px] w-[11px]" aria-hidden="true" />
        </button>
      </SectionHeader>
      {mineOpen && myViews.map(v => (
        <NavLink key={v.id} to={`/views/${v.id}`}
                 className={({ isActive }) => rowCls(isActive, "h-[32px]")}>
          {({ isActive }) => (
            <>
              {/* A board of tiles; the dashed empty square read as a placeholder (2026-09-19). */}
              <LayoutDashboard className={`h-[15px] w-[15px] shrink-0 ${isActive ? "text-accent" : "text-muted-foreground"}`} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{v.name}</span>
            </>
          )}
        </NavLink>
      ))}
      {/* Baskets below the reader's own views (2026-09-18): with 22 curated
          baskets the My views heading and its + had been pushed off the
          rail. The + here makes a basket of the reader's own. */}
      <SectionHeader label="Baskets" open={basketsOpen} onToggle={toggleBaskets}
                     className="mt-1.5 h-[28px] pl-3 pr-2">
        <button
          type="button"
          onClick={() => setBasketOpen(true)}
          aria-label="Create a basket"
          title="Create a basket"
          className={btnCls({ size: "sm", icon: true })}
        >
          <Plus className="h-[11px] w-[11px]" aria-hidden="true" />
        </button>
      </SectionHeader>
      {basketsOpen && themes.length > 6 && (
        // A search once the list is long (2026-09-18): name, description or
        // a ticker it holds. Escape clears it.
        <div className="mx-1.5 mb-1 mt-0.5">
          <input
            value={basketQuery}
            onChange={e => setBasketQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Escape") setBasketQuery("") }}
            placeholder="Find a basket or ticker"
            aria-label="Find a basket by name, description or ticker"
            className="h-[28px] w-full rounded-sm border border-card-border bg-card px-2 text-caption text-foreground placeholder:text-muted-foreground/70 focus:border-accent focus:outline-none"
          />
        </div>
      )}
      {basketsOpen && basketQuery.trim() && !shownBaskets.length && (
        <div className="px-3 py-1.5 text-caption text-muted-foreground">no basket matches “{basketQuery.trim()}”</div>
      )}
      {basketsOpen && shownBaskets.map(t => (
        <NavLink
          key={t.id}
          to={`/themes/${t.id}`}
          className={({ isActive }) => rowCls(isActive, "h-[32px]")}
        >
          <span className="min-w-0 flex-1 truncate">{t.label}</span>
        </NavLink>
      ))}
      {basketOpen && <BasketDialog onClose={() => setBasketOpen(false)} />}

      {libraryOpen && (
        <WidgetLibraryDialog
          title="New view"
          submitLabel="Save view"
          withName
          initialIds={["market-chart", "equity-overview"]}
          onClose={() => setLibraryOpen(false)}
          onSubmit={createFromLibrary}
        />
      )}

      </div>

      {/* The account links sit in a FOOTER, lifted off the rail's bottom
          edge (2026-09-18, the owner's "too low"): a hairline above and
          room below, so the last row is not a target against the card's
          edge. */}
      {me?.user && (
        <div className="shrink-0 border-t border-row-rule pb-2 pt-1">
          <NavLink
            to="/account"
            className={({ isActive }) =>
              `flex h-[32px] shrink-0 items-center gap-2 px-3 text-body ${
                isActive ? "font-extrabold text-foreground" : "font-semibold text-muted-foreground hover:text-foreground"
              }`
            }
          >
            <UserRound className="h-[15px] w-[15px] shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">Account</span>
          </NavLink>
        {/* The owner's admin page (2026-09-18): only for ALPHADESK_OWNER_EMAILS. */}
        {me?.user?.owner && (
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              `flex h-[32px] shrink-0 items-center gap-2 px-3 text-body ${
                isActive ? "font-extrabold text-foreground" : "font-semibold text-muted-foreground hover:text-foreground"
              }`
            }
          >
            <ShieldCheck className="h-[15px] w-[15px] shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">Admin</span>
          </NavLink>
        )}
        </div>
      )}
    </nav>
  )

  if (narrow) {
    return (
      // Below the header (52px) and the symbol strip (46px), not over them —
      // the drawer borrows the CONTENT area, the chrome stays put.
      <div className="fixed inset-x-0 bottom-0 top-[98px] z-[60]" role="dialog" aria-label="Navigation">
        <div className="absolute inset-0 bg-black/60 [animation:fade-in_120ms_linear]" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
        <div className="drawer-in relative h-full w-fit py-1.5 pl-1.5">{rail}</div>
      </div>
    )
  }
  return rail
}
