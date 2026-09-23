import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { Empty, TD, TH, THead, TR, Table, Widget } from "@/components/terminal"
import { api, type CatalystRow } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { TabStrip } from "@/widgets/market"
import { registerWidget } from "@/widgets/registry"

/** THE CATALYST TAPE (2026-09-22) — what just happened, newest first.
 *
 * Four feeds in one list: SEC filings, exchange halts, government action and
 * social posts. They were endpoints and agent tools only; this is the first
 * time they are on screen.
 *
 * THE TAPE IS NOT RANKED. The order is the clock's, which is why the time
 * column is the widest thing on the row and why a stamp that is only a DATE
 * says so rather than being padded out to look like a moment.
 */

const TABS = [
  { id: "all", label: "All" },
  { id: "filings", label: "Filings" },
  { id: "halts", label: "Halts" },
  { id: "government", label: "Government" },
  { id: "social", label: "Social" },
] as const
type Tab = (typeof TABS)[number]["id"]

/** What each feed is, for the row's source column and its hover. */
const FEED_NOTE: Record<CatalystRow["feed"], string> = {
  filings: "Filed with the SEC — EDGAR's own acceptance time",
  halts: "The exchange stopped the stock, at the time it states",
  government: "A federal agency, the Fed or Treasury",
  social: "A social post: unverified, and nobody is accountable for it",
}

/** Time is the whole point of this tile, so it is shown at the precision the
 * source actually has — never padded out. A date-only stamp is written as a
 * date, because the event usually happened before its publication. */
function when(row: CatalystRow): { text: string; title: string } {
  const at = new Date(row.at)
  if (Number.isNaN(at.getTime())) return { text: "—", title: "" }
  if (row.precision === "day") {
    return {
      text: at.toLocaleDateString([], { month: "short", day: "numeric" }),
      title: "Published this day. The source publishes once a day, so this happened at or before it — not at a known time",
    }
  }
  return {
    text: at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    title: at.toLocaleString(),
  }
}

function CatalystTape() {
  const [tab, setTab] = useState<Tab>("all")
  const { add } = useBoardSymbols()
  const q = useQuery({
    queryKey: ["catalysts"],
    queryFn: () => api.catalysts(80),
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  })
  const rows = useMemo(
    () => (q.data?.rows ?? []).filter(r => tab === "all" || r.feed === tab),
    [q.data, tab],
  )
  const off = q.data?.unavailable ?? {}
  const offNames = Object.keys(off)
  const subtitle = offNames.length
    ? `newest first · ${offNames.join(" and ")} not shown`
    : "newest first · the order is the clock's"

  return (
    <Widget
      // FULL WIDTH, unlike the movers tiles that sit two to a row: four of
      // these five columns are text, and at half a board "What" — the record
      // itself, and the only reason to read the row — measured 150px of 574
      // while the fixed columns took the rest.
      span={12}
      title="Catalysts"
      subtitle={subtitle}
      toolbar={<TabStrip tabs={TABS} value={tab} onChange={setTab} />}
    >
      {q.isPending ? (
        <Empty>loading…</Empty>
      ) : q.isError ? (
        <QueryFailure error={q.error}>the catalyst tape is unavailable right now</QueryFailure>
      ) : (
        <>
          {/* A feed that is off is said to be off. An empty tab must never
              read as a quiet market. */}
          {tab !== "all" && off[tab] && (
            <p className="px-3 py-2 text-caption text-muted-foreground">{off[tab]}</p>
          )}
          {rows.length === 0 && !off[tab] ? (
            <Empty>nothing on this feed in the window</Empty>
          ) : (
            <Table>
              <THead>
                {/* Measured at 1440 on a full-width tile: the fixed columns
                    hold their longest real value — "14:15:28" in mono, a
                    five-character ticker with a "+2" marker, "SCHEDULE
                    13D/A", "Federal Reserve" — and What takes the rest. */}
                <TH className="w-[72px]" title="When it happened, at the precision the source actually states">Time</TH>
                <TH className="w-[92px]" title="The symbols the SOURCE tied to it. A ticker inside a social post is the author's claim and is never read out">Symbol</TH>
                <TH className="w-[124px]" title="What kind of thing happened, in the source's own words">Kind</TH>
                <TH title="The record, as the source states it — never a summary written here">What</TH>
                <TH className="w-[136px]" title="Who published it">Source</TH>
              </THead>
              <tbody>
                {rows.map((r, i) => {
                  const w = when(r)
                  const symbol = r.symbols[0]
                  return (
                    <TR key={`${r.feed}-${r.at}-${i}`}
                        onClick={symbol ? () => add(symbol) : undefined}>
                      <TD mono className="text-muted-foreground" title={w.title}>
                        {w.text}
                        {r.precision === "day" && <span className="ml-1 text-label">·d</span>}
                      </TD>
                      <TD mono className="truncate font-semibold"
                          title={r.symbols.length > 1 ? r.symbols.join(" · ") : undefined}>
                        {symbol ?? "—"}
                        {r.symbols.length > 1 && (
                          <span className="ml-1 font-sans text-label text-muted-foreground">
                            +{r.symbols.length - 1}
                          </span>
                        )}
                      </TD>
                      <TD className="truncate text-muted-foreground">{r.kind}</TD>
                      <TD className="truncate" title={r.trust ? `${r.title} — ${r.trust}` : r.title}>
                        {r.url ? (
                          <a href={r.url} target="_blank" rel="noopener noreferrer"
                             className="underline underline-offset-2"
                             onClick={e => e.stopPropagation()}>
                            {r.title}
                          </a>
                        ) : (
                          r.title
                        )}
                        {/* Said on the row itself, not only on hover: this one
                            is nobody's responsibility. */}
                        {r.trust && (
                          <span className="ml-1.5 text-label text-muted-foreground">unverified</span>
                        )}
                      </TD>
                      <TD className="truncate text-muted-foreground" title={FEED_NOTE[r.feed]}>
                        {r.via ?? r.feed}
                      </TD>
                    </TR>
                  )
                })}
              </tbody>
            </Table>
          )}
        </>
      )}
    </Widget>
  )
}

registerWidget({ id: "catalysts", label: "Catalysts", order: 11, component: CatalystTape })

export default CatalystTape
