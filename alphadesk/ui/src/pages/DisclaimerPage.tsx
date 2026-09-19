import { H, L, LegalPage, P } from "@/components/legal"

/** The investment disclaimer — a PUBLIC page (2026-09-18) and part of the
 * Terms of Service. AlphaDesk presents records; it gives no advice. This is
 * the long form of the product's own stance (a consumption
 * terminal that does not trade, rank or score). A DRAFT for counsel review.
 */
export default function DisclaimerPage() {
  return (
    <LegalPage title="Not investment advice" updated="2026-09-18">
      <P>
        AlphaDesk is a research tool. It shows market data, news, filings and calendars as their
        sources supplied them, so that you can read them in one place. <strong>Nothing on AlphaDesk
        is investment, financial, legal, tax or accounting advice</strong>, and nothing on it is an
        offer, solicitation or recommendation to buy, sell or hold any security, derivative,
        cryptocurrency or other instrument.
      </P>

      <H>We are not your adviser</H>
      <P>
        [OPERATOR LEGAL NAME] is not a registered investment adviser, broker-dealer, research
        analyst or financial planner in any jurisdiction, and is not registered with the US
        Securities and Exchange Commission, the Securities and Exchange Board of India or any
        other regulator as any of these. Using AlphaDesk creates no adviser, fiduciary or client
        relationship. AlphaDesk does not know your finances, objectives or tolerance for risk, and
        nothing it shows takes them into account.
      </P>

      <H>What you see is not a recommendation</H>
      <L items={[
        <>Lists, baskets and "movers" are selected or ordered only by a figure shown on each row,
          such as the percentage change, volume or market capitalization, or alphabetically. An
          order is not a ranking of merit, and appearing on a list is not a signal.</>,
        <>Indicators, charts and statistics are arithmetic on the data received. They describe the
          past and do not predict the future.</>,
        <>News and filings are the words of their authors and issuers, which may be wrong,
          promotional or out of date.</>,
        <>Anything an AI agent you connect writes about these records is that application's output,
          not AlphaDesk's.</>,
      ]} />

      <H>Data may be wrong or late</H>
      <P>
        Data comes from third-party providers under your own agreements with them, and from public
        sources such as SEC EDGAR. It can be delayed, incomplete or inaccurate, and a feed can stop
        without warning. Always confirm prices and facts with your broker or the original source
        before acting on them.
      </P>

      <H>Your decisions and your risk</H>
      <P>
        Investing and trading involve risk, including the loss of more than you put in with some
        instruments. Past performance does not guarantee future results. You alone are responsible
        for your investment decisions and their outcomes. Consider consulting a licensed
        professional who knows your circumstances before making any financial decision.
      </P>
    </LegalPage>
  )
}
