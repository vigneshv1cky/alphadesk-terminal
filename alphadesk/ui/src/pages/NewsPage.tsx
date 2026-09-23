import { useEffect, useMemo, useRef, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { useSearchParams } from "react-router-dom"
import { X } from "lucide-react"
import { ComposedBoard } from "@/components/ComposedBoard"
import { HeadlineTickers } from "@/components/HeadlineTickers"
import { NewsReader } from "@/components/NewsReader"
import { api, isNeedsKey, type NewsArticle } from "@/lib/api"
import { useBoardSymbols } from "@/lib/boardSymbols"
import { boardStories, markSeen, readSeen } from "@/lib/newsSeen"
import { useNews } from "@/lib/queries"
import { Btn, Empty, fieldCls, Widget, btnCls } from "@/components/terminal"
import { newsTime } from "@/lib/newsClock"
import { matchesStory } from "@/lib/newsMatch"
import { useQuery } from "@tanstack/react-query"

/** The news view — a reading list beside a reader.
 *
 * Clicking a headline opens the story IN the terminal: the right pane shows
 * what the pipeline actually holds — title, source, time, the provider's
 * summary, the story's tickers, and the enrichment's sentiment/category when
 * it has run — with the original a deliberate click away. Only the summary is
 * ours to show; the full body belongs to the source, so the reader pane says
 * where it ends and links out rather than pretending.
 *
 * Nothing is ranked: newest-first is chronology, and the filter is the
 * reader narrowing their own view. Stories arrive deduped from /api/news —
 * one row per article, however many tickers it names.
 */

/** Below 900px the board is one column, so the Reader panel lands under the
 * whole list — a tapped headline appeared to do nothing. On those widths the
 * story opens IN the list panel with a back row (the market-news tile's
 * pattern) and the separate Reader panel is not rendered at all. */
function useOneColumn(): boolean {
  const [narrow, setNarrow] = useState(() => {
    try { return window.matchMedia("(max-width: 900px)").matches } catch { return false }
  })
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 900px)")
    const on = () => setNarrow(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return narrow
}

/** How far back the list fills on its own, and the row ceiling that stops a
 * noisier set of feeds filling the page forever. MEASURED on three feeds
 * (2026-09-17): two days took 2,800 rows and 16 seconds, arriving in pages
 * behind the first one; at that size the list scrolled in 28ms and refiltered
 * in 138ms. THREE DAYS since 2026-09-18 (the owner's call, "always as a
 * minimum"), so the ceiling rose with it: it sits well above three days'
 * rows rather than under them. Past it, Load older stories takes over. */
const FILL_HOURS = 72
const FILL_MAX_ROWS = 8000

export default function NewsPage() {
  const { data, error } = useNews()
  const oneColumn = useOneColumn()
  const [query, setQuery] = useState("")
  // The open story lives in ?article= — that is what lets every news row on
  // every OTHER screen link straight into this reader, and what makes an
  // open story shareable and reload-safe.
  const [params, setParams] = useSearchParams()
  const openId = params.get("article")
  const setOpenId = (id: string) => {
    const next = new URLSearchParams(params)
    next.set("article", id)
    setParams(next, { replace: true })
  }
  const err = error ? String(error.message ?? error) : null

  // Arriving from another screen's headline: bring the selected row into
  // view once the list has rendered it.
  const openRef = useRef<HTMLLIElement>(null)
  const arrived = useRef(false)
  useEffect(() => {
    if (arrived.current || !openId || !openRef.current) return
    arrived.current = true
    openRef.current.scrollIntoView({ block: "center" })
  })

  // Older pages the reader loaded below the window, and a search of all
  // stored news that replaces the list while it is open (2026-09-15).
  const [older, setOlder] = useState<NewsArticle[]>([])
  const [olderState, setOlderState] = useState<"idle" | "loading" | "end" | "error">("idle")
  const [search, setSearch] = useState<{ q: string; rows: NewsArticle[] | null } | null>(null)
  const window_ = data?.articles ?? []
  const articles = useMemo(() => {
    if (search) return search.rows ?? []
    const seen = new Set(window_.map(a => a.article_id))
    return [...window_, ...older.filter(a => !seen.has(a.article_id))]
  }, [window_, older, search])
  const loadOlder = async () => {
    const last = articles[articles.length - 1]?.published_at
    if (!last || olderState === "loading") return
    setOlderState("loading")
    try {
      const page = await api.newsPage({ before: last, limit: 100 })
      setOlder(o => [...o, ...page.articles])
      setOlderState(page.articles.length ? "idle" : "end")
    } catch {
      setOlderState("error")
    }
  }

  // THREE DAYS ARE THERE BEFORE THE READER ASKS (two from 2026-09-17, three
  // from 2026-09-18 — the owner's calls). The first response is one page —
  // 500 stories spanned 5.6 hours on this reader's three feeds, so the window
  // runs to thousands of stories and several megabytes, which
  // is not a payload to send on a 60-second poll. So the page keeps pulling
  // pages in the background until the oldest story it holds is older than
  // the window, and the poll keeps refetching only the first page.
  useEffect(() => {
    if (search || olderState !== "idle" || !window_.length) return
    const oldest = articles[articles.length - 1]?.published_at
    if (!oldest) return
    if (Date.now() - Date.parse(oldest) >= FILL_HOURS * 3_600_000) return
    if (articles.length >= FILL_MAX_ROWS) return      // the button takes it from here
    void loadOlder()
  }, [articles, olderState, search, window_.length])
  const runSearch = async () => {
    const q = query.trim()
    if (q.length < 2) return
    setSearch({ q, rows: null })
    try {
      const page = await api.newsPage({ q, limit: 100 })
      setSearch(cur => (cur?.q === q ? { q, rows: page.articles } : cur))
    } catch {
      setSearch(cur => (cur?.q === q ? { q, rows: [] } : cur))
    }
  }

  // Narrowing: stories naming a stock on the board, and one source.
  const { symbols: boardSymbols } = useBoardSymbols()
  const [onBoard, setOnBoard] = useState(false)
  const [source, setSource] = useState("")
  // WHO WROTE IT and WHICH FEED BROUGHT IT are different questions, and one
  // picker answering the first was read as answering the second (2026-09-22,
  // the reader: "why does it show more data sources if only alpaca is
  // used?"). A feed like Alpha Vantage's is an AGGREGATOR — one connection
  // delivers 24/7 Wall St., CNBC, Yahoo Finance and the rest — so a list of
  // thirty publishers on one feed is correct and looked alarming.
  const [feed, setFeed] = useState("")
  // POSTS ARE NOT STORIES, AND THIS PAGE COULD NOT SHOW THEM (2026-09-23,
  // the reader: "not able to filter and see only this in news"). They ride
  // the news TILE mixed into the stream, but every filter lives here — and a
  // post has no publisher, no feed and no ticker to filter BY, so it cannot
  // join the pickers above. It gets a view of its own: the list becomes the
  // posts, and the controls that cannot apply are disabled rather than left
  // looking as though they did.
  const [postsOnly, setPostsOnly] = useState(false)
  const posts = useQuery({
    queryKey: ["social-posts"],
    queryFn: () => api.socialPosts(50),
    enabled: postsOnly,
    staleTime: 60_000,
    retry: false,
  })
  const sources = useMemo(() => [...new Set(articles.map(a => a.source).filter((x): x is string => !!x))].sort(), [articles])
  const feeds = useMemo(
    () => [...new Set(articles.flatMap(a => a.feeds ?? []))].sort(),
    [articles],
  )
  // As typed: a ticker in capitals is matched exactly (lib/newsMatch).
  const needle = search ? "" : query.trim()
  // The companies the words name, resolved off the SEC list by the server,
  // so "robinhood" also keeps stories tagged HOOD. A config read, cached.
  const companies = useQuery({
    queryKey: ["newsTerms", needle],
    queryFn: () => api.newsTerms(needle),
    enabled: needle.length >= 2,
    staleTime: Infinity,
  }).data
  // Stories related in MEANING to what is typed (2026-09-19): asked of the
  // server once typing pauses, and added under the word matches marked
  // "related". Newest first with the rest — found by meaning, never ranked.
  const [meant, setMeant] = useState("")
  useEffect(() => {
    const t = setTimeout(() => setMeant(needle.length >= 3 ? needle : ""), 450)
    return () => clearTimeout(t)
  }, [needle])
  const related = useQuery({
    queryKey: ["newsRelated", meant],
    queryFn: () => api.newsRelated(meant),
    enabled: meant.length >= 3,
    staleTime: 60_000,
  }).data?.articles
  const shown = useMemo(() => {
    const board = new Set(boardSymbols.map(s => s.toUpperCase()))
    const keep = (a: NewsArticle) =>
      (!onBoard || a.tickers.some(t => board.has(t.toUpperCase())))
      && (!source || a.source === source)
      && (!feed || (a.feeds ?? []).includes(feed))
    // Whole words, their forms, and the companies the words name.
    const words = articles.filter(a => keep(a) && (!needle || matchesStory(needle, a, companies)))
    if (!needle || meant !== needle || !related?.length) return words
    const have = new Set(words.map(a => a.article_id))
    const extra = related.filter(a => !have.has(a.article_id) && keep(a))
    return [...words, ...extra].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
  }, [articles, needle, companies, onBoard, source, boardSymbols, meant, related])
  const open = articles.find(a => a.article_id === openId) ?? window_.find(a => a.article_id === openId) ?? null

  // Stories about the board's stocks stand out, and those published since the
  // last visit are marked new (2026-09-15). The mark is read once when the
  // page opens, so this visit's highlights hold while it is open, and moved
  // to now whenever the list changes, so the rail's count clears here.
  const [seenAtOpen] = useState(readSeen)
  const board = useMemo(() => boardStories(articles, boardSymbols, seenAtOpen), [articles, boardSymbols, seenAtOpen])
  useEffect(() => { if (data) markSeen() }, [data])
  const closeStory = () => {
    const next = new URLSearchParams(params)
    next.delete("article")
    setParams(next, { replace: true })
  }
  const readingInList = oneColumn && open != null

  // The reader appears when a headline is pressed and not before (the
  // reader's call, 2026-09-11 — the same shape as the earnings insights
  // box); the list takes the full width until then, and a double-click on
  // the open headline closes it again.
  const listPanel = (
      <Widget
        span={open ? 7 : 12}
        title={readingInList ? "Reader" : "Market news"}
        subtitle={readingInList ? undefined
          : search ? `search of all stored news for “${search.q}”${search.rows ? ` · ${search.rows.length} stories` : " · searching…"}`
          : data ? `${articles.length} stories, newest first · new stories arrive as they publish` : "loading…"}
        scroll="calc(100vh - 212px)"
        // Not expandable, same as the Reader beside it: the list and the
        // reader ARE this page's layout, and full-width for either one just
        // hides the other.
        expandable={false}
      >
        {readingInList ? (
          <NewsReader article={open} onBack={closeStory} />
        ) : (<>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-row-rule px-2.5 py-2.5">
          <input
            value={query}
            onChange={e => { setQuery(e.target.value); if (search) setSearch(null) }}
            onKeyDown={e => { if (e.key === "Enter") void runSearch() }}
            placeholder="Filter — ticker, word or source…"
            aria-label="Filter the headlines"
            title="Filters the list as you type; Enter searches all stored news"
            className={`${fieldCls} w-64`}
          />
          {query.trim().length >= 2 && !search && (
            <Btn variant="ghost" onClick={() => void runSearch()} title="Search every story stored for you, not only the list">
              Search all
            </Btn>
          )}
          {(query || search) && <Btn variant="ghost" onClick={() => { setQuery(""); setSearch(null) }}>Clear</Btn>}
          <Btn variant="ghost" active={onBoard} onClick={() => setOnBoard(v => !v)}
               title={boardSymbols.length ? `Only stories naming ${boardSymbols.join(", ")}` : "Add chips to the board to use this"}>
            On my board{board.onBoard.size ? ` · ${board.onBoard.size}` : ""}{board.fresh.size ? ` (${board.fresh.size} new)` : ""}
          </Btn>
          <Btn variant="ghost" active={postsOnly} onClick={() => setPostsOnly(v => !v)}
               title="Social posts only. A post has no publisher, no feed and no ticker, so the pickers beside this cannot apply to one">
            Posts
          </Btn>
          <select value={source} onChange={e => setSource(e.target.value)} aria-label="Publisher"
                  disabled={postsOnly}
                  title="Who wrote the story. One feed can carry many publishers — an aggregating feed delivers dozens"
                  className="h-[28px] border border-border bg-panel px-1.5 text-caption text-foreground">
            <option value="">All publishers</option>
            {sources.map(src => <option key={src} value={src}>{src}</option>)}
          </select>
          {/* Only worth a control when more than one feed actually delivered
              into the window; on a single feed it would be a picker with one
              choice. */}
          {feeds.length > 1 && (
            <select value={feed} onChange={e => setFeed(e.target.value)} aria-label="Feed"
                    disabled={postsOnly}
                    title="Which of your feeds delivered the story — the connection it came down, not who wrote it"
                    className="h-[28px] border border-border bg-panel px-1.5 text-caption text-foreground">
              <option value="">All feeds</option>
              {feeds.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          <span className="tnum ml-auto text-caption text-muted-foreground">
            {shown.length} / {articles.length}
          </span>
        </div>
        {/* THE POSTS VIEW REPLACES THE LIST rather than joining it: nothing
            here is a story, so the reader, the board's "new" marks and the
            word search would all be answering about something they were
            never given. Each row opens the post itself. */}
        {postsOnly ? (
          posts.isPending ? <Empty>loading…</Empty>
          : isNeedsKey(posts.error) ? (
            <Empty>The social source is off — switch it on from the Account page.</Empty>
          ) : posts.isError ? (
            <QueryFailure error={posts.error}>the social source could not be read</QueryFailure>
          ) : (posts.data?.posts ?? []).length === 0 ? (
            <Empty>no posts — switch the social source on from the Account page if it is off</Empty>
          ) : (
            <ul>
              {posts.data!.posts.map((post, i) => (
                <li key={post.url ?? i} className="row-rule hover:bg-foreground/5">
                  <a href={post.url ?? undefined} target="_blank" rel="noopener noreferrer"
                     title={post.trust ?? undefined} className="block w-full px-3 py-3 text-left">
                    <span className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
                      <span className="border border-border px-1 text-label font-semibold leading-[17px] tracking-ticker text-muted-foreground">post</span>
                      <span className="text-muted-foreground">{post.platform ?? "social"}</span>
                      <span className="normal-case tracking-normal text-warn">unverified</span>
                      <span className="normal-case tracking-normal text-muted-foreground">{newsTime(post.at)}</span>
                      {post.via && (
                        <span className="normal-case tracking-normal text-muted-foreground"
                              title="Read from a third party's copy of the account, not the platform itself">
                          via {post.via}
                        </span>
                      )}
                    </span>
                    <span className="block text-body leading-[1.3] text-muted-foreground">{post.text}</span>
                  </a>
                </li>
              ))}
            </ul>
          )
        ) : (<>
        {err && <QueryFailure error={error}>{err}</QueryFailure>}
        {!err && !data && <Empty>loading…</Empty>}
        {!err && data && shown.length === 0 && !(search && !search.rows) && (
          <Empty>{search ? `no stored story matches “${search.q}”`
            : needle || onBoard || source || feed ? "nothing matches these filters" : "no news in the window"}</Empty>
        )}
        {!err && shown.length > 0 && (
          <ul>
            {shown.map(a => {
              const on = a.article_id === openId
              return (
                <li key={a.article_id} ref={on ? openRef : undefined}
                    className={`row-rule ${on ? "bg-row-selected" : "hover:bg-foreground/5"} ${
                      board.onBoard.has(a.article_id) ? "shadow-[inset_3px_0_0_var(--accent)]" : ""}`}>
                  <button
                    type="button"
                    onClick={() => setOpenId(a.article_id)}
                    onDoubleClick={() => { if (on) closeStory() }}
                    aria-current={on ? "true" : undefined}
                    className={`block w-full px-3 py-3 text-left`}
                  >
                    <span className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
                      {board.fresh.has(a.article_id) && (
                        <span className="bg-accent px-1 text-label font-extrabold tracking-caps text-accent-foreground"
                              title="New since your last visit, about a stock on your board">New</span>
                      )}
                      <HeadlineTickers symbols={a.tickers} />
                      {/* The publisher, with the feed that delivered it on
                          hover — the two are different and the name alone
                          cannot say which it is (2026-09-22). */}
                      <span className="text-accent-700"
                            title={a.feeds?.length
                              ? `Published by ${a.source} · delivered by ${a.feeds.join(" and ")}`
                              : `Published by ${a.source}`}>{a.source}</span>
                      {a.why === "related" && (
                        <span className="text-muted-foreground" title="Found by meaning, not by the words you typed">related</span>
                      )}
                      {a.published_at && (
                        <span className="normal-case tracking-normal text-muted-foreground">
                          {newsTime(a.published_at)}
                        </span>
                      )}
                    </span>
                    <span className="block text-body font-semibold leading-[1.3]">{a.title}</span>
                    {a.summary && (
                      <span className="mt-1 line-clamp-2 block text-caption leading-[1.4] text-muted-foreground">
                        {a.summary}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {!err && data && !search && articles.length > 0 && (
          <div className="flex items-center justify-center gap-2 border-t border-row-rule px-3 py-3 text-caption text-muted-foreground">
            {olderState === "end" ? "no older stories from your feeds"
              : <Btn variant="ghost" onClick={() => void loadOlder()} disabled={olderState === "loading"}>
                  {olderState === "loading" ? "loading older stories…" : olderState === "error" ? "Couldn't load — try again" : "Load older stories"}
                </Btn>}
            {/* The way back out of a long list, as on every other news
                surface: drop what was paged in and return to the window. */}
            {older.length > 0 && (
              <Btn variant="ghost" onClick={() => { setOlder([]); setOlderState("idle") }}
                   disabled={olderState === "loading"}>Show less</Btn>
            )}
          </div>
        )}
        </>)}
        </>)}
      </Widget>
  )

  const readerPanel = open ? (
      <Widget
        span={5}
        title="Reader"
        scroll="calc(100vh - 212px)"
        expandable={false}
        actions={
          <button type="button" aria-label="Close the reader" title="Close"
            onClick={closeStory}
            className={btnCls({ icon: true })}>
            <X className="h-[13px] w-[13px]" />
          </button>
        }
      >
        <NewsReader article={open} />
      </Widget>
  ) : null

  return (
    <ComposedBoard
      page="news"
      panels={oneColumn
        ? [{ id: "list", label: "Market news", node: listPanel }]
        : [
            { id: "list", label: "Market news", node: listPanel },
            { id: "reader", label: "Reader", node: readerPanel },
          ]}
    />
  )
}
