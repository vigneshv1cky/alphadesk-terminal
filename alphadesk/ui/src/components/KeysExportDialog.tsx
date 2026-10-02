import { useState } from "react"
import { Dialog, btnCls } from "@/components/terminal"
import { api, ReauthRequired } from "@/lib/api"

/** Downloading the reader's vendor keys as a file (2026-10-02), to use them on
 * another server without typing them again. The file is PLAIN TEXT — no
 * passphrase (the owner's call): anyone holding it holds the keys. The server
 * also wants a recent sign-in, and says so with `reauth` — the one case this
 * dialog answers by sending the reader to sign in again rather than showing
 * an error. */
export function KeysExportDialog({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reauth, setReauth] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const { blob, name } = await api.exportKeys("")
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
      setBusy(false)
    }
  }

  return (
    <Dialog title="Export your keys" onClose={onClose}>
      {saved ? (
        <div className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Saved <strong>{saved}</strong>. It is plain text and holds every vendor key you have connected, readable
            by anyone who has the file. Keep it somewhere private, and delete it once the keys are moved.
          </p>
          <p className="text-caption text-muted-foreground">
            To put the keys into another AlphaDesk: <code>python -m alphadesk.main keys import-file {saved}</code>.
          </p>
          <div className="flex justify-end">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" }, "rounded-md")}>Done</button>
          </div>
        </div>
      ) : reauth ? (
        <div className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Exporting your keys needs a recent sign-in, so a session that was left open cannot do it. Sign out, sign
            back in, then export again.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" }, "rounded-md")}>Cancel</button>
            <button type="button" className={btnCls({ variant: "accent", size: "lg" }, "rounded-md")}
                    onClick={() => { void api.logout().finally(() => { window.location.href = "/" }) }}>
              Sign out
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3 px-4 py-4">
          <p className="text-body leading-[1.5]">
            Downloads the vendor keys you have connected as one plain-text file, to use on another server. The file is
            not encrypted: anyone who gets it has your keys.
          </p>
          {error && <p className="text-caption text-loss">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={btnCls({ size: "lg" }, "rounded-md")}>Cancel</button>
            <button type="submit" disabled={busy}
                    className={btnCls({ variant: "accent", size: "lg" }, "rounded-md px-3 uppercase tracking-caps")}>
              {busy ? "Preparing…" : "Download keys"}
            </button>
          </div>
        </form>
      )}
    </Dialog>
  )
}
