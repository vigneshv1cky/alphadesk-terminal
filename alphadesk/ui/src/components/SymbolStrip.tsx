import { SymbolSearch } from "@/components/SymbolSearch"
import { DEFAULT_SYMBOL, useBoardSymbols } from "@/lib/boardSymbols"
import { btnCls } from "@/components/terminal"

/** The symbol strip — the band under the header, on every screen.
 *
 * The symbols on the board render as square chips; the ACTIVE one takes the
 * same 3px accent bottom rule the header tabs use, because it is the same
 * statement: this is what is selected. Only the marked chip scopes the board —
 * chart and overview follow it — so a second chip is a
 * second thing you can switch to, not a second chart drawn at once.
 *
 * There is no command bar. One was designed and cut — it could only scope the
 * board or forward a question, and a permanent bar doing two half-jobs earns
 * less room than a chip strip doing one. Search lives behind the `+`.
 */
export function SymbolStrip() {
  const { ordered, active, activate, remove, clear } = useBoardSymbols()
  // Clearing is offered only when there is something to clear: a board that
  // is already the lone default chip has nothing to do.
  const clearable = ordered.length > 1 || (ordered.length === 1 && ordered[0] !== DEFAULT_SYMBOL)

  return (
    // Only the CHIP ROW scrolls sideways — an overflow on the whole strip
    // would clip the search dropdown, which hangs below the strip from an
    // absolutely positioned panel.
    <div className="flex shrink-0 items-center gap-2 border-b-2 border-border bg-surface px-3 py-2 sm:px-4">
      <span className="mr-1 hidden shrink-0 text-label font-medium uppercase tracking-caps text-muted-foreground sm:inline">
        On the board
      </span>
      <div className="scrollbar-none flex min-w-0 shrink items-center gap-2 overflow-x-auto">
      {ordered.map(symbol => {
        const on = symbol === active
        return (
          <span
            key={symbol}
            className={`inline-flex h-[28px] shrink-0 items-center gap-2 rounded-sm px-2.5 text-caption font-extrabold tracking-caps ${
              on
                ? "border border-transparent border-b-[3px] border-b-accent bg-panel text-foreground"
                : "border border-border text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
            }`}
          >
            <button
              type="button"
              onClick={() => activate(symbol)}
              aria-current={on ? "true" : undefined}
              aria-label={on ? `${symbol}, scoping the board` : `Scope the board to ${symbol}`}
              className="cursor-pointer"
            >
              {symbol}
            </button>
            {ordered.length > 1 && (
              // The last chip has no close button. The board is never empty —
              // closing the final chip would just re-seed the default, so on a
              // one-chip strip the ✕ is a button that visibly does nothing.
              // Withholding it states the rule instead of breaking the promise.
              <button
                type="button"
                onClick={() => remove(symbol)}
                aria-label={`Close ${symbol}`}
                className="text-label text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            )}
          </span>
        )
      })}
      </div>
      <SymbolSearch />
      {clearable && (
        <button
          type="button"
          onClick={clear}
          title={`Clear the board — back to ${DEFAULT_SYMBOL} alone`}
          aria-label="Clear the board"
          className={btnCls({ variant: "danger", size: "lg" }, "ml-1 text-label uppercase tracking-caps")}
        >
          Clear
        </button>
      )}
    </div>
  )
}
