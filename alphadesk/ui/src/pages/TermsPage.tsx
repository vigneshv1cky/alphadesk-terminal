import { H, L, LegalPage, P } from "@/components/legal"

/** The Terms of Service — a PUBLIC page, readable before sign-in (consent to
 * terms nobody could read is not consent; the auth gate lets this route
 * through). First drafted 2026-09-04 for the integration-platform posture;
 * extended 2026-09-18: eligibility, price, account closure, and the Privacy
 * Policy and investment disclaimer as companion pages. AlphaDesk is FREE
 * (the owner, 2026-09-18), so the trial-and-subscription section was
 * replaced by a short Price section; restore it only with a real processor.
 *
 * A DRAFT for counsel review before the service takes payment. Every
 * bracketed placeholder is theirs to fill: the operator's legal name, the
 * jurisdiction and the contact address.
 */
export default function TermsPage() {
  return (
    <LegalPage title="AlphaDesk Terms of Service" updated="2026-09-18">
      <P>
        These terms are an agreement between you and [OPERATOR LEGAL NAME] ("we", "us"), the
        operator of AlphaDesk. By creating an account or using the service you agree to them, to
        the <a href="/privacy" className="underline">Privacy Policy</a> and to
        the <a href="/disclaimer" className="underline">investment disclaimer</a>. If you do not
        agree, do not use the service.
      </P>

      <H>1. What AlphaDesk is, and what it is not</H>
      <P>
        AlphaDesk is a market research workspace and integration platform. It connects to data
        providers, organizes what they return, and presents it for reading. It runs no
        artificial-intelligence model of its own. It is <strong>not</strong> a broker-dealer, an
        exchange, an investment adviser, a financial planner, or a trading system: it routes no
        orders, holds no positions or funds, executes no transactions, and gives no personalized
        investment advice. Nothing on this service is a recommendation to buy, sell, or hold any
        security or other instrument. The <a href="/disclaimer" className="underline">investment
        disclaimer</a> sets this out in full and forms part of these terms.
      </P>

      <H>2. Who may use it</H>
      <P>
        You must be at least 18 years old and able to form a binding contract. You may not use the
        service if you are barred from receiving it under the laws that apply to you, including
        sanctions laws. You are responsible for everything done through your account, and for
        keeping access to your sign-in method secure.
      </P>

      <H>3. Your keys, your provider agreements</H>
      <P>
        AlphaDesk works with credentials you supply: API keys for news feeds, market data and
        transcript sources ("your keys"). When you add a key, AlphaDesk calls that provider on your
        behalf, under your credential, to serve you alone. You are responsible for holding a valid
        agreement with each provider, for making sure your plan permits access through third-party
        software, for the provider's charges, and for complying with the provider's terms. Some
        providers' personal or free plans do not permit display inside a hosted third-party
        application; it is your responsibility to use a plan that does. AlphaDesk does not resell,
        sublicense, or redistribute any provider's data to you; it is the software through which
        your own access is exercised.
      </P>
      <P>
        Keys are stored encrypted and are used only to serve your requests. You can remove a key at
        any time, which stops its use. Public government data (such as SEC EDGAR filings and US
        Treasury yields) is fetched without a key.
      </P>

      <H>4. Connecting your own AI agent</H>
      <P>
        You may connect an AI agent you control, through a token you create or by signing that
        application in, to AlphaDesk's read-only tools. Calls made with that credential run as you,
        on your keys, and count against your provider limits. What you connect, what it does with
        the records it reads, and what it costs you are your responsibility: AlphaDesk cannot
        inspect or control that application. You can revoke a token or disconnect an application at
        any time on the Account page, which stops its access.
      </P>

      <H>5. Output produced elsewhere</H>
      <P>
        AlphaDesk produces no machine-learning output: it returns records as its sources supplied
        them. Anything an AI agent you connect writes about those records, such as a summary, a
        classification or an answer, is that application's output, not AlphaDesk's, and it can be
        wrong, incomplete, or out of date even when it reads fluently. Records may also contain
        errors from their sources. You are responsible for any decision you make on the basis of
        either.
      </P>

      <H>6. Price</H>
      <P>
        AlphaDesk is free. If we ever introduce paid plans, we will tell you in advance, by email or in
        the service, and nothing will be charged without your agreement. Your data providers bill you
        directly under your own agreements with them; AlphaDesk does not include any provider's data.
      </P>

      <H>7. No warranty on data or availability</H>
      <P>
        Market data, news, filings, and derived figures are presented as received from their
        sources and may be delayed, incomplete, or erroneous. The service is provided "as is" and
        "as available", without warranties of any kind, express or implied, including
        merchantability, fitness for a particular purpose, accuracy, and non-infringement. We do
        not promise that the service will be uninterrupted or free of errors.
      </P>

      <H>8. Your account and data</H>
      <P>
        Your account is keyed to your email address. The service stores what you create in it, such
        as your board, saved views and baskets, your encrypted provider keys, and the tokens or
        connected applications under Agent access, scoped to your account and not visible to other
        users. How we handle personal information is described in
        the <a href="/privacy" className="underline">Privacy Policy</a>.
      </P>

      <H>9. Closing your account</H>
      <P>
        You may stop using the service at any time. To close your account and have its data
        deleted, contact us at [CONTACT ADDRESS]; we will confirm the request from the email address
        on the account and complete it as described in the Privacy Policy. You can also delete it
        yourself on the Account page.
      </P>

      <H>10. Acceptable use</H>
      <P>You agree not to:</P>
      <L items={[
        "use the service to breach a data provider's terms, including by using keys you are not entitled to use;",
        "share your account, or resell or redistribute access to the service or to data obtained through it;",
        "probe, overload, or disrupt the service, or use it to attack anything else;",
        "attempt to access another user's account or data; or",
        "scrape or mass-export content from the service.",
      ]} />
      <P>
        These terms govern the hosted service, not the software. The AlphaDesk source code is
        available under the GNU Affero General Public License, version 3, and nothing here limits
        what that licence permits; a commercial licence is available from us for uses it does not
        cover.
      </P>

      <H>11. Indemnification</H>
      <P>
        You will indemnify and hold us harmless from claims, damages, and expenses (including
        reasonable legal fees) arising from your use of the service, your keys, the tools you
        connect, your content, or your breach of these terms, including any claim by a data
        provider concerning access exercised with your credentials.
      </P>

      <H>12. Limitation of liability</H>
      <P>
        To the maximum extent permitted by law, we are not liable for indirect, incidental, special,
        consequential, or punitive damages, or for lost profits, lost data, or trading or investment
        losses, arising from or related to the service, regardless of the theory of liability and
        even if advised of the possibility. Our total liability for all claims shall not exceed the
        greater of the amount you paid for the service in the twelve months before the claim arose,
        or fifty US dollars. Some jurisdictions do not allow certain limitations; in those, our
        liability is limited to the extent the law permits.
      </P>

      <H>13. Changes, suspension, termination</H>
      <P>
        The service and these terms may change. Material changes to the terms will be posted on this
        page with a new date and notified by email or in the service at least 14 days before they
        take effect; continued use after that is acceptance. We may
        suspend or terminate the service or any account, including for breach of these terms. Sections 5, 7, 11, 12, and 14 survive termination.
      </P>

      <H>14. Governing law, disputes and contact</H>
      <P>
        These terms are governed by the laws of [JURISDICTION], without regard to conflict-of-law
        rules, and disputes will be resolved in the courts of [VENUE], except where the law of your
        place of residence gives you a right to bring proceedings elsewhere. Questions about these
        terms: [CONTACT ADDRESS].
      </P>

      <p className="mt-6 text-caption leading-[1.5] text-muted-foreground">
        Third-party names (data providers, and applications you may connect) are used to identify
        interoperability only and imply no affiliation or endorsement.
      </p>
    </LegalPage>
  )
}
