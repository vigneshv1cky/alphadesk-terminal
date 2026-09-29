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

/** WHAT A STORY IS ABOUT, BEFORE READING IT (2026-09-29, the owner: "i can
 * know what they are about before even reading them").
 *
 * THE PUBLISHER'S OWN CLASSIFICATION, NOT OURS. Benzinga files every article
 * under a channel and that channel is in the URL path — so the kind is a FACT
 * about the record, on the same footing as the wire-host rule above and as
 * the SEC item numbers behind the Filings scope. Nothing here reads the story
 * and nothing infers a topic: an unrecognised channel stays unlabelled rather
 * than being guessed at.
 *
 * MEASURED before it was built, on 45 stories sampled by ticker across sectors
 * rather than by keyword (a keyword sample is a topic sample, and an earlier
 * earnings-flavoured one put the generic share at 55% — nearly double the
 * truth): 73% carried a specific channel. Of the 27% that did not, three
 * mechanical title patterns claimed nine of twelve, leaving under 7% of the
 * window unlabelled. That last slice is what a classifier model would buy, and
 * it is not worth ~700MB of weights on a 4GiB instance.
 *
 * ONE PUBLISHER. Every story in the sample came from Benzinga, because it is
 * the only feed delivering. Another feed brings its own paths, so this is a
 * per-publisher mapping like WIRE_HOSTS — extend it, never generalise it.
 */
export type StoryKind =
  | "earnings" | "transcript" | "rating" | "movers" | "why" | "offering"
  | "ma" | "ipo" | "fund" | "macro" | "crypto" | "legal" | "opinion"
  | "pickup" | "release" | "company"

export const KIND_LABEL: Record<StoryKind, string> = {
  earnings: "Earnings", transcript: "Transcript", rating: "Analyst",
  movers: "Movers", why: "Why it moved", offering: "Offering",
  ma: "M&A", ipo: "IPO", fund: "Funds", macro: "Macro", crypto: "Crypto",
  legal: "Legal", opinion: "Opinion", pickup: "Press pickup",
  release: "Press release", company: "Company",
}

/** Channel path → kind. LONGEST PREFIX WINS, so a narrower channel beats the
 * section it sits in ("markets/earnings" is earnings, "markets/tech" is not
 * a kind at all and falls through to the title rules). */
const CHANNELS: [string, StoryKind][] = [
  ["wiim", "why"],
  ["news/earnings", "earnings"],
  ["markets/earnings", "earnings"],
  ["trading-ideas/movers", "movers"],
  ["trading-ideas/previews", "earnings"],
  ["trading-ideas/long-ideas", "opinion"],
  ["analyst-stock-ratings", "rating"],
  ["markets/offerings", "offering"],
  ["markets/ipos", "ipo"],
  ["etfs", "fund"],
  ["economics", "macro"],
  ["crypto", "crypto"],
  ["m-a", "ma"],
  ["m", "ma"],
]

/** Titles that name their own kind, for stories the channel left generic.
 * Deliberately narrow and anchored: an analyst note is formulaic ("HSBC
 * Maintains Hold on JPMorgan Chase, Raises Price Target to $377") and a
 * third-party pickup is quoted with its publication trailing. A loose rule
 * here would mislabel a company announcement, which is the one thing the
 * generic bucket is genuinely full of. */
const RATING = /\b(maintains|reiterates|upgrades|downgrades|initiates|assumes)\b[^.]{0,80}\b(buy|sell|hold|neutral|outperform|underperform|overweight|underweight|price target)\b/i
const PRICE_TARGET = /\b(raises|lowers|cuts|boosts)\b[^.]{0,40}\bprice target\b/i
const TRANSCRIPT = /\btranscript\b|\bearnings (conference )?call\b/i
// "'JPMorgan Tweaks Data-Sharing Notices in Battle With Fintechs' - Bloomberg"
const PICKUP = /^['"“].{10,}['"”]\s*[-–—]\s*\S/

export function storyKind(
  a: Pick<NewsArticle, "url" | "source" | "title">,
): StoryKind | null {
  if (isWireRelease(a)) return "release"
  const title = (a.title ?? "").trim()
  // The title rules go FIRST for the two kinds the channel scatters: an
  // analyst note appears both under its own channel and under the generic
  // one, and a transcript is always generic. Reading the title first means
  // one kind rather than two names for the same thing.
  if (TRANSCRIPT.test(title)) return "transcript"
  if (RATING.test(title) || PRICE_TARGET.test(title)) return "rating"
  const channel = channelOf(a.url)
  if (channel) {
    let best: StoryKind | null = null, bestLen = -1
    for (const [prefix, kind] of CHANNELS) {
      if ((channel === prefix || channel.startsWith(`${prefix}/`)) && prefix.length > bestLen) {
        best = kind; bestLen = prefix.length
      }
    }
    if (best) return best
  }
  if (PICKUP.test(title)) return "pickup"
  return channel ? "company" : null
}

/** The channel a Benzinga URL files the story under: the path before the
 * date segments. "/markets/tech/26/09/62057613/slug" → "markets/tech". */
function channelOf(url?: string | null): string {
  if (!url) return ""
  let path: string
  try {
    const u = new URL(url)
    if (!u.hostname.toLowerCase().endsWith("benzinga.com")) return ""
    path = u.pathname
  } catch { return "" }
  const parts = path.split("/").filter(Boolean)
  const out: string[] = []
  for (const p of parts) {
    // The two-digit year starts the article's own identifiers; everything
    // before it is the channel.
    if (/^\d+$/.test(p)) break
    out.push(p.toLowerCase())
  }
  return out.join("/")
}
