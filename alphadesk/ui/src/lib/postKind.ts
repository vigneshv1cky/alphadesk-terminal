/** WHAT KIND OF POST A POST IS (2026-10-01) — the app's copy of
 * alphadesk/postkind.py; tests/test_postkind.py fails when they diverge.
 *
 * THE SAME STANDING DECISION AS newsKind.ts: one rule, no model, and a kind is
 * a fact about the record or it is not given. A post has no publisher channel,
 * so the only kinds are the ones its own shape states: a repost, a post with
 * no words, a bare link, or text.
 *
 * NO TOPIC IS READ OUT OF POST TEXT, for the reason no ticker is: it would
 * turn an unverified claim into a label that looks like ours. */
import type { SocialPost } from "./api"

export type PostKind = "repost" | "media" | "link" | "text"

export const POST_KIND_LABEL: Record<PostKind, string> = {
  repost: "Repost", media: "Media only", link: "Link only", text: "Text",
}

// "RT @someone: …" / "RT: https://…" — a repost names itself at the front.
const REPOST = /^RT\b\s*[:@]/i
// Nothing but one or more links.
const LINK_ONLY = /^(?:https?:\/\/\S+\s*)+$/i

export function postKind(p: Pick<SocialPost, "text" | "no_text">): PostKind {
  const body = (p.text ?? "").trim()
  if (p.no_text || !body) return "media"
  if (REPOST.test(body)) return "repost"
  if (LINK_ONLY.test(body)) return "link"
  return "text"
}
