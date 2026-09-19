import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { api, type SymbolHit } from "@/lib/api"
import { fieldCls } from "@/components/terminal"
import { normalize } from "@/lib/symbols"

/** A symbol input with the strip search's suggestions — trending on focus,
 * typeahead as you type, arrows/Enter to pick — for forms that add symbols
 * (the watchlist, anywhere else a bare ticker box would otherwise sit).
 * Controlled: the caller owns the text, so its own submit button can still
 * act on whatever was typed; picking clears the text and keeps focus, so
 * adding several symbols is one flow.
 */
export function SymbolSuggest({ value, onChange, onPick, placeholder, width = "w-48" }: {
  value: string
  onChange: (v: string) => void
  onPick: (symbol: string) => void
  placeholder: string
  width?: string
}) {
  const [open, setOpen] = useState(false)
  const [hits, setHits] = useState<SymbolHit[]>([])
  const [trending, setTrending] = useState(true)
  const [active, setActive] = useState(0)
  // The panel PORTALS to the document with a fixed position — this input
  // lives inside scrolling tile bodies, and an absolutely positioned child
  // would be clipped at the tile edge (the strip search hit the same wall).
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)

  const openAt = () => {
    const r = input.current?.getBoundingClientRect()
    if (r) setAnchor({ top: r.bottom + 6,
                       left: Math.max(8, Math.min(r.left, window.innerWidth - 408)) })
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    // A fixed panel drifts from its input when anything scrolls — so it
    // FOLLOWS: every scroll or resize re-anchors it to the input's live
    // rect, and only the input actually leaving the viewport closes it.
    // (Closing on any scroll looked simpler and was wrong twice: focusing
    // the input scrolls the tile to reveal it, killing the panel it opened.)
    const follow = () => {
      const r = input.current?.getBoundingClientRect()
      if (!r || r.bottom < 0 || r.top > window.innerHeight) { setOpen(false); return }
      setAnchor({ top: r.bottom + 6,
                  left: Math.max(8, Math.min(r.left, window.innerWidth - 408)) })
    }
    window.addEventListener("scroll", follow, true)
    window.addEventListener("resize", follow)
    return () => {
      window.removeEventListener("scroll", follow, true)
      window.removeEventListener("resize", follow)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    // Debounced, same as the strip search: only the last keystroke's answer
    // is still wanted.
    const id = setTimeout(() => {
      api.search(value)
        .then(d => { setHits(d.results); setTrending(d.trending); setActive(0) })
        .catch(() => setHits([]))
    }, value ? 140 : 0)
    return () => clearTimeout(id)
  }, [value, open])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      const t = e.target as Node
      if (box.current?.contains(t) || panel.current?.contains(t)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", away)
    return () => document.removeEventListener("mousedown", away)
  }, [open])

  const pick = (symbol: string) => {
    onPick(symbol)
    onChange("")
    input.current?.focus()          // several adds are one flow
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (!open) return
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(a + 1, hits.length - 1)) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === "Enter") {
      e.preventDefault()
      // Falls through to the typed text when the list has nothing — Enter
      // never silently does nothing on a symbol the search does not know.
      if (hits[active]) pick(hits[active].symbol)
      else if (normalize(value)) pick(value)
    }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false) }
  }

  return (
    <div ref={box} className="relative">
      <input
        ref={input}
        value={value}
        onChange={e => { onChange(e.target.value); if (!open) openAt() }}
        // Click AND focus both open: a focus that landed before hydration
        // attached this listener leaves the input focused with no panel,
        // and a second focus() is a no-op — the click still lands.
        onClick={() => { if (!open) openAt() }}
        onFocus={openAt}
        onKeyDown={onKey}
        placeholder={placeholder}
        aria-label={placeholder}
        aria-expanded={open}
        className={`${fieldCls} ${width}`}
      />
      {open && anchor && createPortal(
        <div ref={panel} data-slot="dialog" data-symbol-suggest
             style={{ top: anchor.top, left: anchor.left }}
             className="pop-in fixed z-[80] w-[400px] overflow-hidden border border-card-border bg-card shadow-card max-sm:w-[min(400px,86vw)]">
          {trending && hits.length > 0 && (
            <div className="px-3.5 pb-1.5 pt-3 text-label font-medium uppercase tracking-caps text-muted-foreground">
              Trending tickers
            </div>
          )}
          <div className="max-h-[320px] overflow-y-auto">
            {hits.length === 0 ? (
              value ? (
                <button
                  type="button"
                  onClick={() => pick(value)}
                  className="flex w-full items-baseline justify-between gap-3 rounded-none px-3.5 py-2.5 text-left bg-accent text-accent-foreground"
                >
                  <span className="text-body font-semibold">{normalize(value) || value.toUpperCase()}</span>
                  <span className="shrink-0 text-label opacity-90">Add</span>
                </button>
              ) : (
                <p className="px-3.5 py-3.5 text-body text-muted-foreground">Nothing moving right now.</p>
              )
            ) : hits.map((h, i) => (
              <button
                key={h.symbol}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(h.symbol)}
                className={`flex w-full items-baseline gap-3 rounded-none border-b border-row-rule px-3.5 py-2.5 text-left last:border-b-0 ${
                  i === active ? "bg-accent text-accent-foreground" : "hover:bg-muted"
                }`}
              >
                <span className="w-[52px] shrink-0 text-body font-extrabold tracking-ticker">{h.symbol}</span>
                <span className={`min-w-0 flex-1 truncate text-body ${
                  i === active ? "opacity-90" : "text-muted-foreground"}`}>
                  {h.name ?? ""}
                </span>
                <span className={`shrink-0 text-label ${
                  i === active ? "opacity-90" : "text-muted-foreground"}`}>
                  {h.exchange ?? ""}
                </span>
              </button>
            ))}
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
