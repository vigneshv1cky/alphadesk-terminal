import { useState } from "react"
import { Dialog, btnCls, fieldCls } from "@/components/terminal"
import { api, ReauthRequired } from "@/lib/api"
import { passphraseProblem } from "@/lib/keyExport"

/** Downloading the reader's vendor keys as a file (2026-10-02), to use them on
 * another server without typing them again. The file is sealed under a
 * passphrase chosen here; AlphaDesk keeps no copy of it, so a forgotten
 * passphrase cannot be recovered. The server also wants a recent sign-in, and
 * says so with `reauth` — the one case this dialog answers by sending the
 * reader to sign in again rather than showing an error. */
export function KeysExportDialog({ onClose }: { onClose: () => void }) {
  const [passphrase, setPassphrase] = useState("")
  const [again, setAgain] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reauth, setReauth] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    const problem = passphraseProblem(passphrase, again)
    if (problem) { setError(problem); return }
    setBusy(true)
    setError(null)
    try {
      const { blob, name } = await api.exportKeys(passphrase)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
      setSaved(name)
    } catch (err) {
      if (err instanceof ReauthRequired) setReauth(true)
      else setError(err instanceof Error ? err.message : "The export failed.")
    } finally {
      // Nothing typed stays in the page once the answer is back.
      setPassphrase("")
      setAgain("")
      setBusy(false)
    }
  }

  return (
    <Dialog title="Export your keys" onClose={onClose}>
      {saved ? (
        <div className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Saved <strong>{saved}</strong>. It is sealed with your passphrase and holds every vendor key you have
            connected. Without the passphrase it cannot be opened, and AlphaDesk cannot recover it.
          </p>
          <p className="text-caption text-muted-foreground">
            To read it: <code>python -m alphadesk.main keys decrypt {saved}</code>. To put the keys into another
            AlphaDesk: <code>python -m alphadesk.main keys import-file {saved}</code>.
          </p>
          <div className="flex justify-end">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" })}>Done</button>
          </div>
        </div>
      ) : reauth ? (
        <div className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Exporting your keys needs a recent sign-in, so a session that was left open cannot do it. Sign out, sign
            back in, then export again.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" })}>Cancel</button>
            <button type="button" className={btnCls({ variant: "accent", size: "lg" })}
                    onClick={() => { void api.logout().finally(() => { window.location.href = "/" }) }}>
              Sign out
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Downloads the vendor keys you have connected as one file, sealed with a passphrase only you know, to use
            on another server. Anyone with both the file and the passphrase has your keys — keep them apart.
          </p>
          <label className="block">
            <span className="mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground">
              Passphrase (at least 12 characters)
            </span>
            <input type="password" value={passphrase} onChange={e => setPassphrase(e.target.value)}
                   autoComplete="new-password" className={`${fieldCls} w-full`} />
          </label>
          <label className="block">
            <span className="mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground">
              Type it again
            </span>
            <input type="password" value={again} onChange={e => setAgain(e.target.value)}
                   autoComplete="new-password" className={`${fieldCls} w-full`} />
          </label>
          {error && <p className="text-caption text-loss">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" })}>Cancel</button>
            <button type="submit" disabled={busy}
                    className={btnCls({ variant: "accent", size: "lg" }, "px-3 uppercase tracking-caps")}>
              {busy ? "Sealing…" : "Download keys"}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
