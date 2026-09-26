/** THE SHARED LAYOUT OF THE FOUR PUBLIC PAGES — About, Terms, Privacy and
 * the investment disclaimer — so they read as one document set.
 *
 * WHAT WAS WRONG (2026-09-26, the reader: "all of these pages doesnt look
 * good even loggedin, and doesnt have good navigation once entered"):
 *
 * * There were TWO half-layouts. The legal pages carried sibling links in a
 *   footer; About linked only to the Terms. So which page you could reach
 *   depended on which page you were standing on.
 * * The links were plain anchors, so every move between them threw the
 *   whole application away and reloaded it.
 * * The navigation that did exist was at the BOTTOM of a document several
 *   screens long — past the end of what most readers read.
 * * And the page was raw text on the background. Every other panel in this
 *   app is a card on a page ground (#225); these were the only surfaces
 *   that were not, which is most of why they did not look like the product.
 *
 * So: one layout, the document in a card, and the set of four named at the
 * TOP where they can be used. It sits inside Shell when signed in and
 * inside the public shell when signed out, and needs nothing from either.
 */

import { useEffect, useRef, useState } from "react"
import { Link, useLocation } from "react-router-dom"

/** SENTENCE CASE, NOT A CAPS BAND (2026-09-26, the reader: "these pages
 * doesnt look like nextjs pages at all").
 *
 * The headings were WRITTEN in sentence case — "What it is", "1. What we
 * collect" — and then force-uppercased by `uppercase tracking-caps`. That is
 * the one thing this project's own Next.js-style rule forbids: "headings as
 * small grey sentence-case text, never filled uppercase bands" (#283), the
 * same call that was made for the menus and again for the chart's side
 * panels (#304). These four pages never got it.
 *
 * Bigger than the body text too, so a heading reads as a heading rather than
 * as bold prose the same size as everything around it. */
export const H = ({ children }: { children: React.ReactNode }) => (
  <h2 className="mb-2 mt-8 scroll-mt-6 text-emph font-semibold tracking-tight text-foreground">{children}</h2>
)

export const P = ({ children }: { children: React.ReactNode }) => (
  <p className="mb-2.5 text-body leading-[1.65] text-foreground/90">{children}</p>
)

export const L = ({ items }: { items: React.ReactNode[] }) => (
  <ul className="mb-2.5 ml-5 list-disc space-y-1 text-body leading-[1.6] text-foreground/90">
    {items.map((it, i) => <li key={i}>{it}</li>)}
  </ul>
)

/** The DRAFT banner. Every legal page carries it until counsel has reviewed
 * the text and the bracketed placeholders are filled. */
export const Draft = () => (
  // 24px under it, on the 4px grid: the banner had a top margin and no
  // bottom one, so the document's first paragraph sat flush against a
  // bordered box and read as part of it.
  <p className="mb-6 mt-3 rounded-sm border border-warn/60 px-3 py-2 text-caption leading-[1.5] text-warn">
    Draft for legal review. Bracketed items such as [OPERATOR LEGAL NAME] are placeholders to be
    completed before this service accepts payment.
  </p>
)

const PAGES: [string, string][] = [
  ["/about", "About"],
  ["/terms", "Terms of Service"],
  ["/privacy", "Privacy Policy"],
  ["/disclaimer", "Not investment advice"],
]

/** The four, named at the top of every one of them. React Router links, so
 * moving between them does not reload the application. */
function Siblings() {
  const { pathname } = useLocation()
  return (
    <nav aria-label="Public pages"
         className="-mx-1 mb-5 mt-4 flex flex-wrap items-center gap-1 border-b border-row-rule pb-3">
      {PAGES.map(([to, label]) => (
        pathname === to
          ? <span key={to} aria-current="page"
                  className="rounded-xs bg-foreground/10 px-2 py-1 text-caption font-semibold text-foreground">{label}</span>
          : <Link key={to} to={to}
                  className="rounded-xs px-2 py-1 text-caption font-semibold text-muted-foreground no-underline hover:bg-foreground/5 hover:text-foreground">{label}</Link>
      ))}
    </nav>
  )
}

/** ON THIS PAGE — the contents rail a documentation site has and these did
 * not. Built from what actually rendered rather than from a list somebody
 * has to keep in step with the prose: the headings are read out of the
 * article after it mounts, so it cannot drift. Hidden below xl, where there
 * is no room for it beside the text. */
function Contents({ of }: { of: React.RefObject<HTMLElement | null> }) {
  // Keyed on the ROUTE, not on a counter bumped during render: that would
  // make this effect run on every render, set state, and render again.
  const { pathname } = useLocation()
  const [items, setItems] = useState<{ id: string; text: string }[]>([])
  useEffect(() => {
    const el = of.current
    if (!el) return
    const found = [...el.querySelectorAll("h2")].map((h, i) => {
      if (!h.id) h.id = `s${i}-` + (h.textContent || "").toLowerCase()
        .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40)
      return { id: h.id, text: h.textContent || "" }
    })
    setItems(found)
  }, [of, pathname])
  if (items.length < 3) return null
  return (
    <nav aria-label="On this page" className="hidden xl:block">
      <div className="sticky top-8">
        <p className="mb-2 text-label font-semibold uppercase tracking-caps text-muted-foreground">On this page</p>
        <ul className="space-y-0.5 border-l border-row-rule">
          {items.map(it => (
            <li key={it.id}>
              <a href={`#${it.id}`}
                 className="-ml-px block border-l border-transparent py-1 pl-3 text-caption leading-[1.4] text-muted-foreground no-underline hover:border-accent hover:text-foreground">
                {it.text}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  )
}

export function PublicPage({ title, subtitle, updated, draft, children }: {
  title: string
  /** One line under the title saying what the document is. */
  subtitle?: React.ReactNode
  /** Legal pages date themselves; About does not. */
  updated?: string
  draft?: boolean
  children: React.ReactNode
}) {
  const body = useRef<HTMLElement | null>(null)
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-page">
      <div className="mx-auto grid w-full max-w-[1180px] grid-cols-1 gap-8 px-4 py-6 sm:px-6 sm:py-10 xl:grid-cols-[minmax(0,1fr)_200px]">
        <article ref={body}
                 className="min-w-0 rounded-lg border border-card-border bg-card px-5 py-7 shadow-card sm:px-10 sm:py-10">
          {/* A documentation page leads with what it is, then the set it
              belongs to, then the text — not with a row of tabs. */}
          <h1 className="text-display font-extrabold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-2 max-w-[62ch] text-body leading-[1.6] text-muted-foreground">{subtitle}</p>}
          {updated && <p className="mt-2 text-caption text-muted-foreground">Last updated {updated}</p>}
          <Siblings />
          {draft && <Draft />}
          <div className="max-w-[68ch]">{children}</div>
          <p className="mt-10 border-t border-row-rule pt-4 text-caption leading-[1.5] text-muted-foreground">
            Research, not advice. Nothing here is a recommendation to buy, sell or hold anything.
          </p>
        </article>
        <Contents of={body} />
      </div>
    </div>
  )
}

/** Kept for the three legal pages, which date themselves and carry the
 * draft banner. About calls PublicPage directly. */
export function LegalPage({ title, updated, children }: {
  title: string
  updated: string
  children: React.ReactNode
}) {
  return <PublicPage title={title} updated={updated} draft>{children}</PublicPage>
}
