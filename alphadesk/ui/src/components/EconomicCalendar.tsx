import { Fragment, useMemo, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { useQuery } from "@tanstack/react-query"
import { api, type EconomicEvent } from "@/lib/api"
import { Menu } from "@/components/ChartToolbar"
import { DEFAULT_FILTER, countryCounts, isDefault, parseFilter, passes, type EconomicFilter, type ImpactFloor } from "@/lib/economicFilter"
import { Btn, Empty, Table, TD, TH, THead, Widget, btnCls } from "@/components/terminal"

/** Scheduled economic releases for a week — CPI, payrolls, rate decisions,
 * PMIs — with the consensus, the prior figure and the actual once out,
 * grouped by day in Eastern time. A KEYED surface: without a connected
 * vendor that carries it the panel shows the key prompt, never an empty
 * week. */

const dash = "—"
/** A figure with its unit when the unit is a percent sign; other units
 * (K, M, an index) are left off the cell — the release name carries them. */
const fmt = (v: number | null, unit: string | null) =>
  v == null ? dash : `${v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2 })}${unit === "%" ? "%" : ""}`

const etDay = (iso: string) => new Date(iso).toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "long", month: "short", day: "numeric" })
const etTime = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })

const isoDate = (d: Date) => d.toISOString().slice(0, 10)
const shift = (day: string, days: number) => { const d = new Date(day + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + days); return isoDate(d) }
/** The Monday of the week holding `day`. */
const weekStart = (day: string) => { const d = new Date(day + "T12:00:00Z"); const off = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - off); return isoDate(d) }

const IMPACT: Record<string, string> = { high: "bg-loss", medium: "bg-accent-700", low: "bg-muted-foreground/50" }

const FILTER_KEY = "alphadesk.economic.filter"
function readFilter(): EconomicFilter {
  try { return parseFilter(localStorage.getItem(FILTER_KEY)) } catch { return DEFAULT_FILTER }
}
function writeFilter(f: EconomicFilter) {
  try { localStorage.setItem(FILTER_KEY, JSON.stringify(f)) } catch { /* private mode: the filter lasts the visit */ }
}

let regionNames: Intl.DisplayNames | null = null
/** "US" -> "United States"; the code itself when the browser does not know it. */
function countryName(code: string): string {
  try {
    regionNames ??= new Intl.DisplayNames(["en"], { type: "region" })
    return regionNames.of(code) ?? code
  } catch {
    return code
  }
}

const IMPACT_FLOORS: { id: ImpactFloor; label: string; hint: string }[] = [
  { id: "all", label: "All", hint: "Every release, holidays included" },
  { id: "low", label: "Low+", hint: "Hides releases with no market impact (holidays, observances)" },
  { id: "medium", label: "Medium+", hint: "Medium and high impact only" },
  { id: "high", label: "High", hint: "High impact only" },
]

/** The filter popover, in the movers tile's style: an impact floor as a
 * segmented row, then the week's countries as a checklist with counts.
 * Changes apply at once — the table behind it is the preview. */
function FilterPopover({ filter, onChange, countries }: {
  filter: EconomicFilter
  onChange: (f: EconomicFilter) => void
  countries: { code: string; count: number }[]
}) {
  const toggle = (code: string) => onChange({
    ...filter,
    countries: filter.countries.includes(code) ? filter.countries.filter(c => c !== code) : [...filter.countries, code],
  })
  const chip = (on: boolean) => btnCls({ active: on }, "flex-1 px-1.5")
  return (
    <div className="w-[272px]">
      <div className="px-3 pb-1 pt-1.5 text-label font-medium uppercase tracking-caps text-muted-foreground">Impact · at least</div>
      <div className="flex gap-1 px-3 pb-2">
        {IMPACT_FLOORS.map(o => (
          <button key={o.id} type="button" title={o.hint} aria-pressed={filter.impact === o.id}
                  onClick={() => onChange({ ...filter, impact: o.id })} className={chip(filter.impact === o.id)}>
            {o.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 border-t border-row-rule px-3 pb-1 pt-2">
        <span className="mr-auto text-label font-medium uppercase tracking-caps text-muted-foreground">Countries</span>
        <button type="button" onClick={() => onChange({ ...filter, countries: [] })}
                className={`text-caption font-semibold ${filter.countries.length ? "text-muted-foreground hover:text-foreground" : "text-accent-700"}`}>All</button>
        <button type="button" onClick={() => onChange({ ...filter, countries: ["US"] })}
                className={`text-caption font-semibold ${filter.countries.length === 1 && filter.countries[0] === "US" ? "text-accent-700" : "text-muted-foreground hover:text-foreground"}`}>US only</button>
      </div>
      <div className="max-h-[240px] overflow-y-auto pb-1">
        {countries.length === 0 && <p className="px-3 py-2 text-caption text-muted-foreground">No countries this week.</p>}
        {countries.map(c => (
          <label key={c.code} className="flex cursor-pointer items-center gap-2 px-3 py-1 text-caption hover:bg-foreground/5">
            <input type="checkbox" checked={filter.countries.includes(c.code)} onChange={() => toggle(c.code)} className="accent-[var(--accent)]" />
            <span className="w-[26px] shrink-0 font-semibold">{c.code}</span>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{countryName(c.code)}</span>
            <span className="tnum text-label text-muted-foreground">{c.count}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-1.5 border-t border-row-rule px-3 pb-1.5 pt-2">
        <span className="mr-auto text-label text-muted-foreground">{filter.countries.length ? `${filter.countries.length} selected` : "every country"}</span>
        <button type="button" onClick={() => onChange(DEFAULT_FILTER)}
                className={btnCls()}>Reset</button>
      </div>
    </div>
  )
}

export function useEconomicCalendar(start: string, end: string) {
  return useQuery({
    queryKey: ["economic", start, end],
    queryFn: () => api.economic(start, end),
    staleTime: 30 * 60_000,
    refetchInterval: 30 * 60_000,
    refetchIntervalInBackground: true,
    retry: false,
  })
}

export function EconomicCalendarPanel({ span = 12 }: { span?: number }) {
  const [start, setStart] = useState(() => weekStart(isoDate(new Date())))
  const end = shift(start, 6)
  const q = useEconomicCalendar(start, end)
  const [filter, setFilterState] = useState<EconomicFilter>(readFilter)
  const setFilter = (f: EconomicFilter) => { setFilterState(f); writeFilter(f) }
  const all = useMemo(() => q.data?.rows ?? [], [q.data])
  const countries = useMemo(() => {
    // A selected country with no releases this week still shows, so it can be unticked.
    const present = countryCounts(all)
    const missing = filter.countries.filter(c => !present.some(p => p.code === c)).map(code => ({ code, count: 0 }))
    return [...present, ...missing]
  }, [all, filter.countries])
  const rows = useMemo(() => all.filter(r => passes(r, filter)), [all, filter])
  const groups = useMemo(() => {
    const m = new Map<string, EconomicEvent[]>()
    for (const r of rows) {
      const key = r.time ? (r.time.length > 10 ? etDay(r.time) : r.time) : "Unscheduled"
      m.set(key, [...(m.get(key) ?? []), r])
    }
    return [...m.entries()]
  }, [rows])
  const label = `${start} → ${end}`
  return (
    <Widget span={span} title="Economic calendar" scroll={380} fitViewport={false}
            subtitle={q.data?.source
              ? `${label} · ${rows.length === all.length ? `${all.length} releases` : `${rows.length} of ${all.length} releases`} · ${q.data.source}`
              : label}
            actions={
              <div className="flex items-center gap-1">
                {q.data && (
                  <Menu label="Filter" align="right" chevron={false} active={!isDefault(filter)}
                        title={isDefault(filter) ? "Filter by impact and country" : "Filter on: impact and country"}>
                    {() => <FilterPopover filter={filter} onChange={setFilter} countries={countries} />}
                  </Menu>
                )}
                <Btn onClick={() => setStart(s => shift(s, -7))} title="Previous week">‹</Btn>
                {/* "THIS WEEK", NOT "TODAY" (2026-09-25, #75, the reader: "this button
          is misleading, making all feel like today"). It sits between two
          week arrows and jumps back to the CURRENT week — its own tooltip
          already said "This week" while the label said "Today", so the
          control disagreed with itself. A calendar showing five days should
          never label anything "Today" unless that is the day it is
          showing. */}
      <Btn onClick={() => setStart(weekStart(isoDate(new Date())))}
           title="Jump back to the current week">This week</Btn>
                <Btn onClick={() => setStart(s => shift(s, 7))} title="Next week">›</Btn>
              </div>
            }>
      {q.isPending ? <Empty>loading…</Empty>
        : q.isError ? <QueryFailure error={q.error}>the calendar source is unavailable right now</QueryFailure>
        : all.length === 0 ? <Empty>nothing scheduled in this window</Empty>
        : rows.length === 0 ? (
          <Empty>
            none of this week&apos;s {all.length} releases pass the filter{" "}
            <button type="button" onClick={() => setFilter(DEFAULT_FILTER)} className="font-semibold text-accent-700 hover:underline">reset it</button>
          </Empty>
        ) : (
        <div className="overflow-x-auto"><div className="min-w-[640px]">
        <Table>
          <THead>
            <TH className="w-[88px]" title="Scheduled release time, New York time">Time (ET)</TH>
            <TH className="w-[52px]" title="The country the release covers">Ctry</TH>
            <TH title="The economic report or event">Release</TH>
            <TH className="w-[84px]" title="How much the release usually moves markets, per the vendor">Impact</TH>
            <TH align="right" className="w-[88px]" title="The figure as released: green above the consensus, red below it">Actual</TH>
            <TH align="right" className="w-[88px]" title="The forecast the vendor lists ahead of the release">Consensus</TH>
            <TH align="right" className="w-[88px]" title="The figure for the prior period">Previous</TH>
          </THead>
          <tbody>
            {groups.map(([day, evs]) => (
              <Fragment key={day}>
                <tr>
                  <TD colSpan={7} className="bg-card pt-4 text-caption font-extrabold uppercase tracking-caps text-foreground">{day}</TD>
                </tr>
                {evs.map((r, i) => {
                  const beat = r.actual != null && r.estimate != null ? r.actual > r.estimate : null
                  return (
                    <tr key={`${day}:${i}:${r.event}`}>
                      {/* A corrected time says whose clock it is: the vendor
                          lists some US releases an hour late (2026-09-15). */}
                      <TD mono className={r.time_source === "agency" ? "text-foreground" : "text-muted-foreground"}
                          title={r.time_source === "agency"
                            ? `${r.time_agency ?? "The agency"} releases this at ${etTime(r.time!)} ET; your calendar vendor listed ${r.vendor_time ? etTime(r.vendor_time) : "another time"}`
                            : undefined}>
                        {r.time && r.time.length > 10 ? etTime(r.time) : dash}
                      </TD>
                      <TD className="text-muted-foreground">{r.country ?? dash}</TD>
                      <TD className="font-medium">{r.event}</TD>
                      <TD>{r.impact ? <span className="inline-flex items-center gap-1 text-label capitalize text-muted-foreground"><i className={`inline-block h-[8px] w-[8px] rounded-full ${IMPACT[r.impact]}`} />{r.impact}</span> : dash}</TD>
                      <TD align="right" mono className={beat == null ? "" : beat ? "text-gain" : "text-loss"}>{fmt(r.actual, r.unit)}</TD>
                      <TD align="right" mono className="text-muted-foreground">{fmt(r.estimate, r.unit)}</TD>
                      <TD align="right" mono className="text-muted-foreground">{fmt(r.previous, r.unit)}</TD>
                    </tr>
                  )
                })}
              </Fragment>
            ))}
          </tbody>
        </Table>
        </div></div>
      )}
    </Widget>
  )
}
