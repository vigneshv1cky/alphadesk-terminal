/** WHAT KIND OF NEWS A STORY IS — for the News page's scopes (2026-09-28, the
 * owner: "I want what we get earlier than the official in news by other
 * providers").
 *
 * NEWS IS THE FAST LANE AND THE SEC IS THE SLOW COPY. Measured that day, a
 * company's wire release beat its own 8-K by 10 minutes (Gray Media) to three
 * and a half hours (NETSOL, Moving iMage), and never the other way except
 * once. So the official record belongs on the Earnings tab, where it is the
 * authority, and News carries what arrived first.
 *
 * ONE RULE, NO MODEL — the same standing decision as the news search
 * (newsquery.py / newsMatch.ts).
 */
import type { NewsArticle } from "./api"

/** The newswires a company distributes its OWN statement through. Mirrors
 * `_WIRES` in alphadesk/ingest/earnings_announcements.py; keep the two in
 * step. A wire host is a FACT about the URL, not a reading of the story —
 * which is what makes the Press releases scope a record. A reporter's article
 * about a company is not the company's word, however well sourced. */
const WIRE_HOSTS = [
  "globenewswire.com", "prnewswire.com", "prnewswire.co.uk", "newswire.ca",
  "businesswire.com", "newsfilecorp.com", "accessnewswire.com", "accesswire.com",
  "thenewswire.com",
]

export function isWireRelease(a: Pick<NewsArticle, "url" | "source">): boolean {
  // EITHER the link or the named source, not the link falling back to the
  // source: a feed may hand over a canonical publisher URL on its own host
  // while naming the wire that distributed it, and that is still the
  // company's own statement. Requiring the URL to be the wire would drop it.
  const host = hostOf(a.url)
  const named = (a.source ?? "").trim().toLowerCase()
  const isWire = (h: string) => !!h && WIRE_HOSTS.some(w => h === w || h.endsWith(`.${w}`))
  return isWire(host) || isWire(named)
}

function hostOf(url?: string | null): string {
  if (!url) return ""
  try { return new URL(url).hostname.toLowerCase() } catch { return "" }
}
