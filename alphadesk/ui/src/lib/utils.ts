import { extendTailwindMerge } from "tailwind-merge"

/** The theme's own type roles (index.css). Without this, tailwind-merge would
 * read `text-caption` as a COLOUR and let a later `text-muted-foreground`
 * delete it — size and colour share the `text-` prefix. */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["label", "caption", "body", "emph", "figure", "display"],
      tracking: ["caps", "ticker", "tight"],
    },
  },
})

/** Anything a conditional class expression can evaluate to. Non-strings
 * (false from `cond && "x"`, 0 from a numeric guard) are dropped rather than
 * stringified — `0` and `true` are never intended as class names. */
export type ClassValue = string | number | boolean | null | undefined

/** Join truthy class fragments, then MERGE them: when two classes set the same
 * property, the later one wins (2026-09-18).
 *
 * This used to be a plain join, on the reasoning that tailwind-merge only
 * served shadcn's variant machinery. It cost more than it saved: without
 * merging, a caller's `h-[44px]` beside a component's own `h-[32px]` left the
 * winner to the stylesheet's order, and twice in one day that needed a
 * workaround — a scoped descendant rule for taller table rows, and buttons
 * rebuilt from a base because an appended hover colour did not take. MIT,
 * ~7 kB gzipped, and not a component library, so the no-component-library
 * rule is untouched.
 *
 * Only what passes through here merges. A class string assembled with a
 * template literal is still a plain concatenation — use cn() wherever a
 * caller's classes are meant to override a base. */
export function cn(...parts: ClassValue[]): string {
  return twMerge(parts.filter((p): p is string => typeof p === "string" && p.length > 0).join(" "))
}
