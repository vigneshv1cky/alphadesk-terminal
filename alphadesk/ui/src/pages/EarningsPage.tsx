import { useNarrowViewport } from "@/lib/viewport"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ComposedBoard } from "@/components/ComposedBoard"
import { EarningsCalendar } from "@/components/EarningsCalendar"
import type { EarningsRow } from "@/lib/api"
import {
  EarningsHistoryPanel, EarningsInsightsPanel, EpsPanel, RevenueEarningsPanel,
} from "@/components/EarningsPanels"
import { EarningsTranscriptPanel } from "@/components/EarningsTranscript"
import { Widget } from "@/components/terminal"
import { MarketChart } from "@/widgets/chart"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { normalize } from "@/lib/symbols"

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
    <Widget span={4} title={label} expandable={false}>
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
              subtitle="a week at a time — every reporter your calendar vendors list, largest companies first"
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
        {
          id: "chart", label: "Chart",
          node: <MarketChart symbol={symbol} />,
        },
        {
          id: "revenue", label: "Revenue & earnings",
          node: symbol ? <RevenueEarningsPanel symbol={symbol} /> : needPick("Revenue & Earnings"),
        },
        {
          id: "eps", label: "EPS",
          node: symbol ? <EpsPanel symbol={symbol} /> : needPick("EPS"),
        },
        {
          id: "consensus", label: "Consensus estimates",
          node: symbol ? <EarningsInsightsPanel symbol={symbol} /> : needPick("Consensus Estimates"),
        },
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
