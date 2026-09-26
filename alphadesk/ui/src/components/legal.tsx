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

import { Link, useLocation } from "react-router-dom"

export const H = ({ children }: { children: React.ReactNode }) => (
  <h2 className="mb-1.5 mt-6 text-body font-extrabold uppercase tracking-caps">{children}</h2>
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
  <p className="mt-3 rounded-sm border border-warn/60 px-3 py-2 text-caption leading-[1.5] text-warn">
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

export function PublicPage({ title, subtitle, updated, draft, children }: {
  title: string
  /** One line under the title saying what the document is. */
  subtitle?: React.ReactNode
  /** Legal pages date themselves; About does not. */
  updated?: string
  draft?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-page">
      <div className="mx-auto w-full max-w-[820px] px-4 py-6 sm:px-5 sm:py-8">
        <article className="rounded-lg border border-card-border bg-card px-5 py-6 shadow-card sm:px-8 sm:py-8">
          <h1 className="text-display font-extrabold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-caption leading-[1.5] text-muted-foreground">{subtitle}</p>}
          {updated && <p className="mt-1 text-caption text-muted-foreground">Last updated {updated}</p>}
          <Siblings />
          {draft && <Draft />}
          {children}
          <p className="mt-8 border-t border-row-rule pt-3 text-caption leading-[1.5] text-muted-foreground">
            Research, not advice. Nothing here is a recommendation to buy, sell or hold anything.
          </p>
        </article>
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
