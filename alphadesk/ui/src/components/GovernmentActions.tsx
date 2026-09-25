import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { Empty, TD, TH, THead, TR, Table, Widget } from "@/components/terminal"
import { api, type GovEvent } from "@/lib/api"

/** WHAT THE GOVERNMENT JUST DID, beside the economic calendar (2026-09-23).
 *
 * The economic calendar says when a release is DUE. This says what an agency
 * actually DID: a rule, a proposed rule, an FOMC statement, an auction and
 * the rate it struck. Both are market-wide and neither is about one company,
 * which is what this page is for.
 *
 * Keyless — the Federal Register, the Fed and TreasuryDirect are public
 * government data like EDGAR and the yield curve, so there is no key prompt
 * and nothing is scraped.
 */

/** Where each row came from, for the source column's hover. */
const WHERE: Record<GovEvent["source"], string> = {
  agencies: "Published in the Federal Register — one day's edition, so the decision itself was usually earlier",
  fed: "The Federal Reserve Board's own announcement, at the minute it landed",
  treasury: "A Treasury auction result, from TreasuryDirect",
}

/** THE STAMP IS NOT THE SAME ON EVERY ROW, and the difference decides what a
 * reader may conclude. The Federal Register publishes once a day, so its
 * stamp is a DATE and the ruling was announced at or before it; the Fed's
 * carries a real moment. A date shown as a time would tell a reader a stock
 * moved before its news, when that is only the publication lag. */
function when(e: GovEvent): { text: string; title: string } {
  const at = new Date(e.at)
  if (Number.isNaN(at.getTime())) return { text: "—", title: "" }
  return e.at_precision === "day"
    ? {
      text: at.toLocaleDateString([], { month: "short", day: "numeric" }),
      title: "Published this day. This source publishes once a day, so it happened at or before this — not at a known time",
    }
    : {
      text: `${at.toLocaleDateString([], { month: "short", day: "numeric" })} ${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
      title: at.toLocaleString(),
    }
}

export function GovernmentActionsPanel({ span = 12 }: { span?: number }) {
  const q = useQuery({
    queryKey: ["gov-feed"],
    queryFn: () => api.govFeed(40, 7),
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
    refetchIntervalInBackground: true,
  })
  const events = q.data?.events ?? []
  const off = Object.entries(q.data?.unavailable ?? {})

  return (
    <Widget span={span} title="Government actions"
            subtitle="agency rulemaking, the Fed and Treasury auctions · newest first · no key needed">
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>government actions are unavailable right now</QueryFailure>
        : (
        <>
          {/* A source that could not be read is named. An empty list must
              never be mistaken for a week in which nothing was decided. */}
          {off.length > 0 && (
            <p className="px-3 py-2 text-caption text-muted-foreground">
              {off.map(([name, why]) => `${q.data?.sources[name] ?? name}: ${why}`).join(" · ")}
            </p>
          )}
          {events.length === 0 && off.length === 0 ? (
            <Empty>nothing from these agencies in the last week</Empty>
          ) : (
            <Table>
              <THead>
                <TH className="w-[96px]" title="When, at the precision the source actually states">When</TH>
                <TH className="w-[132px]" title="A rule changes what a company may do; a proposed rule is the consultation before it">Kind</TH>
                <TH title="The record's own title, never a summary written here">What</TH>
                {/* 300px, not 196 (2026-09-25, #75, the reader: "reduce what
                    coloumn width a bit, and increase who"). Every agency name
                    was cut — "Environmental Protection Ag…", "National
                    Highway Traffic Safe…" — while the title column had room
                    to give. An agency's name IS the answer to "who acted",
                    so truncating it costs more than a few characters of a
                    rule's title do. */}
                <TH className="w-[300px]" title="Which agency or body acted">Who</TH>
              </THead>
              <tbody>
                {events.map((e, i) => {
                  const w = when(e)
                  const who = e.agencies?.length
                    ? e.agencies[e.agencies.length - 1]
                    : e.source === "fed" ? "Federal Reserve" : "US Treasury"
                  return (
                    <TR key={`${e.source}-${e.at}-${i}`}>
                      {/* NO "·d" MARKER (2026-09-25, #75, the reader: "what is
                          this d in every row" — which is the whole answer).
                          It meant day-precision, and it was both cryptic and
                          redundant: a row with a real clock SHOWS the clock,
                          so the absence of one already says the source only
                          publishes a date. The explanation stays on hover,
                          where it does not have to be decoded. */}
                      <TD mono className="text-muted-foreground" title={w.title}>{w.text}</TD>
                      <TD className="truncate text-muted-foreground">{e.kind}</TD>
                      <TD className="truncate" title={e.abstract || e.title}>
                        {e.url
                          ? <a href={e.url} target="_blank" rel="noopener noreferrer"
                               className="underline underline-offset-2">{e.title}</a>
                          : e.title}
                        {/* The auction's own figure, where it struck one. */}
                        {e.rate != null && (
                          <span className="num ml-2 text-caption text-muted-foreground">{e.rate.toFixed(3)}%</span>
                        )}
                      </TD>
                      <TD className="truncate text-muted-foreground" title={WHERE[e.source]}>{who}</TD>
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
