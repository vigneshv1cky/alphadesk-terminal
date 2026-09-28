import { useNarrowViewport } from "@/lib/viewport"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ComposedBoard } from "@/components/ComposedBoard"
import { EarningsCalendar } from "@/components/EarningsCalendar"
import type { EarningsRow } from "@/lib/api"
import {
  EarningsHistoryPanel, EpsPanel, RevenueEarningsPanel,
} from "@/components/EarningsPanels"
import { EarningsTranscriptPanel } from "@/components/EarningsTranscript"
import { Widget } from "@/components/terminal"
import { MarketChart } from "@/widgets/chart"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { normalize } from "@/lib/symbols"
import { FiledQuarterPanel } from "@/components/FiledQuarterPanel"

/** The earnings hub (2026-09-14: the market-wide calendars — economic,
 * dividends, IPOs, splits — moved to their own Calendars tab, and the
 * company's dividend and split history lives on Analysis).
 *
 * The calendar takes the full width, the picked company's chart under it:
 * a week of reporters is the page's
 * subject, and every column it carries is worth its room. Under it, three
 * company-scoped panels — revenue vs. earnings, EPS estimate against actual,
 * and the analyst-consensus grid — follow whichever company is picked.
 *
 * Two kinds of selection, kept apart: the calendar's own day selection stays
 * internal (a date filters the week), while picking a COMPANY goes to
 * ?symbol= where the rest of the app — the strip, the agent panel, Analysis —
 * can see it. With nothing picked the board's active chip scopes the panels,
 * so arriving from any other screen lands on the company you were reading.
 */
export default function EarningsPage() {
  const narrow = useNarrowViewport()
  const [params] = useSearchParams()
  const { active, add } = useBoardSymbols()
  const symbol = normalize(params.get("symbol") || "") || active
  /** The report whose insights box sits beside the calendar — set by a row
   * click, cleared by a second click on the same row or by the box's own
   * close. Nothing is asked until a row is clicked; the calendar is full
   * width until then. */
  const [report, setReport] = useState<EarningsRow | null>(null)
  /** A row click ADDS the company to the board — the same persisted add
   * the strip's own + uses, so the chip stays until it is closed there —
   * and opens the row's box. A second click on the open row closes the
   * box and nothing else: what is on the board leaves only from the board
   * (the reader's rule, 2026-09-12). */
  const pickRow = (sym: string, row: EarningsRow) => {
    if (report && report.symbol === row.symbol && report.report_date === row.report_date) {
      setReport(null)
      return
    }
    add(sym)
    setReport(row)
  }
  // Without a company picked, each company panel states what would fill it —
  // one placeholder per panel, so hiding or resizing them still composes.
  const needPick = (label: string) => (
    <Widget span={4} title={label}>
      <div className="px-3 py-4 text-left text-body text-muted-foreground">
        Pick a reporter in the calendar — or mark a chip on the board.
      </div>
    </Widget>
  )

  return (
    <ComposedBoard
      page="earnings"
      panels={[
        {
          id: "calendar", label: "Earnings calendar",
          node: (
            <Widget
              span={12}
              title="Earnings calendar"
              subtitle="every company that reported, from its own SEC filing — newest first"
              // The panel scrolls, not the page — which is what lets the column
              // header stay put. As tall as the screen allows (2026-09-11, the
              // reader's call), but no taller than the day: a number is a cap
              // that grows to the viewport and SHRINKS to a short day, where
              // the fixed height left an empty block under nine rows
              // (2026-09-19). On a phone the page is the one scroll — a
              // scrolling box inside a scrolling page is a trap for a thumb.
              scroll={narrow ? undefined : 560}
            >
              <EarningsCalendar pickedRow={report} onPick={pickRow} />
            </Widget>
          ),
        },
        // The picked company's price, under the calendar (2026-09-18, the
        // reader's ask, then their default: calendar first, chart second).
        // A row click adds the company to the board and the chart follows
        // it, so a report and its price move sit together.
        // THE CHART AND THE FIGURES SHARE A ROW, HALF EACH — the owner's own
        // arrangement, set in the board editor and made the default here
        // (2026-09-28). They answer one question from two sides: what the
        // company filed, and what the price did about it. A reader who has
        // already arranged this page keeps their layout; this is only what a
        // board with no stored arrangement opens as.
        {
          id: "chart", label: "Chart",
          node: <MarketChart span={6} symbol={symbol} />,
        },
        // WHAT THE REPORT SAID, straight after the chart: the company's own
        // filed figures against the year-ago quarter. Keyless SEC data, so it
        // is there for a reader with no vendor at all -- and it states figures
        // and direction only, never a verdict (invariant 1).
        {
          id: "filed", label: "What the report said",
          node: symbol
            ? <Widget span={6} title="What the report said"
                      subtitle="the company's own figures, as filed with the SEC">
                <FiledQuarterPanel symbol={symbol} reportDate={report?.report_date} />
              </Widget>
            : needPick("What the report said"),
        },
        {
          id: "revenue", label: "Revenue & earnings",
          node: symbol ? <RevenueEarningsPanel symbol={symbol} /> : needPick("Revenue & Earnings"),
        },
        {
          id: "eps", label: "EPS",
          node: symbol ? <EpsPanel symbol={symbol} /> : needPick("EPS"),
        },
        // CONSENSUS ESTIMATES IS NOT HERE ANY MORE (2026-09-28, the owner:
        // keep only the facts). It is a forecast of something that has not
        // happened, so it has no factual form at all — and the estimates
        // behind it were measured against a licensed consensus and agreed on
        // about half the rows. It was not deleted: it lives on the Analysis
        // page, which is where a forecast belongs. Don't add it back here.
        {
          id: "history", label: "Earnings history",
          node: symbol ? <EarningsHistoryPanel symbol={symbol} span={6} /> : needPick("Earnings history"),
        },
        {
          id: "transcript", label: "Earnings transcript",
          node: symbol ? <EarningsTranscriptPanel symbol={symbol} span={6} /> : needPick("Earnings transcript"),
        },
      ]}
    />
  )
}
