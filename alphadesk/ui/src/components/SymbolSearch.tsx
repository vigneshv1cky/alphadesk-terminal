import { useEffect, useRef, useState } from "react"
import { Plus } from "lucide-react"
import { api, type SymbolHit } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { normalize } from "@/lib/symbols"

/** Add a symbol to the board's strip and scope the board to it.
 *
 * Opened from a `+` beside the symbol chips, the way theirs is, rather than
 * sitting in the header as a permanent input — the board is usually already
 * scoped, and a search box you are not using is chrome.
 *
 * Picking APPENDS a chip rather than replacing the one already there, so the
 * board accumulates the names you are working through and switching between
 * them is one click instead of one search. Picking a symbol already on the
 * strip just activates that chip.
 *
 * Results come from the cached Alpaca asset list server-side, so it can only
 * ever offer symbols the terminal will actually render. A free-text box would
 * take a ticker that resolves to nothing and leave every tile blank with no
 * explanation.
 *
 * Empty query shows what is currently most active. Theirs calls that "Trending
 * Tickers"; this is the same idea sourced from data we actually have rather
 * than a curated list we would have to invent.
 */
export function SymbolSearch() {
  const { add } = useBoardSymbols()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState("")
  const [hits, setHits] = useState<SymbolHit[]>([])
  const [trending, setTrending] = useState(true)
  const [active, setActive] = useState(0)
  // The panel is ANCHORED to the + and clamped into the viewport. It used to
  // be absolutely positioned from the button's left edge, so a 420px panel
  // hanging off a + that sits at the right end of a full strip ran past the
  // window and pushed the whole page sideways (2026-09-16). Same rule the
  // symbol-suggest box already used.
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const anchorTo = (r: DOMRect) => ({
    top: r.bottom + 10,
    left: Math.max(8, Math.min(r.left, window.innerWidth - 428)),
  })
  const placeAt = () => {
    const r = box.current?.getBoundingClientRect()
    if (r) setAnchor(anchorTo(r))
  }
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { if (open) input.current?.focus() }, [open])

  // The panel follows its + while anything scrolls or the window resizes, so
  // a fixed panel cannot drift away from the button it belongs to.
  useEffect(() => {
    if (!open) return
    const follow = () => {
      const r = box.current?.getBoundingClientRect()
      if (r) setAnchor(anchorTo(r))
    }
    follow()
    window.addEventListener("scroll", follow, true)
    window.addEventListener("resize", follow)
    return () => {
      window.removeEventListener("scroll", follow, true)
      window.removeEventListener("resize", follow)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    // Debounced: a request per keystroke would be ten for "microsoft", and only
    // the last one's answer is still wanted.
    const id = setTimeout(() => {
      api.search(q)
        .then(d => { setHits(d.results); setTrending(d.trending); setActive(0) })
        .catch(() => setHits([]))
    }, q ? 140 : 0)
    return () => clearTimeout(id)
  }, [q, open])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", away)
    return () => document.removeEventListener("mousedown", away)
  }, [open])

  const pick = (symbol: string) => {
    add(symbol)          // appends a chip and makes it active; see lib/boardSymbols
    setQ("")
    setOpen(false)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, hits.length - 1)) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === "Enter") {
      e.preventDefault()
      // Falls through to the typed text when the list has nothing, so Enter
      // never silently does nothing on a symbol the search does not know.
      if (hits[active]) pick(hits[active].symbol)
      else if (normalize(q)) pick(q)
    }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false) }
  }

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => { placeAt(); setOpen(o => !o) }}
        aria-label="Add a symbol"
        // A bare dashed circle does not say "you can search the whole listed
        // universe from here", and the search behind it covers every symbol
        // the terminal accepts — so the hover says so.
        title="Add a symbol — search any ticker or company"
        aria-expanded={open}
        // 26px explicitly, not h-6 — rem sizes scale off this app's 14px root.
        // Square, like every corner here; the plus is accent because adding a
        // symbol is the strip's one primary action.
        className={`flex h-[28px] w-[28px] shrink-0 items-center justify-center border transition-colors ${
          open ? "border-accent text-accent" : "border-border text-accent hover:bg-foreground/5"
        }`}
      >
        <Plus className="h-[13px] w-[13px]" aria-hidden="true" />
      </button>

      {open && anchor && (
        // Fixed and clamped: on a phone it lands within the 8px gutters like
        // everywhere else, and on a wide screen it stays inside the window
        // however far right the + has been pushed.
        <div data-slot="dialog"
             style={{ top: anchor.top, left: anchor.left }}
             className="pop-in fixed z-50 w-[420px] overflow-hidden border border-card-border bg-card shadow-card max-sm:w-[min(420px,86vw)]">
          <input
            ref={input}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder="Search ticker or company…"
            aria-label="Search ticker or company"
            className="w-full rounded-none border-b border-row-rule bg-transparent px-4 py-3 text-body text-foreground outline-none placeholder:text-muted-foreground"
          />
          {trending && hits.length > 0 && (
            <div className="px-4 pb-1 pt-3 text-label font-medium uppercase tracking-caps text-muted-foreground">Trending tickers</div>
          )}
          <div className="max-h-[320px] overflow-y-auto">
            {hits.length === 0 ? (
              q ? (
                /* A symbol the list does not carry is still offered, in the
                   same shape as any other row rather than as a warning. The
                   list behind this box is the SEC's ticker file — it does not
                   carry a foreign listing without SEC filings, or anything
                   listed since the file was cached, and the reader's own
                   vendor can price several of those. So "not in the
                   list" was never the same claim as "the terminal cannot show
                   it", and saying so in the picker made the search speak for
                   the whole app. It just offers the symbol. */
                <button
                  type="button"
                  onClick={() => pick(q)}
                  className="flex w-full items-baseline justify-between gap-3 rounded-none border-b border-row-rule px-4 py-2 text-left last:border-b-0 bg-row-selected"
                >
                  <span className="text-body font-semibold">
                    {normalize(q) || q.toUpperCase()}
                  </span>
                  <span className="shrink-0 text-caption text-accent-700">Add</span>
                </button>
              ) : (
                <p className="px-4 py-4 text-body text-muted-foreground">
                  Nothing moving right now.
                </p>
              )
            ) : hits.map((h, i) => (
              <button
                key={h.symbol}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(h.symbol)}
                // The full accent fill, by request ("make it red like
                // before") — the selection here shouts on purpose.
                className={`flex w-full flex-col gap-0.5 rounded-none border-b border-row-rule px-4 py-2 text-left last:border-b-0 ${
                  i === active ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                }`}
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="text-body font-extrabold tracking-ticker">
                    {h.symbol}
                  </span>
                  <span className={`text-caption ${i === active ? "opacity-90" : "text-muted-foreground"}`}>
                    {h.asset_class ?? ""}
                  </span>
                </span>
                <span className="flex items-baseline justify-between gap-3">
                  <span className={`truncate text-body ${i === active ? "opacity-90" : "text-muted-foreground"}`}>
                    {h.name ?? ""}
                  </span>
                  <span className={`shrink-0 text-caption ${i === active ? "opacity-90" : "text-muted-foreground"}`}>
                    {h.exchange ?? ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
