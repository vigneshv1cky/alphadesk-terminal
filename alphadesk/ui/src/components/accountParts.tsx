import { btnCls } from "@/components/terminal"

/** The pieces the Account page and the Agent access page share (2026-10-02):
 * rows, labels, small buttons and status pills, moved out of the Account page
 * so the two pages are built from the same parts and cannot drift apart. */

/** The caption under a panel's table — muted, never bold. One line where the
 * panel is wide enough to hold it; below 520px it wraps rather than ending
 * in an ellipsis, because a clipped sentence is not a caption. */
export function Caption({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-2.5 text-label leading-[1.45] text-muted-foreground @[520px]:truncate">
      {children}
    </div>
  )
}

/** One row of the Account page: a name, what is on file, and the buttons.
 *
 * ONE SHAPE AT EVERY WIDTH (2026-09-17, the owner's call): the name and its
 * buttons take the first line, and what is on file reads beneath the name
 * across the full width. The row was three-across — a fixed 140px name, a
 * flexible note, the buttons — which at ~360px of pane left the note about
 * 30px wide, one word per line with the buttons printed over it, and at
 * full width left a block of empty space under every name while the note
 * wrapped in a narrow middle column. */
export function Row({ label, children, actions }: {
  label: React.ReactNode
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="row-rule grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1.5 px-4 py-3.5">
      <span className="min-w-0 text-body font-extrabold">{label}</span>
      <span className="col-span-2 min-w-0 text-caption leading-[1.45] text-muted-foreground">
        {children}
      </span>
      <span className="col-start-2 row-start-1 flex shrink-0 justify-end gap-1.5">
        {actions}
      </span>
    </div>
  )
}

/* The shared small button, 20px caps (2026-09-18, the owner's call): at 22px
   and 12px a row of Replace / Remove outweighed the vendor name it acts on. */
export const BTN = btnCls({ size: "sm" })
export const BTN_DANGER = btnCls({ variant: "danger", size: "sm" })
/* The way forward on a row (Connect, Add key, Create) differs from Replace
   only in full-strength text: a red outline on every unconnected vendor made
   the table shout at the reader to click (2026-09-18, the owner's call). */
export const BTN_PRIMARY = btnCls({ variant: "strong", size: "sm" })

/* Taller rows for the Account tables only (2026-09-18, the owner's call): a
   row carries a key, a status pill and two buttons, and 30px read cramped.
   A descendant rule, because the shared cell hard-codes its own height and,
   without tailwind-merge, a second height class on it would not reliably
   win; this one outranks it by specificity and touches no other table. */
export const ROOMY = "[&_td]:h-[44px]"

/** A panel title in the accent red (2026-09-18, the owner's call) — the same
 * red the board gives a widget's symbol prefix, so the colour means "a
 * heading" here as it does there. Chrome-grade: accent is tuned to 3:1
 * against the header band, which holds for 13px bold capitals, not prose. */
export const Heading = ({ children }: { children: React.ReactNode }) => <span className="text-accent">{children}</span>

/** A status word in a table cell or a panel header: connected, the plan,
 * how a feed arrives. Tinted, never a filled block, so a column of them
 * reads as a column of facts rather than of buttons. */
export function Pill({ tone, children }: { tone: "gain" | "warn" | "info" | "muted"; children: React.ReactNode }) {
  const cls = {
    gain: "bg-gain-tint text-gain",
    warn: "bg-warn-tint text-warn",
    info: "bg-info-tint text-info",
    muted: "bg-surface text-muted-foreground",
  }[tone]
  return (
    <span className={`inline-flex h-[20px] items-center whitespace-nowrap rounded-xs px-2 text-label font-bold uppercase tracking-caps ${cls}`}>
      {children}
    </span>
  )
}

/** A heading row inside a panel, the section labels the matrix is read by.
 * On the card itself above a hairline (2026-09-18): a grey band under a
 * 40%-ink rule read as a slab across the white card. */
export function SubLabel({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    // Wraps: on a phone the controls beside a label ("Connect a client" and
    // its four client tabs) drop to their own line instead of squeezing the
    // label onto two.
    // justify-between, not a margin: on one line the controls sit right;
    // wrapped onto their own line they start at the left rather than hang
    // off the right edge.
    <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-2 border-b border-row-rule bg-card px-4 pb-2 pt-4">
      <span className="whitespace-nowrap text-label font-bold uppercase tracking-caps text-muted-foreground">{children}</span>
      {right && <span>{right}</span>}
    </div>
  )
}
