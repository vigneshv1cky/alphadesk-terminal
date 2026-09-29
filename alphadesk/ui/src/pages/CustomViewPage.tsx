import "@/widgets/builtin"
import "@/widgets/chart"
import "@/widgets/market"
import "@/widgets/external"
import "@/widgets/more"
import "@/widgets/desk"
import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { BoardEditor } from "@/components/BoardEditor"
import { Empty, OverflowMenu, TileSlot, Widget, btnCls } from "@/components/terminal"
import { usePageLayout } from "@/lib/boardLayout"
import { serializeLayout } from "@/lib/layoutEntries"
import { useMyViews, viewLayoutKey, type MyViewsApi } from "@/lib/customViews"
import { WidgetLibraryDialog } from "@/components/WidgetLibrary"
import { widgets } from "@/widgets/registry"

/** One reader-created view: any registered tile, in any order, at any width —
 * the same composition machinery as every built-in tab, under the page key
 * `view:<id>`. This page adds the identity chrome (rename, clone, delete)
 * and, signed in, the account sync: the browser's working copy is seeded
 * from the server row on open, and edits save back debounced — so the same
 * view greets you on the next device.
 */

function NameBar({ id, name, mine, onEditWidgets, saveState }: {
  id: string
  name: string
  mine: MyViewsApi
  onEditWidgets: () => void
  saveState: string
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const commit = () => {
    mine.rename(id, draft)
    setEditing(false)
  }

  return (
    <div className="flex items-center gap-2 px-4 pt-3">
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === "Enter") commit()
            if (e.key === "Escape") setEditing(false)
          }}
          className="h-[28px] border border-border bg-card px-2 text-emph font-extrabold focus:border-accent focus:outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={() => { setDraft(name); setEditing(true) }}
          title="Rename this view"
          className="text-emph font-extrabold tracking-ticker hover:text-accent"
        >
          {name}
        </button>
      )}
      <span className="text-label font-medium uppercase tracking-caps text-muted-foreground">
        {saveState}
      </span>
      <div className="min-w-0 flex-1" />
      <button
        type="button"
        onClick={onEditWidgets}
        className={btnCls({}, "uppercase tracking-caps")}
      >
        Widgets
      </button>
      <OverflowMenu
        label="View actions"
        items={[
          { label: "Rename", onPick: () => { setDraft(name); setEditing(true) } },
          { label: "Clone", onPick: () => { void mine.clone(id).then(next => { if (next) navigate(`/views/${next}`) }) } },
          { label: "Delete", danger: true, onPick: () => { mine.remove(id); navigate("/markets") } },
        ]}
      />
    </div>
  )
}

function Board({ viewId, viewName, mine, editorOpen, onEditorOpenChange, libraryOpen, onLibraryClose, onSaveState }: {
  viewId: string
  viewName: string
  mine: MyViewsApi
  editorOpen: boolean
  onEditorOpenChange: (open: boolean) => void
  libraryOpen: boolean
  onLibraryClose: () => void
  onSaveState: (s: string) => void
}) {
  const base = usePageLayout(`view:${viewId}`, widgets(), { addNew: false })
  // A VIEW RESETS TO ITS OWN TILES. The shared reset clears the layout, and
  // "no layout" means the page's default board — every registered widget —
  // which for a hand-picked set is not a reset but an explosion. Falls back
  // to the shared behaviour only when the view has nothing stored yet.
  const saved = mine.layoutOf(viewId)
  const layout = useMemo(
    () => (saved ? { ...base, reset: () => base.restore(saved) } : base),
    [base, saved],
  )

  // Save the composition back to the account, debounced while editing and
  // FLUSHED on unmount and on the editor's Save — a navigation inside the
  // debounce window must never lose the change (it once did).
  // THE CANONICAL SERIALISER, not a copy of it (2026-09-29). This was a
  // hand-rolled duplicate of serializeLayout that knew about spans and
  // places, so when heights arrived it silently dropped them: a height set
  // inside a view survived until you navigated, and was gone when you came
  // back. Anything the layout format gains from here on travels with a view
  // because this no longer has its own opinion about the format.
  const serialized = useMemo(
    () => serializeLayout(
      layout.items.map(({ def, span, align, height }) => ({ id: def.id, span, align, height })),
      layout.all, false),
    [layout.items, layout.all],
  )
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<string | null>(null)
  const flush = () => {
    if (timer.current) clearTimeout(timer.current)
    if (pending.current != null) {
      mine.saveLayout(viewId, pending.current)
      pending.current = null
    }
    onSaveState(mine.serverBacked ? "saved to your account" : "saved in this browser")
  }
  const flushRef = useRef(flush)
  flushRef.current = flush
  useEffect(() => {
    if (!mine.serverBacked || !layout.isCustom) return
    pending.current = serialized
    onSaveState("saving…")
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => flushRef.current(), 800)
    return () => { if (timer.current) clearTimeout(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialized, viewId, mine.serverBacked])
  useEffect(() => () => flushRef.current(), [])   // unmount = flush

  return (
    <>
      {libraryOpen && (
        <WidgetLibraryDialog
          title={`${viewName} — widgets`}
          submitLabel="Save"
          initialIds={layout.items.map(i => i.def.id)}
          onClose={onLibraryClose}
          onSubmit={(_name, ids) => {
            layout.applyIds(ids)
            onLibraryClose()
            // Membership changed: don't let a quick navigation lose it.
            setTimeout(() => flushRef.current(), 0)
          }}
        />
      )}
      <div className="px-4 pt-2">
        <BoardEditor
          layout={layout}
          open={editorOpen}
          onOpenChange={v => { if (!v) flushRef.current(); onEditorOpenChange(v) }}
          doneLabel="Save"
        />
      </div>
      <div className="collage !pt-0">
        {layout.items.map(({ def, span, align, height }) => {
          const W = def.component
          return (
            <TileSlot key={def.id} span={span} align={align} height={height}>
              <W />
            </TileSlot>
          )
        })}
      </div>
    </>
  )
}

export default function CustomViewPage() {
  const { viewId } = useParams()
  const [params] = useSearchParams()
  // Arriving from the create flow (the widget library), the spacing step
  // follows immediately: the editor starts open. The Widgets button reopens
  // it any time after.
  const composing = !!(useLocation().state as { compose?: boolean } | null)?.compose
  const [editorOpen, setEditorOpen] = useState(composing)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [saveState, setSaveState] = useState("")
  const mine = useMyViews()
  const view = mine.views.find(v => v.id === viewId) ?? null

  // Signed in, the server row is the durable copy: seed the browser's
  // working store from it BEFORE the board mounts, unless the URL already
  // names a layout (a shared link wins — and will be saved back).
  const [seeded, setSeeded] = useState(false)
  useEffect(() => {
    if (!mine.ready || !viewId) return
    if (mine.serverBacked && !params.get("tiles")) {
      const server = mine.layoutOf(viewId)
      if (server) {
        try { localStorage.setItem(viewLayoutKey(viewId), server) } catch { /* private mode */ }
      }
    }
    setSeeded(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mine.ready, viewId])

  if (!mine.ready) return null

  if (!view) {
    return (
      <div className="collage">
        <Widget span={12} title="My views">
          <Empty>
            This view doesn't exist{mine.serverBacked ? " on your account" : " in this browser"} —
            create one with the + beside My Views in the rail.
          </Empty>
        </Widget>
      </div>
    )
  }

  return (
    <>
      <NameBar id={view.id} name={view.name} mine={mine}
               onEditWidgets={() => setLibraryOpen(true)}
               saveState={saveState || (mine.serverBacked ? "my view · synced to your account" : "my view · this browser")} />
      {seeded && (
        <Board viewId={view.id} viewName={view.name} mine={mine} editorOpen={editorOpen}
               onEditorOpenChange={setEditorOpen}
               libraryOpen={libraryOpen} onLibraryClose={() => setLibraryOpen(false)}
               onSaveState={setSaveState} />
      )}
    </>
  )
}
