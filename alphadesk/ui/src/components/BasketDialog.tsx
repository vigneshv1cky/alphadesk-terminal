import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { api, type Theme } from "@/lib/api"
import { newBasketId } from "@/lib/basketId"
import { keys } from "@/lib/queries"
import { btnCls, Dialog, fieldCls } from "@/components/terminal"

const LABEL = "mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground"

/** Make or edit one of the reader's own baskets (2026-09-18): a name, a line
 * on what moves it, and its tickers typed as one list. The server cleans the
 * tickers (upper case, each once, anything that is not a symbol dropped) and
 * nothing is looked up, so a crypto pair or a fund the SEC list does not
 * carry is still a member. Saved per reader; the rail and the reader's agent
 * see it beside the curated baskets. */
export function BasketDialog({ basket, onClose }: { basket?: Theme; onClose: () => void }) {
  const [label, setLabel] = useState(basket?.label ?? "")
  // A new basket's description starts in the house wording (2026-09-18,
  // the owner's call): every basket says what moves its companies.
  const [why, setWhy] = useState(basket ? (basket.why ?? "") : "These companies move up or down based on ")
  const [symbols, setSymbols] = useState(basket?.symbols.join(", ") ?? "")
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const id = basket?.id ?? newBasketId(label)
      await api.saveBasket(id, { label, why, symbols })
      await qc.invalidateQueries({ queryKey: keys.themes })
      onClose()
      navigate(`/themes/${id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not save the basket")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog title={basket ? "Edit basket" : "New basket"} onClose={onClose} maxWidth="max-w-[480px]">
      <form onSubmit={save}>
        <label className="block border-b border-row-rule px-4 py-3">
          <span className={LABEL}>Name</span>
          <input value={label} onChange={e => setLabel(e.target.value)} maxLength={60}
                 placeholder="e.g. Shipping rates" className={`${fieldCls} w-full`} />
        </label>
        <label className="block border-b border-row-rule px-4 py-3">
          <span className={LABEL}>What moves them</span>
          <textarea value={why} onChange={e => setWhy(e.target.value)} maxLength={300} rows={2}
                    placeholder="These companies move up or down based on freight rates and port news."
                    className="w-full resize-y border border-input bg-card px-2 py-1.5 text-body leading-snug text-foreground placeholder:text-muted-foreground/70 focus:border-accent focus:outline-none" />
        </label>
        <label className="block border-b border-row-rule px-4 py-3">
          <span className={LABEL}>Tickers</span>
          <input value={symbols} onChange={e => setSymbols(e.target.value)}
                 placeholder="ZIM, MATX, DAC" className={`${fieldCls} w-full uppercase`} />
          <span className="mt-1 block text-caption text-muted-foreground">Separated by commas or spaces, up to 40.</span>
        </label>
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <span role="status" className="min-w-0 text-caption text-loss">{error}</span>
          <button type="submit" disabled={saving || !label.trim() || !symbols.trim()}
                  className={btnCls({ variant: "accent", size: "lg" }, "px-4 font-extrabold uppercase tracking-caps")}>
            {saving ? "Saving…" : basket ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
