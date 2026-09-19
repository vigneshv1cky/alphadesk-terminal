import { useEffect, useMemo, useState } from "react"
import { useKeptState } from "@/lib/keptState"
import { defaultDay } from "@/lib/earningsDefaultDay"
import { useQueryClient } from "@tanstack/react-query"
import { X } from "lucide-react"
import { api, type EarningsDay, type EarningsFind, type EarningsRow, type EarningsWeek } from "@/lib/api"
import { keys, useEarningsFind, useEarningsWeek } from "@/lib/queries"
import { Empty, btnCls } from "@/components/terminal"
import { QueryFailure } from "@/components/KeyPrompt"
import { ago, etClock, inBackfillWindow, sessionLabel, todayInEt, whenLabel } from "@/lib/earningsClock"
import { vendorLabel } from "@/lib/vendors"

export { sessionLabel }


/** The earnings calendar as a WEEK, not a two-bucket split.
 *
 * A reporting season is read one week at a time — "who is on Thursday" is the
 * question, and the old upcoming/reported split could not answer it because
 * both halves were sorted by their own clocks. So: a seven-cell strip with the
 * call count per day, then one table per day.
 *
 * Weekend cells are rendered even though US equities never report then. Seven
 * cells is what makes the strip readable as a week at a glance; dropping the
 * empty ones would shift every other day sideways depending on the month.
 *
 * Rows come back biggest-cap-first from the server — on a 50-name day that is
 * the difference between scanning and hunting. */

function money(n: number | null | undefined): string {
  if (n == null || n === 0) return "—"
  const abs = Math.abs(n)
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(0)
}

function eps(n: number | null | undefined): string {
  return n == null ? "—" : n.toFixed(2)
}

/** "Sunday, August 16" — the heading over each day's table. */
function longDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric",
  })
}

function rangeLabel(start: string, end: string): string {
  const a = new Date(`${start}T12:00:00`)
  const b = new Date(`${end}T12:00:00`)
  const m = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  return `${m(a)} — ${m(b)}, ${b.getFullYear()}`
}

function shiftWeek(start: string, weeks: number): string {
  const d = new Date(`${start}T12:00:00`)
  d.setDate(d.getDate() + weeks * 7)
  return d.toISOString().slice(0, 10)
}

/** One day cell in the strip. Count is the headline: it is what tells you
 * which day of the week actually matters. */
function DayCell({
  day, today, active, onSelect,
}: {
  day: EarningsDay
  today: string
  active: boolean
  onSelect: () => void
}) {
  const isToday = day.date === today
  const empty = day.count === 0
  const month = new Date(`${day.date}T12:00:00`).toLocaleDateString("en-US", { month: "short" })
  // A card per day, theirs' shape (2026-09-11): a bordered box with the
  // weekday, the date, and the count as a pill; the selected day takes the
  // accent border and tint; a day with nothing on it sits back.
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      aria-label={`${day.weekday} ${month} ${Number(day.date.slice(8))}, ${empty ? "no calls" : `${day.count} calls`}`}
      className={`flex min-w-0 flex-col items-start rounded-md border px-2 py-1 text-left transition-colors ${
        // The picked day is solid red with white text, like the rail's
        // current page (2026-09-19, the owner: "make the selected red") —
        // an exception to the grey selection used by pickers elsewhere.
        active ? "border-accent bg-accent [&_*]:!text-white" : "border-border hover:bg-foreground/5"
      } ${empty && !active ? "opacity-60" : ""}`}
    >
      {/* Two short lines, so the strip reads as a picker and not a board of
          its own (the reader's call, 2026-09-12). Today is marked in AMBER,
          not accent: time-sensitive is what amber means, and accent is
          reserved for what is selected or scoped. */}
      {/* Wraps between the weekday and the date, never inside "Sep 14" —
          on a phone the date had broken over two lines in some cells and
          not others (2026-09-19). */}
      <span className="flex flex-wrap items-baseline gap-x-1.5">
        <span className={`text-label font-medium uppercase tracking-caps ${
          isToday ? "font-extrabold text-warn" : "text-muted-foreground"
        }`}>
          {day.weekday}
        </span>
        <span className="tnum whitespace-nowrap text-caption font-semibold text-foreground">
          {month} {Number(day.date.slice(8))}
        </span>
      </span>
      <span className={`truncate text-label ${empty ? "text-muted-foreground" : "text-foreground"}`}>
        {empty ? "No calls" : `${day.count} ${day.count === 1 ? "call" : "calls"}`}
      </span>
    </button>
  )
}

/** "Wed Sep 9" — a report date in the finder's sentence. */
function shortDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
}

/** The finder's answer under the header: where the company reports, why
 * that date (moved onto its 8-K, or from EDGAR alone), and its other dates
 * as jumps. Says plainly when there is nothing to find. */
function FindResult({ found, current, onJump, onClear }: {
  found: EarningsFind
  current: string | null
  onJump: (date: string) => void
  onClear: () => void
}) {
  const who = found.company_name ? `${found.symbol} · ${found.company_name}` : found.symbol
  const at = found.reports.find(r => r.report_date === current)
  const others = found.reports.filter(r => r.report_date !== current)
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-row-rule bg-card px-3 py-2 text-caption">
      <span className="font-semibold text-foreground">{who}</span>
      {!found.listed ? (
        <span className="text-muted-foreground">is not an SEC filer, so the calendar does not list it.</span>
      ) : !found.reports.length ? (
        <span className="text-muted-foreground">
          has no report in your calendar vendors between {shortDay(found.start)} and {shortDay(found.end)}.
        </span>
      ) : (
        <>
          {at && (
            <span className="text-muted-foreground">
              reports {shortDay(at.report_date)}
              {at.edgar_only ? " — no vendor listed it; found from its results 8-K on EDGAR"
                : at.date_from_edgar && at.vendor_date ? ` — your vendor listed ${shortDay(at.vendor_date)}; the results 8-K reports a release this day`
                : at.announcement && at.vendor_date ? ` — your vendor listed ${shortDay(at.vendor_date)}; the company announced this day`
                : at.announcement ? " — announced by the company"
                : at.released_at || at.released_on ? " — results 8-K on EDGAR" : ""}
            </span>
          )}
          {others.length > 0 && (
            <span className="text-muted-foreground">
              {at ? "· also" : "reports"}{" "}
              {others.map((r, i) => (
                <button key={r.report_date} type="button" onClick={() => onJump(r.report_date)}
                  className="font-medium text-accent-700 hover:underline">
                  {shortDay(r.report_date)}{i < others.length - 1 ? "," : ""}
                </button>
              )).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, " ", el] : [el]), [])}
            </span>
          )}
        </>
      )}
      <button type="button" onClick={onClear} aria-label="Clear the symbol filter"
        className={btnCls({ variant: "ghost", size: "sm", icon: true }, "ml-auto")}>
        <X className="h-[12px] w-[12px]" />
      </button>
    </div>
  )
}

/** What the company's announcement said, who carried it and what it changed. */
function announcementTitle(r: EarningsRow): string {
  const a = r.announcement!
  const session = r.session === "BMO" ? "before the open" : r.session === "AMC" ? "after the close" : null
  const how = a.basis === "call time" ? " (implied by its conference call time)" : ""
  return [
    `Announced by the company${a.source ? ` via ${a.source}` : ""} on ${new Date(a.published_at).toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric" })}`,
    a.sentence ? `“${a.sentence}”` : null,
    session && a.basis ? `Reports ${session}${how}` : "The release names the date, not the session",
    r.vendor_date ? `Your calendar vendor listed ${shortDay(r.vendor_date)}` : null,
    (r.vendor_session === "BMO" || r.vendor_session === "AMC") && r.vendor_session !== r.session ? `your vendor had it ${r.vendor_session === "BMO" ? "before the open" : "after the close"}` : null,
    r.sources === "announcement" ? "None of your calendar vendors lists this report" : null,
  ].filter(Boolean).join(" · ")
}

/** Where a single vendor's actual comes from. */
function singleVendorTitle(r: EarningsRow): string {
  const who = vendorLabel(r.actual_source) ?? "one calendar vendor"
  return `Reported by ${who}; no second vendor carries it and no results 8-K is on SEC EDGAR yet`
}

/** Why a vendor's "actual" is not shown. */
function placeholderTitle(r: EarningsRow): string {
  const who = vendorLabel(r.placeholder_source) ?? "One calendar vendor"
  return `${who} lists an actual of ${eps(r.placeholder_actual)}, exactly its estimate, and the company has filed nothing with the SEC for this report — treated as a placeholder, not a result`
}

function DayTable({ day, picked, pickedRow, onPick, found }: {
  day: EarningsDay
  /** The symbol the finder is on: its row is marked and scrolled to. */
  found?: string | null
  /** The company the page is scoped to, so the row can show as selected. */
  picked?: string | null
  pickedRow?: EarningsRow | null
  onPick?: (symbol: string, row: EarningsRow) => void
}) {
  if (!day.rows.length) return null
  return (
    <section id={`day-${day.date}`} className="scroll-mt-2">
      {/* A day heading sits on the card itself above a hairline (2026-09-18):
          a grey band under a 40%-ink rule read as a slab across a white card
          once the panels became cards. */}
      <h3 className="border-b border-card-rule bg-card px-3 pb-2 pt-4 text-body font-extrabold uppercase tracking-caps">
        {longDay(day.date)}
        <span className="ml-2 font-normal normal-case tracking-normal text-muted-foreground">
          {day.count} {day.count === 1 ? "call" : "calls"}
        </span>
      </h3>
      {/* The one table. Most small reporters carry no consensus estimate, so
          Surprise is an em dash for most rows — they stay: they reported. */}
      {/* Eight columns need ~640px; a narrower tile scrolls them sideways
          rather than squeezing Mkt cap, Volatility and Liquidity out of view. */}
      <div className="overflow-x-auto"><div className="min-w-[560px]">
      <table className="w-full table-fixed border-separate border-spacing-0 text-body">
          <thead>
            <tr>
              <th className="w-[112px] border-b border-row-rule bg-panel px-2 py-2 text-left text-label font-medium uppercase tracking-caps text-muted-foreground" data-tip="The ticker. Click a row to add it to the board and read the report in the insights box" aria-description="The ticker. Click a row to add it to the board and read the report in the insights box">Symbol</th>
              {/* The name needs room: at a narrow tile it was left with a
                  few pixels and read as one letter. It hides below md; the
                  columns that matter less at that width hide below lg. */}
              <th className="hidden border-b border-row-rule bg-panel px-2 py-2 text-left text-label font-medium uppercase tracking-caps text-muted-foreground md:table-cell" />
              <th className="w-[104px] border-b border-row-rule bg-panel px-2 py-2 text-left text-label font-medium uppercase tracking-caps text-muted-foreground" data-tip="When the company reports: BMO before the open, AMC after the close, or the release time once it is out. Green: released. Amber: the date is not confirmed by the company. Hover a row for how the time is known" aria-description="When the company reports: BMO before the open, AMC after the close, or the release time once it is out. Green: released. Amber: the date is not confirmed by the company. Hover a row for how the time is known">When</th>
              <th className="w-[70px] whitespace-nowrap border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground" data-tip="The analyst consensus for earnings per share, adjusted for any split since it was quoted" aria-description="The analyst consensus for earnings per share, adjusted for any split since it was quoted">Est EPS</th>
              <th className="hidden w-[90px] whitespace-nowrap border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground lg:table-cell" data-tip="Earnings per share as reported, once released" aria-description="Earnings per share as reported, once released">Actual EPS</th>
              <th className="w-[76px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground" data-tip="How far reported earnings per share came in above or below the estimate, in percent" aria-description="How far reported earnings per share came in above or below the estimate, in percent">Surprise</th>
              <th className="w-[80px] whitespace-nowrap border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground"
                  data-tip="Market capitalisation today, from your company data vendor. Each day lists the largest companies first" aria-description="Market capitalisation today, from your company data vendor. Each day lists the largest companies first">Mkt cap</th>
              <th className="w-[74px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground"
                  data-tip="Annualised volatility of daily returns over the last twenty sessions, from your chart vendor" aria-description="Annualised volatility of daily returns over the last twenty sessions, from your chart vendor">Volatility</th>
              <th className="w-[78px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground"
                  data-tip="Average dollar volume a day over the last twenty sessions, from your chart vendor" aria-description="Average dollar volume a day over the last twenty sessions, from your chart vendor">Liquidity</th>
            </tr>
          </thead>
          <tbody>
            {day.rows.map(r => {
              const surprise = r.surprise_pct
              // Marked by the open report when the page tracks one (the
              // Earnings page), else by the symbol (a theme, a tile).
              const on = pickedRow
                ? pickedRow.symbol === r.symbol && pickedRow.report_date === r.report_date
                : picked === r.symbol
              const out = r.eps_actual != null || !!r.released_at || !!r.released_on
              const sure = !!r.confirmed || out
              // Once the report is OUT the cell says so, with the clock:
              // EDGAR's acceptance of the 8-K, or when the actual was first
              // seen here. Before that, BMO / AMC once the company has named
              // the time; "TBA" while the date is only a projection.
              // The clock is EDGAR's acceptance, or the actual's first
              // sighting when that sighting was timely; a backfilled row
              // just says Out.
              // EDGAR's acceptance or a same-day sighting is the report's
              // clock ("Out 6:59 AM"); a later sighting is named for what it
              // is, with its day ("Seen Sat 1:47 AM") — precise, and not a
              // claim about when the company reported.
              // The rule lives in lib/earningsClock.whenLabel, where it is
              // tested; the tooltip below spells out the evidence.
              const todayEt = todayInEt()
              const past = r.report_date < todayEt
              const when = whenLabel(r, todayEt)
              const sighted = !!r.actual_at && inBackfillWindow(r.actual_at, r.report_date)
              const whenTitle = out
                ? [r.released_at ? `8-K accepted by EDGAR ${etClock(r.released_at, r.report_date, true)} ET (${ago(r.released_at)})`
                     : r.released_on
                       ? (r.filed_on && r.filed_on !== r.released_on
                           ? `released ${r.released_on}; the results 8-K was filed on EDGAR ${r.filed_on}${r.filed_at ? ` at ${etClock(r.filed_at, r.filed_on, true)} ET` : ""}, so no release time is claimed`
                           : `results 8-K filed on EDGAR ${r.released_on}`)
                       : null,
                   r.actual_at ? `actual EPS first seen here ${etClock(r.actual_at, r.report_date, true)} ET (${ago(r.actual_at)})`
                     : r.eps_actual != null ? "actual EPS from your calendar vendor"
                     : "actual EPS not on your calendar vendor yet",
                   !r.released_at && (r.session === "BMO" || r.session === "AMC")
                     ? `${r.session === "BMO" ? "before the open" : "after the close"}, as ${r.announcement?.basis ? "the company announced" : "your calendar vendor lists it"}` : null]
                    .filter(Boolean).join(" · ")
                : past ? (sure
                    ? "The company named this report time, but no actual has reached the calendar and no results 8-K was accepted on EDGAR"
                    : "The date was the calendar's projection from last year; it has passed with no actual on the calendar and no results 8-K on EDGAR")
                : r.announcement ? announcementTitle(r)
                : sure && (r.session === "BMO" || r.session === "AMC") ? "The company has named its report time"
                : r.session_predicted
                  ? `Predicted: the company released ${r.session_predicted === "BMO" ? "before the open" : "after the close"} on at least 3 of its last ${r.session_basis ?? 4} reports (SEC filing times). Not confirmed by the company yet`
                : sure ? "The company has named its report time" : "Date not confirmed by the company — the calendar's projection from last year"
              // The age tag under the surprise follows the same rule: a real
              // arrival of the number, never a bookkeeping stamp.
              const freshAge = sighted ? ago(r.actual_at!) : null
              const key = `${r.symbol}-${r.report_date}`
              const isFound = found === r.symbol
              return (
                <tr
                  key={key}
                  id={isFound ? `found-${key}` : undefined}
                  // The click is two things at once: the company joins the
                  // board, and the insights box beside the calendar reads
                  // this report. The page decides what a second click on the
                  // same row means (the Earnings page closes the box).
                  onClick={() => onPick?.(r.symbol, r)}
                  aria-selected={on}
                  className={`cursor-pointer ${
                    on ? "bg-row-selected" : isFound ? "bg-foreground/[0.07]" : "hover:bg-foreground/5"} ${
                    isFound ? "shadow-[inset_3px_0_0_0_var(--accent)]" : ""}`}
                >
                  <td className={`overflow-hidden text-ellipsis whitespace-nowrap border-b border-row-rule px-2 py-1.5 font-medium tracking-ticker`}>
                    {r.symbol}
                    {r.edgar_only && (
                      <span className="ml-1 text-label text-muted-foreground" title={`None of your calendar vendors listed this report; its results 8-K on EDGAR reports a release on ${r.report_date}`}>·EDGAR</span>
                    )}
                    {r.announcement && (
                      // The release itself, one click away; the row's own click stays the pick.
                      <a href={r.announcement.url} target="_blank" rel="noreferrer noopener"
                         onClick={e => e.stopPropagation()}
                         className="ml-1 text-label text-accent-700 hover:underline"
                         title={announcementTitle(r)}>·PR</a>
                    )}
                    {r.date_from_edgar && (
                      <span className="ml-1 text-label text-muted-foreground" title={`Your calendar vendor listed ${r.vendor_date}; the results 8-K on EDGAR reports a release on ${r.report_date}`}>·EDGAR</span>
                    )}
                    {/* A results 8-K already landed, days before this report:
                        preliminary or restated figures, not this quarter, so
                        the date stands (Hub Group, 2026-09-15). */}
                    {r.earlier_release_on && (
                      <span className="ml-1 text-label text-warn"
                            title={`A results 8-K on EDGAR carries a release on ${r.earlier_release_on} — earlier figures, not this report, so this date is unchanged`}>·8-K {r.earlier_release_on.slice(5)}</span>
                    )}
                    {/* Below md the name column is hidden, so the name rides
                        under the ticker — a bare ticker list meant nothing
                        on a phone (2026-09-19). */}
                    {r.company_name && (
                      <span className="block truncate text-label font-normal tracking-normal text-muted-foreground md:hidden">
                        {r.company_name}
                      </span>
                    )}
                  </td>
                  <td className="hidden overflow-hidden text-ellipsis whitespace-nowrap border-b border-row-rule px-2 py-1.5 text-muted-foreground md:table-cell">
                    {r.company_name ?? ""}
                  </td>
                  <td className={`overflow-hidden text-ellipsis whitespace-nowrap border-b border-row-rule px-2 py-1.5 text-label font-medium uppercase tracking-caps ${out ? "text-gain" : sure || past ? "text-muted-foreground" : "text-warn"}`}
                      title={whenTitle}>
                    {when}
                  </td>
                  <td className="tnum border-b border-row-rule px-2 py-1.5 text-right"
                      title={r.split_note ? `Adjusted for the ${r.split_note}; your vendor quoted ${eps(r.eps_estimate_unadjusted)} on the old share count` : undefined}>
                    {eps(r.eps_estimate)}{r.split_note ? <span className="text-muted-foreground">†</span> : null}
                  </td>
                  <td className="tnum hidden border-b border-row-rule px-2 py-1.5 text-right lg:table-cell">
                    {r.eps_actual == null && r.placeholder_actual != null ? (
                      <span title={placeholderTitle(r)}>—</span>
                    ) : r.actual_basis === "single_vendor" ? (
                      <span title={singleVendorTitle(r)}>{eps(r.eps_actual)}</span>
                    ) : eps(r.eps_actual)}
                  </td>
                  <td className={`tnum border-b border-row-rule px-2 py-1.5 text-right font-semibold ${
                    surprise == null ? "text-muted-foreground"
                      : surprise >= 0 ? "text-gain" : "text-loss"
                  }`}
                      // The number's AGE rides with it: a surprise with no
                      // age is what makes it look tradeable when it is stale.
                      title={r.actual_at ? `Actual first seen here ${etClock(r.actual_at, r.report_date, true)} ET · ${ago(r.actual_at)}` : undefined}>
                    {surprise == null
                      ? (r.placeholder_actual != null ? <span title={placeholderTitle(r)}>—</span> : "—")
                      : `${surprise >= 0 ? "+" : ""}${surprise.toFixed(2)}%`}
                    {surprise != null && freshAge && (
                      <span className="block text-label font-normal text-muted-foreground">{freshAge}</span>
                    )}
                  </td>
                  <td className="tnum border-b border-row-rule px-2 py-1.5 text-right">
                    {money(r.market_cap)}
                  </td>
                  <td className="tnum border-b border-row-rule px-2 py-1.5 text-right text-muted-foreground">
                    {r.volatility == null ? "—" : `${r.volatility.toFixed(0)}%`}
                  </td>
                  <td className={`tnum border-b border-row-rule px-2 py-1.5 text-right ${r.low_liquidity ? "text-warn" : "text-muted-foreground"}`}
                      title={r.low_liquidity ? "Under $10M a day: thin enough that a report-day move can gap" : undefined}>
                    {r.liquidity == null ? "—" : money(r.liquidity)}
                  </td>
                </tr>
              )
            })}
          </tbody>
      </table>
      </div></div>
    </section>
  )
}

export function EarningsCalendar({ picked, pickedRow, onPick }: {
  /** The symbol whose rows are marked (a theme page, a board tile). */
  picked?: string | null
  /** The one report that is marked, when the page tracks an open report;
   * takes precedence over `picked`. */
  pickedRow?: EarningsRow | null
  /** A row was clicked: the symbol joins the board, and the row is what the
   * insights box beside the calendar reads. */
  onPick?: (symbol: string, row: EarningsRow) => void
} = {}) {
  // Kept across pages for the session (lib/keptState): leaving Earnings and
  // coming back used to reopen this week with no day picked.
  const [start, setStart] = useKeptState<string | undefined>("alphadesk.earnings.week", undefined)
  const { data, isPending, isError, error, isPlaceholderData } = useEarningsWeek(start)
  const qc = useQueryClient()
  // The weeks either side are asked for once this one is on screen, one after
  // the other, so the server has built them by the time an arrow is clicked:
  // a week it has not built takes it 8–12s (release-time lookups paced for
  // SEC EDGAR), one it has takes well under a second (2026-09-14).
  const loadedStart = !isPlaceholderData ? data?.start : undefined
  useEffect(() => {
    if (!loadedStart) return
    let cancelled = false
    const ahead = async () => {
      for (const n of [1, -1]) {
        if (cancelled) return
        const s = shiftWeek(loadedStart, n)
        await qc.prefetchQuery({ queryKey: keys.earningsWeek(s), queryFn: () => api.earningsWeek(s), staleTime: 60_000 })
      }
    }
    void ahead()
    return () => { cancelled = true }
  }, [loadedStart, qc])
  // A picked day, `null` for the whole week, or `undefined` — nothing picked
  // yet, which opens on today (lib/earningsDefaultDay).
  const [selected, setSelected] = useKeptState<string | null | undefined>("alphadesk.earnings.day", undefined)
  const [stepped, setStepped] = useKeptState<boolean>("alphadesk.earnings.stepped", false)
  // The symbol filter: typed, submitted on Enter, answered by the finder,
  // which moves the week and the day onto the company's report.
  const [q, setQ] = useState("")
  const [findSym, setFindSym] = useState<string | null>(null)
  const find = useEarningsFind(findSym)
  const [jumped, setJumped] = useState<string | null>(null)
  const jump = (d: string) => { setStart(d); setSelected(d); setJumped(d) }
  useEffect(() => {
    if (find.data?.pick && find.data.symbol === findSym) jump(find.data.pick)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [find.data, findSym])
  useEffect(() => {
    if (!findSym || !jumped || !data?.days.some(d => d.date === jumped)) return
    const el = document.getElementById(`found-${findSym}-${jumped}`)
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [data, findSym, jumped, selected])
  const clearFind = () => { setFindSym(null); setQ(""); setJumped(null) }
  const submitFind = () => {
    const sym = q.trim().toUpperCase()
    if (!sym) { clearFind(); return }
    setFindSym(sym)
    // A repeat submit of the same symbol jumps again from the cache.
    if (sym === findSym && find.data?.pick) jump(find.data.pick)
  }

  const week: EarningsWeek | undefined = data
  /** OTC listings and a company's second tickers (warrants, preferreds,
   * another share class) are hidden by default — the consumer calendars list
   * each company once, on its exchange listing (2026-09-14). */
  const [showAll, setShowAll] = useState<boolean>(() => {
    try { return localStorage.getItem("alphadesk.earnings.showAllListings") === "1" } catch { return false }
  })
  const toggleAll = () => setShowAll(v => {
    try { localStorage.setItem("alphadesk.earnings.showAllListings", v ? "0" : "1") } catch { /* private mode */ }
    return !v
  })
  const hiddenCount = useMemo(
    () => (week?.days ?? []).reduce((n, d) => n + d.rows.filter(r => (r.listing ?? "primary") !== "primary").length, 0),
    [week])
  // Monday to Friday only: the market is closed at the weekend and no
  // company reports then, so the two empty cards only took the room the
  // five real days need (the reader's call, 2026-09-12).
  const days = useMemo(() => (week?.days ?? []).filter(d => {
    const dow = new Date(`${d.date}T12:00:00Z`).getUTCDay()
    return dow !== 0 && dow !== 6
  }).map(d => {
    if (showAll) return d
    const rows = d.rows.filter(r => (r.listing ?? "primary") === "primary")
    return { ...d, rows, count: rows.length }
  }), [week, showAll])
  const confirmedTotal = useMemo(
    () => days.reduce((n, d) => n + d.rows.filter(r => !!r.confirmed || r.eps_actual != null).length, 0),
    [days])
  const total = useMemo(() => days.reduce((n, d) => n + d.count, 0), [days])
  // With nothing picked, open on today — or the last reporting day before it.
  const todayNY = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" })
  const auto = week && !isPlaceholderData && selected === undefined
    ? defaultDay(days, week.start, week.end, todayNY, stepped)
    : { day: null, stepBack: false }
  const day = selected === undefined ? auto.day : selected
  useEffect(() => {
    if (!auto.stepBack || !week) return
    setStepped(true)
    setStart(shiftWeek(week.start, -1))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto.stepBack, week?.start])

  if (isPending && !data) return <Empty>loading…</Empty>
  if (isError) return <QueryFailure error={error}>the calendar could not be loaded</QueryFailure>
  if (!week) return <Empty>the calendar could not be loaded</Empty>

  // Selecting a day filters the tables to it; selecting it again clears.
  const shown = day ? days.filter(d => d.date === day) : days
  const first = days[0]?.date ?? week.start
  const last = days[days.length - 1]?.date ?? week.end

  return (
    <div>
      {/* No "Today" button — deliberately dropped. The arrows and the day
          strip reach the current week; a third control was chrome. */}
      <div className="flex flex-wrap items-center gap-3 border-b border-row-rule px-3 py-2.5">
        <span className="inline-flex">
          <button
            type="button"
            aria-label="Previous week"
            onClick={() => { setStart(shiftWeek(isPlaceholderData && start ? start : week.start, -1)); setSelected(null) }}
            className={btnCls({ icon: true }, "text-body")}
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Next week"
            onClick={() => { setStart(shiftWeek(isPlaceholderData && start ? start : week.start, 1)); setSelected(null) }}
            className={btnCls({ icon: true }, "ml-1 text-body")}
          >
            ›
          </button>
        </span>
        <span className="num text-emph font-extrabold tracking-tight">{rangeLabel(first, last)}</span>
        <span className="text-caption text-muted-foreground">
          {!isPlaceholderData && (week.pending?.timing || week.pending?.announcements) ? (
            <span className="mr-2 text-accent-700"
                  title="A busy week: companies' usual report times (from SEC filings) and their press releases are being looked up, and fill in as they arrive">
              filling in report times for {Math.max(week.pending?.timing ?? 0, week.pending?.announcements ?? 0)} companies…
            </span>
          ) : null}
          {isPlaceholderData && start && <span className="mr-2 font-semibold text-accent-700">loading the week of {new Date(`${start}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" })}…</span>}
          {total} {total === 1 ? "call" : "calls"} this week
          {confirmedTotal < total && <> · {confirmedTotal} with a confirmed time</>}
        </span>
        {hiddenCount > 0 && (
          <button type="button" onClick={toggleAll}
                  title="Over-the-counter listings and a company's other tickers — warrants, preferred series, a second share class"
                  className="text-caption font-semibold text-muted-foreground hover:text-foreground hover:underline">
            {showAll ? "hide OTC & other tickers" : `+${hiddenCount} OTC & other tickers`}
          </button>
        )}
        <form
          className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto"
          onSubmit={e => { e.preventDefault(); submitFind() }}
        >
          {day && (
            // A real button, not a red text link (2026-09-19: "doesn't look
            // good"), the height of the search field beside it.
            <button
              type="button"
              onClick={() => setSelected(null)}
              title="Show every day of the week, not just the one picked"
              className={btnCls({}, "h-[28px] shrink-0 sm:h-[24px]")}
            >
              Whole week
            </button>
          )}
          <input
            value={q}
            onChange={e => setQ(e.target.value.toUpperCase())}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); submitFind() } }}
            placeholder="Find a symbol"
            aria-label="Find a company's report in the calendar"
            spellCheck={false}
            className="h-[28px] min-w-0 flex-1 rounded-sm border border-border bg-transparent px-2 text-caption uppercase tracking-caps outline-none placeholder:normal-case placeholder:tracking-normal placeholder:text-muted-foreground focus:border-accent sm:h-[24px] sm:w-[120px] sm:flex-none"
          />
        </form>
      </div>
      {findSym && find.isPending && (
        <div className="border-b border-row-rule bg-card px-3 py-2 text-caption text-muted-foreground">finding {findSym}…</div>
      )}
      {findSym && find.isError && (
        <div className="border-b border-row-rule bg-card px-3 py-2 text-caption">
          <QueryFailure error={find.error} compact>{findSym} could not be looked up</QueryFailure>
        </div>
      )}
      {findSym && find.data && find.data.symbol === findSym && (
        <FindResult found={find.data} current={jumped} onJump={jump} onClear={clearFind} />
      )}

      {/* Five equal columns: a week always fits the strip, on a phone too,
          where a row of 88px cells ran off the edge behind a scrollbar. */}
      <div className="grid grid-cols-5 gap-1.5 border-b-2 border-border px-3 py-1.5">
        {days.map(d => (
          <DayCell
            key={d.date}
            day={d}
            today={week.today}
            active={day === d.date}
            onSelect={() => setSelected(day === d.date ? null : d.date)}
          />
        ))}
      </div>

      <div className={isPlaceholderData ? "pointer-events-none opacity-50 transition-opacity" : undefined} aria-busy={isPlaceholderData}>
      {total === 0 ? (
        <Empty>nothing reports this week</Empty>
      ) : (
        shown.map(d => <DayTable key={d.date} day={d} picked={picked} pickedRow={pickedRow} onPick={onPick} found={findSym} />)
      )}
      </div>
    </div>
  )
}
