import { ComposedBoard } from "@/components/ComposedBoard"
import { EconomicCalendarPanel } from "@/components/EconomicCalendar"
import { DividendCalendarPanel, IpoCalendarPanel, SplitCalendarPanel } from "@/components/CorporateCalendars"

/** Market-wide calendars (2026-09-14) — what happens across the market in a
 * week, not to one company: economic releases, ex-dividend dates, IPOs and
 * stock splits. Split off the Earnings page, which had grown to a dozen
 * grids; Earnings keeps the reporters' calendar and the company's own
 * earnings panels. Each panel pages its own week and is a keyed surface.
 */
export default function CalendarsPage() {
  return (
    <ComposedBoard
      page="calendars"
      panels={[
        { id: "economic", label: "Economic calendar", node: <EconomicCalendarPanel span={12} /> },
        { id: "dividend-calendar", label: "Dividend calendar", node: <DividendCalendarPanel span={12} /> },
        { id: "ipo-calendar", label: "IPO calendar", node: <IpoCalendarPanel span={6} /> },
        { id: "split-calendar", label: "Stock splits", node: <SplitCalendarPanel span={6} /> },
      ]}
    />
  )
}
