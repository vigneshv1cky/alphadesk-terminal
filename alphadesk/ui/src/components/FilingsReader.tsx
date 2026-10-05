import { useMemo, useRef, useState } from "react"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { Empty, btnCls } from "@/components/terminal"
import {
  describeFiling, dayLabel, filingKey, groupByDay, moveSelection, otherTickers, timeLabel,
  type ReaderFiling,
} from "@/lib/filingsReader"
import { cn } from "@/lib/utils"

/** THE FILINGS PAGE AS A READER (2026-10-05, the owner picked option B of four
 * drafts: "Reader"). A list down the left, one filing in full on the right.
 *
 * WHY THIS SHAPE: a filing's own words run long — a single 8-K can declare eight
 * items, and the old row cut them to one truncated line. Here the list stays a
 * scannable column (time, ticker, company, form) and the right pane gives the
 * chosen filing all its room: every declared item with the SEC's number, the
 * tickers, when it was accepted, and the way out to EDGAR.
 *
 * NOTHING IS RANKED OR COLOURED BY IMPORTANCE. The order is the SEC's acceptance
 * time and the items are the registrant's own wording, listed as filed; which
 * one matters is the reader's call (invariant 3). Selection is the one accent. */
export function FilingsReader({ rows, unavailable, groups, unlistedHidden, filtered }: {
  rows: ReaderFiling[]
  unavailable?: Record<string, string>
  groups?: Record<string, string>
  unlistedHidden: number
  /** An item filter is on: the "no ticker" count describes the whole feed, not this list. */
  filtered: boolean
}) {
  const { add } = useBoardSymbols()
  const keys = useMemo(() => rows.map(filingKey), [rows])
  const [picked, setPicked] = useState<string | null>(null)
  const refs = useRef(new Map<string, HTMLButtonElement>())
  // The chosen filing stays chosen across the feed's refreshes (its key does not
  // change); if the filter drops it, the first row stands in.
  const at = picked ? keys.indexOf(picked) : -1
  const idx = at >= 0 ? at : 0
  const sel = rows[idx]
  const off = Object.entries(unavailable ?? {})

  const onKeyDown = (e: React.KeyboardEvent) => {
    const delta = e.key === "ArrowDown" || e.key === "j" ? 1 : e.key === "ArrowUp" || e.key === "k" ? -1 : 0
    if (!delta || e.metaKey || e.ctrlKey || e.altKey) return
    e.preventDefault()
    const next = moveSelection(rows.length, idx, delta)
    if (next < 0) return
    setPicked(keys[next])
    refs.current.get(keys[next])?.focus()            // focus scrolls it into view
  }

  if (rows.length === 0) {
    return (
      <>
        {off.length > 0 && <p className="px-3 py-2 text-caption text-muted-foreground">{off.map(([g, why]) => `${groups?.[g] ?? g}: ${why}`).join(" · ")}</p>}
        <Empty>nothing filed in this window</Empty>
      </>
    )
  }

  const day = groupByDay(rows)
  const info = describeFiling(sel)
  const symbols = sel.symbols ?? []
  const ticker = symbols[0]
  const others = otherTickers(symbols)

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {/* THE LIST */}
      <div className="flex min-h-0 flex-col border-b border-row-rule max-md:max-h-[340px] md:w-[380px] md:shrink-0 md:border-b-0 md:border-r">
        {off.length > 0 && (
          <p className="border-b border-row-rule px-3 py-2 text-caption text-muted-foreground">
            {off.map(([g, why]) => `${groups?.[g] ?? g}: ${why}`).join(" · ")}
          </p>
        )}
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-row-rule bg-surface px-3 text-label font-semibold uppercase tracking-caps text-muted-foreground">
          <span className="w-[64px]">Filed</span><span className="w-[56px]">Ticker</span><span>Company</span>
        </div>
        {/* NO VISIBLE SCROLL BAR on the list (2026-10-05, the owner): it still scrolls with
            the wheel, touch and the arrow keys; only the bar is gone. */}
        <div className="scrollbar-none min-h-0 flex-1 overflow-y-auto" onKeyDown={onKeyDown}>
          {day.map(g => (
            <div key={g.label}>
              <div className="px-3 pb-1 pt-3 text-label font-semibold uppercase tracking-caps text-muted-foreground">{g.label}</div>
              <ul>
                {g.rows.map(f => {
                  const key = filingKey(f)
                  const on = key === keys[idx]
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        ref={el => { if (el) refs.current.set(key, el); else refs.current.delete(key) }}
                        onClick={() => setPicked(key)}
                        aria-current={on ? "true" : undefined}
                        title={`${f.form} — ${f.company}${f.role ? ` (${f.role})` : ""}`}
                        className={cn("flex min-h-[44px] w-full items-center gap-2 border-b border-row-rule px-3 text-left hover:bg-foreground/5", on && "bg-row-selected")}
                      >
                        <span className="num w-[64px] shrink-0 text-caption text-muted-foreground">{timeLabel(f.filed_at)}</span>
                        <span className={cn("w-[56px] shrink-0 truncate text-body font-extrabold tracking-ticker", on && "text-accent-700")}>{f.symbols?.[0] ?? "—"}</span>
                        <span className="min-w-0 flex-1 truncate text-caption">{f.company}</span>
                        <span className="shrink-0 text-label text-muted-foreground">{f.form.replace("SCHEDULE ", "")}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
          {/* ONLY WHEN NOTHING IS FILTERED OUT BY ITEM: this count is the whole
              feed's, and beside a list narrowed to one item it would describe
              rows that are not there (the old list's rule, kept). */}
          {!filtered && unlistedHidden > 0 && (
            <p className="px-3 py-3 text-caption text-muted-foreground">
              {unlistedHidden} more from registrants the SEC lists no ticker for — trusts and agency
              banks, which file constantly and trade nowhere.
            </p>
          )}
        </div>
      </div>

      {/* THE FILING */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-5 overflow-y-auto p-6 max-sm:p-4">
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-display font-extrabold tracking-tight">{ticker ?? "—"}</span>
            <span className="text-emph">{sel.company}</span>
          </div>
          <p className="text-caption text-muted-foreground">
            {sel.form} · filed {dayLabel(sel.filed_at)}, {timeLabel(sel.filed_at)} ET
            {sel.role === "subject" ? " · filed about this company" : ""}
            {others.length > 0 ? ` · also listed as ${others.join(", ")}` : ""}
          </p>
        </div>
        <div>
          <h3 className="pb-2 text-label font-semibold uppercase tracking-caps text-muted-foreground">
            {info.declared ? `What the company declared (${info.lines.length})` : "What this filing is"}
          </h3>
          <ul>
            {info.lines.map((l, i) => (
              <li key={`${l.n}-${i}`} className="flex gap-4 border-t border-row-rule py-3 text-body leading-[20px]">
                <span className="tnum w-10 shrink-0 text-muted-foreground">{l.n}</span>
                <span className="min-w-0">{l.label}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-wrap gap-2">
          {sel.url && (
            <a href={sel.url} target="_blank" rel="noopener noreferrer" className={btnCls({ variant: "accent", size: "lg" })}>
              Open on EDGAR →
            </a>
          )}
          {ticker && (
            <button type="button" onClick={() => add(ticker)} className={btnCls({ variant: "strong", size: "lg" })}>
              Add {ticker} to the board
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
