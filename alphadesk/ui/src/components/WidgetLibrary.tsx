import { useState } from "react"
import { Dialog, btnCls } from "@/components/terminal"
import { widgets } from "@/widgets/registry"

/** The widget library — one popup for both moments it serves:
 * CREATING a view (name field + "Save view") and EDITING one later (the
 * view's Widgets button reopens it, pre-checked with the current tiles).
 * Membership only: order and widths live in the inline layout editor.
 */
export function WidgetLibraryDialog({ title, submitLabel, initialIds, withName, options, onClose, onSubmit }: {
  title: string
  submitLabel: string
  initialIds: string[]
  /** Creation asks for the view's name; editing already has one. */
  withName?: boolean
  /** The tiles to offer: the board's own panels. Defaults to the Markets
   * registry, which is every view's library; a page board passing nothing
   * once offered Markets tiles on Analysis, and saving kept only the one
   * id the two lists share. */
  options?: { id: string; label: string }[]
  onClose: () => void
  onSubmit: (name: string, ids: string[]) => void
}) {
  const all = options ?? widgets()
  const [name, setName] = useState("")
  const [picked, setPicked] = useState<Set<string>>(() => new Set(initialIds))
  const toggle = (id: string) => setPicked(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  return (
    <Dialog title={title} onClose={onClose} maxWidth="max-w-[640px]">
      {withName && (
        <label className="block border-b border-row-rule px-4 py-3">
          <span className="mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground">
            Name
          </span>
          <input
            autoFocus
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. Energy Desk"
            className="h-[32px] w-full border border-border bg-card px-2 text-body focus:border-accent focus:outline-none"
          />
        </label>
      )}
      <div className="grid max-h-[52vh] grid-cols-1 overflow-y-auto sm:grid-cols-2">
        {all.map(w => (
          <label key={w.id} className="flex cursor-pointer items-center gap-3 border-b border-row-rule px-4 py-2.5 hover:bg-foreground/5 sm:odd:border-r">
            <input
              type="checkbox"
              checked={picked.has(w.id)}
              onChange={() => toggle(w.id)}
              className="h-[14px] w-[14px] accent-[var(--accent)]"
            />
            <span className="min-w-0 flex-1 truncate text-body font-semibold">{w.label}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center justify-between border-t border-row-rule px-4 py-3">
        <span className="text-label text-muted-foreground">
          {picked.size} tile{picked.size === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          disabled={picked.size === 0 || (withName && !name.trim())}
          onClick={() => onSubmit(name, all.filter(w => picked.has(w.id)).map(w => w.id))}
          className={btnCls({ variant: "accent", size: "lg" }, "px-4 font-extrabold uppercase tracking-caps")}
        >
          {submitLabel}
        </button>
      </div>
    </Dialog>
  )
}
