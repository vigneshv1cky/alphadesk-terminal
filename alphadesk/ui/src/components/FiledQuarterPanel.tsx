/** WHAT THE COMPANY FILED — its own XBRL from SEC EDGAR, each figure against
 * the same quarter a year earlier.
 *
 * NO VERDICT IS RENDERED and none should be added. The panel states figures
 * and their direction; whether that is a good report is the reader's call
 * (invariant 1, and the same call that removed screener ranking). The market's
 * own reading is already on the calendar row beside this, as the price move.
 *
 * THE PERIOD IS ALWAYS NAMED IN THE HEADER, because "the quarter just
 * reported" is a claim this data cannot support: XBRL lands with the 10-Q,
 * which can trail the 8-K by weeks, and an Item 2.02 8-K is sometimes a
 * guidance update carrying no period at all (Gray Media, 2026-09-28). */
import { Empty } from "@/components/terminal"
import { useEarningsFiled } from "@/lib/queries"
import { QueryFailure } from "@/components/KeyPrompt"

/** A DOLLAR SIGN ONLY WHERE THE COMPANY FILED DOLLARS. Novo Nordisk reports
 * in kroner, Alibaba in renminbi, VinFast in dong — and TSMC's revenue is
 * NT$2.89 trillion, which behind a "$" would be off by a factor of thirty.
 * Non-USD figures carry no symbol here; the column headings name the currency
 * once, which is where a reader looks for units and keeps the table clean. */
function money(v?: number | null, currency = "USD"): string {
  if (v == null) return "—"
  const a = Math.abs(v)
  const s = v < 0 ? "-" : ""
  const c = currency === "USD" ? "$" : ""
  if (a >= 1e12) return `${s}${c}${(a / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${s}${c}${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${s}${c}${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${s}${c}${(a / 1e3).toFixed(1)}K`
  return `${s}${c}${a.toFixed(2)}`
}

function shown(v: number | null | undefined, unit: string, currency = "USD"): string {
  if (v == null) return "—"
  return unit === "percent" ? `${v.toFixed(2)}%` : money(v, currency)
}

/** The change, said the way the figure allows: a percent where the base is
 * positive, percentage points for a margin, and the bare direction through a
 * sign change — where a percent of a negative base would read as a collapse. */
function change(m: { change_pct?: number | null; change_pp?: number | null; direction?: string | null }) {
  if (m.change_pp != null) return `${m.change_pp >= 0 ? "+" : ""}${m.change_pp.toFixed(2)}pp`
  if (m.change_pct != null) return `${m.change_pct >= 0 ? "+" : ""}${m.change_pct.toFixed(1)}%`
  if (m.direction === "up") return "up"
  if (m.direction === "down") return "down"
  if (m.direction === "flat") return "flat"
  return "—"
}

/** WHAT EACH FIGURE IS, on the row rather than beside it (2026-09-29, the
 * owner: "remove the calc, and include explanations in tooltip"). A "·calc"
 * mark beside two rows was too cryptic to read without hovering it anyway —
 * and hovering is where the explanation belongs, for every row rather than
 * the two that carried a marker.
 *
 * DERIVED FIGURES SAY SO IN WORDS. Margins and free cash flow are arithmetic
 * on figures the company filed, not figures it filed, and the panel claims
 * "as filed with the SEC" over the whole table — so the distinction has to
 * survive losing its marker. */
const WHAT: Record<string, string> = {
  revenue: "What the company took in over the period, as tagged in its own filing.",
  gross_profit: "Revenue less what it cost to produce, as filed.",
  operating_income: "Profit from running the business, before interest and tax, as filed.",
  net_income: "Profit or loss after everything — interest, tax and the rest. As filed.",
  diluted_eps: "Profit per share, counting every share that would exist if options and convertibles were exercised. As filed.",
  ocf: "Cash the business itself generated, as filed — which can differ sharply from profit.",
  capex: "Cash spent on property, plant and equipment, as filed. Shown negative because it leaves the business.",
  fcf: "DERIVED, not filed: operating cash flow less capital expenditure. No company tags this figure; it is computed here from the two above it.",
  operating_income_margin: "DERIVED, not filed: operating income as a percentage of revenue. Computed here from two filed figures, and shown only where revenue is positive in both periods.",
  net_income_margin: "DERIVED, not filed: net income as a percentage of revenue. Computed here from two filed figures.",
}

function day(d?: string | null): string {
  if (!d) return "—"
  return new Date(`${d}T12:00:00`).toLocaleDateString("en-US",
    { month: "short", day: "numeric", year: "numeric" })
}

export function FiledQuarterPanel({ symbol, reportDate }: { symbol: string; reportDate?: string }) {
  const { data, isPending, isError, error } = useEarningsFiled(symbol, reportDate)
  if (isPending) return <Empty>loading…</Empty>
  if (isError) return <QueryFailure error={error}>the filed figures could not be read</QueryFailure>
  if (!data) return <Empty>the filed figures could not be read</Empty>

  // An empty answer says what the SEC holds, never that the company was
  // silent -- invariant 8's rule about empty panels, on a keyless source.
  if (!data.metrics.length) {
    return <Empty>{data.note ?? "SEC EDGAR holds no quarterly figures for this filer."}</Empty>
  }

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-row-rule px-3 py-2.5">
        {/* A FOREIGN PRIVATE ISSUER FILES A YEAR, NOT A QUARTER. Printing
            "Quarter ended" over its annual figures would misstate the period
            the numbers cover, which is the one thing this header exists for. */}
        <span className="text-caption font-semibold text-foreground">
          {data.period === "annual" ? "Year" : "Quarter"} ended {day(data.period_end)}
        </span>
        <span className="text-caption text-muted-foreground">
          against {day(data.prior_end)}
        </span>
        {/* Marked, not hidden: these figures are true of the period named, and
            saying which period that is is what keeps them true. */}
        {data.covers_report === false && (
          <span className="text-caption font-semibold text-warn"
                title={data.note ?? undefined}>
            the {data.period === "annual" ? "year" : "quarter"} behind this report is not filed yet
          </span>
        )}
        <span className="ml-auto text-caption text-muted-foreground"
              title="The company's own XBRL from SEC EDGAR. No vendor key is used and no figure here is a summary.">
          as filed with the SEC
        </span>
      </div>
      <table className="w-full table-fixed border-separate border-spacing-0 text-body">
        <thead>
          <tr>
            <th className="border-b border-row-rule bg-panel px-3 py-2 text-left text-label font-medium uppercase tracking-caps text-muted-foreground">Figure</th>
            {/* The column says the same thing the header does — an annual filer's
                figures are a YEAR's, and "This quarter" over them is the same
                misstatement one level down. */}
            <th className="w-[104px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground">
              This {data.period === "annual" ? "year" : "quarter"}
              {data.currency && data.currency !== "USD" ? ` (${data.currency})` : ""}
            </th>
            <th className="w-[104px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground">
              Year ago{data.currency && data.currency !== "USD" ? ` (${data.currency})` : ""}
            </th>
            <th className="w-[86px] border-b border-row-rule bg-panel px-2 py-2 text-right text-label font-medium uppercase tracking-caps text-muted-foreground">Change</th>
          </tr>
        </thead>
        <tbody>
          {data.metrics.map(m => (
            <tr key={m.id} className="hover:bg-foreground/5">
              <td className="overflow-hidden text-ellipsis whitespace-nowrap border-b border-row-rule px-3 py-1.5"
                  title={WHAT[m.id] ?? (m.filed === false
                    ? "Derived here from figures the company filed, not a figure it filed."
                    : "As filed with the SEC.")}>
                {m.label}
              </td>
              <td className="tnum border-b border-row-rule px-2 py-1.5 text-right font-semibold">{shown(m.value, m.unit, data.currency)}</td>
              <td className="tnum border-b border-row-rule px-2 py-1.5 text-right text-muted-foreground">{shown(m.prior, m.unit, data.currency)}</td>
              <td className={`tnum border-b border-row-rule px-2 py-1.5 text-right font-semibold ${
                m.direction === "up" ? "text-gain" : m.direction === "down" ? "text-loss" : "text-muted-foreground"}`}
                  title={m.change_pct == null && m.change_pp == null && m.direction
                    ? "One of the two periods is negative, so a percentage would read as a collapse rather than a recovery. The direction is stated instead."
                    : undefined}>
                {change(m)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default FiledQuarterPanel
