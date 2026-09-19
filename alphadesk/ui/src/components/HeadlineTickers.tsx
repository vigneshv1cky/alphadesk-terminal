import { useState } from "react"
import { Link } from "react-router-dom"

/** The ticker chips on a story. One article often names several companies —
 * /api/news serves it once with the full list — so the tickers render as
 * chips, first few + an overflow count, each linking to that company's
 * Analysis while the headline itself opens the article or the reader.
 *
 * THE COUNT EXPANDS (2026-09-17). It was a hover title, which says nothing
 * on a touch screen, cannot be clicked through to a company, and on a story
 * naming ten tickers hid six of them behind a tooltip. Now it is a button:
 * the rest of the chips appear in place, and a second press folds them back.
 * The press is stopped from reaching the row so expanding never opens the
 * story underneath. */
export function HeadlineTickers({ symbols, max = 4 }: { symbols: string[]; max?: number }) {
  const [open, setOpen] = useState(false)
  const shown = open ? symbols : symbols.slice(0, max)
  const more = symbols.length - shown.length
  return (
    <>
      {shown.map(s => (
        <Link
          key={s}
          to={`/analysis?symbol=${encodeURIComponent(s)}`}
          onClick={e => e.stopPropagation()}
          className="border border-border px-1 text-label font-semibold leading-[17px] tracking-ticker text-foreground hover:border-accent hover:text-accent-700"
        >
          {s}
        </Link>
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
