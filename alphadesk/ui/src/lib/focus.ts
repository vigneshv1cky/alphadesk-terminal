/** Keyboard focus for the overlays (2026-09-18).
 *
 * Measured before this: the key dialog let Tab walk out into the page behind
 * it and never returned focus to the button that opened it, and the menus
 * never moved focus into themselves at all — a keyboard user opened one and
 * was left on the trigger with no way into its items but tabbing through
 * whatever followed. Both overlays now share these two hooks rather than
 * each hand-rolling half of the behaviour.
 */
import { useEffect, useRef, type RefObject } from "react"

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])", "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
].join(",")

/** The elements inside `root` that Tab would stop on, in document order.
 * Hidden ones are skipped — the Account tables render a narrow fallback
 * beside each table and hide one of the two, and focus must never land on
 * the invisible copy. Exported for the tests. */
export function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(el => el.getClientRects().length > 0 && !el.closest("[inert]"))
}

/** A text field keeps its own arrow keys: the menu must not steal them from
 * a price floor being typed into. */
function isTextEntry(el: Element | null): boolean {
  if (!el) return false
  const tag = el.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable
}

/** A MODAL: while it is mounted, focus starts inside it, Tab and Shift+Tab
 * wrap within it, the rest of the app is inert (unreachable by Tab, by a
 * screen reader, and by the pointer), and on close focus goes back to what
 * opened it.
 *
 * Initial focus goes to the first text field when there is one — someone
 * opening "Connect your Alpaca key" means to type the key — and to the
 * first focusable element otherwise. */
export function useModalFocus(ref: RefObject<HTMLElement | null>, initial: "field" | "first" = "field") {
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const opener = document.activeElement as HTMLElement | null
    const app = document.getElementById("root")
    const wasInert = app?.inert ?? false
    if (app) app.inert = true

    // A TEXT field first: in the key dialog the vendor picker comes first,
    // but the row that opened it already chose the vendor — the key is what
    // the reader came to type. A picker or text area only when there is none.
    const field = initial === "field"
      ? (root.querySelector<HTMLElement>("input:not([type=hidden]):not([type=checkbox]):not([type=radio])")
        ?? root.querySelector<HTMLElement>("select, textarea"))
      : null
    const first = field ?? focusables(root)[0] ?? root
    first.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return
      const items = focusables(root)
      if (!items.length) { e.preventDefault(); return }
      const head = items[0], tail = items[items.length - 1]
      const at = document.activeElement
      if (e.shiftKey && (at === head || !root.contains(at))) { e.preventDefault(); tail.focus() }
      else if (!e.shiftKey && (at === tail || !root.contains(at))) { e.preventDefault(); head.focus() }
    }
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("keydown", onKey)
      if (app) app.inert = wasInert
      // Back to the opener, if it is still on the page (a Save can re-render
      // the row that held it).
      if (opener && opener.isConnected) opener.focus()
    }
  }, [ref, initial])
}

/** A POPOVER menu: on open, focus moves to its first item; the arrow keys
 * move between items, Home and End to the ends; and when it closes — by
 * Escape, by a pick, by its trigger — focus returns to the trigger.
 *
 * Not when it closed because the reader clicked somewhere else: pulling
 * focus back to the trigger then would yank it away from what they clicked. */
export function usePopoverFocus(
  open: boolean,
  panel: RefObject<HTMLElement | null>,
  trigger: RefObject<HTMLElement | null>,
) {
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open) {
      wasOpen.current = true
      const root = panel.current
      if (!root) return
      const items = focusables(root)
      ;(root.querySelector<HTMLElement>("[aria-checked=true], [aria-selected=true]") ?? items[0])?.focus()
      const onKey = (e: KeyboardEvent) => {
        if (!root.contains(document.activeElement) || isTextEntry(document.activeElement)) return
        const list = focusables(root)
        const i = list.indexOf(document.activeElement as HTMLElement)
        let next = -1
        if (e.key === "ArrowDown") next = i < 0 ? 0 : (i + 1) % list.length
        else if (e.key === "ArrowUp") next = i < 0 ? list.length - 1 : (i - 1 + list.length) % list.length
        else if (e.key === "Home") next = 0
        else if (e.key === "End") next = list.length - 1
        if (next < 0 || !list.length) return
        e.preventDefault()
        list[next].focus()
      }
      document.addEventListener("keydown", onKey)
      return () => document.removeEventListener("keydown", onKey)
    }
    if (wasOpen.current) {
      wasOpen.current = false
      const at = document.activeElement
      // Only when focus was left with nowhere to be: in the panel that just
      // vanished (so now on the body) or already on the trigger.
      if (!at || at === document.body || at === trigger.current) trigger.current?.focus()
    }
  }, [open, panel, trigger])
}
