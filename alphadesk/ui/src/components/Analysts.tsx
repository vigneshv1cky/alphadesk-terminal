import { useQuery } from "@tanstack/react-query"
import { KeyPrompt, QueryFailure } from "@/components/KeyPrompt"
import { api } from "@/lib/api"
import { compact } from "@/components/Treemap"
import { Empty, Table, TD, TH, THead, Widget } from "@/components/terminal"
import { vendorLabel } from "@/lib/vendors"

/** The sell side on ONE symbol — two panels any page can place (the Analysis
 * page carries them by default):
 *
 *   Analyst view — the target range drawn as a bar with the current price on
 *   it, the consensus rating with the analyst count, the rating distribution
 *   for the last four months, and the short-interest report.
 *   Rating changes — the recent upgrades, downgrades, initiations and
 *   reiterations, each with the firm's target move.
 *
 * Nothing here scores the analysts: the record is shown as it was made. */

const dash = "—"
const money = (v: number | null | undefined) => (v == null ? dash : v.toFixed(2))

export function useAnalysts(symbol: string) {
  return useQuery({
    queryKey: ["analysts", symbol],
    queryFn: () => api.analysts(symbol),
    enabled: !!symbol,
    staleTime: 60 * 60_000,
    retry: false,
  })
}

type PanelProps = { symbol: string; span?: number; scroll?: number | string }

type Dist = { strong_buy: number; buy: number; hold: number; sell: number; strong_sell: number }

/** The five ratings as one stacked bar, strong buy on the left, with every
 * segment's count printed inside it — the bar reads as "1 buy · 15 hold ·
 * 3 sell" without a hover. Widths follow the counts, but a rating anyone
 * holds keeps at least room for its number: NVDA's one sell among 69 was a
 * 1.4% sliver with no figure, so the row seemed to total 68 (2026-09-15).
 * Hovering a segment names the rating, its count and its share. */
function RatingBar({ d, when }: { d: Dist; when: string }) {
  const total = d.strong_buy + d.buy + d.hold + d.sell + d.strong_sell
  if (!total) return <span className="text-muted-foreground">{dash}</span>
  const parts: [number, string, string, string][] = [
    [d.strong_buy, "bg-gain text-white", "Strong buy", "SB"], [d.buy, "bg-gain/60 text-white", "Buy", "B"],
    [d.hold, "bg-muted-foreground/40 text-foreground", "Hold", "H"],
    [d.sell, "bg-loss/60 text-white", "Sell", "S"], [d.strong_sell, "bg-loss text-white", "Strong sell", "SS"],
  ]
  return (
    <div className="flex h-[16px] w-full overflow-hidden rounded-[3px] bg-muted/40">
      {parts.map(([n, cls, l]) => n > 0 ? (
        <div key={l} className={`flex min-w-[18px] items-center justify-center overflow-hidden text-label font-semibold leading-none tnum ${cls}`}
             style={{ flex: `${n} 1 0` }}
             data-tip={`${l} ${when}: ${n} of ${total} analyst${total === 1 ? "" : "s"} (${((n / total) * 100).toFixed(1)}%)`}>
          {n}
        </div>
      ) : null)}
    </div>
  )
}

/** The low–high target range as a bar with its end values on it, the
 * current price marked in black and the mean target in red, each with its
 * value printed beside the mark so the picture reads without a hover. */
function TargetRange({ t }: { t: { current: number | null; low: number | null; mean: number | null; median: number | null; high: number | null } }) {
  if (t.low == null || t.high == null || t.high <= t.low) return null
  const lo = Math.min(t.low, t.current ?? t.low)
  const hi = Math.max(t.high, t.current ?? t.high)
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100
  const x = (v: number) => `${pct(v)}%`
  // A label sits to the right of its mark, or to the left near the end.
  const label = (v: number, text: string, cls: string, top: string) => {
    const p = pct(v)
    const right = p > 78
    return (
      <span className={`absolute whitespace-nowrap text-label leading-none tnum ${cls}`}
            style={{ top, left: right ? undefined : `calc(${x(v)} + 5px)`, right: right ? `calc(${100 - p}% + 5px)` : undefined }}>
        {text}
      </span>
    )
  }
  const marksClose = t.mean != null && t.current != null && Math.abs(pct(t.mean) - pct(t.current)) < 14
  return (
    <div className="relative my-1 h-[54px]">
      <div className="absolute top-[24px] h-[4px] rounded-[2px] bg-accent-700/40" style={{ left: x(t.low), width: `calc(${x(t.high)} - ${x(t.low)})` }}
           data-tip={`Every target on file runs from ${money(t.low)} to ${money(t.high)}`} />
      <span className="absolute top-[32px] text-label leading-none text-muted-foreground tnum" style={{ left: x(t.low) }}>low {money(t.low)}</span>
      <span className="absolute top-[32px] text-label leading-none text-muted-foreground tnum" style={{ right: `calc(${100 - pct(t.high)}%)` }}>high {money(t.high)}</span>
      {/* The median sits with the mean: on a range a few high targets
          stretch, the two are dollars apart and only the mean was marked. */}
      {t.median != null && <div className="absolute top-[22px] h-[8px] w-[2px] bg-accent-700/50"
                                style={{ left: x(t.median) }}
                                data-tip={`Median target ${money(t.median)} — half the targets sit either side`} />}
      {t.current != null && <div className="absolute top-[18px] h-[16px] w-[2px] bg-foreground" style={{ left: x(t.current) }}
                                 data-tip={`The last price, ${money(t.current)}`} />}
      {t.current != null && label(t.current, `price ${money(t.current)}`, "text-foreground font-medium", "6px")}
      {t.mean != null && <div className="absolute top-[20px] h-[12px] w-[2px] bg-accent-700" style={{ left: x(t.mean) }}
                               data-tip={`Mean of every target on file, ${money(t.mean)}`} />}
      {t.mean != null && label(t.mean, `mean target ${money(t.mean)}`, "text-accent-700 font-medium", marksClose ? "44px" : "6px")}
    </div>
  )
}

export function AnalystPanel({ symbol, span = 5, scroll = 420 }: PanelProps) {
  const q = useAnalysts(symbol)
  const d = q.data
  const t = d?.targets
  const upside = t?.current != null && t.mean != null && t.current > 0 ? ((t.mean / t.current) - 1) * 100 : null
  const si = d?.short_interest
  const siChange = si?.shares_short != null && si.prior_month ? ((si.shares_short / si.prior_month) - 1) * 100 : null
  // Two counts from the record, and they differ: the analysts who publish
  // a price target, and the (usually larger) set who publish a rating. Each
  // sits with the figures it counts, never in the header as one number.
  // Who answered, said once when the sections agree and section by section
  // when they do not. The header used to carry the ratings vendor alone, so
  // FMP's targets read as Finnhub's (2026-09-15).
  const answered = [...new Set(Object.values(d?.sources ?? {}).filter(Boolean) as string[])]
  const oneVendor = answered.length === 1
  const subtitle = !d ? (q.isPending ? "loading…" : "no analyst coverage on record")
    : oneVendor ? `sell-side record · ${vendorLabel(answered[0]) ?? answered[0]}` : "sell-side record"
  const from = (section: "analyst_ratings" | "price_targets" | "short_interest") => {
    const who = oneVendor ? null : vendorLabel(d?.sources?.[section])
    return who ? ` · ${who}` : ""
  }
  const rated = d?.distribution[0]
  const ratedCount = rated ? rated.strong_buy + rated.buy + rated.hold + rated.sell + rated.strong_sell : null
  return (
    <Widget span={span} symbol={symbol} title="Analyst view" subtitle={subtitle} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the analyst record is unavailable right now</QueryFailure>
        : !d ? <Empty>no analyst coverage on record for {symbol}</Empty> : (
        <div className="px-3 py-2 text-body">
          <div className="flex items-baseline justify-between">
            <span className="text-muted-foreground">Consensus{ratedCount ? ` of ${ratedCount} ratings` : ""}
              <span className="text-label">{from("analyst_ratings")}</span></span>
            <span className="font-semibold capitalize">{d.recommendation.key ?? dash}
              {d.recommendation.mean != null && <span className="ml-1.5 font-normal text-muted-foreground tnum">{d.recommendation.mean.toFixed(2)} / 5</span>}
            </span>
          </div>
          <div className="mt-2 text-label uppercase tracking-caps text-muted-foreground">
            Price targets{t?.analysts ? ` · ${t.analysts} analysts publish one`
              : t?.published_month ? ` · ${t.published_month} set in the last month`
              : t?.published_quarter ? ` · ${t.published_quarter} set in the last three months` : ""}
            {from("price_targets")}
          </div>
          {d.needs?.price_targets && t?.mean == null
            ? <div className="-mx-3"><KeyPrompt prompt={d.needs.price_targets} compact /></div>
            : t && <TargetRange t={t} />}
          {!(d.needs?.price_targets && t?.mean == null) && (<>
          <div className="grid grid-cols-4 gap-2 tnum">
            {([["Low", t?.low], ["Mean", t?.mean], ["Median", t?.median], ["High", t?.high]] as [string, number | null | undefined][]).map(([l, v]) => (
              <div key={l}>
                <div className="text-label uppercase tracking-caps text-muted-foreground">{l}</div>
                <div className="font-medium">{money(v)}</div>
              </div>
            ))}
          </div>
          {upside != null && (
            <div className="mt-1.5 text-muted-foreground">
              Mean target is <span className={upside >= 0 ? "text-gain" : "text-loss"}>{upside >= 0 ? "+" : ""}{upside.toFixed(1)}%</span> from {money(t!.current)}
            </div>
          )}
          {/* The consensus counts targets no firm has restated in a year, so
              a stale low stretches the range; this is where the current ones
              sit (2026-09-15). */}
          {t?.recent_mean != null && (
            <div className="text-muted-foreground">
              The {t.published_month ?? t.published_quarter} set in the last {t.recent_window === "quarter" ? "three months" : "month"} average{" "}
              <span className="tnum text-foreground">{money(t.recent_mean)}</span>
              {t.current ? <> · <span className={t.recent_mean >= t.current ? "text-gain" : "text-loss"}>
                {t.recent_mean >= t.current ? "+" : ""}{((t.recent_mean / t.current - 1) * 100).toFixed(1)}%</span> from {money(t.current)}</> : null}
            </div>
          )}
          </>)}
          {d.distribution.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">Ratings{ratedCount ? ` · ${ratedCount} analysts publish one` : ""} · by month{from("analyst_ratings")}</div>
              {d.distribution.slice(0, 6).map(m => (
                <div key={m.period} className="mb-1 flex items-center gap-2">
                  <span className="w-[50px] shrink-0 whitespace-nowrap text-right tnum text-muted-foreground"
                        data-tip={m.as_of ? `The count as your vendor recorded it on ${m.as_of}` : undefined}>{m.period === "0m" ? "now" : `${m.period.replace(/\D/g, "")}m ago`}</span>
                  <RatingBar d={m} when={m.period === "0m" ? "now" : `${m.period.replace(/\D/g, "")} month${m.period.replace(/\D/g, "") === "1" ? "" : "s"} ago`} />
                  <span className="w-[28px] shrink-0 tnum text-muted-foreground">{m.strong_buy + m.buy + m.hold + m.sell + m.strong_sell}</span>
                </div>
              ))}
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-label text-muted-foreground">
                <span><i className="mr-1 inline-block h-[8px] w-[8px] rounded-[2px] bg-gain align-middle" />Strong buy</span>
                <span><i className="mr-1 inline-block h-[8px] w-[8px] rounded-[2px] bg-gain/60 align-middle" />Buy</span>
                <span><i className="mr-1 inline-block h-[8px] w-[8px] rounded-[2px] bg-muted-foreground/40 align-middle" />Hold</span>
                <span><i className="mr-1 inline-block h-[8px] w-[8px] rounded-[2px] bg-loss/60 align-middle" />Sell</span>
                <span><i className="mr-1 inline-block h-[8px] w-[8px] rounded-[2px] bg-loss align-middle" />Strong sell</span>
                <span className="ml-auto">the number is how many analysts</span>
              </div>
            </div>
          )}
          {d.needs?.short_interest && (si?.shares_short == null) && (
            <div className="mt-3">
              <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">Short interest</div>
              <div className="-mx-3"><KeyPrompt prompt={d.needs.short_interest} compact /></div>
            </div>
          )}
          {si && si.shares_short != null && (
            <div className="mt-3">
              <div className="mb-1 text-label uppercase tracking-caps text-muted-foreground">Short interest{si.as_of ? ` · as of ${si.as_of}` : ""}{from("short_interest")}</div>
              <div className="grid grid-cols-3 gap-2 tnum">
                <div><div className="text-label text-muted-foreground">Shares short</div><div className="font-medium">{compact(si.shares_short)}</div></div>
                <div><div className="text-label text-muted-foreground">Of float</div><div className="font-medium">{si.pct_float == null ? dash : `${si.pct_float.toFixed(2)}%`}</div></div>
                <div><div className="text-label text-muted-foreground">Days to cover</div><div className="font-medium">{si.days_to_cover == null ? dash : si.days_to_cover.toFixed(2)}</div></div>
              </div>
              {siChange != null && (
                <div className="mt-1 text-muted-foreground">
                  <span className={siChange <= 0 ? "text-gain" : "text-loss"}>{siChange >= 0 ? "+" : ""}{siChange.toFixed(1)}%</span> from the prior report ({compact(si.prior_month)})
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Widget>
  )
}

const tone = (a: string | null) => a === "upgrade" ? "text-gain" : a === "downgrade" ? "text-loss" : "text-muted-foreground"

export function RatingChangesPanel({ symbol, span = 7, scroll = 420 }: PanelProps) {
  const q = useAnalysts(symbol)
  const rows = q.data?.changes ?? []
  return (
    <Widget span={span} symbol={symbol} title="Rating changes" subtitle={rows.length ? `${rows.length} most recent${q.data?.sources?.rating_changes ? ` · ${vendorLabel(q.data.sources.rating_changes) ?? q.data.sources.rating_changes}` : ""}` : undefined} scroll={scroll}>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the analyst record is unavailable right now</QueryFailure>
        : rows.length === 0 && q.data?.needs?.rating_changes ? <KeyPrompt prompt={q.data.needs.rating_changes} />
        : rows.length === 0 ? <Empty>no rating changes on record for {symbol}</Empty> : (
        <div className="overflow-x-auto"><div className="min-w-[520px]">
        <Table>
          <THead>
            <TH className="w-[92px]" title="The day the firm published the change">Date</TH>
            <TH title="The research firm">Firm</TH>
            <TH className="w-[96px]" title="What the firm did: upgrade, downgrade, initiate coverage, maintain and so on">Action</TH>
            <TH title="The firm's rating, after the previous one when it changed">Rating</TH>
            <TH align="right" className="w-[132px]" title="The firm's price target for the stock, after the previous target when it moved: green raised, red cut">Target</TH>
          </THead>
          <tbody>
            {rows.map((r, i) => {
              const moved = r.target != null && r.prior_target != null && r.target !== r.prior_target
              return (
                <tr key={`${r.date}:${r.firm}:${i}`}>
                  <TD mono className="text-muted-foreground">{r.date ?? dash}</TD>
                  <TD className="font-medium">{r.firm ?? dash}</TD>
                  <TD className={`text-label font-extrabold uppercase ${tone(r.action)}`}>{r.action ?? dash}</TD>
                  <TD>
                    {r.from_grade && r.from_grade !== r.to_grade ? <span className="text-muted-foreground">{r.from_grade} → </span> : null}
                    {r.to_grade ?? dash}
                  </TD>
                  <TD align="right" mono>
                    <span data-tip={r.prior_target != null && r.prior_target_date
                      ? `Its previous target, ${money(r.prior_target)}, was set on ${r.prior_target_date}`
                      : undefined}>
                      {moved ? <span className="text-muted-foreground">{money(r.prior_target)} → </span> : null}
                      <span className={moved ? (r.target! > r.prior_target! ? "text-gain" : "text-loss") : ""}>{money(r.target)}</span>
                    </span>
                  </TD>
                </tr>
              )
            })}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}
