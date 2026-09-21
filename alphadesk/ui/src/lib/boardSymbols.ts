import { useCallback, useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"
import { byRecency } from "@/lib/boardOrder"
import { whichWins } from "@/lib/boardSync"
import { normalize } from "@/lib/symbols"

/** The strip, mirrored to browser storage so it survives navigation.
 *
 * The URL stays the source of truth — a shared link restores exactly the
 * board it names — but the header tabs and the nav rail navigate WITHOUT a
 * query, and a strip that empties every time you switch views is a tab bar
 * that forgets its tabs. So: whatever the URL says is written here, and a
 * navigation that arrives with no board at all is refilled from it.
 *
 * The board is never empty. When neither the URL nor storage names anything —
 * a first visit, or the last chip just closed — it falls back to the default
 * symbol, so every tile renders data instead of a "pick a symbol"
 * placeholder. A consequence worth stating: closing the last chip returns
 * the board to the default rather than to a blank state, which makes the
 * default chip effectively un-closable when it is alone. That is the deal
 * a default implies — and the strip renders it honestly by omitting the
 * close button on a one-chip board. The placeholder states in the tiles
 * survive only as fallbacks for a render frame before the seed lands.
 */
const KEY = "alphadesk.board"

/** What a fresh board shows. One symbol, not a curated list: the default is
 * a starting point, not a recommendation. */
export const DEFAULT_SYMBOL = "NVDA"

type StoredBoard = { symbols: string[]; active: string; seen?: string[]; at?: string }

/** The symbols most recently SCOPED TO, newest first — what orders the strip
 * (2026-09-20, the owner: "show the most recent viewed stocks on left most
 * side"). Held here rather than in the URL: it is how this reader has been
 * working, not part of the board a link describes, and writing it into
 * `?symbols=` would reshuffle a shared link every time someone clicked a
 * chip. Every change to it arrives with a change to the active symbol, so
 * the strip re-renders without this needing to be React state. */
let seen: string[] = []

function noteSeen(symbol: string) {
  const sym = normalize(symbol)
  if (!sym) return
  seen = [sym, ...seen.filter(s => s !== sym)].slice(0, 50)
}

function readStored(): StoredBoard | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredBoard
    const symbols = (parsed.symbols ?? []).map(normalize).filter(Boolean)
    const order = (parsed.seen ?? []).map(normalize).filter(Boolean)
    if (order.length && !seen.length) seen = order
    return { symbols, active: normalize(parsed.active || ""), seen: order }
  } catch {
    return null
  }
}

function writeStored(board: StoredBoard) {
  try { localStorage.setItem(KEY, JSON.stringify({ ...board, seen })) } catch { /* private mode */ }
  mirrorToAccount(board)
}


/** The board, mirrored to the reader's account a moment after it settles,
 * so their own agent can see which names they follow (the my_board MCP
 * tool, 2026-09-17). Several hooks write the same board on one mount, so
 * writes are debounced and an unchanged board is not sent again. A failed
 * write (signed out, offline) is simply retried on the next change. */
let mirrorTimer: ReturnType<typeof setTimeout> | null = null
let mirrored = ""
function mirrorToAccount(board: StoredBoard) {
  // NOT BEFORE THE ACCOUNT HAS BEEN ASKED (2026-09-21). This runs on every
  // load, not only on a change — so a device that merely opened the page
  // would stamp its own stale board as the newest and win, and the two
  // devices would push their old boards at each other forever.
  if (!boardSynced) return
  const body = JSON.stringify(board)
  if (body === mirrored) return
  if (mirrorTimer) clearTimeout(mirrorTimer)
  mirrorTimer = setTimeout(() => {
    mirrorTimer = null
    void import("@/lib/api")
      .then(({ api }) => api.saveBoard(board.symbols, board.active))
      .then(() => { mirrored = body })
      .catch(() => { /* retried on the next change */ })
  }, 1500)
}

/** THE STRIP FOLLOWS THE ACCOUNT TOO (2026-09-21). It was already written
 * to the account on every change — for the reader's own agent to read
 * through the my_board tool — but never read back, so the names a reader
 * put on the board in one browser were absent in the next.
 *
 * The DEFAULT is still seeded at once, and the account's board replaces it a
 * moment later if there is one. The other way round — waiting for the answer
 * before seeding anything — leaves every tile on its "pick a symbol"
 * placeholder for the length of a round trip, which is worse than a default
 * that is briefly wrong. The replacement is abandoned if the reader has
 * touched the strip meanwhile: what is on screen was chosen by a person and
 * outranks an answer to a question asked before they did. */
/** True once this session has compared its board with the account's. */
let boardSynced = false
let accountBoard: Promise<{ board: StoredBoard; at: string } | null> | null = null

function fetchAccountBoard(): Promise<{ board: StoredBoard; at: string } | null> {
  const pending = accountBoard ?? (accountBoard = import("@/lib/api")
    .then(({ api }) => api.getBoard())
    .then(b => {
      const symbols = (b.symbols ?? []).map(normalize).filter(Boolean)
      return symbols.length
        ? { board: { symbols, active: normalize(b.active || "") || symbols[0] }, at: b.updated_at || "" }
        : null
    })
    .catch(() => null))
  return pending
}

/** The symbol strip above the Markets board.
 *
 * Two params, one invariant. `?symbols=` is the strip, in the order you added
 * them; `?symbol=` is the one that is ACTIVE, and the active symbol is the
 * only one the board renders — chart, equity overview and the AI rail all
 * follow it. The strip is a tab bar, not a multi-chart layout: a second chip
 * is a second thing you can switch to, not a second chart drawn at once.
 *
 * Keeping the active symbol in `?symbol=` rather than as "whichever is first
 * in `?symbols=`" is what lets every existing link keep working untouched. A
 * movers row and an earnings row both link with `?symbol=NVDA` alone, and that
 * arrives here as a one-chip strip with NVDA active — no redirect, no
 * migration.
 *
 * THE ACTIVE CHIP RENDERS FIRST. The strip used to hold insertion order on the
 * grounds that a chip which moves when you click it can move out from under a
 * second click — a real hazard, and the reason it was built the other way. It
 * is ordered active-first now because the one chip that scopes the entire
 * board should not be somewhere in the middle of the row, and reading it at a
 * glance matters more often than double-clicking a chip does. The underlying
 * `?symbols=` order is untouched, so the ordering is presentation only and a
 * shared link still restores the same strip.
 *
 * URL state first, storage second: `?symbol=` is already how the pages and
 * the agent panel talk to each other, and a board you can send someone is
 * worth more than one that only restores itself. The storage mirror above
 * exists for the one case the URL cannot cover — chrome navigation that
 * carries no query — and it never overrides a URL that names a board.
 */
export function useBoardSymbols() {
  const [params, setParams] = useSearchParams()

  const active = normalize(params.get("symbol") || "")
  const raw = params.get("symbols") || ""

  // Memoized on the two raw param strings, not rebuilt per render: every
  // callback below closes over this array, and a fresh identity each render
  // would make all of them new too — which re-renders the search popover and
  // every chip on any unrelated param change.
  const symbols = useMemo(() => {
    const listed = raw.split(",").map(normalize).filter(Boolean)
    // An inbound link carrying only `?symbol=` is a strip of one. Deduplicated,
    // because the same ticker twice would render two chips that activate the
    // same board — indistinguishable, and one of them un-closable in practice.
    return [...new Set(active && !listed.includes(active) ? [active, ...listed] : listed)]
  }, [raw, active])

  const commit = useCallback((next: string[], nextActive: string) => {
    // Whatever the board is scoped to now is the most recently viewed.
    noteSeen(nextActive)
    const p = new URLSearchParams(params)
    if (next.length) p.set("symbols", next.join(","))
    else p.delete("symbols")
    if (nextActive) p.set("symbol", nextActive)
    else p.delete("symbol")
    // A filing chosen for the previous company must not survive a switch to a
    // different one — but closing some other chip is not a switch, so the
    // selection only clears when the ACTIVE symbol actually changes.
    if (nextActive !== normalize(params.get("symbol") || "")) p.delete("accession")
    // Every gesture is persisted. An emptied board is written as empty here
    // and re-seeded with the default by the effect below — the board is
    // never blank.
    // Stamped, because THIS is an arrangement a person made — the passive
    // writes below are not, and a stamp on those would make merely opening
    // the page outrank a board someone built on another device.
    writeStored({ symbols: next, active: nextActive, at: new Date().toISOString() })
    setParams(p, { replace: true })
  }, [params, setParams])

  /** Mirror, restore, and seed. When the URL carries a board, storage follows
   * it — this is what catches an inbound `?symbol=` link that never went
   * through a gesture. When the URL carries none (the header tabs and the
   * rail navigate bare), the stored board is put back — and when storage has
   * nothing either, the default symbol is seeded so the board is never blank.
   * Several components run this hook at once; the writes are idempotent and
   * the restore is a no-op after the first one lands. */
  useEffect(() => {
    if (symbols.length) {
      // An inbound link is a view too: arriving at ?symbol= counts, so a
      // symbol opened from a movers row leads the strip on the next screen.
      noteSeen(active)
      writeStored({ symbols, active })
      return
    }
    const stored = readStored()
    const board = stored?.symbols.length
      ? stored
      : { symbols: [DEFAULT_SYMBOL], active: DEFAULT_SYMBOL }
    // Functional, for the same reason boardLayout's restore is: the layout
    // hook writes ?tiles= on the same mount, and snapshot-based writers
    // erase each other's parameter.
    setParams(prev => {
      const p = new URLSearchParams(prev)
      p.set("symbols", board.symbols.join(","))
      if (board.active && board.symbols.includes(board.active)) p.set("symbol", board.active)
      return p
    }, { replace: true })
    // THE LATER BOARD WINS. Asked whatever this browser holds, not only
    // when it holds nothing: two devices that have both been used each kept
    // their own strip forever otherwise, which is the fault this was
    // supposed to fix. A local board with no stamp predates this and loses
    // to a row on the account, which is an arrangement somebody saved.
    const seeded = board.symbols.join(",")
    let dropped = false
    void fetchAccountBoard().then(mine => {
      boardSynced = true
      if (dropped || !mine) return
      const theirs = mine.board.symbols.join(",")
      if (whichWins({ tiles: stored?.symbols.join(",") || "", at: stored?.at },
                    { tiles: theirs, at: mine.at }) !== "adopt") return
      setParams(prev => {
        const p = new URLSearchParams(prev)
        if ((p.get("symbols") || "") !== seeded) return prev      // the reader moved first
        p.set("symbols", theirs)
        if (mine.board.active) p.set("symbol", mine.board.active)
        return p
      }, { replace: true })
      writeStored({ ...mine.board, at: mine.at })
    })
    return () => { dropped = true }
    // Keyed on PARAMS, not the derived board, and that is load-bearing: two
    // hooks restore into the URL on the same mount (this one and the board
    // layout's), the router batches same-tick navigations, and the swallowed
    // writer's own derived value never changes — so it would never retry.
    // Re-running on every params change retries the restore against the
    // now-current URL; once the key is present the effect only mirrors, so
    // it terminates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  /** Add a symbol to the strip and make it active. Adding one already on the
   * strip just activates it — a second identical chip is never what was
   * meant. */
  const add = useCallback((raw: string) => {
    const sym = normalize(raw)
    if (!sym) return
    commit(symbols.includes(sym) ? symbols : [...symbols, sym], sym)
  }, [symbols, commit])

  const activate = useCallback((raw: string) => {
    const sym = normalize(raw)
    if (sym && symbols.includes(sym)) commit(symbols, sym)
  }, [symbols, commit])

  /** Close a chip. Closing the ACTIVE one hands the board to its neighbour on
   * the right, or the left when it was last — what closing a browser tab
   * does. Closing the last chip leaves the board with no symbol at all, which
   * is a real state: the tiles fall back to their "pick a symbol" placeholders
   * rather than the strip refusing to empty. */
  const remove = useCallback((raw: string) => {
    const sym = normalize(raw)
    const i = symbols.indexOf(sym)
    if (i < 0) return
    const next = symbols.filter(s => s !== sym)
    commit(next, sym === active ? (next[i] ?? next[i - 1] ?? "") : active)
  }, [symbols, active, commit])

  /** Clear the whole board in one gesture (2026-09-17, the owner's call:
   * closing chips one at a time was the only way, and the last chip has no
   * close button). The board is never empty, so clearing returns it to the
   * default symbol rather than to a blank strip — same end state as a first
   * visit. A board already showing just the default is left alone. */
  const clear = useCallback(() => {
    if (symbols.length === 1 && symbols[0] === DEFAULT_SYMBOL) return
    commit([DEFAULT_SYMBOL], DEFAULT_SYMBOL)
  }, [symbols, commit])

  /** The strip AS RENDERED: MOST RECENTLY VIEWED FIRST (2026-09-20), which
   * puts the active chip at the left because scoping the board to it is the
   * most recent view there is. Symbols this browser has never opened — a
   * shared link's — keep the link's own order behind them. Separate from
   * `symbols` on purpose: add/activate/remove all reason about the real
   * order, and only the tab bar reads this one, so `?symbols=` still
   * restores a link exactly as it was sent.
   *
   * It used to be insertion order behind the active chip. The hazard that
   * argued for that — a chip which moves when clicked can move out from
   * under a second click — is unchanged, and is the reason this is worth
   * knowing about rather than assuming. The owner asked for recency anyway:
   * the names you are working between should be the ones nearest the left,
   * not the ones you happened to add first. */
  const ordered = useMemo(
    () => {
      const by = byRecency(symbols, seen)
      return active && symbols.includes(active)
        ? [active, ...by.filter(s => s !== active)]
        : by
    },
    [symbols, active],
  )

  return { symbols, ordered, active, add, activate, remove, clear }
}


/* A picked row does NOT scroll the page to the chart (2026-09-19, the
 * owner: "remove the scroll up that happens in markets when we pick
 * anything"). The chart used to be brought into view so a scope change was
 * seen; it jumped the reader away from the list they were working down. */
