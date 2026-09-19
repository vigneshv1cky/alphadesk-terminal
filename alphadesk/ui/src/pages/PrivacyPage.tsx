import { H, L, LegalPage, P } from "@/components/legal"

/** The Privacy Policy — a PUBLIC page (2026-09-18), readable before sign-in
 * and required by Google before its sign-in can leave testing mode.
 *
 * Every statement here was checked against the code on the day it was
 * written; keep it that way when either changes:
 * - sign-in asks Google, GitHub and Microsoft for the email address only
 *   ("openid email" / "user:email" in app/auth.py);
 * - three cookies, all necessary: the session, the sign-in state guard and
 *   the agent-consent return (app/auth.py, app/agent_oauth.py);
 * - browser storage holds preferences only (theme, display choices);
 * - no analytics, advertising or third-party scripts; fonts are bundled;
 * - provider keys are vault-sealed; agent tokens are stored as SHA-256;
 * - vendor data is pruned hourly to what features read (store.prune_vendor_
 *   data: stories 7 days, text 72 hours, calendar records up to 120 days)
 *   and purged when the key that fetched it is removed.
 *
 * A DRAFT for counsel review. Bracketed items are theirs to fill.
 */
export default function PrivacyPage() {
  return (
    <LegalPage title="AlphaDesk Privacy Policy" updated="2026-09-18">
      <P>
        This policy explains what personal information AlphaDesk collects, why, who it is shared
        with, and the choices you have. AlphaDesk is operated by [OPERATOR LEGAL NAME],
        [REGISTERED ADDRESS] ("we", "us"), which is responsible for your information. Contact us
        about privacy at [PRIVACY CONTACT ADDRESS].
      </P>

      <H>1. What we collect</H>
      <P><strong>Your account.</strong></P>
      <L items={[
        <>Your email address, received from the sign-in service you choose (Google, GitHub or
          Microsoft). We ask those services for your email address only, not your name, photo or
          contacts.</>,
        "Which sign-in methods you have used, and when you first and last used each.",
        "When your account was created and when it was last active.",
      ]} />
      <P><strong>What you add and create.</strong></P>
      <L items={[
        <>The API keys you connect for data providers. They are stored encrypted; we keep the last
          few characters in the clear so you can tell your keys apart.</>,
        "Your board of symbols, saved views, baskets, chart settings and layouts, and display preferences.",
        <>Tokens you create for AI agents (stored only as a one-way fingerprint, so the token itself
          cannot be read back) and the agent applications you approve.</>,
      ]} />
      <P><strong>Data fetched for you.</strong> News stories, calendar records and similar data
        retrieved from your connected providers are stored under your account so your window loads
        quickly. They are not shared with other users.</P>
      <P><strong>Plan records.</strong> AlphaDesk is free and takes no payments. A trial date is recorded
        when your account is created, in case paid plans are ever introduced; nothing else about
        payment is collected.</P>
      <P><strong>Technical information.</strong> Our hosting provider records server logs of requests
        to the service, including IP address, browser type, the address requested and the time.
        Sign-in events in those logs include the email address.</P>

      <H>2. Cookies and browser storage</H>
      <P>AlphaDesk uses three cookies, all strictly necessary for the service to work:</P>
      <L items={[
        "a session cookie that keeps you signed in (up to 14 days);",
        "a short-lived cookie that protects the sign-in handshake against forgery; and",
        "a short-lived cookie that returns you to an AI agent's approval page after you sign in.",
      ]} />
      <P>
        Your browser's local storage keeps display preferences such as the theme. We use no
        analytics, advertising or tracking cookies, and the service loads no third-party scripts or
        fonts, so your browser contacts no one but AlphaDesk (and the sign-in page you
        choose to open).
      </P>

      <H>3. How we use it</H>
      <L items={[
        "to provide the service: signing you in, calling your data providers with your keys, and showing you the results;",
        "to keep it secure: preventing abuse, enforcing rate limits, and investigating problems;",
        "to send service messages about your account (we do not send marketing without your consent); and",
        "to comply with the law.",
      ]} />
      <P>
        We do not sell your personal information, use it for advertising, or use it to train
        artificial-intelligence models. Where the law requires a legal basis, we rely on performing
        our contract with you, our legitimate interest in running a secure service, our legal
        obligations, and, where needed, your consent.
      </P>

      <H>4. Who we share it with</H>
      <L items={[
        <><strong>Hosting:</strong> Google Cloud, which runs the service and its database in the
          United States (Virginia).</>,
        <><strong>Sign-in services:</strong> Google, GitHub or Microsoft, when you choose to sign in
          with them.</>,
        <><strong>Your data providers:</strong> when AlphaDesk calls a provider with your key, that
          provider receives the request (for example, the symbols asked for) under your account with
          them, and handles it under its own privacy policy.</>,
        <><strong>AI agents you connect:</strong> they receive what they request through your token
          or approval, under their own terms.</>,
        <><strong>Authorities:</strong> where the law requires it.</>,
        <><strong>A successor:</strong> if the business is sold or reorganized, under this policy.</>,
      ]} />

      <H>5. Where it is stored</H>
      <P>
        Your information is stored in the United States. If you use the service from elsewhere, it
        is transferred there. [OPERATOR LEGAL NAME] is based in [COUNTRY]. Where the law requires
        safeguards for such transfers, we use [TRANSFER MECHANISM, e.g. standard contractual
        clauses].
      </P>

      <H>6. How long we keep it</H>
      <L items={[
        "Account data, keys and what you create: while your account is open.",
        <>Data fetched from your providers is kept only as long as the feature that shows it needs it:
          news stories for up to 7 days (their full text only while they are in your three-day news
          window), calendar and earnings records for up to 120 days, and working lookups for a day
          or a few days. It is deleted automatically every hour.</>,
        "When you remove a provider key, the data fetched with it is deleted at once.",
        "After you ask us to close your account: deleted within 30 days, and removed from backups as they expire within [BACKUP RETENTION].",
        "Server logs: [LOG RETENTION, e.g. 30 days].",
      ]} />

      <H>7. How we protect it</H>
      <P>
        Connections are encrypted (HTTPS). Provider keys are encrypted with a key held separately
        from the database. Agent tokens are stored only as one-way fingerprints. Session cookies are
        signed and can be revoked from the Account page with "sign out everywhere". Access to
        production systems is limited to the operator. No system is perfectly secure; if a breach
        affects your information we will notify you and the authorities as the law requires.
      </P>

      <H>8. Your rights</H>
      <P>
        Depending on where you live, you may have the right to access your information, correct it,
        delete it, receive a copy of it, object to or restrict certain uses, and withdraw consent.
        You can remove keys, tokens and connected applications yourself on the Account page. For
        anything else, contact [PRIVACY CONTACT ADDRESS]; we will verify the request from the email
        address on your account and respond within 30 days.
      </P>
      <L items={[
        <><strong>European Economic Area and United Kingdom:</strong> you may also complain to your
          data protection authority.</>,
        <><strong>California:</strong> we do not sell or share personal information as those terms
          are defined in California law, and we will not treat you differently for exercising your
          rights.</>,
        <><strong>India:</strong> you may raise a grievance with our Grievance Officer,
          [GRIEVANCE OFFICER NAME AND CONTACT], and, if unresolved, with the Data Protection Board
          of India.</>,
      ]} />

      <H>9. Children</H>
      <P>
        AlphaDesk is not for anyone under 18, and we do not knowingly collect information from
        them. If you believe a minor has an account, contact us and we will delete it.
      </P>

      <H>10. Changes</H>
      <P>
        We will post changes here with a new date. If a change materially affects how we use your
        information, we will tell you by email or in the service before it takes effect.
      </P>
    </LegalPage>
  )
}
