import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { Btn, Empty, fieldCls } from "@/components/terminal"
import { on, isNeedsKey } from "@/lib/api"
import { newsTime } from "@/lib/newsClock"
import { matchesQuery } from "@/lib/newsMatch"

/** SOCIAL POSTS, ON THEIR OWN PAGE (2026-09-29, the owner: "lets make Trump
 * Truth social a tab too").
 *
 * IT WAS A SCOPE THAT REPLACED THE LIST, exactly like the filings scopes
 * beside it, and for the same stated reason: nothing here is a story, so the
 * reader pane, the board's "new" marks and the word search would all be
 * answering about something they were never given. Every control in the News
 * toolbar was switched off under it — and the filter box was not, which is
 * why it sat there filtering stories nobody could see.
 *
 * A POST IS NOT A STORY AND IS NOT A RECORD. Every card says it is read from
 * a scraped copy of the account, and NO
 * TICKER IS READ OUT OF POST TEXT anywhere in this codebase: a ticker in a
 * post is the author's claim, and tagging it would route an unverified
 * assertion into that symbol's context. That is why this page has no symbol
 * filter and never will.
 *
 * FOUR EMPTY STATES, NOT ONE, and the difference between them is the whole
 * lesson of #63: a source that was never switched on and a source that is on
 * and would not answer are different facts, and telling a reader to "switch it
 * on" when they already did is the one instruction that cannot help them.
 */
export default function PostsPage() {
  const posts = useQuery({
    queryKey: ["social-posts"],
    queryFn: ({ signal }) => on(signal).socialPosts(100),
    staleTime: 60_000,
    retry: false,
  })
  // An errored query has no posts: a failed refetch keeps the last good
  // answer beside the error, and a source switched off must take its past
  // data with it.
  const live = posts.isError ? [] : posts.data?.posts ?? []
  const off = Object.values(posts.data?.unavailable ?? {})

  // ONLY TEXT POSTS ARE SERVED NOW (2026-10-03, the owner's call: "in posts
  // only keep the text posts"), so the kind picker that stood here has
  // nothing to choose between and is gone.
  // THE NEWS FILTER'S OWN WORD RULE (lib/newsMatch): whole words, in order,
  // plurals folded, the last word allowed to stop part-way. Over the post's
  // TEXT only — no ticker or company is resolved from a post, so a search for
  // "HOOD" finds the word, not a claim about Robinhood.
  const [query, setQuery] = useState("")
  const needle = query.trim()
  const shown = live.filter(p => !needle || matchesQuery(needle, p.text))

  // A message in the place the list would be, framed like a card so the page
  // does not jump between states.
  const note = (children: React.ReactNode) => (
    <div className="rounded-lg border border-card-border bg-card shadow-card">{children}</div>
  )

  return (
    // RESTYLED AS A FEED (2026-10-03, the owner: "restyle posts page"). One
    // readable column of cards instead of a dense table of tiny capitals:
    // the account and the time on a line, the words in full-strength ink at
    // reading size, and the source as a quiet footer. Same tokens as every
    // other card (radius-lg, card surface, card shadow) — nothing new.
    <div className="px-4 pb-8 pt-2">
      <div className="mx-auto w-full max-w-[760px]">
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h1 className="text-emph font-extrabold tracking-tight">Posts</h1>
            <p className="mt-0.5 text-caption text-muted-foreground">never read for tickers</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search posts — a word or phrase…"
              aria-label="Search the posts"
              title="Whole words, in order, as in the news filter. Searches the loaded posts' text only."
              className={`${fieldCls} w-60 !rounded-md`}
            />
            {query && <Btn variant="ghost" onClick={() => setQuery("")}>Clear</Btn>}
            <span className="tnum text-caption text-muted-foreground">{`${shown.length} / ${live.length}`}</span>
          </div>
        </div>

        <div className="mt-4">
          {posts.isPending ? note(<Empty>loading…</Empty>)
          : isNeedsKey(posts.error) ? note(<Empty>The social source is off — switch it on from the Account page.</Empty>)
          : posts.isError ? note(<QueryFailure error={posts.error}>the social source could not be read</QueryFailure>)
          : off.length > 0 ? (
            // THE SOURCE IS ON AND THE SITE WOULD NOT ANSWER (2026-09-23). This
            // used to fall through to "switch it on", which is the one
            // instruction that cannot help a reader who already did.
            note(<Empty>the social source is on, but could not be read — {off.join("; ")}</Empty>)
          ) : live.length === 0 ? note(<Empty>the social source answered, but with no posts in it</Empty>)
          : shown.length === 0 ? note(<Empty>no post matches these filters</Empty>)
          : (
            <ul className="space-y-3">
              {shown.map((post, i) => (
                <li key={post.url ?? i}>
                  <a href={post.url ?? undefined} target="_blank" rel="noopener noreferrer"
                     title={post.trust ?? undefined}
                     className="group block rounded-lg border border-card-border bg-card px-5 py-4 shadow-card transition-colors hover:border-border">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 truncate text-body font-bold text-foreground">
                        {post.account ? `@${post.account}` : post.platform ?? "social"}
                        {post.account && post.platform && (
                          <span className="ml-2 text-caption font-normal text-muted-foreground">{post.platform}</span>
                        )}
                      </span>
                      <span className="tnum shrink-0 text-caption text-muted-foreground">{newsTime(post.at)}</span>
                    </div>
                    {/* A WORDLESS POST IS STILL A POST (#66): it says so rather
                        than vanish, though only text posts are served now. */}
                    <p className="mt-2 whitespace-pre-wrap text-[15px] leading-[1.6] text-foreground">
                      {post.no_text
                        ? <span className="italic text-muted-foreground">no text — a picture or video, posted without a caption. Open it to see.</span>
                        : post.text}
                    </p>
                    <div className="mt-3 flex items-center gap-2 text-caption text-muted-foreground">
                      {post.via && <span>via {post.via}</span>}
                      <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">Open ↗</span>
                    </div>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
