/** What the news filter box counts as a match — the same rule as the
 * server's alphadesk/newsquery.py, so filtering the loaded window, "Search
 * all" and the agent's news_search agree. No model: words, word forms and the
 * SEC ticker list.
 *
 * - WHOLE WORDS, in order (2026-09-18). "ARM" used to return an ARMS sale
 *   and Senator ARMSTRONG because a word could stop part-way. Only the LAST
 *   word may, once it is five characters or more: "robin" finds Robinhood.
 * - WORD FORMS (2026-09-18). A plural matches its singular and back —
 *   "tariff" finds "tariffs", "rate cut" finds "rate cuts".
 * - A TICKER TYPED IN CAPITALS IS EXACT: "ARM" never takes the word-form
 *   rule, or "arms" would come back; "arm" in lower case is the word.
 * - COMPANY NAMES (2026-09-18). The server resolves a query that names a
 *   company exactly (/api/news/terms) to its tickers and the short name a
 *   headline uses: "robinhood" also keeps stories tagged HOOD, and "HOOD"
 *   also keeps headlines naming Robinhood.
 *
 * (2026-09-17, still true: "hood" no longer finds neighborhood.)
 */

export const PREFIX_MIN = 5

const KEEP = new Set(["news", "series", "species", "always", "perhaps", "whereas"])
const TICKER_TYPED = /^[A-Z][A-Z0-9]{0,4}$/

/** A plural's singular, by suffix — the server's stem() exactly. */
export function stem(w: string): string {
  if (w.length <= 3 || KEEP.has(w)) return w
  if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y"
  if (["sses", "shes", "ches", "xes", "zes"].some(s => w.endsWith(s))) return w.slice(0, -2)
  if (w.endsWith("s") && !["ss", "us", "is"].some(s => w.endsWith(s))) return w.slice(0, -1)
  return w
}

function words(text: string): string[] {
  return text.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)
}

function terms(query: string): [string, boolean][] {
  return query.split(/[^A-Za-z0-9]+/).filter(Boolean).map(w => [w.toLowerCase(), TICKER_TYPED.test(w)])
}

function phraseIn(ts: [string, boolean][], hay: string[]): boolean {
  if (!ts.length) return true
  const stems = hay.map(stem)
  const last = ts.length - 1
  for (let i = 0; i + ts.length <= hay.length; i++) {
    let ok = true
    for (let k = 0; k <= last && ok; k++) {
      const [term, literal] = ts[k]
      const got = hay[i + k]
      ok = literal
        ? got === term
        : stems[i + k] === stem(term) || got === term || (k === last && term.length >= PREFIX_MIN && got.startsWith(term))
    }
    if (ok) return true
  }
  return false
}

/** The companies a query names, as the server resolved them. */
export interface QueryCompanies { tickers: string[]; names: string[] }

export function matchesQuery(query: string, ...fields: (string | null | undefined)[]): boolean {
  const ts = terms(query)
  if (!ts.length) return true
  return fields.some(f => f != null && phraseIn(ts, words(f)))
}

/** A story matches when its text does, when it is tagged with a company the
 * query names, or when its headline names that company. */
export function matchesStory(
  query: string,
  story: { title: string; summary?: string | null; source?: string | null; tickers: string[] },
  companies?: QueryCompanies | null,
): boolean {
  const ts = terms(query)
  if (!ts.length) return true
  // A query typed as a ticker that names a company is about THAT company:
  // its tag, its name in the headline and the ticker as a headline word —
  // not the word anywhere in a summary ("HOOD" had matched "under the hood").
  const asTicker = !!companies?.tickers.length && ts.every(([, lit]) => lit)
  const texts = asTicker ? [story.title] : [story.title, story.summary, story.source]
  if (texts.some(f => f != null && phraseIn(ts, words(f)))) return true
  if (!companies) return false
  if (companies.tickers.some(t => story.tickers.includes(t))) return true
  // A company's name is matched exactly, word for word: "Arm", never "arms".
  return companies.names.some(n => phraseIn(words(n).map(w => [w, true] as [string, boolean]), words(story.title)))
}
