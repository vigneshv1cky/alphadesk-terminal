import { useState } from "react"
import { api, type Access } from "@/lib/api"
import { btnCls } from "@/components/terminal"

/** What an account sees instead of the terminal once its free trial has
 * ended — only when the access gate is ON (alphadesk/billing.py). Its keys,
 * data and settings are untouched; subscribing brings the terminal back as
 * it was. With no payment processor configured the button says so plainly
 * rather than pretending to take a card. */
export function SubscribePage({ email, access, onRecheck }: {
  email: string | null
  access: Access | null
  onRecheck: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const canPay = !!access?.can_subscribe

  const subscribe = (plan: "monthly" | "yearly") => {
    setBusy(true)
    setNote(null)
    api.billingCheckout(plan)
      .then(r => window.location.assign(r.url))
      .catch(e => { setNote(String(e.message ?? e)); setBusy(false) })
  }
  const signOut = () => {
    void fetch("/api/auth/logout", { method: "POST" }).finally(() => window.location.assign("/"))
  }

  return (
    <div className="flex h-dvh items-center justify-center bg-page px-4 text-foreground">
      <div data-slot="widget" className="w-full max-w-[440px] border border-card-border bg-card p-6 shadow-card">
        <div className="mb-4 flex items-center gap-2">
          <span aria-hidden="true" className="h-[14px] w-[14px] rounded-xs bg-accent" />
          <span className="text-figure font-extrabold tracking-tight">ALPHADESK</span>
        </div>
        <h1 className="text-emph font-bold">Your free trial has ended</h1>
        <p className="mt-2 text-body text-muted-foreground">
          Subscribe to keep using the terminal. Your boards, views, baskets and connected keys are kept
          exactly as you left them.
        </p>
        {email && <p className="mt-3 text-caption text-muted-foreground">Signed in as {email}</p>}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button type="button" disabled={!canPay || busy} onClick={() => subscribe("monthly")}
                  className={btnCls({ variant: "accent", size: "lg" }, "px-4 font-extrabold uppercase tracking-caps")}>
            {busy ? "Opening checkout…" : "Subscribe monthly"}
          </button>
          <button type="button" disabled={!canPay || busy} onClick={() => subscribe("yearly")}
                  className={btnCls({ variant: "strong", size: "lg" })}>Yearly</button>
          <button type="button" onClick={onRecheck} className={btnCls({ size: "lg" })}>I have subscribed</button>
          <button type="button" onClick={signOut} className={btnCls({ variant: "ghost", size: "lg" })}>Sign out</button>
        </div>
        {!canPay && (
          <p className="mt-3 text-caption text-muted-foreground">
            Payments are not open yet. You will be able to subscribe here as soon as they are.
          </p>
        )}
        {note && <p className="mt-3 text-caption text-loss">{note}</p>}
        <p className="mt-5 text-caption text-muted-foreground">
          <a href="/terms" className="underline hover:text-foreground">Terms</a>
          {" · "}
          <a href="/privacy" className="underline hover:text-foreground">Privacy</a>
          {" · "}
          <a href="/about" className="underline hover:text-foreground">About</a>
        </p>
      </div>
    </div>
  )
}
