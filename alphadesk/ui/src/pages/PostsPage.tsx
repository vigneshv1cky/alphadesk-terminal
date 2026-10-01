import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { QueryFailure } from "@/components/KeyPrompt"
import { Empty, Widget } from "@/components/terminal"
import { on, isNeedsKey } from "@/lib/api"
import { newsTime } from "@/lib/newsClock"
import { postKind, POST_KIND_LABEL, type PostKind } from "@/lib/postKind"

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
 * A POST IS NOT A STORY AND IS NOT A RECORD. It is marked UNVERIFIED on every
 * row because the social source is the one anyone can write into, and NO
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
    queryFn: ({ signal }) => on(signal).socialPosts(50),
    staleTime: 60_000,
    retry: false,
  })
  // An errored query has no posts: a failed refetch keeps the last good
  // answer beside the error, and a source switched off must take its past
  // data with it.
  const live = posts.isError ? [] : posts.data?.posts ?? []
  const off = Object.values(posts.data?.unavailable ?? {})

  // THE KIND IS THE POST'S OWN SHAPE (repost, media, link, text) — never its
  // topic, for the reason no ticker is read out of post text. Only the kinds
  // the window holds are offered, with counts, like the News kind picker.
  const [kind, setKind] = useState<PostKind | "">("")
  const kinds = useMemo(() => {
    const n = new Map<PostKind, number>()
    for (const p of live) { const k = postKind(p); n.set(k, (n.get(k) ?? 0) + 1) }
    return [...n.entries()].sort((a, b) => b[1] - a[1] || POST_KIND_LABEL[a[0]].localeCompare(POST_KIND_LABEL[b[0]]))
  }, [live])
  const shown = kind ? live.filter(p => postKind(p) === kind) : live

  return (
    <>
      {/* THE PAGE SAYS WHICH PAGE IT IS (2026-09-29, the owner: "include
          heading in filings and posts too"). Every composed board carries one
          above its tiles; these two are single panels on no board, so they
          had none and read as a panel floating with no context. Same type and
          inset as the board heading, without the Customize control — there is
          no board here to compose. */}
      <div className="px-4 pt-2">
        <h1 className="mb-2 text-emph font-extrabold tracking-tight">Posts</h1>
      </div>
      {/* THE PANEL SITS IN THE SAME FRAME AS EVERY OTHER PAGE'S TILES
          (2026-09-29, the owner: "the gap between left sidebar and tiles is
          not maintained in filings and posts"). These two are single panels
          on no board, so they never got the board's 16px inset: the HEADING
          was inset by its own padding and the panel was not, leaving it flush
          against the rail and the window edge while every board page stood
          16px clear. Measured: 10px against 26px on both sides.
          The board's own wrapper, rather than a matching pair of paddings —
          a second way of expressing the same inset is a second thing to keep
          in step, and this is the page that proves it does not stay in step
          on its own. */}
      <div className="collage !pt-0">
    <Widget
      span={12}
      title="Social posts"
      subtitle="an account mirror — unverified, and never read for tickers"
      scroll="fit"
      actions={kinds.length > 1 ? (
        <select value={kind} onChange={e => setKind(e.target.value as PostKind | "")}
                aria-label="Kind"
                title="The shape of the post — a repost, media with no caption, a bare link or text. Never what it is about."
                className="h-[28px] border border-border bg-panel px-1.5 text-caption text-foreground">
          <option value="">All kinds</option>
          {kinds.map(([k, n]) => <option key={k} value={k}>{`${POST_KIND_LABEL[k]} · ${n}`}</option>)}
        </select>
      ) : undefined}
    >
      {posts.isPending ? <Empty>loading…</Empty>
      : isNeedsKey(posts.error) ? (
        <Empty>The social source is off — switch it on from the Account page.</Empty>
      ) : posts.isError ? (
        <QueryFailure error={posts.error}>the social source could not be read</QueryFailure>
      ) : off.length > 0 ? (
        // THE SOURCE IS ON AND THE SITE WOULD NOT ANSWER (2026-09-23). This
        // used to fall through to "switch it on", which is the one
        // instruction that cannot help a reader who already did.
        <Empty>the social source is on, but could not be read — {off.join("; ")}</Empty>
      ) : live.length === 0 ? (
        <Empty>the social source answered, but with no posts in it</Empty>
      ) : (
        <ul>
          {shown.map((post, i) => (
            <li key={post.url ?? i} className="row-rule hover:bg-foreground/5">
              <a href={post.url ?? undefined} target="_blank" rel="noopener noreferrer"
                 title={post.trust ?? undefined} className="block w-full px-3 py-3 text-left">
                <span className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
                  <span className="border border-border px-1 text-label font-semibold leading-[17px] tracking-ticker text-muted-foreground">post</span>
                  <span className="text-muted-foreground">{post.platform ?? "social"}</span>
                  <span className="text-muted-foreground"
                        title="The post's own shape, not its topic">{POST_KIND_LABEL[postKind(post)]}</span>
                  <span className="normal-case tracking-normal text-warn">unverified</span>
                  <span className="normal-case tracking-normal text-muted-foreground">{newsTime(post.at)}</span>
                  {post.via && (
                    <span className="normal-case tracking-normal text-muted-foreground"
                          title="Read from a third party's copy of the account, not the platform itself">
                      via {post.via}
                    </span>
                  )}
                </span>
                <span className="block text-body leading-[1.3] text-muted-foreground">
                  {/* A WORDLESS POST IS STILL A POST (#66). Two of a day's
                      posts were dropped for having no text — both were media
                      posted without a caption, so "he did not post" and "he
                      posted a photo" looked identical. */}
                  {post.no_text
                    ? <span className="italic">no text — a picture or video, posted without a caption. Open it to see.</span>
                    : post.text}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Widget>
      </div>
    </>
  )
}
