import { useState } from "react"
import { Dialog, btnCls, fieldCls } from "@/components/terminal"

/** Deleting an account, confirmed by typing its email (2026-09-18). One
 * dialog for both doors: a reader deleting their own account, and the
 * owner deleting one from the admin page. The server checks the typed
 * address too, so this is a guard against a stray click, not the lock. */
export function DeleteAccountDialog({ email, own, onConfirm, onClose }: {
  email: string
  /** The reader's own account (wording says "your"). */
  own: boolean
  onConfirm: (typed: string) => Promise<unknown>
  onClose: () => void
}) {
  const [typed, setTyped] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const matches = typed.trim().toLowerCase() === email.toLowerCase()

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!matches || busy) return
    setBusy(true)
    setError(null)
    onConfirm(typed.trim())
      .catch(err => { setError(String(err.message ?? err)); setBusy(false) })
  }

  return (
    <Dialog title={own ? "Delete your account" : "Delete account"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3 px-4 py-4">
        <p className="text-body leading-[1.5]">
          {own ? "This permanently deletes your account" : <>This permanently deletes <strong>{email}</strong></>}
          {" "}and everything in it: connected keys, board, views, baskets, chart settings, stored news and
          calendar data, and agent tokens and connections. It cannot be undone.
        </p>
        <label className="block">
          <span className="mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground">
            Type {own ? "your" : "the account's"} email to confirm
          </span>
          <input value={typed} onChange={e => setTyped(e.target.value)} placeholder={email}
                 autoComplete="off" className={`${fieldCls} w-full`} />
        </label>
        {error && <p className="text-caption text-loss">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnCls({ size: "lg" })}>Cancel</button>
          <button type="submit" disabled={!matches || busy}
                  className={btnCls({ variant: "danger", size: "lg" }, "px-3 uppercase tracking-caps")}>
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
