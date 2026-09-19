import { lazy, Suspense, useCallback, useEffect, useState } from "react"
import { Menu, Monitor, Moon, Sun } from "lucide-react"
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom"
import { api } from "@/lib/api"
import { useTheme } from "@/lib/theme"
import { SubscribePage } from "@/components/SubscribePage"
import { LandingPage } from "@/components/LandingPage"
import type { Access } from "@/lib/api"
import { OPEN_MENU_EVENT, Sidebar } from "@/components/Sidebar"
import { SymbolStrip } from "@/components/SymbolStrip"
import { HeaderTips, btnCls } from "@/components/terminal"

// Lazy routes — each page is its own chunk, so it loads like a real page.
const DashboardPage = lazy(() => import("@/pages/DashboardPage"))
const NewsPage = lazy(() => import("@/pages/NewsPage"))
const AnalysisPage = lazy(() => import("@/pages/AnalysisPage"))
const SectorsPage = lazy(() => import("@/pages/SectorsPage"))
const PortfolioPage = lazy(() => import("@/pages/PortfolioPage"))
const EarningsPage = lazy(() => import("@/pages/EarningsPage"))
const CalendarsPage = lazy(() => import("@/pages/CalendarsPage"))
const AccountPage = lazy(() => import("@/pages/AccountPage"))
const AdminPage = lazy(() => import("@/pages/AdminPage"))
const ThemePage = lazy(() => import("@/pages/ThemePage"))
const OptionsPage = lazy(() => import("@/pages/OptionsPage"))
const CustomViewPage = lazy(() => import("@/pages/CustomViewPage"))
const TermsPage = lazy(() => import("@/pages/TermsPage"))
const PrivacyPage = lazy(() => import("@/pages/PrivacyPage"))
const DisclaimerPage = lazy(() => import("@/pages/DisclaimerPage"))
const AboutPage = lazy(() => import("@/pages/AboutPage"))
const CompanyPage = lazy(() => import("@/pages/CompanyPage"))
const ChartPage = lazy(() => import("@/pages/ChartPage"))

const TITLES: Record<string, string> = {
  "/markets": "Markets · AlphaDesk",
  "/sectors": "Sectors · AlphaDesk",
  "/analysis": "Analysis · AlphaDesk",
  "/news": "News · AlphaDesk",
  "/portfolio": "Portfolio · AlphaDesk",
  "/earnings": "Earnings · AlphaDesk",
  "/calendars": "Calendars · AlphaDesk",
  "/account": "Account · AlphaDesk",
  "/admin": "Admin · AlphaDesk",
  "/terms": "Terms · AlphaDesk",
  "/privacy": "Privacy · AlphaDesk",
  "/disclaimer": "Not investment advice · AlphaDesk",
  "/about": "About · AlphaDesk",
  "/welcome": "AlphaDesk — research the market",
  "/profile": "Profile · AlphaDesk",
}

/** The header tabs — shortcuts to the surfaces you live on; the rail
 * carries the full list. The AI tab led until the in-app agent was removed
 * (2026-09-17): readers now ask through their own agent over MCP. */
const TABS = [
  { to: "/markets", label: "Markets", short: "Markets" },
  { to: "/analysis", label: "Analysis", short: "Analysis" },
  { to: "/earnings", label: "Earnings week", short: "Earnings" },
  // From md: under 768 the rail (a drawer on phones) carries it, and the
  // header had no room left even for four tabs.
  { to: "/calendars", label: "Calendars", short: "Calendars", wideOnly: true },
] as const

/** A redirect that keeps ?symbol= / ?accession=. A bare <Navigate> would drop
 * the query, so an old /chart?symbol=NVDA link would land on Analysis showing
 * the default company instead of the one that was linked. */
function RedirectKeepingQuery({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
}

function Shell({ userEmail }: { userEmail?: string | null }) {
  const { pathname } = useLocation()
  const [theme, toggleTheme] = useTheme()

  // Per-page document title
  useEffect(() => { document.title = TITLES[pathname] ?? "AlphaDesk" }, [pathname])

  return (
    // dvh, not vh: on a phone the browser chrome overlaps a 100vh box and the
    // strip at the bottom becomes unreachable; dvh tracks the visible height.
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      {/* The 52px header. No max-width container anywhere in the shell: a
          data-dense terminal uses the full width of the display. Below the
          tablet width the info-only pieces yield — the tagline, the live
          badge and freshness are facts, not controls, and the controls are
          what must survive on a phone. */}
      <header className="chrome z-30 flex h-[52px] shrink-0 items-center gap-3 pl-3 sm:pl-4 lg:gap-5">
        <div className="flex shrink-0 items-center gap-2.5">
          {/* The phone's way to the views and baskets: the rail has no strip
              below 640px (2026-09-18), so this opens it as a drawer. */}
          <button type="button" aria-label="Open the menu"
                  onClick={() => window.dispatchEvent(new Event(OPEN_MENU_EVENT))}
                  className={btnCls({ variant: "ghost", size: "lg", icon: true }, "-ml-1 sm:hidden")}>
            <Menu className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
          <span aria-hidden="true" className="h-[14px] w-[14px] rounded-xs bg-accent" />
          {/* The wordmark shows on a phone too since 2026-09-18: the page
              tabs moved into the menu drawer there, which frees the room. */}
          <span className="text-figure font-extrabold tracking-tight">ALPHADESK</span>
        </div>
        {/* No tagline (2026-09-18, the owner's call). "Research workspace — no
            order routing" and its divider sat here; the not-a-broker stance
            is stated on the Terms and About pages. */}
        <div className="min-w-0 flex-1" />
        {/* Below 640px the tabs are the menu drawer's (the header button):
            menu, wordmark, tabs and controls overflowed a 375px screen. */}
        <nav aria-label="Workspaces" className="hidden h-full shrink-0 items-stretch sm:flex">
          {TABS.map(tab => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `${"wideOnly" in tab ? "hidden md:flex" : "flex"} items-center px-1.5 text-caption font-extrabold uppercase tracking-caps sm:px-2.5 xl:px-4 ${
                  isActive
                    ? "border-b-[3px] border-accent bg-panel text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`
              }
            >
              {/* Five tabs since Calendars (2026-09-14): the long labels need
                  the room a 1280px header has, or the live cluster is pushed
                  off the right edge at 1024. */}
              <span className="xl:hidden">{tab.short}</span>
              <span className="hidden xl:inline">{tab.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="flex h-full shrink-0 items-center gap-2 border-l-2 border-border pl-2.5 pr-2.5 sm:gap-3.5 sm:pl-4 sm:pr-4">
          {/* No "Live data" mark or news-age readout (2026-09-18, the owner's
              call before going live): the terminal is always live, and the
              news list dates its own stories. */}
          {/* The theme switch, shaped like the strip's AI pill rather than a
              shouting caps chip: an icon that says the state, a quiet label. */}
          <button
            onClick={toggleTheme}
            aria-label="Cycle the colour theme"
            title={`Theme: ${theme === "dark" ? "dark" : theme === "light" ? "light" : "follows the system"} — click to change`}
            className={btnCls({ size: "lg" }, "gap-1.5")}
          >
            {theme === "dark" ? <Moon className="h-[13px] w-[13px]" aria-hidden="true" />
              : theme === "light" ? <Sun className="h-[13px] w-[13px]" aria-hidden="true" />
              : <Monitor className="h-[13px] w-[13px]" aria-hidden="true" />}
            <span className="hidden sm:inline">{theme === "dark" ? "Dark" : theme === "light" ? "Light" : "Auto"}</span>
          </button>
          {userEmail && (
            // The signed-in presence: an identity chip that opens the
            // Account page (where Sign out lives with the rest of "me").
            <NavLink
              to="/account"
              title={`Signed in as ${userEmail} — open your account`}
              className={({ isActive }) =>
                // No accent ring on the active state: the chip is identity,
                // not navigation emphasis — it stays quiet on every page.
                `flex h-[24px] max-w-[180px] shrink-0 items-center gap-1.5 rounded-sm border border-border px-2 text-label font-extrabold tracking-ticker ${
                  isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                }`
              }
            >
              <span aria-hidden="true"
                    className="flex h-[14px] w-[14px] shrink-0 items-center justify-center rounded-xs bg-info text-label font-extrabold uppercase text-background">
                {userEmail[0]}
              </span>
              <span className="hidden min-w-0 truncate normal-case sm:inline">{userEmail.split("@")[0]}</span>
            </NavLink>
          )}
        </div>
      </header>
      {/* The symbol strip replaces the ticker tape: a static chip row that
          scopes the board, on every screen. */}
      <SymbolStrip />
      {/* Nav rail and content are flex siblings. (A third column, the agent
          panel, was removed on 2026-09-17.) Since the soft-radius pass (2026-09-02) the rails FLOAT:
          rounded panels on the app ground with 10px gutters, instead of
          full-bleed surfaces fenced off by border rules — a border line has
          no corner to round; a floating panel does. */}
      <div className="flex min-h-0 flex-1 gap-1.5 p-1.5 sm:gap-2.5 sm:p-2.5">
      <Sidebar />
      {/* overscroll-x-contain is the backstop for the chart's horizontal pan:
          on macOS an unprevented horizontal wheel is the browser's back
          gesture, so a swipe that the chart does not claim would navigate away
          from the board instead of doing nothing. */}
      <main className="min-h-0 flex-1 overflow-y-auto overscroll-x-contain">
        {/* Full height so a page that fills the viewport (the chart
            workspace) can; the boards are taller than it and scroll. */}
        <div className="h-full">
          <Suspense fallback={<div className="p-3 text-body text-muted-foreground">loading…</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/markets" replace />} />
              <Route path="/markets" element={<DashboardPage />} />
              <Route path="/sectors" element={<SectorsPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              {/* Compare folded into Portfolio (2026-09-16): same board
                  chips, one page. Old links keep their symbols. */}
              <Route path="/compare" element={<RedirectKeepingQuery to="/portfolio" />} />
              <Route path="/profile" element={<CompanyPage />} />
              {/* The page was /company for a day; the name was wrong for
                  funds, trusts and everything else it covers. */}
              <Route path="/company" element={<RedirectKeepingQuery to="/profile" />} />
              <Route path="/news" element={<NewsPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/earnings" element={<EarningsPage />} />
              <Route path="/calendars" element={<CalendarsPage />} />
              <Route path="/themes/:id" element={<ThemePage />} />
              <Route path="/views/:viewId" element={<CustomViewPage />} />
              <Route path="/options" element={<OptionsPage />} />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/disclaimer" element={<DisclaimerPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/admin" element={<AdminPage />} />
              {/* Old paths, kept as redirects so links and bookmarks still
                  land somewhere. /filings merged into Analysis and
                  carries its ?symbol= across; /research was only ever an ask
                  form. /ai was the in-app agent, removed 2026-09-17 — the
                  catch-all sends it to Markets. */}
              <Route path="/dashboard" element={<Navigate to="/markets" replace />} />
              <Route path="/screener" element={<Navigate to="/news" replace />} />
              <Route path="/chart" element={<ChartPage />} />
              <Route path="/filings" element={<RedirectKeepingQuery to="/analysis" />} />
              <Route path="/trade" element={<RedirectKeepingQuery to="/analysis" />} />
              <Route path="/research" element={<RedirectKeepingQuery to="/analysis" />} />
              <Route path="*" element={<Navigate to="/markets" replace />} />
            </Routes>
          </Suspense>
        </div>
      </main>
      </div>
      {/* The column descriptions on every table's headings. */}
      <HeaderTips />
    </div>
  )
}

/** The hosted-mode gate. One question at boot — does this instance require
 * a login, and do I have one? — then either the terminal or the login
 * screen. An open (self-hosted) instance never shows the gate at all, and
 * a session dying mid-use (the 401 event from lib/api) swaps back to the
 * login screen instead of leaving every panel erroring in place. */
/** Readable before sign-in: what AlphaDesk is, and what you agree to. */
const PUBLIC_PAGES = ["/terms", "/privacy", "/disclaimer", "/about"]

function Gate() {
  const { pathname } = useLocation()
  const [state, setState] = useState<"checking" | "open" | "login" | "subscribe">("checking")
  const [email, setEmail] = useState<string | null>(null)
  const [access, setAccess] = useState<Access | null>(null)
  const [providers, setProviders] = useState<{ id: string; label: string }[]>([])

  const check = useCallback(() => {
    api.authMe()
      .then(me => {
        // A reader who left an agent app's consent page to sign in goes
        // back to it (the server only ever names that page, once).
        if (me.user && me.next?.startsWith("/oauth/consent?")) {
          window.location.assign(me.next)
          return
        }
        setEmail(me.user?.email ?? null)
        setProviders(me.providers ?? [])
        setAccess(me.user?.access ?? null)
        // The access gate (alphadesk/billing.py): only when it is ON and this
        // account's trial has ended with no subscription.
        const stopped = !!me.user?.access?.enforced && me.user.access.state === "expired"
        setState(!me.auth_required || me.user ? (stopped ? "subscribe" : "open") : "login")
      })
      .catch(() => setState("open"))   // an unreachable check must not lock out a dev server
  }, [])

  useEffect(() => { check() }, [check])
  useEffect(() => {
    const onExpired = () => setState("login")
    window.addEventListener("alphadesk:unauthorized", onExpired)
    // A trial that ends mid-session: the next data request answers 402, and
    // a fresh check shows the subscribe screen.
    window.addEventListener("alphadesk:payment-required", check)
    return () => {
      window.removeEventListener("alphadesk:unauthorized", onExpired)
      window.removeEventListener("alphadesk:payment-required", check)
    }
  }, [check])

  if (state === "checking") return null
  // The landing page is the ROOT for everyone, and /welcome too (2026-09-18,
  // the owner's call): signed out it signs you in, signed in it leads into
  // the app. The app starts at /markets, where a sign-in lands.
  if (pathname === "/" || pathname === "/welcome") {
    return <LandingPage providers={providers} signedIn={!!email}
                        onPasswordSignIn={state === "login" && !providers.length ? check : undefined} />
  }
  // Public pages: what the thing is, and what you agree to, are readable
  // before there is an account to read them with.
  if ((state === "login" || state === "subscribe") && PUBLIC_PAGES.includes(pathname)) {
    return (
      <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
        <Suspense fallback={null}>
          {pathname === "/about" ? <AboutPage />
            : pathname === "/privacy" ? <PrivacyPage />
            : pathname === "/disclaimer" ? <DisclaimerPage />
            : <TermsPage />}
        </Suspense>
      </div>
    )
  }
  // Signed out: the landing page IS the sign-in — provider buttons on an
  // SSO instance (they create the account), the password form without one.
  if (state === "login") {
    return <LandingPage providers={providers} onPasswordSignIn={providers.length ? undefined : check} />
  }
  if (state === "subscribe") return <SubscribePage email={email} access={access} onRecheck={check} />
  return <Shell userEmail={email} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Gate />
    </BrowserRouter>
  )
}
