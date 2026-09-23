import { useState } from "react"
import { useBoardSymbols } from "@/lib/boardSymbols"

/** The ticker chips on a story. One article often names several companies —
 * /api/news serves it once with the full list — so the tickers render as
 * chips, first few + an overflow count, while the headline itself opens the
 * article or the reader.
 *
 * A CHIP SCOPES THE BOARD; IT DOES NOT NAVIGATE (2026-09-23, the reader:
 * "why clicking at a ticker in news goes to analysis? it shouldnt"). Each
 * chip was a link to that company's Analysis page, which is the one thing
 * every other symbol on the terminal does NOT do: a mover, a fund and a
 * holding all ADD the symbol and scope the board in place — the same reason
 * the chart scroll was deleted in #279, that it jumped the reader away from
 * the list they were working down. A news list is exactly that list, and
 * leaving it also lost whatever article was open.
 *
 * THE COUNT EXPANDS (2026-09-17). It was a hover title, which says nothing
 * on a touch screen, cannot be clicked through to a company, and on a story
 * naming ten tickers hid six of them behind a tooltip. Now it is a button:
 * the rest of the chips appear in place, and a second press folds them back.
 * The press is stopped from reaching the row so expanding never opens the
 * story underneath. */
export function HeadlineTickers({ symbols, max = 4 }: { symbols: string[]; max?: number }) {
  const [open, setOpen] = useState(false)
  const { add } = useBoardSymbols()
  const shown = open ? symbols : symbols.slice(0, max)
  const more = symbols.length - shown.length
  const pick = (s: string) => (e: React.SyntheticEvent) => {
    // The press must not reach the row beneath, which would open the story.
    e.stopPropagation()
    e.preventDefault()
    add(s)
  }
  return (
    <>
      {shown.map(s => (
        // A SPAN carrying the button role, for the same reason as the count
        // below: every caller puts these chips inside the row's own button,
        // and a button within a button is invalid nesting.
        <span
          key={s}
          role="button"
          tabIndex={0}
          title={`Put ${s} on the board and scope it`}
          onClick={pick(s)}
          onKeyDown={e => { if (e.key === "Enter" || e.key === " ") pick(s)(e) }}
          className="cursor-pointer select-none border border-border px-1 text-label font-semibold leading-[17px] tracking-ticker text-foreground hover:border-accent hover:text-accent-700"
        >
          {s}
        </span>
      ))}
      {(more > 0 || open) && (
        // A SPAN carrying the button role, not a <button>: every caller puts
        // these chips inside the row's own button, and a button within a
        // button is invalid nesting that React warns about.
        <span
          role="button"
          tabIndex={0}
          aria-expanded={open}
          aria-label={open ? "Show fewer tickers" : `Show ${more} more tickers`}
          onClick={e => { e.stopPropagation(); e.preventDefault(); setOpen(v => !v) }}
          onKeyDown={e => {
            if (e.key !== "Enter" && e.key !== " ") return
            e.stopPropagation(); e.preventDefault(); setOpen(v => !v)
          }}
          className="cursor-pointer select-none text-label font-medium leading-[15px] text-muted-foreground hover:text-foreground"
        >
          {open ? "−" : `+${more}`}
        </span>
      )}
    </>
  )
}
