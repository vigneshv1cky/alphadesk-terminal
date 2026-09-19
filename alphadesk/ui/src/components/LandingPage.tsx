import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { btnCls, fieldCls } from "@/components/terminal"
import { cn } from "@/lib/utils"
import { PROVIDER_MARKS } from "@/components/providerMarks"

/** The front page a signed-out visitor sees (2026-09-18, the owner's pick
 * of four directions drafted on a design canvas: "B2", the ink hero with the
 * app). It replaces the sign-in screen on an SSO instance and doubles as the
 * sign-up: the provider buttons ARE the account creation. A password-gated
 * instance gets the email-and-password form in the same spot (PasswordForm,
 * 2026-09-18 — the old LoginPage was deleted). It is THE ROOT, "/", for
 * everyone (2026-09-18, the owner's call) and /welcome too; signed in, its
 * buttons become "Open your terminal" into /markets, where a sign-in lands.
 *
 * THE SCREENSHOTS ARE BLURRED (public/landing/*.jpg): every price, figure and
 * headline in them came from vendor keys, and showing vendor data on a
 * public page is the display the vendors' terms restrict. Re-shoot them the
 * same way — layout sharp, figures blurred — when the app changes.
 *
 * The hero and section headings are sized outside the six type roles on
 * purpose: this is a marketing page read at a distance, not the terminal.
 * Everything else — colours, cards, radii, spacing — is the app's own
 * tokens, so the page follows light and dark with the rest. The hero is a
 * `.chrome` scope, the same dark ink as the app header. */

type Provider = { id: string; label: string }

const SHOTS = [
  { src: "/landing/markets.jpg", title: "Markets", text: "a board you compose: live chart, quotes, movers, sectors, yields.",
    alt: "The Markets board with a live chart, an equity overview and the funds built on the stock" },
  { src: "/landing/earnings.jpg", title: "Earnings week", text: "every reporter, dated by the company's own release and its SEC filing.",
    alt: "The earnings week calendar with each company's session, estimates and market cap" },
  { src: "/landing/news.jpg", title: "News", text: "your feeds in one three-day window, filtered by ticker, word or source.",
    alt: "The news list merging the reader's feeds, with a filter by ticker, word or source" },
  { src: "/landing/options.jpg", title: "Options", text: "chains by expiry, calls and puts either side of the price.",
    alt: "The options chain, calls in green and puts in red around the current price" },
]

const STEPS = [
  { title: "Sign in", text: "Your account is created on the spot, and only your email address is asked for." },
  { title: "Connect your data", text: "Add the market-data and news providers you use. Keys are encrypted and serve only you. SEC filings and Treasury yields need no key." },
  { title: "Read, or ask your agent", text: "Work the board yourself, or connect Claude, ChatGPT, Codex, Cursor or opencode to read the same records, as you." },
]

const PROMISES = [
  { title: "Charts you can trust", text: "One tape per chart, never stitched. RSI and MACD hide when the feed is too thin to support them, instead of drawing a confident line on sparse data." },
  { title: "Earnings, dated by the company", text: "Report dates come from the company's own release and its SEC filing, with the session predicted from its history." },
  { title: "Nothing ranked for you", text: "Lists are ordered by the figure on each row, or alphabetically. No scores, no picks: the judgement stays yours." },
  { title: "Your data stays yours", text: "No analytics, no ads, no tracking. Provider data is kept only as long as a feature needs it; delete your account and everything goes." },
]

/** The sign-in errors an SSO callback bounces back with, in words. */
const OAUTH_ERRORS: Record<string, string> = {
  "account-disabled": "That account has been disabled by this instance's operator.",
  "state-mismatch": "The sign-in attempt expired or was tampered with — try again.",
  "sso-failed": "Sign-in failed — try again.",
  "no-verified-email": "That account has no verified email address.",
  "not-configured": "That sign-in method isn't configured on this instance.",
}

/** The sign-in for an instance with no SSO provider configured — local
 * testing with sign-in on, or the live break-glass when every provider's
 * settings are removed. Accounts there are created by the operator. */
function PasswordForm({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await api.login(email, password)
      onSignedIn()
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setBusy(false)
    }
  }
  const field = cn(fieldCls, "h-[44px] w-full rounded-md border-foreground/30 bg-transparent")
  return (
    <form onSubmit={e => void submit(e)} className="flex flex-col gap-3">
      <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email"
             aria-label="Email" autoComplete="email" required className={field} />
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Password"
             aria-label="Password" autoComplete="current-password" required className={field} />
      {error && <p className="text-caption text-loss">{error}</p>}
      <button type="submit" disabled={busy}
              className={btnCls({ size: "lg" }, "h-[52px] rounded-md border-0 bg-foreground text-body font-extrabold uppercase tracking-caps text-background hover:bg-foreground/85 hover:text-background")}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-caption text-muted-foreground">Accounts on this instance are created by its operator.</p>
    </form>
  )
}

function SignIn({ providers, signedIn, primaryFirst = true, row = false }: {
  providers: Provider[]
  signedIn: boolean
  primaryFirst?: boolean
  row?: boolean
}) {
  // Already signed in, or an instance without single sign-on (the local open
  // one, a password gate): no provider buttons, the page leads into the app.
  if (signedIn || !providers.length) {
    return (
      <a href="/markets" className="flex h-[52px] items-center justify-center rounded-md bg-foreground px-6 text-body font-extrabold uppercase tracking-caps text-background no-underline hover:bg-foreground/85">
        Open your terminal
      </a>
    )
  }
  return (
    <div className={row ? "flex flex-wrap gap-3" : "flex flex-col gap-3"}>
      {providers.map((p, i) => (
        <a key={p.id} href={`/api/auth/${p.id}/start`}
           className={`flex h-[52px] items-center justify-center gap-2.5 rounded-md px-6 text-body font-extrabold uppercase tracking-caps no-underline transition-colors ${
             i === 0 && primaryFirst
               ? "bg-foreground text-background hover:bg-foreground/85"
               : "border border-foreground/30 text-foreground hover:bg-foreground/10"}`}>
          <span aria-hidden="true" className="flex shrink-0 items-center">{PROVIDER_MARKS[p.id]}</span>
          Continue with {p.label}
        </a>
      ))}
    </div>
  )
}

const Legal = ({ className = "" }: { className?: string }) => (
  <>
    <a href="/terms" className={`underline decoration-dotted hover:text-accent ${className}`}>Terms</a>{" · "}
    <a href="/privacy" className={`underline decoration-dotted hover:text-accent ${className}`}>Privacy</a>{" · "}
    <a href="/disclaimer" className={`underline decoration-dotted hover:text-accent ${className}`}>Not investment advice</a>
  </>
)

export function LandingPage({ providers, signedIn = false, onPasswordSignIn }: {
  providers: Provider[]
  signedIn?: boolean
  /** Set when this instance signs in by password (no SSO provider): the
   * hero shows the form, and this runs once it succeeds. */
  onPasswordSignIn?: () => void
}) {
  const ask = !signedIn && providers.length > 0
  // The gate renders this outside the shell, whose effect sets page titles.
  useEffect(() => { document.title = "AlphaDesk — research the market" }, [])
  const error = (() => {
    const code = new URLSearchParams(window.location.search).get("auth_error")
    return code ? OAUTH_ERRORS[code] ?? "Sign-in failed — try again." : null
  })()

  return (
    <div className="h-dvh overflow-y-auto bg-background text-foreground">
      {/* ── hero: the app header's dark ink ─────────────────────────── */}
      <section className="chrome bg-background px-5 pb-[200px] sm:px-10 sm:pb-[300px] lg:px-24">
        <nav className="flex h-[64px] items-center gap-3 sm:h-[72px]" aria-label="AlphaDesk">
          <span aria-hidden="true" className="h-[16px] w-[16px] rounded-xs bg-accent" />
          <span className="text-figure font-extrabold tracking-tight">ALPHADESK</span>
          <span className="flex-1" />
          <a href="#inside" className="hidden text-body font-semibold text-muted-foreground no-underline hover:text-foreground sm:inline">Inside</a>
          <a href="/about" className="text-body font-semibold text-muted-foreground no-underline hover:text-foreground sm:ml-6">About</a>
        </nav>
        <div className="flex flex-col gap-10 pt-10 sm:pt-16 lg:flex-row lg:items-end lg:gap-20">
          <div className="min-w-0 flex-1">
            <h1 className="m-0 text-[clamp(48px,7.2vw,96px)] font-black leading-[0.95] tracking-[-0.04em]">
              Research<br /><span className="text-accent">the market.</span>
            </h1>
            <p className="mt-8 max-w-[620px] text-[clamp(16px,1.4vw,19px)] leading-[1.55] text-muted-foreground">
              A dense, fast terminal for reading quotes, charts, news, SEC filings and earnings, on the data
              providers you connect. No model of its own, no ads. Free.
            </p>
          </div>
          <div id="signin" className="w-full shrink-0 lg:w-[360px]">
            {onPasswordSignIn && !signedIn
              ? <PasswordForm onSignedIn={onPasswordSignIn} />
              : <SignIn providers={providers} signedIn={signedIn} />}
            {error && <p className="mt-3 text-caption text-loss">{error}</p>}
            <p className="mt-3 text-caption leading-[1.5] text-muted-foreground">
              {ask && "Signing in creates your account. "}<Legal />
            </p>
          </div>
        </div>
      </section>

      {/* The hero shot straddles the ink and the page below it. */}
      <div className="-mt-[160px] px-5 sm:-mt-[240px] sm:px-10 lg:px-24">
        <figure className="m-0 overflow-hidden rounded-xl border border-foreground/15 bg-black shadow-[0_24px_64px_rgba(12,12,12,0.45)]">
          <img src="/landing/chart.jpg" width={2400} height={1500} className="block h-auto w-full"
               alt="The AlphaDesk chart workspace on one-minute bars across the overnight, pre-market, regular and after-hours sessions" />
        </figure>
      </div>

      {/* ── how it works ─────────────────────────────────────────────── */}
      <section className="px-5 pt-20 sm:px-10 sm:pt-24 lg:px-24">
        <div className="text-label font-bold uppercase tracking-caps text-muted-foreground">How it works</div>
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <div key={s.title} className="rounded-lg border border-card-border bg-card p-7 shadow-card">
              <div className="text-[44px] font-black leading-none text-accent">{i + 1}</div>
              <h3 className="mt-4 text-[22px] font-extrabold">{s.title}</h3>
              <p className="mt-2 text-[15px] leading-[1.55] text-muted-foreground">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── inside the terminal ──────────────────────────────────────── */}
      <section id="inside" className="px-5 pt-20 sm:px-10 sm:pt-24 lg:px-24">
        <div className="text-label font-bold uppercase tracking-caps text-muted-foreground">Inside the terminal</div>
        <h2 className="mt-2.5 text-[clamp(30px,3vw,40px)] font-black tracking-[-0.03em]">Everything on one board.</h2>
        <div className="mt-8 grid grid-cols-1 gap-x-6 gap-y-10 md:grid-cols-2">
          {SHOTS.map(s => (
            <figure key={s.src} className="m-0">
              <div className="overflow-hidden rounded-lg border border-card-border bg-black shadow-card">
                <img src={s.src} width={1600} height={1000} loading="lazy" alt={s.alt} className="block h-auto w-full" />
              </div>
              <figcaption className="mt-3.5 text-[15px] leading-[1.5] text-muted-foreground">
                <span className="text-[17px] font-extrabold text-foreground">{s.title}</span> — {s.text}
              </figcaption>
            </figure>
          ))}
        </div>
        <p className="mt-6 text-caption text-muted-foreground">Figures in these screenshots are blurred.</p>
      </section>

      {/* ── promises ─────────────────────────────────────────────────── */}
      <section className="grid grid-cols-1 px-5 pt-20 sm:px-10 sm:pt-24 md:grid-cols-2 lg:px-24">
        {PROMISES.map((p, i) => (
          <div key={p.title}
               className={`py-7 ${i < 2 ? "md:border-t-2 md:border-foreground" : "md:border-t md:border-row-rule"} border-t border-row-rule ${i % 2 === 0 ? "md:pr-8" : "md:pl-8"}`}>
            <h3 className="text-[20px] font-extrabold">{p.title}</h3>
            <p className="mt-2 text-[15px] leading-[1.55] text-muted-foreground">{p.text}</p>
          </div>
        ))}
      </section>

      {/* ── closing call ─────────────────────────────────────────────── */}
      <section className="chrome mx-5 mt-16 flex flex-col gap-8 rounded-xl bg-background p-8 sm:mx-10 sm:p-12 lg:mx-24 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <h2 className="text-[clamp(28px,2.6vw,36px)] font-black tracking-[-0.03em]">Open your terminal.</h2>
          <p className="mt-2.5 text-[16px] text-muted-foreground">
            {ask ? "Free. Sign in and your account is ready." : "Free."}
          </p>
        </div>
        {onPasswordSignIn && !signedIn
          ? <a href="#signin" className="flex h-[52px] items-center justify-center rounded-md bg-foreground px-6 text-body font-extrabold uppercase tracking-caps text-background no-underline hover:bg-foreground/85">Sign in</a>
          : <SignIn providers={providers} signedIn={signedIn} row />}
      </section>

      <footer className="chrome mt-20 flex flex-wrap items-center gap-x-6 gap-y-2 bg-background px-5 py-6 text-caption text-muted-foreground sm:px-10 lg:px-24">
        <span className="flex items-center gap-2 font-extrabold text-foreground">
          <span aria-hidden="true" className="h-[8px] w-[8px] rounded-[2px] bg-accent" />ALPHADESK
        </span>
        <span>Research only. Not investment advice.</span>
        <span className="flex-1" />
        <a href="/about" className="no-underline hover:text-foreground">About</a>
        <a href="/terms" className="no-underline hover:text-foreground">Terms</a>
        <a href="/privacy" className="no-underline hover:text-foreground">Privacy</a>
        <a href="/disclaimer" className="no-underline hover:text-foreground">Not investment advice</a>
      </footer>
    </div>
  )
}
