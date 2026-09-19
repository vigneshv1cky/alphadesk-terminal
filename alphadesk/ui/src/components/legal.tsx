/** The shared layout of the public legal pages — Terms, Privacy and the
 * investment disclaimer — so the three read as one document set. */

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

export function LegalPage({ title, updated, children }: {
  title: string
  updated: string
  children: React.ReactNode
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[720px] px-5 py-8">
        <h1 className="text-display font-extrabold tracking-tight">{title}</h1>
        <p className="mt-1 text-caption text-muted-foreground">Last updated {updated}</p>
        <Draft />
        {children}
        <p className="mt-8 border-t border-row-rule pt-3 text-caption leading-[1.5] text-muted-foreground">
          <a href="/terms" className="underline decoration-dotted hover:text-foreground">Terms of Service</a>
          {" · "}
          <a href="/privacy" className="underline decoration-dotted hover:text-foreground">Privacy Policy</a>
          {" · "}
          <a href="/disclaimer" className="underline decoration-dotted hover:text-foreground">Not investment advice</a>
          {" · "}
          <a href="/about" className="underline decoration-dotted hover:text-foreground">About</a>
        </p>
      </div>
    </div>
  )
}
