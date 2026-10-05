import { useMemo, useState } from "react"
import { Empty, Widget } from "@/components/terminal"
import { FilingsReader } from "@/components/FilingsReader"
import { QueryFailure } from "@/components/KeyPrompt"
import { useFilingFeed } from "@/lib/queries"
import { shortItem } from "@/lib/filingItem"

/** THE OFFICIAL RECORD, ON ITS OWN PAGE (2026-09-29, the owner: "separating
 * news and filings away from news tab into a new tab … the official ones").
 *
 * WHY THEY WERE IN NEWS AT ALL, and why that still holds: a company must file
 * within four business days and is NEVER obliged to publicise, so an auditor
 * resignation or a delisting notice reaches no newswire. Measured 2026-09-28:
 * 188 material events in one week — 136 officer departures, 17 auditor
 * changes, 17 delisting notices, 5 restatements — with Churchill Downs (~$6B)
 * and Getty Realty (~$1.5B) each filing a material 8-K that no story covered.
 *
 * WHY THEY ARE NOT IN NEWS ANY MORE: as scopes they REPLACED the story list
 * with this component, and the News toolbar is built for stories — four of its
 * controls were switched off under a filings scope and the filter box was not,
 * so it sat there filtering nothing. That is two pages sharing one shell, with
 * a control that lied on one of them.
 *
 * THE ITEM PICKER REPLACES THE OLD "Earnings" SCOPE and generalises it. That
 * scope was item 2.02 alone, hard-coded; every item the window holds is
 * offered here with its count, so a reader hunting a delisting notice is not
 * worse served than one hunting results. The wording is EDGAR's own and the
 * order is the SEC's — the registrant picks these from a fixed list under
 * signature, so naming them is a record, and which one matters is the
 * reader's call, never a ranking (invariant 3).
 */
export default function FilingsPage() {
  const [item, setItem] = useState("")
  const q = useFilingFeed()
  const filings = useMemo(() => q.data?.filings ?? [], [q.data])
  // Narrowed by the picked item; the reader shows these in the SEC's own order.
  const rows = useMemo(
    () => (item ? filings.filter(f => (f.items ?? []).some(i => i.number === item)) : filings),
    [filings, item])

  // ONLY THE ITEMS THE WINDOW HOLDS, with counts — offering an item with
  // nothing behind it is the same fault as a key prompt for a vendor the
  // reader already has. Sorted by the SEC's own numbering, which is an
  // ordering of the list rather than a judgment of what matters.
  const items = useMemo(() => {
    const n = new Map<string, { label: string; count: number }>()
    for (const f of filings) {
      for (const i of f.items ?? []) {
        const at = n.get(i.number)
        if (at) at.count += 1
        else n.set(i.number, { label: i.label, count: 1 })
      }
    }
    return [...n.entries()].sort((a, b) =>
      a[0].localeCompare(b[0], undefined, { numeric: true }))
  }, [filings])

  return (
    <>
      {/* THE PAGE SAYS WHICH PAGE IT IS (2026-09-29, the owner: "include
          heading in filings and posts too"). Every composed board carries one
          above its tiles; these two are single panels on no board, so they
          had none and read as a panel floating with no context. Same type and
          inset as the board heading, without the Customize control — there is
          no board here to compose. */}
      <div className="px-4 pt-2">
        <h1 className="mb-2 text-emph font-extrabold tracking-tight">Filings</h1>
      </div>
      {/* THE PANEL SITS IN THE SAME FRAME AS EVERY OTHER PAGE'S TILES
          (2026-09-29, the owner: "the gap between left sidebar and tiles is
          not maintained in filings and posts"). These two are single panels
          on no board, so they never got the board's 16px inset: the HEADING
          was inset by its own padding and the panel was not, leaving it flush
          against the rail and the window edge while every board page stood
          16px clear. Measured: 10px against 26px on both sides.
          The board's own wrapper, rather than a matching pair of paddings —
          a second way of expressing the same inset is a second thing to keep
          in step, and this is the page that proves it does not stay in step
          on its own. */}
      <div className="collage !pt-0">
    <Widget
      span={12}
      title="Market filings"
      subtitle="what companies just filed with the SEC — most of it never reaches a newswire"
      // A fixed box the reader's two panes scroll inside (2026-10-05): the list and
      // the filing each scroll on their own, so neither carries the other away.
      scroll="calc(100vh - 230px)"
      // OUTSIDE THE SCROLLER, like the News toolbar beside it: a control that
      // names what the list shows must not scroll away with the rows it
      // labels. It wraps rather than scrolling sideways, which is the rule for
      // any toolbar that can hold a drop-down (#77).
      toolbarWraps
      toolbar={items.length > 0 ? (
        <>
          <select
            value={item}
            onChange={e => setItem(e.target.value)}
            aria-label="Item"
            title="The event the registrant declared, in the SEC's own words — picked from its fixed list and filed under signature"
            className="h-[28px] border border-border bg-panel px-1.5 text-caption text-foreground"
          >
            <option value="">All items</option>
            {items.map(([number, { label, count }]) => (
              <option key={number} value={number}>{`${shortItem(label)} · ${count}`}</option>
            ))}
          </select>
          <span className="tnum ml-auto text-caption text-muted-foreground">
            {item
              ? `${items.find(([n]) => n === item)?.[1].count ?? 0} / ${filings.length}`
              : `${filings.length} filings`}
          </span>
        </>
      ) : undefined}
    >
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the market's filings are unavailable right now</QueryFailure>
        : <FilingsReader rows={rows} unavailable={q.data?.unavailable} groups={q.data?.groups}
                         unlistedHidden={q.data?.unlisted_hidden ?? 0} filtered={!!item} />}
    </Widget>
      </div>
    </>
  )
}
