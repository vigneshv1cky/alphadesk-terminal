import type { OlderState } from "@/lib/olderNews"
import { Btn } from "@/components/terminal"

/** The foot of any headline list: read further back, or say the reader's
 * stored history has run out. One component so the tile, the panel and the
 * page word it the same way (2026-09-16). */
export function OlderNews({ state, onLoad, onReset, loaded = 0, subject }: {
  state: OlderState
  onLoad: () => void
  /** Drops what was paged in, so the list returns to the live window. */
  onReset?: () => void
  /** How many stories have been paged in; nothing shows the way back at 0. */
  loaded?: number
  /** What ran out, in the reader's words: "stories about this company". */
  subject?: string
}) {
  return (
    <div className="flex items-center justify-center gap-2 border-t border-row-rule px-3 py-2.5 text-caption text-muted-foreground">
      {state === "end"
        ? <span>no older {subject ?? "stories"} in your feeds</span>
        : (
          <Btn variant="ghost" onClick={onLoad} disabled={state === "loading"}>
            {state === "loading" ? "reading further back…"
              : state === "error" ? "Couldn't load — try again"
              : "Load older stories"}
          </Btn>
        )}
      {/* The way back out of a long list: the reader who went digging can
          return the panel to the live window without reloading the page. */}
      {loaded > 0 && onReset && (
        <Btn variant="ghost" onClick={onReset} disabled={state === "loading"}>Show less</Btn>
      )}
    </div>
  )
}
